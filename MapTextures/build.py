"""Salvage Ops map textures: retexture the prototype (greybox) maps.

Drop textures into textures/<Slot>/ and run:
    python build.py list                 show slots and which have textures
    python build.py init                 create the textures/<Slot>/ folders
    python build.py build [--install]    cook the materials into a pak (and copy it into the game)
    python build.py install | uninstall  copy the built pak into the game, or remove it
    python build.py package              zip the installer + built pak in out/ to share with friends
    python build.py build --textures DIR use another textures folder (e.g. from make_debug_textures.py)

Requires Unreal Engine 4.26 (the game's engine version). Standard library only.
"""
import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TEXTURES = os.path.join(HERE, 'textures')
BUILD = os.path.join(HERE, '_build')
PROJECT = os.path.join(BUILD, 'LemnisGate')
OUT = os.path.join(HERE, 'out')
PAK_NAME = 'SalvageOps_MapTextures_P.pak'
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.tga', '.bmp', '.psd', '.exr')
MAPS = ('albedo', 'normal', 'orm')
DEFAULT_UE = r'C:\Program Files\Epic Games\UE_4.26'
SETTINGS_KEYS = ('tile_size', 'blend_sharpness', 'tint_strength', 'normal_strength', 'roughness', 'metallic', 'color')


def load_config():
    return json.load(open(os.path.join(HERE, 'slots.json')))


def find_maps(slot, folder=None):
    """Return {albedo|normal|orm: file} found in textures/<slot>/ (or `folder`)."""
    folder = folder or os.path.join(TEXTURES, slot)
    found = {}
    if os.path.isdir(folder):
        for f in sorted(os.listdir(folder)):
            stem, ext = os.path.splitext(f)
            if ext.lower() in IMAGE_EXT and stem.lower() in MAPS:
                found[stem.lower()] = os.path.join(folder, f)
    return found


def albedo_mean(path):
    """Average linear luminance of a texture, so tinting keeps the slot's original brightness.
    Needs Pillow; without it the default 0.5 (a mid-grey texture) is assumed."""
    try:
        from PIL import Image
    except ImportError:
        return 0.5
    img = Image.open(path).convert('RGB').resize((64, 64))
    lin = lambda v: (v / 255.0) / 12.92 if v <= 10 else ((v / 255.0 + 0.055) / 1.055) ** 2.4
    lums = [0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b) for r, g, b in img.getdata()]
    return max(sum(lums) / len(lums), 0.01)


def slot_settings(cfg, name, folder=None):
    folder = folder or os.path.join(TEXTURES, name)
    s = dict(cfg['defaults'])
    s.update({k: cfg['slots'][name][k] for k in ('color', 'roughness', 'metallic')})
    maps = find_maps(name, folder)
    s['tint_mean'] = albedo_mean(maps['albedo']) if 'albedo' in maps else 0.5
    if 'orm' in maps:
        # The ORM texture supplies roughness/metallic; parameters become multipliers.
        s.update(roughness=1.0, metallic=1.0)
    user = os.path.join(folder, 'settings.json')
    if os.path.exists(user):
        extra = json.load(open(user))
        unknown = set(extra) - set(SETTINGS_KEYS)
        if unknown:
            sys.exit('%s: unknown settings %s (allowed: %s)' % (user, sorted(unknown), ', '.join(SETTINGS_KEYS)))
        s.update(extra)
    return s, maps


FLOOR_DIR = 'floor'
SURFACE_KEYS = ('tile_size', 'tint_strength', 'tint_mean', 'normal_strength', 'roughness', 'metallic')


def floor_settings(cfg, name, folder, wall):
    """Settings and maps for upward-facing surfaces: <slot folder>/floor/ if it has textures, otherwise the wall set.
    Floor settings start from the wall's (colour and edge blend are shared) and floor/settings.json overrides them."""
    floor_folder = os.path.join(folder, FLOOR_DIR)
    maps = find_maps(name, floor_folder)
    if not maps:
        return {k: wall[k] for k in SURFACE_KEYS}, {}
    s = {k: wall[k] for k in SURFACE_KEYS}
    s['tint_mean'] = albedo_mean(maps['albedo']) if 'albedo' in maps else 0.5
    s['roughness'], s['metallic'] = (1.0, 1.0) if 'orm' in maps else (cfg['slots'][name]['roughness'], cfg['slots'][name]['metallic'])
    user = os.path.join(floor_folder, 'settings.json')
    if os.path.exists(user):
        extra = json.load(open(user))
        unknown = set(extra) - set(SETTINGS_KEYS)
        if unknown:
            sys.exit('%s: unknown settings %s (allowed: %s)' % (user, sorted(unknown), ', '.join(SETTINGS_KEYS)))
        s.update({k: v for k, v in extra.items() if k in SURFACE_KEYS})
    return s, maps


# ---------------------------------------------------------------- per-map overrides
# textures/_maps/<Map>/<Slot>/ holds a texture set used only by that map. The build gives the map its own copy of
# the slot's material at a path of exactly the same length, and patches the map's name table to point at it.

MAP_DIR = '_maps'


def map_folder(map_name, slot):
    return os.path.join(TEXTURES, MAP_DIR, map_name, slot)


def map_overrides(cfg):
    """{map: [slot, ...]} for every per-map folder that has textures."""
    root = os.path.join(TEXTURES, MAP_DIR)
    found = {}
    if os.path.isdir(root):
        for m in sorted(os.listdir(root)):
            slots = [s for s in cfg['slots'] if find_maps(s, map_folder(m, s))]
            if slots:
                found[m] = slots
    return found


def map_asset(map_name, asset):
    """Same-length package path for a map's own copy of `asset`, e.g. /Game/SOM/CTF_Arches/xxxx/MI_Name."""
    folder, name = asset.rsplit('/', 1)
    prefix = '/Game/SOM/%s/' % map_name
    pad = len(folder) - len(prefix)
    if pad < 1 or not re.fullmatch(r'\w+', map_name):
        raise ValueError('Map name %r is too long or invalid for a per-map override of %s' % (map_name, asset))
    return prefix + 'x' * pad + '/' + name


def map_package(paks, map_name):
    hits = [k for p in paks for k in p.files if k.endswith('/' + map_name + '.umap') and '/Content/Levels/' in k]
    if not hits:
        raise KeyError('No map called %s in the game files' % map_name)
    return hits[0]


# ---------------------------------------------------------------- game / engine discovery

def find_game():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as k:
            steam = winreg.QueryValueEx(k, 'SteamPath')[0]
    except OSError:
        return None
    libs = [steam]
    vdf = os.path.join(steam, 'steamapps', 'libraryfolders.vdf')
    if os.path.exists(vdf):
        for line in open(vdf, encoding='utf-8', errors='ignore'):
            parts = line.strip().split('"')
            if len(parts) >= 4 and parts[1] == 'path':
                libs.append(parts[3].replace('\\\\', '\\'))
    for lib in libs:
        game = os.path.join(lib, 'steamapps', 'common', 'LemnisGate')
        if os.path.exists(os.path.join(game, 'LemnisGate', 'Content', 'Paks')):
            return os.path.normpath(game)
    return None


def engine_tools(ue):
    bin_dir = os.path.join(ue, 'Engine', 'Binaries', 'Win64')
    editor, pak = os.path.join(bin_dir, 'UE4Editor-Cmd.exe'), os.path.join(bin_dir, 'UnrealPak.exe')
    for f in (editor, pak):
        if not os.path.exists(f):
            sys.exit('Not found: %s\nPass --ue with your Unreal Engine 4.26 folder.' % f)
    return editor, pak


# ---------------------------------------------------------------- project setup

def write_png(path, w, h, rgb):
    raw = b''.join(b'\x00' + bytes(rgb) * w for _ in range(h))
    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    data = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
    open(path, 'wb').write(data)


def ini_section(path, name):
    lines, on = [], False
    for line in open(path, encoding='utf-8-sig'):
        if line.startswith('['):
            on = line.strip() == '[%s]' % name
        if on:
            lines.append(line.rstrip('\n'))
    return '\n'.join(lines)


def make_project():
    for sub in ('Content', os.path.join('Saved', 'Cooked')):
        shutil.rmtree(os.path.join(PROJECT, sub), ignore_errors=True)
    os.makedirs(os.path.join(PROJECT, 'Config'), exist_ok=True)
    os.makedirs(os.path.join(PROJECT, 'Content'), exist_ok=True)
    json.dump({'FileVersion': 3, 'EngineAssociation': '4.26', 'Category': '', 'Description': '',
               'Plugins': [{'Name': 'PythonScriptPlugin', 'Enabled': True},
                           {'Name': 'EditorScriptingUtilities', 'Enabled': True}]},
              open(os.path.join(PROJECT, 'LemnisGate.uproject'), 'w'), indent=1)
    # Shader permutations must match the game, so copy its renderer settings.
    game_ini = os.path.join(REPO, 'PakContent', 'LemnisGate', 'Config', 'DefaultEngine.ini')
    renderer = ini_section(game_ini, '/Script/Engine.RendererSettings')
    open(os.path.join(PROJECT, 'Config', 'DefaultEngine.ini'), 'w').write(
        renderer + '\n\n[/Script/WindowsTargetPlatform.WindowsTargetSettings]\n'
        '-TargetedRHIs=PCD3D_SM4\n+TargetedRHIs=PCD3D_SM5\n')
    open(os.path.join(PROJECT, 'Config', 'DefaultGame.ini'), 'w').write(
        '[/Script/EngineSettings.GeneralProjectSettings]\nProjectName=LemnisGate\n\n'
        '[/Script/UnrealEd.ProjectPackagingSettings]\nbShareMaterialShaderCode=False\n'
        'bSharedMaterialNativeLibraries=False\nUsePakFile=True\n'
        '+DirectoriesToAlwaysCook=(Path="/Game")\n')
    defaults = os.path.join(BUILD, 'defaults')
    os.makedirs(defaults, exist_ok=True)
    write_png(os.path.join(defaults, 'albedo.png'), 4, 4, (188, 188, 188))  # mid grey: tint shows the slot colour
    write_png(os.path.join(defaults, 'normal.png'), 4, 4, (128, 128, 255))
    write_png(os.path.join(defaults, 'orm.png'), 4, 4, (255, 255, 255))     # parameters drive roughness/metallic
    return defaults


def make_job(cfg, enabled, defaults, overrides):
    tex_root = '/Game/SalvageOps/Textures'
    textures = [{'src': os.path.join(defaults, k + '.png'), 'dest': '%s/Default/T_Default_%s' % (tex_root, k), 'kind': k}
                for k in MAPS]
    materials, instances = [], []

    def add(slot_name, asset, folder, tex_folder, tex_prefix):
        folder = folder or os.path.join(TEXTURES, slot_name)
        s, maps = slot_settings(cfg, slot_name, folder)
        for k in MAPS:
            if k in maps:
                dest = '%s/%s/%s_%s' % (tex_root, tex_folder, tex_prefix, k)
                textures.append({'src': maps[k], 'dest': dest, 'kind': k})
                s[k] = dest
            else:
                s[k] = '%s/Default/T_Default_%s' % (tex_root, k)
        floor, floor_maps = floor_settings(cfg, slot_name, folder, s)
        for k in MAPS:
            if k in floor_maps:
                dest = '%s/%s/%s_floor_%s' % (tex_root, tex_folder, tex_prefix, k)
                textures.append({'src': floor_maps[k], 'dest': dest, 'kind': k})
                floor[k] = dest
            else:
                floor[k] = s[k] if not floor_maps else '%s/Default/T_Default_%s' % (tex_root, k)
        s['floor'] = floor
        kind = cfg['slots'][slot_name]['kind']
        (materials if kind == 'material' else instances).append({'asset': asset, 'params': s})

    for name in enabled:
        add(name, cfg['slots'][name]['asset'], None, name, 'T_' + name)
    for map_name, slots in overrides.items():
        for name in slots:
            add(name, map_asset(map_name, cfg['slots'][name]['asset']), map_folder(map_name, name),
                'Maps/%s/%s' % (map_name, name), 'T_%s_%s' % (map_name, name))
    passthroughs = [p for p in cfg['passthroughs']
                    if p['when_slot'] in enabled and p.get('unless_slot') not in enabled]
    stubs = {path: s for path, s in cfg['stubs'].items()
             if passthroughs and s['unless_slot'] not in enabled}
    parent_defaults = dict(cfg['defaults'], color=[0.5, 0.5, 0.5], roughness=0.5, metallic=0.0, tint_mean=0.5,
                           **{k: '%s/Default/T_Default_%s' % (tex_root, k) for k in MAPS})
    parent_defaults['floor'] = {k: parent_defaults[k] for k in SURFACE_KEYS + MAPS}
    return {'parent_material': cfg['parent_material'], 'parent_defaults': parent_defaults,
            'textures': textures, 'materials': materials, 'instances': instances,
            'passthroughs': passthroughs, 'stubs': stubs,
            'result_file': os.path.join(BUILD, 'result.json')}


# ---------------------------------------------------------------- build steps

def run(cmd, log, env=None):
    print('  > ' + os.path.basename(cmd[0]) + ' ' + ' '.join(cmd[1:3]) + ' ...  (log: %s)' % log)
    with open(log, 'w', encoding='utf-8', errors='replace') as f:
        code = subprocess.call(cmd, stdout=f, stderr=subprocess.STDOUT, env=env)
    if code != 0:
        tail = open(log, encoding='utf-8', errors='replace').read().splitlines()[-40:]
        sys.exit('\n'.join(tail) + '\n\nFailed (exit %d). Full log: %s' % (code, log))


def cooked_files(asset):
    rel = asset[len('/Game/'):].replace('/', os.sep)
    base = os.path.join(PROJECT, 'Saved', 'Cooked', 'WindowsNoEditor', 'LemnisGate', 'Content', rel)
    files = [base + ext for ext in ('.uasset', '.uexp', '.ubulk') if os.path.exists(base + ext)]
    if not files:
        sys.exit('Cook did not produce %s - check the cook log.' % asset)
    return files


def build(args):
    cfg = load_config()
    textured = [n for n in cfg['slots'] if find_maps(n)]
    if args.only:
        textured = [n for n in textured if n in args.only.split(',')]
    shared = [n for n in textured if cfg['slots'][n]['shared']]
    if shared and not args.allow_shared:
        print('Skipping %s: these also change the shipped maps (pass --allow-shared to include).' % ', '.join(shared))
    enabled = [n for n in textured if n not in shared or args.allow_shared]
    overrides = map_overrides(cfg)
    if not enabled and not overrides:
        sys.exit('No slots to build. Put albedo.png (and optionally normal.png / orm.png) in textures/<Slot>/ '
                 '- run "python build.py list".')
    if enabled:
        print('Building slots: ' + ', '.join(enabled))
    for m, slots in overrides.items():
        print('Per-map overrides for %s: %s' % (m, ', '.join(slots)))
    editor, unrealpak = engine_tools(args.ue)
    patched = patch_maps(cfg, overrides, args.game or find_game()) if overrides else []
    snap = snapshot(cfg)

    print('[1/4] Preparing mod project')
    defaults = make_project()
    job = make_job(cfg, enabled, defaults, overrides)
    job_file = os.path.join(BUILD, 'job.json')
    json.dump(job, open(job_file, 'w'), indent=1)
    if os.path.exists(job['result_file']):
        os.remove(job['result_file'])
    logs = os.path.join(BUILD, 'logs')
    os.makedirs(logs, exist_ok=True)
    uproject = os.path.join(PROJECT, 'LemnisGate.uproject')
    common = ['-unattended', '-nosplash', '-nop4', '-utf8output']

    print('[2/4] Creating materials in Unreal (first run compiles engine shaders and can take a long time)')
    run([editor, uproject, '-run=pythonscript', '-script=' + os.path.join(HERE, 'ue', 'build_materials.py')] + common,
        os.path.join(logs, 'materials.log'), env=dict(os.environ, SALVAGE_JOB=job_file))
    result = json.load(open(job['result_file'])) if os.path.exists(job['result_file']) else {}
    if not result.get('ok'):
        sys.exit('Material script failed:\n%s\nLog: %s' % (result.get('error', 'no result written'),
                                                            os.path.join(logs, 'materials.log')))

    print('[3/4] Cooking for Windows')
    run([editor, uproject, '-run=cook', '-targetplatform=WindowsNoEditor', '-unversioned'] + common,
        os.path.join(logs, 'cook.log'))

    print('[4/4] Packing')
    assets = ([job['parent_material']] + [m['asset'] for m in job['materials'] + job['instances'] + job['passthroughs']]
              + [t['dest'] for t in job['textures']])
    resp = os.path.join(BUILD, 'pak_files.txt')
    with open(resp, 'w') as f:
        for asset in assets:
            for src in cooked_files(asset):
                rel = os.path.relpath(src, os.path.join(PROJECT, 'Saved', 'Cooked', 'WindowsNoEditor')).replace(os.sep, '/')
                f.write('"%s" "../../../%s"\n' % (src, rel))
        for src, rel in patched:
            f.write('"%s" "../../../%s"\n' % (src, rel))
    os.makedirs(OUT, exist_ok=True)
    pak = os.path.join(OUT, PAK_NAME)
    run([unrealpak, pak, '-create=' + resp], os.path.join(logs, 'pak.log'))
    print('Built %s (%d assets, %d patched maps)' % (pak, len(assets), len(patched)))
    default_textures = os.path.normcase(TEXTURES) == os.path.normcase(os.path.join(HERE, 'textures'))
    json.dump({'snapshot': snap if default_textures else None, 'allow_shared': args.allow_shared},
              open(BUILT_STATE, 'w'))
    if args.install:
        install(args)


def patch_maps(cfg, overrides, game):
    """Write each overridden map's header with its material references redirected; returns [(file, pak path)]."""
    import pakfile
    if not game:
        sys.exit('Per-map overrides need the game files. Pass --game with the Lemnis Gate folder.')
    paks = pakfile.game_paks(game)
    out = []
    for map_name, slots in overrides.items():
        rel = map_package(paks, map_name)
        original = pakfile.find(paks, rel)
        names = {n for _, n, _ in pakfile.name_table(original)}
        unused = [s for s in slots if cfg['slots'][s]['asset'] not in names]
        if unused:
            sys.exit('%s does not use %s, so it cannot be overridden there.' % (map_name, ', '.join(unused)))
        mapping = {cfg['slots'][s]['asset']: map_asset(map_name, cfg['slots'][s]['asset']) for s in slots}
        dest = os.path.join(BUILD, 'patched', rel.replace('/', os.sep))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, 'wb').write(pakfile.replace_names(original, mapping))
        out.append((dest, rel))
    return out


BUILT_STATE = os.path.join(BUILD, 'built_state.json')


def snapshot(cfg):
    """What a build of textures/ contains: each slot's texture files (size + mtime) and settings, including per-map
    overrides. Saved after every build so tools can tell whether the installed pak is up to date."""
    snap = {}
    for scope in [None] + list(map_overrides(cfg)):
        for name in cfg['slots']:
            folder = map_folder(scope, name) if scope else os.path.join(TEXTURES, name)
            maps = find_maps(name, folder)
            if maps:
                for sub, sub_maps in (('', maps), ('/floor', find_maps(name, os.path.join(folder, FLOOR_DIR)))):
                    if not sub_maps:
                        continue
                    settings = os.path.join(folder + sub.replace('/', os.sep), 'settings.json')
                    snap[(scope + '/' if scope else '') + name + sub] = {
                        'files': {k: [os.path.getsize(f), int(os.path.getmtime(f))] for k, f in sub_maps.items()},
                        'settings': json.load(open(settings)) if os.path.exists(settings) else {}}
    return snap


def mods_dir(args):
    game = args.game or find_game()
    if not game:
        sys.exit('Could not find Lemnis Gate. Pass --game with the game folder (the one containing LemnisGate.exe).')
    return os.path.join(game, 'LemnisGate', 'Content', 'Paks')


def install(args):
    pak = os.path.join(OUT, PAK_NAME)
    if not os.path.exists(pak):
        sys.exit('Nothing built yet - run "python build.py build" first.')
    dest = mods_dir(args)
    shutil.copy2(pak, dest)
    print('Installed to ' + os.path.join(dest, PAK_NAME))


def uninstall(args):
    removed = False
    for target in (os.path.join(mods_dir(args), PAK_NAME), os.path.join(mods_dir(args), '~mods', PAK_NAME)):
        if os.path.exists(target):
            os.remove(target)
            print('Removed ' + target)
            removed = True
    if not removed:
        print('Not installed.')


def package(args):
    pak = os.path.join(OUT, PAK_NAME)
    if not os.path.exists(pak):
        sys.exit('Nothing built yet - run "python build.py build" first.')
    import glob
    import zipfile
    dest = os.path.join(OUT, 'SalvageOps_MapTextures.zip')
    # Plus the Map Kit's edited maps (mapkit/kit.py build), which everyone in a match needs too.
    paks = sorted(glob.glob(os.path.join(OUT, 'SalvageOps_*_P.pak')))
    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in ('Install.bat', 'Uninstall.bat', 'installer.ps1', 'README.txt'):
            z.write(os.path.join(HERE, 'installer', f), f)
        for p in paks:
            z.write(p, os.path.basename(p))
    print('Packaged %s (%s)' % (dest, ', '.join(os.path.basename(p) for p in paks)))


def init(args):
    cfg = load_config()
    for name, slot in cfg['slots'].items():
        folder = os.path.join(TEXTURES, name)
        os.makedirs(folder, exist_ok=True)
        open(os.path.join(folder, 'about.txt'), 'w').write(
            '%s\nReplaces: %s\nUsed in %d prototype maps. %s%s\n\n'
            'Put albedo.png here (optionally normal.png and orm.png).\n'
            'Optional settings.json, e.g. {"tile_size": 300, "tint_strength": 0.5}\n' % (
                name, slot['asset'], slot['proto_maps'], slot['note'],
                '\nAffects shipped maps: needs --allow-shared.' if slot['shared'] else ''))
    print('Created %d folders in %s' % (len(cfg['slots']), TEXTURES))


def list_slots(args):
    cfg = load_config()
    print('%-17s %-6s %-22s %s' % ('Slot', 'Maps', 'Textures', 'Notes'))
    for name, slot in cfg['slots'].items():
        maps = find_maps(name)
        print('%-17s %-6d %-22s %s%s' % (name, slot['proto_maps'], ', '.join(maps) or '-',
                                        '[shared] ' if slot['shared'] else '', slot['note']))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', choices=('list', 'init', 'build', 'install', 'uninstall', 'package'))
    ap.add_argument('--ue', default=DEFAULT_UE, help='Unreal Engine 4.26 folder (default: %(default)s)')
    ap.add_argument('--game', help='Lemnis Gate folder (default: found through Steam)')
    ap.add_argument('--install', action='store_true', help='copy the pak into the game after building')
    ap.add_argument('--allow-shared', action='store_true', help='include slots that also change shipped maps')
    ap.add_argument('--textures', help='textures folder (default: textures/ next to this script)')
    ap.add_argument('--only', help='comma-separated slots to build (default: every slot with textures)')
    args = ap.parse_args()
    if args.textures:
        global TEXTURES
        TEXTURES = os.path.abspath(args.textures)
    {'list': list_slots, 'init': init, 'build': build, 'install': install, 'uninstall': uninstall, 'package': package}[args.command](args)


if __name__ == '__main__':
    main()
