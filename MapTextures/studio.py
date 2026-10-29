"""Salvage Ops Texture Studio: browse ambientCG, assign materials to slots, preview, build and install.

    python studio.py            opens http://127.0.0.1:8765 in your browser

Requires Pillow (pip install pillow) and, for building, Unreal Engine 4.26 (see README).
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image

import build

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, 'studio', 'index.html')
CACHE = os.path.join(build.BUILD, 'acg_cache')
STAGING = os.path.join(build.BUILD, 'acg_staging')
HISTORY = os.path.join(build.BUILD, 'history')
BUILT_STATE = build.BUILT_STATE
PORT = 8765
ACG_API = 'https://ambientcg.com/api/v2/full_json'
RESOLUTIONS = ('1K', '2K', '4K')
TINTED_BY_DEFAULT = {'White', 'Orange', 'Green', 'Red', 'Yellow', 'Black', 'PaintedMetalBase'}
MAP_RE = re.compile(r'_(Color|NormalDX|NormalGL|Roughness|AmbientOcclusion|Metalness)\.(jpg|jpeg|png)$', re.I)
USER_AGENT = {'User-Agent': 'SalvageOpsTextureStudio/1.0'}

CFG = build.load_config()
JOB = {'running': False, 'ok': None, 'title': '', 'log': ''}
JOB_LOCK = threading.Lock()
STAGE_LOCK = threading.Lock()


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=USER_AGENT), timeout=120) as r:
        return r.read()


def slot_dir(slot, scope=None):
    """Folder holding a slot's textures: the all-maps default, or one map's override when `scope` is a map."""
    return build.map_folder(scope, slot) if scope else os.path.join(build.TEXTURES, slot)


def read_json(path, default):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def slot_state(name, scope=None):
    """A slot's textures and settings. In a map scope without an override, the all-maps state is returned with
    inherited=True so the page can show what the map currently gets."""
    slot = CFG['slots'][name]
    d = slot_dir(name, scope)
    maps = build.find_maps(name, d)
    if scope and not maps:
        state = slot_state(name)
        state.update(inherited=True, scope=scope, shared=False)
        return state
    files = list(maps.values()) + [os.path.join(d, 'settings.json')]
    stamp = max((os.path.getmtime(f) for f in files if os.path.exists(f)), default=0)
    return {
        'name': name, 'asset': slot['asset'], 'proto_maps': slot['proto_maps'],
        'shared': slot['shared'] and not scope, 'note': slot['note'], 'maps': sorted(maps),
        'stamp': int(stamp * 1000), 'color': slot['color'], 'scope': scope, 'inherited': False,
        'source': read_json(os.path.join(d, 'source.json'), None),
        'settings': read_json(os.path.join(d, 'settings.json'), {}),
        'effective': build.slot_settings(CFG, name, d)[0] if maps else None,
    }


MAP_INDEX_FILE = os.path.join(build.BUILD, 'map_index.json')
_MAP_INDEX = {}


def map_index():
    """Every game map that uses at least one slot: {name: {path, group, slots}}. Cached until the game paks change."""
    game = build.find_game()
    if not game:
        return {}
    import pakfile
    folder = os.path.join(game, 'LemnisGate', 'Content', 'Paks')
    key = [[f, os.path.getsize(os.path.join(folder, f))] for f in sorted(os.listdir(folder)) if f.startswith('pakchunk')]
    if _MAP_INDEX.get('key') == key:
        return _MAP_INDEX['maps']
    cached = read_json(MAP_INDEX_FILE, {})
    if cached.get('key') != key:
        paks = pakfile.game_paks(game)
        assets = {s['asset']: n for n, s in CFG['slots'].items()}
        maps = {}
        for p in paks:
            for f in p.files:
                if f.endswith('.umap') and '/Content/Levels/' in f:
                    names = {n for _, n, _ in pakfile.name_table(p.read(f))}
                    used = [assets[a] for a in assets if a in names]
                    if used:
                        name = f.rsplit('/', 1)[1][:-5]
                        maps[name] = {'path': f, 'slots': used,
                                      'group': 'Prototype' if '/Levels/Playable/' in f else 'Original'}
        cached = {'key': key, 'maps': dict(sorted(maps.items()))}
        os.makedirs(build.BUILD, exist_ok=True)
        json.dump(cached, open(MAP_INDEX_FILE, 'w'))
    _MAP_INDEX.update(key=key, maps=cached['maps'])
    return cached['maps']


def scope_arg(scope):
    if not scope:
        return None
    if scope not in map_index():
        raise ValueError('Unknown map: %s' % scope)
    return scope


def snapshot():
    return build.snapshot(CFG)


_RUNNING = {'at': 0.0, 'value': False}


def game_running(max_age=5.0):
    if time.time() - _RUNNING['at'] < max_age:
        return _RUNNING['value']
    _RUNNING.update(at=time.time(), value=_game_running())
    return _RUNNING['value']


def _game_running():
    try:
        out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq LemnisGate-Win64-Shipping.exe', '/NH'],
                             capture_output=True, text=True, timeout=10, creationflags=0x08000000).stdout
        return 'LemnisGate-Win64-Shipping' in out
    except (OSError, subprocess.SubprocessError):
        return False


def all_state(scope=None):
    names = map_index()[scope]['slots'] if scope else list(CFG['slots'])
    states = [slot_state(n, scope) for n in names]
    ue = os.path.join(build.DEFAULT_UE, 'Engine', 'Binaries', 'Win64', 'UE4Editor-Cmd.exe')
    built = read_json(BUILT_STATE, None)
    return {'slots': states,
            'dirty': built is None or built.get('snapshot') != snapshot(),
            'built_shared': bool(built and built.get('allow_shared')),
            'overrides': build.map_overrides(CFG),
            'status': {'ue': os.path.exists(ue), 'ue_path': build.DEFAULT_UE, 'game': build.find_game(),
                       'game_running': game_running()}}


# ---------------------------------------------------------------- ambientCG

def acg_search(query):
    params = {'type': 'Material', 'limit': '48', 'include': 'imageData,downloadData',
              'sort': query.get('sort', ['Popular'])[0], 'offset': query.get('offset', ['0'])[0]}
    for key in ('q', 'category'):
        if query.get(key, [''])[0]:
            params[key] = query[key][0]
    data = json.loads(fetch(ACG_API + '?' + urllib.parse.urlencode(params)))
    results = []
    for a in data.get('foundAssets', []):
        try:
            downloads = a['downloadFolders']['default']['downloadFiletypeCategories']['zip']['downloads']
        except KeyError:
            downloads = []
        res = [d['attribute'][:2] for d in downloads if d.get('attribute', '').endswith('-JPG')]
        if not res:
            continue
        results.append({'id': a['assetId'], 'name': a.get('displayName', a['assetId']),
                        'tags': a.get('tags', [])[:8], 'category': a.get('displayCategory', ''),
                        'preview': a.get('previewImage', {}).get('256-PNG', ''), 'resolutions': res})
    return {'total': data.get('numberOfResults', 0), 'results': results}


def acg_zip(asset_id, res):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, '%s_%s-JPG.zip' % (asset_id, res))
    if not os.path.exists(path):
        data = fetch('https://ambientcg.com/get?file=%s_%s-JPG.zip' % (asset_id, res))
        tmp = path + '.part'
        open(tmp, 'wb').write(data)
        os.replace(tmp, path)
    return path


def staged(asset_id, res):
    """Download and convert an ambientCG material once; returns the folder holding albedo/normal/orm.png."""
    d = os.path.join(STAGING, '%s_%s' % (asset_id, res))
    if os.path.exists(os.path.join(d, 'albedo.png')):
        return d
    with STAGE_LOCK:
        if not os.path.exists(os.path.join(d, 'albedo.png')):
            convert(zipfile.ZipFile(acg_zip(asset_id, res)), asset_id, d)
    return d


def convert(z, asset_id, d):
    """Write albedo, DirectX normal and ORM (R=AO, G=roughness, B=metalness) PNGs from an ambientCG zip."""
    found = {}
    for n in z.namelist():
        m = MAP_RE.search(n)
        if m and '/' not in n:
            found[m.group(1).lower()] = n
    if 'color' not in found:
        raise ValueError('%s has no colour map' % asset_id)

    def img(key, mode):
        return Image.open(io.BytesIO(z.read(found[key]))).convert(mode)

    albedo = img('color', 'RGB')
    size = albedo.size
    def channel(key, default):
        return img(key, 'L').resize(size) if key in found else Image.new('L', size, default)
    if 'normaldx' in found:
        normal = img('normaldx', 'RGB').resize(size)
    elif 'normalgl' in found:
        r, g, b = img('normalgl', 'RGB').resize(size).split()
        normal = Image.merge('RGB', (r, g.point(lambda v: 255 - v), b))  # OpenGL -> DirectX
    else:
        normal = None
    orm = Image.merge('RGB', (channel('ambientocclusion', 255), channel('roughness', 128), channel('metalness', 0)))

    tmp = d + '.part'
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    albedo.save(os.path.join(tmp, 'albedo.png'))
    if normal:
        normal.save(os.path.join(tmp, 'normal.png'))
    orm.save(os.path.join(tmp, 'orm.png'))
    shutil.rmtree(d, ignore_errors=True)
    os.replace(tmp, d)


SLOT_FILES = ('source.json', 'settings.json')


def slot_files(slot, scope=None):
    d = slot_dir(slot, scope)
    if not os.path.isdir(d):
        return []
    return [f for f in os.listdir(d) if os.path.splitext(f)[0].lower() in build.MAPS or f in SLOT_FILES]


def backup(slot, scope=None):
    """Copy the slot's current files aside so the change can be undone; returns the undo id."""
    undo_id = '%s_%d' % (slot, int(time.time() * 1000))
    dest = os.path.join(HISTORY, undo_id)
    os.makedirs(dest)
    for f in slot_files(slot, scope):
        shutil.copy2(os.path.join(slot_dir(slot, scope), f), dest)
    return undo_id


def undo(slot, undo_id, scope=None):
    src = os.path.join(HISTORY, undo_id)
    if not re.fullmatch(r'\w+_\d+', undo_id) or not undo_id.startswith(slot + '_') or not os.path.isdir(src):
        raise ValueError('Nothing to undo')
    d = slot_dir(slot, scope)
    for f in slot_files(slot, scope):
        os.remove(os.path.join(d, f))
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(src):
        shutil.copy2(os.path.join(src, f), d)


def assign(slot, asset_id, res, scope=None):
    src = staged(asset_id, res)
    undo_id = backup(slot, scope)
    d = slot_dir(slot, scope)
    os.makedirs(d, exist_ok=True)
    for f in slot_files(slot, scope):
        if f != 'settings.json':
            os.remove(os.path.join(d, f))
    for f in os.listdir(src):
        shutil.copy2(os.path.join(src, f), d)
    json.dump({'asset': asset_id, 'resolution': res, 'source': 'https://ambientcg.com/view?id=' + asset_id},
              open(os.path.join(d, 'source.json'), 'w'))
    settings_path = os.path.join(d, 'settings.json')
    if not os.path.exists(settings_path):
        json.dump({'tint_strength': 1.0 if slot in TINTED_BY_DEFAULT else 0.0, 'tile_size': 200},
                  open(settings_path, 'w'))
    return undo_id


def clear(slot, scope=None):
    undo_id = backup(slot, scope)
    for f in slot_files(slot, scope):
        os.remove(os.path.join(slot_dir(slot, scope), f))
    return undo_id


def save_settings(slot, values, scope=None):
    clean = {}
    for k, v in values.items():
        if k not in build.SETTINGS_KEYS:
            continue
        if k == 'color':
            clean[k] = [float(c) for c in v][:3]
        else:
            clean[k] = float(v)
    os.makedirs(slot_dir(slot, scope), exist_ok=True)
    json.dump(clean, open(os.path.join(slot_dir(slot, scope), 'settings.json'), 'w'))


# ---------------------------------------------------------------- build jobs

def run_job(title, commands, on_success=None):
    with JOB_LOCK:
        if JOB['running']:
            raise RuntimeError('A build is already running.')
        JOB.update(running=True, ok=None, title=title, log='')

    def worker():
        ok = True
        for cmd in commands:
            JOB['log'] += '$ ' + ' '.join(cmd[1:]) + '\n'
            p = subprocess.Popen([sys.executable, '-u'] + cmd[1:], cwd=HERE, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, errors='replace', creationflags=0x08000000)
            for line in p.stdout:
                JOB['log'] += line
            if p.wait() != 0:
                ok = False
                break
        if ok and on_success:
            on_success()
        JOB.update(running=False, ok=ok)
    threading.Thread(target=worker, daemon=True).start()


def start_build(kind, allow_shared):
    py = ['python']
    if kind in ('build', 'debug', 'uninstall') and game_running(max_age=0):
        raise RuntimeError('Close Lemnis Gate first: the game locks the texture pak while it is running.')
    if kind == 'build':
        cmd = py + ['build.py', 'build', '--install'] + (['--allow-shared'] if allow_shared else [])
        run_job('Build and install', [cmd])
    elif kind == 'debug':
        run_job('Debug textures', [py + ['make_debug_textures.py'],
                                   py + ['build.py', 'build', '--textures', os.path.join(build.BUILD, 'debug_textures'),
                                         '--allow-shared', '--install']])
    elif kind == 'uninstall':
        run_job('Uninstall', [py + ['build.py', 'uninstall']])
    elif kind == 'package':
        run_job('Package for friends', [py + ['build.py', 'package']])
    else:
        raise ValueError('Unknown job ' + kind)


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype='application/json'):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def slot_arg(self, name):
        if name not in CFG['slots']:
            raise ValueError('Unknown slot: %s' % name)
        return name

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        try:
            if url.path == '/':
                return self.send(200, open(PAGE, 'rb').read(), 'text/html; charset=utf-8')
            query = urllib.parse.parse_qs(url.query)
            scope = scope_arg(query.get('map', [''])[0])
            if url.path == '/api/slots':
                return self.send(200, all_state(scope))
            if url.path == '/api/maps':
                return self.send(200, map_index())
            if url.path == '/api/job':
                return self.send(200, JOB)
            if url.path == '/api/search':
                return self.send(200, acg_search(urllib.parse.parse_qs(url.query)))
            m = re.fullmatch(r'/(tex|stage)/(\w+)/(albedo|normal|orm)', url.path)
            if m:
                if m.group(1) == 'tex':
                    slot = self.slot_arg(m.group(2))
                    path = (build.find_maps(slot, slot_dir(slot, scope)) or build.find_maps(slot)).get(m.group(3))
                else:
                    path = os.path.join(STAGING, m.group(2), m.group(3) + '.png')
                if not path or not os.path.exists(path):
                    return self.send(404, {'error': 'no texture'})
                img = Image.open(path).convert('RGB')
                img.thumbnail((512, 512))
                buf = io.BytesIO()
                img.save(buf, 'PNG')
                return self.send(200, buf.getvalue(), 'image/png')
            self.send(404, {'error': 'not found'})
        except Exception as e:
            self.send(500, {'error': str(e)})

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
            result = {'ok': True}
            scope = scope_arg(body.get('map'))
            if self.path in ('/api/stage', '/api/assign'):
                asset = body['asset']
                if not re.fullmatch(r'[A-Za-z0-9_]+', asset) or body.get('resolution') not in RESOLUTIONS:
                    raise ValueError('Bad asset or resolution')
                if self.path == '/api/stage':
                    d = staged(asset, body['resolution'])
                    result.update(id=os.path.basename(d), maps=sorted(os.path.splitext(f)[0] for f in os.listdir(d)))
                else:
                    result['undo'] = assign(self.slot_arg(body['slot']), asset, body['resolution'], scope)
            elif self.path == '/api/settings':
                save_settings(self.slot_arg(body['slot']), body['settings'], scope)
            elif self.path == '/api/clear':
                result['undo'] = clear(self.slot_arg(body['slot']), scope)
            elif self.path == '/api/undo':
                undo(self.slot_arg(body['slot']), body['undo'], scope)
            elif self.path == '/api/job':
                start_build(body['kind'], bool(body.get('allow_shared')))
            else:
                return self.send(404, {'error': 'not found'})
            self.send(200, result)
        except Exception as e:
            self.send(400, {'error': str(e)})


def main():
    url = 'http://127.0.0.1:%d/' % PORT
    try:
        server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    except OSError:
        print('Texture Studio is already running - opening %s' % url)
        webbrowser.open(url)
        return
    print('Texture Studio running at %s  (Ctrl+C to stop)' % url)
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
