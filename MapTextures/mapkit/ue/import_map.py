"""Rebuild a game map as an editable level from scene.py's JSON (run by kit.py import inside the editor).

Assets the map references that the kit does not have yet get placeholders of the same class at the same path
(a cube for meshes, a plain material for materials): the cooked level then references the game's real ones.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_common import ASSETS, JOB, LIB, TOOLS, convert, load, load_class, log, run, set_prop  # noqa: E402

import unreal  # noqa: E402

PLACEHOLDER_MESH = '/Engine/BasicShapes/Cube'
PLACEHOLDER_PARENT = '/Engine/EngineMaterials/DefaultMaterial'
# Serialization bookkeeping and transforms handled separately - not copied onto spawned actors.
SKIP_PROPS = {'UCSSerializationIndex', 'bNetAddressable', 'CreationMethod', 'UCSModifiedProperties', 'AttachParent',
              'LightGuid', 'MapBuildDataId', 'RelativeLocation', 'RelativeRotation', 'RelativeScale3D',
              'BlueprintCreatedComponents', 'RootComponent', 'StaticMesh', 'OverrideMaterials', 'BrushType',
              'SpawnCollisionHandlingMethod', 'BookmarkArray', 'NavigationSystemConfig', 'bIsEditorOnlyActor',
              'VisualizeComponent', 'bHidden', 'PreviewInfluenceRadius', 'DrawCaptureRadius', 'CaptureOffsetComponent'}
WORLD_SETTINGS = ('/Script/Engine.WorldSettings', '/Script/LemnisGate.ConvergenceWorldSettings')


def refs(value):
    if isinstance(value, dict):
        if 'path' in value:
            yield value
        for v in value.values():
            yield from refs(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from refs(v)


def placeholders(actors):
    """Create placeholders for referenced /Game assets the kit is missing. Returns their paths."""
    made = []
    for ref in {r['path']: r for r in refs(actors)}.values():
        path, cls = ref['path'], ref['class']
        if not path.startswith('/Game/') or ASSETS.does_asset_exist(path):
            continue
        folder, name = path.rsplit('/', 1)
        if cls == 'StaticMesh':
            ASSETS.duplicate_asset(PLACEHOLDER_MESH, path)
        elif cls == 'Material':
            TOOLS.create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())
        elif cls == 'MaterialInstanceConstant':
            mi = TOOLS.create_asset(name, folder, unreal.MaterialInstanceConstant,
                                    unreal.MaterialInstanceConstantFactoryNew())
            unreal.MaterialEditingLibrary.set_material_instance_parent(mi, load(PLACEHOLDER_PARENT))
        else:
            log('  no placeholder for %s (%s)' % (path, cls))
            continue
        ASSETS.save_asset(path)
        made.append(path)
    return made


def components(actor):
    return {c.get_name(): c for c in actor.get_components_by_class(unreal.ActorComponent)}


def apply_props(obj, props):
    for name, (ptype, value) in props.items():
        if name not in SKIP_PROPS and '[' not in name:
            set_prop(obj, name, ptype, value)


def apply_component(comp, props):
    apply_props(comp, props)
    if 'StaticMesh' in props and isinstance(comp, unreal.StaticMeshComponent):
        mesh = convert('ObjectProperty', props['StaticMesh'][1])
        if mesh:
            comp.set_static_mesh(mesh)
    for i, m in enumerate(props.get('OverrideMaterials', (None, []))[1] or []):
        if isinstance(m, dict) and 'dynamic' in m:
            # A material instance the level keeps (e.g. the sky sphere's colours), saved with the level again.
            mid = comp.create_dynamic_material_instance(i, load(m['dynamic']))
            for name, value in m['scalars'].items():
                mid.set_scalar_parameter_value(name, value)
            for name, value in m['vectors'].items():
                mid.set_vector_parameter_value(name, unreal.LinearColor(*value))
            for name, value in m['textures'].items():
                mid.set_texture_parameter_value(name, load(value))
        elif m:
            comp.set_material(i, load(m))


def spawn(world, a):
    cls = load_class(a['class'])
    if not cls:
        raise RuntimeError('class %s not found' % a['class'])
    root = a['components'].get(a.get('root'), {}).get('props', {})
    loc = convert('Vector', root['RelativeLocation'][1]) if 'RelativeLocation' in root else unreal.Vector()
    rot = convert('Rotator', root['RelativeRotation'][1]) if 'RelativeRotation' in root else unreal.Rotator()
    actor = LIB.spawn_actor(world, cls, unreal.Transform(loc, rot, unreal.Vector(1, 1, 1)), a['name'])
    if not actor:
        raise RuntimeError('spawn failed')
    if 'brush' in a and isinstance(actor, unreal.Volume):
        LIB.make_box_brush(actor, unreal.Vector(*a['brush']))
    if 'RelativeScale3D' in root:
        actor.set_actor_scale3d(convert('Vector', root['RelativeScale3D'][1]))
    apply_props(actor, a['props'])
    comps = components(actor)
    for name, c in a['components'].items():
        if name in comps:
            apply_component(comps[name], c['props'])
            # The root too: spawning combines the transform with the class's default (a directional light's
            # -46 pitch), so set the saved values exactly.
            for key in ('RelativeLocation', 'RelativeRotation', 'RelativeScale3D'):
                if key in c['props']:
                    set_prop(comps[name], key, *c['props'][key])
            if c['class'] == 'AtmosphericFogComponent' and a.get('atmosphere') and not LIB.set_atmosphere_data(comps[name], *a['atmosphere']):
                log('  %s: could not load the precomputed sky' % a['name'])
    # Saved component values and construction-script results (team colours, movable parts), re-applied by the
    # stand-in on every construction, which would otherwise reset them.
    values = dict(a.get('component_values', {}), **a.get('construction_values', {}))
    if values and LIB.has_property(actor.get_class(), 'InstanceConstructionValues'):
        actor.set_editor_property('instance_construction_values', values)
    return actor


def snap_near(actor, start, rings=8, step=200.0):
    """Put `actor` on the floor at `start`, or the nearest floor in rings of 8 directions around it."""
    import math
    for ring in range(rings + 1):
        for k in range(8 if ring else 1):
            angle = math.radians(45 * k)
            offset = unreal.Vector(math.cos(angle) * ring * step, math.sin(angle) * ring * step, 0)
            actor.set_actor_location(start + offset, False, False)
            if LIB.snap_to_ground(actor, 300.0, 400.0):
                return True
    return False


def main():
    scene, level = JOB['scene'], JOB['level']
    actors = scene['actors']
    made = placeholders(actors)
    log('%d placeholders' % len(made))
    world = LIB.create_level(level)
    spawned, failed, snap = 0, {}, []
    for a in actors:
        if a['class'] in WORLD_SETTINGS:
            if a['class'].endswith('ConvergenceWorldSettings'):
                apply_props(world.get_world_settings(), a['props'])
            continue
        try:
            actor = spawn(world, a)
            spawned += 1
            if a.get('snap'):
                snap.append(actor)
        except Exception as e:
            failed[a['name']] = str(e)
            log('FAILED %s (%s): %s' % (a['name'], a['class'], e))
    for land in scene.get('landscapes', []):
        material = load(land['material'] + '.' + land['material'].rsplit('/', 1)[1])
        transform = unreal.Transform(convert('Vector', land['location']), convert('Rotator', land['rotation']),
                                     convert('Vector', land['scale']))
        actor = LIB.import_landscape(world, land['file'], unreal.IntPoint(*land['min']), unreal.IntPoint(*land['max']),
                                     land['subsections'], land['subsection_quads'], transform, material, land['name'])
        if actor:
            spawned += 1
        else:
            failed[land['name']] = 'terrain import failed'
            log('FAILED terrain %s' % land['name'])
    for k, f in enumerate(scene.get('foliage', [])):
        mesh = load(f['mesh'] + '.' + f['mesh'].rsplit('/', 1)[1])
        materials = [load(m) if m else None for m in f['materials']]
        name = 'Foliage_' + f['mesh'].rsplit('/', 1)[1]
        actor = LIB.spawn_instanced_mesh(world, name, mesh, materials, f['file'], convert('Vector', f['location']),
                                         f['cull'][0], f['cull'][1], f['collision'])
        if actor:
            spawned += 1
        else:
            failed[name] = 'foliage failed'
            log('FAILED foliage %s' % name)
    # Objectives a mode conversion placed: onto the ground, now that everything is there to stand on.
    for actor in snap:
        # Only ground near the expected height: a gap in the floor would otherwise drop it to whatever is far below.
        # Where there's a gap, use the nearest floor around it.
        start = actor.get_actor_location()
        if not snap_near(actor, start):
            actor.set_actor_location(start, False, False)
            log('  no floor near %s: left at floor height, move it in the editor' % actor.get_actor_label())
    if not LIB.save_level(world):
        raise RuntimeError('could not save ' + level)
    return {'spawned': spawned, 'failed': failed, 'placeholders': made,
            'world_settings': world.get_world_settings().get_class().get_path_name()}


run(main)
