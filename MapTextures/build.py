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


def find_maps(slot):
    """Return {albedo|normal|orm: file} found in textures/<slot>/."""
    folder = os.path.join(TEXTURES, slot)
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


def slot_settings(cfg, name):
    s = dict(cfg['defaults'])
    s.update({k: cfg['slots'][name][k] for k in ('color', 'roughness', 'metallic')})
    maps = find_maps(name)
    s['tint_mean'] = albedo_mean(maps['albedo']) if 'albedo' in maps else 0.5
    if 'orm' in maps:
        # The ORM texture supplies roughness/metallic; parameters become multipliers.
        s.update(roughness=1.0, metallic=1.0)
    user = os.path.join(TEXTURES, name, 'settings.json')
    if os.path.exists(user):
        extra = json.load(open(user))
        unknown = set(extra) - set(SETTINGS_KEYS)
        if unknown:
            sys.exit('%s: unknown settings %s (allowed: %s)' % (user, sorted(unknown), ', '.join(SETTINGS_KEYS)))
        s.update(extra)
    return s, maps


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


def make_job(cfg, enabled, defaults):
    tex_root = '/Game/SalvageOps/Textures'
    textures = [{'src': os.path.join(defaults, k + '.png'), 'dest': '%s/Default/T_Default_%s' % (tex_root, k), 'kind': k}
                for k in MAPS]
    materials, instances = [], []
    for name in enabled:
        s, maps = slot_settings(cfg, name)
        for k in MAPS:
            if k in maps:
                dest = '%s/%s/T_%s_%s' % (tex_root, name, name, k)
                textures.append({'src': maps[k], 'dest': dest, 'kind': k})
                s[k] = dest
            else:
                s[k] = '%s/Default/T_Default_%s' % (tex_root, k)
        slot = cfg['slots'][name]
        (materials if slot['kind'] == 'material' else instances).append({'asset': slot['asset'], 'params': s})
    passthroughs = [p for p in cfg['passthroughs']
                    if p['when_slot'] in enabled and p.get('unless_slot') not in enabled]
    stubs = {path: s for path, s in cfg['stubs'].items()
             if passthroughs and s['unless_slot'] not in enabled}
    parent_defaults = dict(cfg['defaults'], color=[0.5, 0.5, 0.5], roughness=0.5, metallic=0.0, tint_mean=0.5,
                           **{k: '%s/Default/T_Default_%s' % (tex_root, k) for k in MAPS})
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
    if not enabled:
        sys.exit('No slots to build. Put albedo.png (and optionally normal.png / orm.png) in textures/<Slot>/ '
                 '- run "python build.py list".')
    print('Building slots: ' + ', '.join(enabled))
    editor, unrealpak = engine_tools(args.ue)

    print('[1/4] Preparing mod project')
    defaults = make_project()
    job = make_job(cfg, enabled, defaults)
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
    os.makedirs(OUT, exist_ok=True)
    pak = os.path.join(OUT, PAK_NAME)
    run([unrealpak, pak, '-create=' + resp], os.path.join(logs, 'pak.log'))
    print('Built %s (%d assets)' % (pak, len(assets)))
    if args.install:
        install(args)


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
    import zipfile
    dest = os.path.join(OUT, 'SalvageOps_MapTextures.zip')
    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in ('Install.bat', 'Uninstall.bat', 'installer.ps1', 'README.txt'):
            z.write(os.path.join(HERE, 'installer', f), f)
        z.write(pak, PAK_NAME)
    print('Packaged ' + dest)


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
