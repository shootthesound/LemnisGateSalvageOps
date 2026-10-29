"""Apply the map builder's edits to a kit level and save it (run by kit.py apply).

The edits file lists objects moved (new transform), deleted, and added (copies of a level object). Objects are found
by name, so everything the builder didn't touch stays exactly as it was.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_common import JOB, LIB, log, run  # noqa: E402

import unreal  # noqa: E402


def transform(t):
    loc, rot, scale = t['location'], t['rotation'], t['scale']
    return unreal.Transform(unreal.Vector(*loc), unreal.Rotator(roll=rot[2], pitch=rot[0], yaw=rot[1]),
                            unreal.Vector(*scale))


def new_part(world, asset, t):
    """A part from the builder's palette: "mesh:<path>" or "class:<path>"."""
    kind, path = asset.split(':', 1)
    if kind == 'mesh':
        mesh = unreal.load_object(None, path)
        actor = LIB.spawn_actor(world, unreal.StaticMeshActor, t, '') if mesh else None
        if actor:
            actor.static_mesh_component.set_static_mesh(mesh)
    else:
        cls = unreal.load_object(None, path) if path.startswith('/Game/') else unreal.load_class(None, path)
        actor = LIB.spawn_actor(world, cls, t, '') if cls else None
    if actor:
        actor.set_actor_transform(t, False, False)  # spawning combines the class's default placement with t
    return actor


def main():
    edits = json.load(open(JOB['edits']))
    world = LIB.load_level(edits['level'])
    if not world:
        raise RuntimeError('could not open ' + edits['level'])
    missing = []
    moved = 0
    for name, t in edits.get('moved', {}).items():
        actor = LIB.find_actor(world, name)
        if actor:
            actor.set_actor_transform(transform(t), False, False)
            moved += 1
        else:
            missing.append(name)
    added = 0
    for item in edits.get('added', []):
        if 'asset' in item:
            if new_part(world, item['asset'], transform(item['transform'])):
                added += 1
            else:
                missing.append(item['asset'])
            continue
        source = LIB.find_actor(world, item['source'])
        if source and LIB.duplicate_actor(source, transform(item['transform'])):
            added += 1
        else:
            missing.append(item['source'])
    deleted = 0
    for name in edits.get('deleted', []):
        actor = LIB.find_actor(world, name)
        if actor:
            actor.destroy_actor()
            deleted += 1
        else:
            missing.append(name)
    if not LIB.save_level(world):
        raise RuntimeError('could not save ' + edits['level'])
    log('applied: %d moved, %d added, %d deleted, %d not found' % (moved, added, deleted, len(missing)))
    return {'moved': moved, 'added': added, 'deleted': deleted, 'missing': missing}


run(main)
