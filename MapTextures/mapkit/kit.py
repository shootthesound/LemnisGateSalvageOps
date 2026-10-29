"""Lemnis Gate Map Kit: edit the game's maps in the Unreal 4.26 editor.

    python mapkit/kit.py setup              generate the editor project, compile its stand-in C++ module and
                                            create stand-ins for the game's gameplay Blueprints
    python mapkit/kit.py materials          (re)make editor look-alikes of the game's materials (part of setup)
    python mapkit/kit.py meshes             (re)create editor copies of the game's meshes (part of setup)
    python mapkit/kit.py terrain            (re)make the terrain materials (part of setup)
    python mapkit/kit.py library            (re)make the object library level, /Game/MapKit/ObjectLibrary
    python mapkit/kit.py import <Map>       recreate a game map (e.g. CTF_Arches) as an editable level
        --as <Slot>                         ...saved as another map, e.g. import CTF_Box --as CTF_Fork to start a
                                            new CTF map in CTF_Fork's place (the game's map list is fixed)
        --gameplay-only                     ...without its geometry: objectives, spawns, lights and sky only
    python mapkit/kit.py new <Name> --from <Map> [--mode CAP] [--title "MY MAP"] [--gameplay-only]
                                            a new map of your own, added to the game's map list (any mode)
    python mapkit/kit.py mode <Map> <Mode>  play a map (yours or the game's) in another mode: CTF, CAP, DM, DST,
                                            EVA or ASN
    python mapkit/kit.py list               your maps and mode changes
    python mapkit/kit.py remove <Name>      delete one of your maps (frees its slot)
    python mapkit/kit.py light <Map|Name> [--quality Medium]
                                            bake lighting for a level (Lightmass; packed with it from then on)
    python mapkit/kit.py builder [<Map>]    open a map in the map builder (fly around, select, move, copy, delete)
    python mapkit/kit.py apply <Map>        apply the builder's saved edits to the map
    python mapkit/kit.py play <Map>         apply, re-bake if baked, build, install and start the game
    python mapkit/kit.py build [--install]  cook the edited levels into SalvageOps_Maps_P.pak

The project (_build/MapKit) holds stand-ins under the game's own asset paths. A cooked map only references them by
path, so only the map files go into the pak and the game supplies the real Blueprints, meshes and materials.
"""
import argparse
import json
import os
import re
import shutil
import struct
import time
import zlib
import subprocess
import sys

KIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(KIT))
import build  # noqa: E402
import pakfile  # noqa: E402
import bpinfo  # noqa: E402
import mapgeo  # noqa: E402
import maplist  # noqa: E402
import foliage  # noqa: E402
import materials  # noqa: E402
import meshes  # noqa: E402
import modes  # noqa: E402
import terrain  # noqa: E402
import textures  # noqa: E402
import scene  # noqa: E402
import verify  # noqa: E402

PROJECT = os.path.join(build.BUILD, 'MapKit')
UPROJECT = os.path.join(PROJECT, 'LemnisGate.uproject')
LOGS = os.path.join(build.BUILD, 'logs')
COMMON = ['-unattended', '-nosplash', '-nop4', '-utf8output']


def run(cmd, log, env=None):
    os.makedirs(LOGS, exist_ok=True)
    build.run(cmd, os.path.join(LOGS, log), env)


def write_project():
    os.makedirs(os.path.join(PROJECT, 'Config'), exist_ok=True)
    os.makedirs(os.path.join(PROJECT, 'Content'), exist_ok=True)
    src = os.path.join(PROJECT, 'Source')
    shutil.rmtree(src, ignore_errors=True)
    # Fresh timestamps, or UnrealHeaderTool may judge its generated code up to date and miss new functions.
    shutil.copytree(os.path.join(KIT, 'Source'), src, copy_function=shutil.copy)
    json.dump({'FileVersion': 3, 'EngineAssociation': '4.26', 'Category': '', 'Description': '',
               'Modules': [{'Name': 'LemnisGate', 'Type': 'Runtime', 'LoadingPhase': 'Default'},
                           {'Name': 'MapBuilder', 'Type': 'Runtime', 'LoadingPhase': 'Default'}],
               'Plugins': [{'Name': 'PythonScriptPlugin', 'Enabled': True},
                           {'Name': 'EditorScriptingUtilities', 'Enabled': True}]},
              open(UPROJECT, 'w'), indent=1)
    game_ini = os.path.join(build.REPO, 'PakContent', 'LemnisGate', 'Config', 'DefaultEngine.ini')
    open(os.path.join(PROJECT, 'Config', 'DefaultEngine.ini'), 'w').write(
        build.ini_section(game_ini, '/Script/Engine.RendererSettings') +
        '\n\n[/Script/Engine.Engine]\nWorldSettingsClassName=/Script/LemnisGate.ConvergenceWorldSettings\n'
        '\n[/Script/WindowsTargetPlatform.WindowsTargetSettings]\n-TargetedRHIs=PCD3D_SM4\n+TargetedRHIs=PCD3D_SM5\n'
        # The editor opens on the object library rather than an empty template level.
        '\n[/Script/EngineSettings.GameMapsSettings]\nEditorStartupMap=/Game/MapKit/ObjectLibrary.ObjectLibrary\n')
    write_game_ini()


# Content the pak carries: the levels and the kit's own assets. Everything else in the project is an editor copy of
# the game's (stand-ins, meshes, look-alike materials), which the cook leaves alone: levels still reference it by
# path, and the game supplies the real thing.
SHIPPED = ('Levels', 'SalvageOps')


def write_game_ini():
    content = os.path.join(PROJECT, 'Content')
    never = sorted(d for d in os.listdir(content) if os.path.isdir(os.path.join(content, d)) and d not in SHIPPED) \
        if os.path.isdir(content) else []
    open(os.path.join(PROJECT, 'Config', 'DefaultGame.ini'), 'w').write(
        '[/Script/EngineSettings.GeneralProjectSettings]\nProjectName=LemnisGate\n\n'
        '[/Script/UnrealEd.ProjectPackagingSettings]\nbShareMaterialShaderCode=False\n'
        'bSharedMaterialNativeLibraries=False\nUsePakFile=True\n'
        + ''.join('+DirectoriesToNeverCook=(Path="/Game/%s")\n' % d for d in never))


def compile_module(ue):
    bat = os.path.join(ue, 'Engine', 'Build', 'BatchFiles', 'Build.bat')
    run([bat, 'LemnisGateEditor', 'Win64', 'Development', '-Project=' + UPROJECT, '-WaitMutex', '-NoHotReload'],
        'mapkit_compile.log')


def game_maps(paks):
    files = sorted({f for p in paks for f in p.files})
    return [f for f in files if f.endswith('.umap') and '/Levels/Menu/' not in f]


def blueprint_catalog(paks):
    """Every gameplay Blueprint the game's maps place (plus their parents and component Blueprints), with the
    variables maps set on them: float/int/bool values and references to the actor's own components, plus the
    component events the level binds to the Blueprint's functions."""
    roots, variables, links, values, placed, events = set(), {}, {}, {}, {}, {}
    for m in game_maps(paks):
        sc = scene.Scene(paks, m)
        pkg = sc.pkg
        bp_classes = {}
        for imp in pkg.imports:
            if imp['class'] == 'BlueprintGeneratedClass':
                package = pkg.imports[-imp['outer'] - 1]['name']
                if package.startswith('/Game/'):
                    roots.add(package)
                    bp_classes[imp['name']] = package
        for i, e in enumerate(pkg.exports, 1):
            if e['class'] in bp_classes:
                props = sc.tagged(i)
                placed[bp_classes[e['class']]] = placed.get(bp_classes[e['class']], 0) + 1
                found = variables.setdefault(bp_classes[e['class']], {})
                for name, (ptype, _) in props.items():
                    if ptype in VARIABLE_TYPES:
                        found[name] = VARIABLE_TYPES[ptype]
                for name, (component, cls) in sc.component_refs(i, props).items():
                    if cls and cls != 'array:':
                        found[name] = 'array:object:' + cls[6:] if cls.startswith('array:') else 'object:' + cls
                        links.setdefault(bp_classes[e['class']], {})[name] = component
                for prop, functions in sc.events(i, i).items():
                    events.setdefault(bp_classes[e['class']], {})[prop] = ','.join(functions)
                for j, c in enumerate(pkg.exports, 1):
                    if c['outer'] == i:
                        for prop, text in sc.construction_values(j).items():
                            key = '%s.%s' % (c['name'], prop)
                            values.setdefault(bp_classes[e['class']], {}).setdefault(key, []).append(text)
                        for prop, functions in sc.events(j, i).items():
                            events.setdefault(bp_classes[e['class']], {})['%s.%s' % (c['name'], prop)] = ','.join(functions)
    cat = bpinfo.catalog(paks, sorted(roots))
    for path, bp in cat.items():
        if bp:
            bp['variables'] = variables.get(path, {})
            bp['links'] = links.get(path, {})
            bp['events'] = events.get(path, {})
            # Values every placed copy agrees on become the Blueprint's; the rest are set per actor on import.
            bp['construction_values'] = {k: v[0] for k, v in values.get(path, {}).items()
                                         if len(set(v)) == 1 and len(v) == placed.get(path)}
    return cat


VARIABLE_TYPES = {'FloatProperty': 'float', 'IntProperty': 'int', 'BoolProperty': 'bool', 'NameProperty': 'name',
                  'LinearColor': 'struct:LinearColor', 'Color': 'struct:Color', 'Vector': 'struct:Vector',
                  'Rotator': 'struct:Rotator'}


def copy_materials():
    """The texture project's built materials, so the slots look textured in the editor."""
    src = os.path.join(build.PROJECT, 'Content')
    if not os.path.isdir(src):
        print('  (no built textures yet - slots will be untextured in the editor)')
        return
    shutil.copytree(src, os.path.join(PROJECT, 'Content'), dirs_exist_ok=True)


def editor_script(args, script, job, log):
    editor, _ = build.engine_tools(args.ue)
    job['result_file'] = os.path.join(build.BUILD, 'mapkit_result.json')
    job_file = os.path.join(build.BUILD, 'mapkit_job.json')
    json.dump(job, open(job_file, 'w'), indent=1)
    if os.path.exists(job['result_file']):
        os.remove(job['result_file'])
    # The commandlet exits non-zero on any logged error (e.g. one Blueprint failing to compile), so the result file
    # the script writes decides success.
    print('  > %s  (log: %s)' % (script, os.path.join(LOGS, log)))
    os.makedirs(LOGS, exist_ok=True)
    with open(os.path.join(LOGS, log), 'w', encoding='utf-8', errors='replace') as f:
        subprocess.call([editor, UPROJECT, '-run=pythonscript', '-script=' + os.path.join(KIT, 'ue', script)] + COMMON,
                        stdout=f, stderr=subprocess.STDOUT, env=dict(os.environ, MAPKIT_JOB=job_file))
    result = json.load(open(job['result_file'])) if os.path.exists(job['result_file']) else {}
    if not result.get('ok'):
        sys.exit('%s failed:\n%s\nLog: %s' % (script, result.get('error', 'no result written'), os.path.join(LOGS, log)))
    return result


def setup(args):
    paks = pakfile.game_paks(args.game or build.find_game())
    print('[1/7] Writing the Map Kit project')
    write_project()
    copy_materials()
    print('[2/7] Compiling the stand-in C++ module (needs Visual Studio 2019 or later with C++)')
    compile_module(args.ue)
    print('[3/7] Reading the game\'s gameplay Blueprints')
    cat = blueprint_catalog(paks)
    json.dump(cat, open(os.path.join(build.BUILD, 'mapkit_blueprints.json'), 'w'), indent=1)
    print('  %d Blueprints' % len(cat))
    print('[4/7] Making editor look-alikes of the game\'s materials, then copying its meshes (the stand-ins use them)')
    make_materials(args, paks, cat)
    import_meshes(args, paks, cat)
    print('[5/7] Creating Blueprint stand-ins in the editor')
    make_stubs(args, cat)
    print('[6/7] Making the terrain materials')
    make_terrain(args)
    print('[7/7] Laying out the object library')
    make_library(args, paks, cat)
    print('Done: %s' % UPROJECT)


# Terrain sets: (flat ground, slopes), ambientCG CC0 textures.
TERRAIN_SETS = {'Grassland': ('Grass004', 'Rock030'), 'Desert': ('Ground080', 'Rock030'),
                'Dirt': ('Ground048', 'Ground068'), 'Snow': ('Snow004', 'Rock035'), 'Rocky': ('Gravel022', 'Rock035')}
TERRAIN_RES = '1K'
TERRAIN_ROOT = '/Game/SalvageOps/Terrain'


def terrain_material(game_material):
    """The kit terrain set standing in for one of the game's landscape materials (theirs can't be rebuilt)."""
    name = (game_material or '').lower()
    for key, terrain_set in (('desert', 'Desert'), ('sand', 'Desert'), ('snow', 'Snow'), ('ice', 'Snow'),
                             ('rock', 'Rocky'), ('cliff', 'Rocky'), ('dirt', 'Dirt'), ('mud', 'Dirt')):
        if key in name:
            return '%s/MI_Terrain_%s' % (TERRAIN_ROOT, terrain_set)
    return '%s/MI_Terrain_Grassland' % TERRAIN_ROOT


def make_terrain(args):
    import studio  # its ambientCG download and texture conversion
    folders = {}
    for tid in sorted({t for pair in TERRAIN_SETS.values() for t in pair}):
        folder = os.path.join(build.BUILD, 'terrain_textures', tid)
        if not os.path.exists(os.path.join(folder, 'albedo.png')):
            import zipfile
            studio.convert(zipfile.ZipFile(studio.acg_zip(tid, TERRAIN_RES)), tid, folder)
        folders[tid] = folder
    result = editor_script(args, 'make_terrain.py', {'textures': folders, 'sets': TERRAIN_SETS}, 'mapkit_terrain.log')
    print('  %s' % ', '.join(m.rsplit('_', 1)[1] for m in result['materials']))


def make_stubs(args, cat):
    result = editor_script(args, 'make_stubs.py', {'catalog': cat}, 'mapkit_stubs.log')
    print('  %d created, %d failed%s' % (len(result['made']), len(result['failed']),
                                         ''.join('\n    %s: %s' % kv for kv in result['failed'].items())))


def make_library(args, paks=None, cat=None):
    paks = paks or pakfile.game_paks(args.game or build.find_game())
    cat = cat or json.load(open(os.path.join(build.BUILD, 'mapkit_blueprints.json')))
    result = editor_script(args, 'make_library.py', {'meshes': used_meshes(paks, cat),
                                                     'blueprints': sorted(p for p, bp in cat.items() if bp)},
                           'mapkit_library.log')
    print('  %d objects in %s' % (result['placed'], result['level']))


def used_meshes(paks, cat):
    """Static meshes the game's maps and gameplay Blueprints use."""
    paths = set()
    for m in game_maps(paks):
        pkg = mapgeo.Package(pakfile.find(paks, m), pakfile.find(paks, m[:-5] + '.uexp'))
        paths |= {pkg.import_path(-i - 1) for i, imp in enumerate(pkg.imports) if imp['class'] == 'StaticMesh'}
    for bp in cat.values():
        for n in (bp or {}).get('nodes', []) + (bp or {}).get('native_components', []):
            mesh = n.get('template', {}).get('StaticMesh')
            if isinstance(mesh, str):
                paths.add(mesh)
    return sorted(p for p in paths if p.startswith('/Game/'))


def used_materials(paks, cat):
    """Materials the game's maps, meshes and foliage use."""
    paths = set()
    for m in game_maps(paks):
        pkg = mapgeo.Package(pakfile.find(paks, m), pakfile.find(paks, m[:-5] + '.uexp'))
        paths |= {pkg.import_path(-i - 1) for i, imp in enumerate(pkg.imports)
                  if imp['class'] in ('Material', 'MaterialInstanceConstant')}
    for mesh in used_meshes(paks, cat):
        try:
            paths |= {m.split('.')[0] for m in meshes.read(paks, mesh).materials if m}
        except Exception:
            pass
    return sorted(p for p in paths if p.startswith('/Game/'))


def make_materials(args, paks=None, cat=None):
    paks = paks or pakfile.game_paks(args.game or build.find_game())
    cat = cat or json.load(open(os.path.join(build.BUILD, 'mapkit_blueprints.json')))
    folder = os.path.join(build.BUILD, 'mapkit_preview')
    os.makedirs(folder, exist_ok=True)
    kinds, decoded, jobs = {}, {}, []

    def kind(t):
        if t not in kinds:
            try:
                kinds[t] = textures.kind(paks, t)
            except Exception:
                kinds[t] = None
        return kinds[t]

    def png(tex, normal, alpha=False):
        """The texture decoded to a PNG (cached), as (file, asset name) or (None, None). With alpha for cut-outs."""
        key = (tex, alpha)
        if key not in decoded:
            name = re.sub(r'[^A-Za-z0-9_]', '_', tex.rsplit('/', 1)[1]) + '_%08x' % (zlib.crc32(tex.encode()) & 0xffffffff)
            name += '_a' if alpha else ''
            path = os.path.join(folder, name + '.png')
            if not os.path.exists(path):
                try:
                    img = textures.decode(paks, tex, 512 if normal else 1024)
                except Exception:
                    img = None
                if img is None:
                    decoded[key] = (None, None)
                    return decoded[key]
                img.convert('RGBA' if alpha else 'RGB').save(path)
            decoded[key] = (path, name)
        return decoded[key]

    real = os.path.join(build.PROJECT, 'Content')  # the texture project's own materials are real: keep them
    mats = used_materials(paks, cat)
    for k, path in enumerate(mats):
        if os.path.exists(os.path.join(real, path[len('/Game/'):] + '.uasset')):
            continue
        try:
            look = materials.pick(paks, path, kind)
        except Exception:
            continue
        if not look['class']:
            continue
        job = {'path': path, 'class': look['class'], 'tint': look['tint'], 'masked': look['masked']}
        # A child of one of the Texture Studio's materials looks like that in game (the textures pak replaces the
        # parent), so in the editor too: the real material as parent, with the game instance's own settings.
        restyled = next((a for a in look['ancestors']
                         if os.path.exists(os.path.join(real, a[len('/Game/'):] + '.uasset'))), None)
        if restyled and look['class'] == 'MaterialInstanceConstant':
            job.update(parent=restyled, scalars=look['scalars'], colors=look['colors'])
            jobs.append(job)
            continue
        if look['base']:
            job['base_png'], job['base_name'] = png(look['base'], False, look['masked'])
        if look['normal']:
            job['normal_png'], job['normal_name'] = png(look['normal'], True)
        jobs.append(job)
        if k % 100 == 0:
            print('  %d/%d materials read' % (k, len(mats)))
    result = editor_script(args, 'make_previews.py', {'materials': jobs}, 'mapkit_previews.log')
    print('  %d look-alike materials, %d failed%s' % (result['made'], len(result['failed']),
                                                     ''.join('\n    ' + f for f in result['failed'][:10])))


def import_meshes(args, paks=None, cat=None):
    paks = paks or pakfile.game_paks(args.game or build.find_game())
    cat = cat or json.load(open(os.path.join(build.BUILD, 'mapkit_blueprints.json')))
    folder = os.path.join(build.BUILD, 'mapkit_meshes')
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    jobs, unreadable = [], []
    for i, path in enumerate(used_meshes(paks, cat)):
        try:
            mesh = meshes.read(paks, path)
        except Exception as e:
            unreadable.append('%s (%s)' % (path, e))
            continue
        jobs.append((path, os.path.join(folder, '%d.bin' % i)))
        mesh.write(jobs[-1][1])
    result = editor_script(args, 'import_meshes.py', {'meshes': jobs}, 'mapkit_meshes.log')
    print('  %d meshes, %d failed%s' % (len(result['made']), len(result['failed']) + len(unreadable),
                                        ''.join('\n    ' + p for p in result['failed'] + unreadable)))


def map_path(paks, name):
    """CTF_Arches -> LemnisGate/Content/Levels/Playable/CTF_Arches.umap"""
    found = [m for m in game_maps(paks) if m.rsplit('/', 1)[1][:-5].lower() == name.lower()]
    if not found:
        sys.exit('No map called %s. Maps: %s' % (name, ', '.join(m.rsplit('/', 1)[1][:-5] for m in game_maps(paks))))
    return found[0]


def write_atmosphere(sc):
    """Move precomputed sky tables out of the scene into files the editor script loads (too big for the job JSON)."""
    for a in sc['actors']:
        if a.get('atmosphere'):
            files = []
            for part, data in zip(('transmittance', 'irradiance', 'inscatter'), a['atmosphere']):
                files.append(os.path.join(build.BUILD, 'mapkit_atmosphere_%s.bin' % part))
                open(files[-1], 'wb').write(data)
            a['atmosphere'] = files


# Actor classes --gameplay-only drops: level geometry.
GEOMETRY = ('/Script/Engine.StaticMeshActor', '/Script/Engine.BlockingVolume', '/Script/Engine.DecalActor')


def import_map(args):
    paks = pakfile.game_paks(args.game or build.find_game())
    umap = map_path(paks, args.map)
    target = map_path(paks, args.as_map) if args.as_map else umap
    rebuild(args, paks, umap, '/Game/' + target[len('LemnisGate/Content/'):-len('.umap')])


def landscape_jobs(paks, umap):
    """The map's terrains as heightmap files plus placement, for import_map.py."""
    try:
        ubulk = pakfile.find(paks, umap[:-5] + '.ubulk')
    except KeyError:
        ubulk = None
    jobs = []
    for k, land in enumerate(terrain.landscapes(scene.Scene(paks, umap), ubulk)):
        path = os.path.join(build.BUILD, 'mapkit_heights_%d.r16' % k)
        open(path, 'wb').write(struct.pack('<%dH' % len(land['heights']), *land['heights']))
        jobs.append({'file': path, 'name': land['name'], 'min': land['min'],
                     'max': (land['min'][0] + land['size'][0] - 1, land['min'][1] + land['size'][1] - 1),
                     'subsections': land['subsections'], 'subsection_quads': land['subsection_quads'],
                     'location': land['location'], 'rotation': land['rotation'], 'scale': land['scale'],
                     'material': terrain_material(land['material']), 'game_material': land['material']})
    return jobs


def foliage_jobs(paks, umap):
    """The map's foliage as instance files plus mesh and settings, for import_map.py."""
    jobs = []
    for k, f in enumerate(foliage.foliage(scene.Scene(paks, umap))):
        path = os.path.join(build.BUILD, 'mapkit_foliage_%d.bin' % k)
        open(path, 'wb').write(b''.join(struct.pack('<16f', *m) for m in f['instances']))
        jobs.append(dict({k2: v for k2, v in f.items() if k2 != 'instances'}, file=path, count=len(f['instances'])))
    return jobs


# Component settings the editor changes on placed copies, pinned back to the game template's value. (A turret's
# ChildActor: the editor saves bReplicates False, the game's template has True.)
PINNED = {'ChildActorComponent': ('bReplicates',)}


def pin_template_values(sc):
    path = os.path.join(build.BUILD, 'mapkit_blueprints.json')
    cat = json.load(open(path)) if os.path.exists(path) else {}
    for a in sc['actors']:
        bp = cat.get(a['class'].rsplit('.', 1)[0])
        for n in (bp or {}).get('nodes', []):
            for prop in PINNED.get(n['class'], ()):
                value = n['template'].get('values', {}).get(prop)
                if value is not None:
                    a.setdefault('component_values', {}).setdefault('%s.%s' % (n['name'], prop), value)


def rebuild(args, paks, umap, level, convert_to=None):
    existing = os.path.join(PROJECT, 'Content', level[len('/Game/'):] + '.umap')
    if os.path.exists(existing):
        os.remove(existing)
    print('[1/2] Reading %s' % umap)
    sc = scene.export(paks, umap)
    sc['landscapes'] = [] if args.gameplay_only or args.no_terrain else landscape_jobs(paks, umap)
    sc['foliage'] = [] if args.gameplay_only or args.no_foliage else foliage_jobs(paks, umap)
    pin_template_values(sc)
    if convert_to:
        box = scene.export(paks, map_path(paks, modes.BOX[convert_to]))
        pin_template_values(box)
        try:
            n = modes.convert(sc, box, convert_to)
        except ValueError as e:
            sys.exit('Cannot convert to %s: %s' % (convert_to, e))
        print('  converted to %s: %d objectives placed as in %s, gate pods kept' % (
            convert_to, n, modes.BOX[convert_to]))
    if args.gameplay_only:
        sc['actors'] = [a for a in sc['actors'] if a['class'] not in GEOMETRY]
    print('  %d actors' % len(sc['actors']))
    if sc['foliage']:
        print('  foliage: %d instances of %d meshes' % (sum(f['count'] for f in sc['foliage']), len(sc['foliage'])))
    for land in sc['landscapes']:
        print('  terrain %s: %dx%d, drawn with %s (stands in for %s)' % (
            land['name'], land['max'][0] - land['min'][0] + 1, land['max'][1] - land['min'][1] + 1,
            land['material'].rsplit('/', 1)[1], (land['game_material'] or 'none').rsplit('/', 1)[-1]))
    write_atmosphere(sc)
    print('[2/2] Rebuilding it as %s in the editor' % level)
    result = editor_script(args, 'import_map.py', {'scene': sc, 'level': level}, 'mapkit_import.log')
    print('  %d actors placed, %d failed, %d placeholder assets; world settings %s%s' % (
        result['spawned'], len(result['failed']), len(result['placeholders']), result['world_settings'],
        ''.join('\n    %s: %s' % kv for kv in result['failed'].items())))


# ---------------------------------------------------------------- your maps and the game's map list

REGISTRY = os.path.join(PROJECT, 'maps.json')


def registry():
    """{'maps': {Name: {title, mode, template, slot}}, 'modes': {GameMap: mode}}"""
    if os.path.exists(REGISTRY):
        return json.load(open(REGISTRY))
    return {'maps': {}, 'modes': {}}


def save_registry(reg):
    json.dump(reg, open(REGISTRY, 'w'), indent=1)


def mode_name(mode):
    """CAP or Capture -> Capture"""
    full = maplist.MODES.get(mode.upper(), mode)
    if full not in maplist.MODES.values():
        sys.exit('Unknown mode %s: use one of %s' % (mode, ', '.join(maplist.MODES)))
    return full


def free_slots(paks, ml):
    """Maps the game registered but doesn't list (CAP_Box, EV_Urban, ...), as /Game paths. The menu only offers maps
    the game registered when it was built, so a new map is saved in one of these, under its own name and mode."""
    listed = {ml.entry(k).get('level', '').split('/')[-1].split('.')[0].lower() for k in range(ml.count)}
    return ['/Game/' + m[len('LemnisGate/Content/'):-5] for m in game_maps(paks)
            if m.rsplit('/', 1)[1][:-5].lower() not in listed and '/Levels/Playable/' in m]


def custom_level_file(m):
    return os.path.join(PROJECT, 'Content', m['slot'][len('/Game/'):] + '.umap')


def template_entry(ml, source):
    """The map-list entry a new map copies (thumbnail, music, flags): the source map's, or for maps the game doesn't
    list (the *_Box maps) a P2P-menu map of the same mode."""
    try:
        return ml.find(source)
    except KeyError:
        prefix = source.split('_')[0].upper()
        mode = maplist.MODES.get(prefix, maplist.MODES.get(prefix[:3]))
        for k in range(ml.count):
            e = ml.entry(k)
            if e.get('flags') == 1 and e.get('mode') == mode:
                return k
        return next(k for k in range(ml.count) if ml.entry(k).get('flags') == 1)


def new_map(args):
    if not re.match(r'^[A-Za-z][A-Za-z0-9_]*$', args.map):
        sys.exit('Map names are letters, digits and _ (e.g. SO_Warehouse); use --title for the name shown in game.')
    if not args.source:
        sys.exit('Say which map to start from: --from <Map> (e.g. --from CAP_Box)')
    paks = pakfile.game_paks(args.game or build.find_game())
    source = map_path(paks, args.source)
    ml = maplist.MapList(paks)
    template = template_entry(ml, args.source)
    reg = registry()
    slot = reg['maps'].get(args.map, {}).get('slot')
    if not slot:
        taken = {m['slot'] for m in reg['maps'].values()}
        free = [f for f in free_slots(paks, ml) if f not in taken]
        if not free:
            sys.exit('All %d free map slots are used. Delete a map from %s, or replace one of the game\'s maps with '
                     '"import <Map>".' % (len(taken), REGISTRY))
        slot = free[0]
    reg['maps'][args.map] = {'title': args.title or args.map.replace('_', ' ').upper(),
                             'mode': mode_name(args.mode) if args.mode else ml.entry(template)['mode'],
                             'template': args.source, 'slot': slot}
    save_registry(reg)
    source_mode = ml.entry(template)['mode']
    mode = reg['maps'][args.map]['mode']
    rebuild(args, paks, source, slot, convert_to=mode if mode != source_mode else None)
    m = reg['maps'][args.map]
    print('%s: "%s", %s, saved as %s. Build to add it to the game\'s map list.' % (
        args.map, m['title'], m['mode'], slot))


def set_mode(args):
    if not args.mode_arg:
        sys.exit('Usage: kit.py mode <Map> <Mode>')
    reg = registry()
    mode = mode_name(args.mode_arg)
    if args.map in reg['maps']:
        reg['maps'][args.map]['mode'] = mode
    else:
        maplist.MapList(pakfile.game_paks(args.game or build.find_game())).find(args.map)  # must be listed
        reg['modes'][args.map] = mode
    save_registry(reg)
    print('%s now plays as %s (after the next build). Its objectives should suit the mode.' % (args.map, mode))


def remove_map(args):
    reg = registry()
    if args.map in reg['maps']:
        m = reg['maps'].pop(args.map)
        if os.path.exists(custom_level_file(m)):
            os.remove(custom_level_file(m))
        print('Removed %s (%s is free again). Build to update the game.' % (args.map, m['slot']))
    elif args.map in reg['modes']:
        del reg['modes'][args.map]
        print('%s plays in its own mode again after the next build.' % args.map)
    else:
        sys.exit('No map of yours called %s (see: kit.py list)' % args.map)
    save_registry(reg)


def list_maps(args):
    reg = registry()
    for name, m in sorted(reg['maps'].items()):
        missing = '' if os.path.exists(custom_level_file(m)) else '  [level missing]'
        print('%-20s "%s"  %s  (from %s, level %s)%s' % (name, m['title'], m['mode'], m['template'], m['slot'],
                                                         missing))
    for name, mode in sorted(reg['modes'].items()):
        print('%-20s plays as %s' % (name, mode))
    if not reg['maps'] and not reg['modes']:
        print('No maps of your own yet: python mapkit/kit.py new <Name> --from <Map>')


def game_instance(paks):
    """The game's map list with your maps added and mode changes applied, as (header, body); None if unchanged."""
    reg = registry()
    if not reg['maps'] and not reg['modes']:
        return None
    ml = maplist.MapList(paks)
    for game_map, mode in reg['modes'].items():
        ml.set_mode(ml.find(game_map), mode)
    extra = []
    for name, m in sorted(reg['maps'].items()):
        if os.path.exists(custom_level_file(m)):
            level = '%s.%s' % (m['slot'], m['slot'].rsplit('/', 1)[1])
            extra.append(ml.new_entry(template_entry(ml, m['template']), level, m['title'], m['mode']))
    return ml.write(extra)


def level_of(args, name):
    """A kit level's /Game path from one of your map names (SO_Yard) or a game map name (CTF_Arches)."""
    m = registry()['maps'].get(name)
    if m:
        return m['slot']
    for l in kit_levels():
        if l.rsplit('/', 1)[1][:-5].lower() == name.lower():
            return '/Game/' + l[:-5]
    sys.exit('No level %s in the kit (see: kit.py list, or import it first)' % name)


def bake_lighting(args):
    """Bake a level's lighting with Lightmass. The result (<Level>_BuiltData) is packed with the level from then on;
    the game's own meshes use the same lightmap UVs, so it fits them."""
    level = level_of(args, args.map)
    editor, _ = build.engine_tools(args.ue)
    print('Baking lighting for %s (%s quality; can take a while on big maps)' % (level, args.quality))
    run([editor, UPROJECT, '-run=ResavePackages', '-BuildLighting', '-Quality=' + args.quality,
         '-Map=' + level.rsplit('/', 1)[1],
         '-AllowCommandletRendering', '-IgnoreChangelist', '-SCCProvider=None'] + COMMON, 'mapkit_light.log')
    built = os.path.join(PROJECT, 'Content', level[len('/Game/'):] + '_BuiltData.uasset')
    if not os.path.exists(built):
        sys.exit('No lighting data was made - see %s' % os.path.join(LOGS, 'mapkit_light.log'))
    print('Baked: %s. Build to pack it.' % built)


# ---------------------------------------------------------------- the map builder

BUILDER_DIR = os.path.join(PROJECT, 'Saved', 'MapBuilder')


def edits_file(level):
    return os.path.join(BUILDER_DIR, level.rsplit('/', 1)[1] + '.edits.json')


PALETTE = os.path.join(build.BUILD, 'mapkit_palette.json')


def palette(args):
    """The parts the builder offers, by category: the game's gameplay objects, lights, and every mesh and placeable
    Blueprint its maps use, grouped by where they live. Cached; delete the file to rebuild it."""
    if os.path.exists(PALETTE):
        return json.load(open(PALETTE))
    paks = pakfile.game_paks(args.game or build.find_game())
    cat = json.load(open(os.path.join(build.BUILD, 'mapkit_blueprints.json')))
    placed = set()
    for m in game_maps(paks):
        pkg = mapgeo.Package(pakfile.find(paks, m), pakfile.find(paks, m[:-5] + '.uexp'))
        for imp in pkg.imports:
            if imp['class'] == 'BlueprintGeneratedClass' and imp['outer'] < 0:
                package = pkg.imports[-imp['outer'] - 1]['name']
                if package in cat and cat[package]:
                    placed.add('%s.%s' % (package, imp['name']))

    def nice(path):
        return path.rsplit('/', 1)[1].split('.')[0].replace('_', ' ')

    def group(path):
        parts = path.split('/')[2:-1]
        return ' / '.join(parts[:2]) if parts else 'Other'

    def native_base(package):
        seen = set()
        while package in cat and cat[package] and package not in seen:
            seen.add(package)
            parent = cat[package]['parent']
            if not parent.get('package', '').startswith('/Game/'):
                return parent['name']
            package = parent['package']
        return None

    # Things a map references but you don't place: game rules, players, libraries.
    not_parts = {'GameInstance', 'ConvergenceGameInstance', 'GameStateBase', 'GameState', 'ConvergenceGameState',
                 'GameModeBase', 'GameMode', 'ConvergenceGameMode', 'ConstructGameMode', 'HUD', 'ConvergenceHUD',
                 'PlayerController', 'Character', 'ConvergenceCharacter', 'Pawn', 'BlueprintFunctionLibrary',
                 'ActorComponent', 'SceneComponent', 'Object'}
    placed = {c for c in placed if native_base(c.split('.')[0]) not in not_parts}
    groups = {}
    gameplay = []
    for cls in sorted(placed):
        part = {'name': nice(cls), 'asset': 'class:' + cls}
        if cls.startswith('/Game/Gameplay/'):
            gameplay.append(part)
        else:
            groups.setdefault(group(cls), []).append(part)
    for mesh in used_meshes(paks, cat):
        groups.setdefault(group(mesh), []).append({'name': nice(mesh), 'asset': 'mesh:%s.%s' % (mesh, mesh.rsplit('/', 1)[1])})
    out = [{'name': 'Gameplay', 'parts': sorted(gameplay, key=lambda p: p['name'].lower())},
           {'name': 'Lights', 'parts': [{'name': n, 'asset': 'class:/Script/Engine.' + c} for n, c in
                                        (('Point light', 'PointLight'), ('Spot light', 'SpotLight'),
                                         ('Rect light', 'RectLight'))]}]
    out += [{'name': g, 'parts': sorted(p, key=lambda p: p['name'].lower())} for g, p in sorted(groups.items())]
    json.dump(out, open(PALETTE, 'w'), indent=1)
    return out


def write_profile(name, args=None):
    """What the builder needs to know about this game: for now, how to build and play a map. (The builder core is
    game-agnostic; parts, gameplay objects and mode rules will come from here too.)"""
    os.makedirs(BUILDER_DIR, exist_ok=True)
    path = os.path.join(BUILDER_DIR, 'profile.json')
    json.dump({'game': 'Lemnis Gate',
               'build': [sys.executable, os.path.abspath(__file__), 'play', name],
               # Objects the game hides in a match (time-trial checkpoints): the builder can hide them too.
               'helpers': ['CheckPoint'],
               'palette': palette(args)}, open(path, 'w'), indent=1)
    return path


def builder(args, test_folder=None, camera=None):
    """Open a kit level in the map builder (its own window: fly around, select and edit)."""
    level = level_of(args, args.map) if args.map else '/Game/MapKit/ObjectLibrary'
    editor, _ = build.engine_tools(args.ue)
    gui = editor.replace('UE4Editor-Cmd.exe', 'UE4Editor.exe')
    cmd = [gui, UPROJECT, '%s?game=/Script/MapBuilder.MapBuilderGameMode' % level, '-game', '-windowed',
           '-ResX=1600', '-ResY=900', '-nosplash', '-MapBuilderProfile=' + write_profile(args.map or '', args)]
    if camera:
        cmd.append('-MapBuilderCamera=' + ','.join('%g' % v for v in camera))
    if test_folder:
        os.makedirs(test_folder, exist_ok=True)
        cmd.append('-MapBuilderTest=' + test_folder)
        return subprocess.call(cmd)
    subprocess.Popen(cmd)
    print('Map builder opening %s' % level)


def apply_edits(args):
    """Apply the map builder's saved edits to a kit level. The edits file is archived afterwards: copies get new
    names in the level, so applying the same edits again would copy them again."""
    level = level_of(args, args.map)
    path = edits_file(level)
    if not os.path.exists(path):
        print('No builder edits for %s' % level)
        return False
    result = editor_script(args, 'apply_edits.py', {'edits': path}, 'mapkit_apply.log')
    print('  %d moved, %d added, %d deleted%s' % (result['moved'], result['added'], result['deleted'],
          ('; not found: ' + ', '.join(result['missing'])) if result['missing'] else ''))
    stamp = time.strftime('%Y%m%d-%H%M%S')
    os.replace(path, path.replace('.edits.json', '.applied-%s.json' % stamp))
    return True


def play(args):
    """Apply the builder's edits, re-bake the lighting if the map has a bake, build, install and start the game."""
    level = level_of(args, args.map)
    print('[1/4] Applying the builder\'s edits')
    apply_edits(args)
    if os.path.exists(os.path.join(PROJECT, 'Content', level[len('/Game/'):] + '_BuiltData.uasset')):
        print('[2/4] Baking lighting')
        bake_lighting(args)
    else:
        print('[2/4] (no baked lighting)')
    print('[3/4] Building')
    args.install = True
    build_maps(args)
    print('[4/4] Starting the game')
    win64 = os.path.join(args.game or build.find_game(), 'LemnisGate', 'Binaries', 'Win64')
    subprocess.Popen([os.path.join(win64, 'LemnisGate-Win64-Shipping.exe')], cwd=win64)


def kit_levels():
    """Levels in the kit project, as content-relative paths (Levels/Playable/CTF_Arches.umap)."""
    content = os.path.join(PROJECT, 'Content')
    out = []
    for root, _, files in os.walk(content):
        out += [os.path.relpath(os.path.join(root, f), content).replace(os.sep, '/') for f in files if f.endswith('.umap')]
    return sorted(l for l in out if not l.startswith('MapKit/'))  # the kit's own levels (object library) stay home


def built_data(cooked, level):
    """Cooked files of a level's baked lighting, if it has any."""
    base = os.path.join(cooked, 'LemnisGate', 'Content', level[:-5].replace('/', os.sep) + '_BuiltData')
    return [base + ext for ext in ('.uasset', '.uexp', '.ubulk') if os.path.exists(base + ext)]


def build_maps(args):
    levels = kit_levels()
    if not levels:
        sys.exit('No levels in the kit yet - run "python mapkit/kit.py import <Map>" first.')
    editor, unrealpak = build.engine_tools(args.ue)
    write_game_ini()
    cooked = os.path.join(PROJECT, 'Saved', 'Cooked', 'WindowsNoEditor')
    shutil.rmtree(cooked, ignore_errors=True)
    print('[1/3] Cooking %s' % ', '.join(l[:-5] for l in levels))
    run([editor, UPROJECT, '-run=cook', '-targetplatform=WindowsNoEditor', '-unversioned']
        + ['-map=/Game/' + l[:-5] for l in levels] + COMMON, 'mapkit_cook.log')
    print('[2/3] Checking every reference against the game')
    game = args.game or build.find_game()
    paks = pakfile.game_paks(game)
    textures = os.path.join(build.OUT, build.PAK_NAME)
    # The kit's own assets (terrain materials and anything you make under /Game/SalvageOps) ship in the pak.
    own = verify.CookedFolder(cooked, 'SalvageOps')
    lighting = verify.CookedFolder(cooked, 'Levels')  # the levels' own baked lighting (<Level>_BuiltData)
    lighting.files = {k: v for k, v in lighting.files.items() if '_BuiltData.' in k}
    checker = verify.Checker([own, lighting] + ([pakfile.Pak(textures)] if os.path.exists(textures) else []) + paks,
                             os.path.join(game, 'LemnisGate', 'Binaries', 'Win64', 'LemnisGate-Win64-Shipping.exe'))
    bad = False
    to_check = [l[:-5] + '.umap' for l in levels]
    to_check += [l[:-5] + '_BuiltData.uasset' for l in levels if built_data(cooked, l)]
    to_check += [f[len('LemnisGate/Content/'):] for f in own.files if f.endswith('.uasset')]
    for rel in to_check:
        base = os.path.join(cooked, 'LemnisGate', 'Content', os.path.splitext(rel)[0].replace('/', os.sep))
        problems = checker.check(base + os.path.splitext(rel)[1], base + '.uexp')
        if problems or rel.endswith('.umap'):
            print('  %s: %s' % (os.path.splitext(rel)[0], 'ok' if not problems else '%d problems' % len(problems)))
        for p in problems:
            print('    ' + p)
        bad = bad or bool(problems)
    if own.files:
        print('  %d of the kit\'s own files (terrain materials and textures)' % len(own.files))
    if bad and not args.force:
        sys.exit('Not packed: those references would be missing in-game (pass --force to pack anyway).')
    print('[3/3] Packing the maps and the kit\'s own assets (the game supplies everything else)')
    resp = os.path.join(build.BUILD, 'mapkit_pak_files.txt')
    listed = game_instance(paks)
    with open(resp, 'w') as f:
        if listed:
            # The game's map list, with your maps in it.
            for data, ext in zip(listed, ('.uasset', '.uexp')):
                src = os.path.join(build.BUILD, 'ConvergenceGameInstanceBP' + ext)
                open(src, 'wb').write(data)
                f.write('"%s" "../../../%s%s"\n' % (src, maplist.ASSET, ext))
        for l in levels:
            base = os.path.join(cooked, 'LemnisGate', 'Content', l[:-5].replace('/', os.sep))
            files = [base + ext for ext in ('.umap', '.uexp', '.ubulk') if os.path.exists(base + ext)]
            if not files:
                sys.exit('Cook did not produce %s - see %s' % (l, os.path.join(LOGS, 'mapkit_cook.log')))
            for src in files:
                f.write('"%s" "../../../LemnisGate/Content/%s"\n' % (src, l[:-5] + os.path.splitext(src)[1]))
            for src in built_data(cooked, l):
                f.write('"%s" "../../../LemnisGate/Content/%s"\n' % (src, l[:-5] + '_BuiltData' + os.path.splitext(src)[1]))
        for name, src in sorted(own.files.items()):
            f.write('"%s" "../../../%s"\n' % (src, name))
    os.makedirs(build.OUT, exist_ok=True)
    pak = os.path.join(build.OUT, PAK_NAME)
    run([unrealpak, pak, '-create=' + resp], 'mapkit_pak.log')
    print('Built %s (%d maps)' % (pak, len(levels)))
    if args.install:
        dest = build.mods_dir(args)
        shutil.copy2(pak, dest)
        print('Installed to ' + os.path.join(dest, PAK_NAME))


PAK_NAME = 'SalvageOps_Maps_P.pak'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', choices=['setup', 'materials', 'meshes', 'terrain', 'library', 'import', 'new', 'mode', 'list', 'remove', 'light', 'builder', 'apply', 'play', 'build'])
    ap.add_argument('--install', action='store_true', help='build: copy the pak into the game')
    ap.add_argument('--force', action='store_true', help='build: pack even if references are missing')
    ap.add_argument('map', nargs='?', help='map name for import, e.g. CTF_Arches')
    ap.add_argument('mode_arg', nargs='?', help='mode: the mode to play the map in')
    ap.add_argument('--from', dest='source', help='new: the map to start from')
    ap.add_argument('--mode', help='new: game mode (CTF, CAP, DM, DST, EVA, ASN; default: the source map\'s)')
    ap.add_argument('--title', help='new: the name shown in game')
    ap.add_argument('--quality', default='Medium', choices=['Preview', 'Medium', 'High', 'Production'],
                    help='light: Lightmass quality')
    ap.add_argument('--as', dest='as_map', help='import: save as this map instead (its place in the game)')
    ap.add_argument('--gameplay-only', action='store_true', help='import: leave out the level geometry')
    ap.add_argument('--no-terrain', action='store_true', help='import/new: leave out the terrain')
    ap.add_argument('--no-foliage', action='store_true', help='import/new: leave out the foliage')
    ap.add_argument('--ue', default=build.DEFAULT_UE, help='Unreal Engine 4.26 folder')
    ap.add_argument('--game', help='Lemnis Gate folder (default: found through Steam)')
    args = ap.parse_args()
    if args.command in ('import', 'new', 'mode', 'remove', 'light', 'apply', 'play') and not args.map:
        ap.error('%s needs a map name' % args.command)
    {'setup': setup, 'materials': make_materials, 'meshes': import_meshes, 'terrain': make_terrain, 'library': make_library, 'import': import_map, 'new': new_map,
     'mode': set_mode, 'list': list_maps, 'remove': remove_map, 'light': bake_lighting, 'builder': builder, 'apply': apply_edits,
     'play': play, 'build': build_maps}[args.command](args)


if __name__ == '__main__':
    main()
