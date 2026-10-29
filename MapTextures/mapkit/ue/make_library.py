"""Lay out every game mesh and gameplay Blueprint in an editor-only level (/Game/MapKit/ObjectLibrary), in labelled
rows by folder, to browse and copy from (run by kit.py library). The kit never cooks levels under /Game/MapKit.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_common import ASSETS, JOB, LIB, load_class, log, run  # noqa: E402

import unreal  # noqa: E402

LEVEL = '/Game/MapKit/ObjectLibrary'
GAP = 200.0       # cm between items
ROW_GAP = 800.0   # cm between folders
ROW_WIDTH = 30000.0


def label(world, text, location, size=60):
    actor = LIB.spawn_actor(world, unreal.TextRenderActor, unreal.Transform(location, unreal.Rotator(roll=0, pitch=0, yaw=-90)), '')
    comp = actor.get_editor_property('text_render')
    comp.set_editor_property('text', text)
    comp.set_editor_property('world_size', size)
    comp.set_editor_property('horizontal_alignment', unreal.HorizTextAligment.EHTA_CENTER)
    actor.set_actor_label('Label ' + text[:40])
    actor.set_folder_path('Labels')
    return actor


def size_of(actor):
    origin, extent = actor.get_actor_bounds(False)
    return origin, extent


def main():
    if ASSETS.does_asset_exist(LEVEL):
        ASSETS.delete_asset(LEVEL)
    world = LIB.create_level(LEVEL)
    items = [('mesh', p) for p in JOB['meshes']] + [('blueprint', p) for p in JOB['blueprints']]
    rows = {}
    for kind, path in items:
        rows.setdefault(path.rsplit('/', 1)[0], []).append((kind, path))
    y = 0.0
    placed = 0
    for folder in sorted(rows):
        label(world, folder[len('/Game/'):], unreal.Vector(-600, y, 100), 80)
        x, row_depth = 0.0, 0.0
        for kind, path in sorted(rows[folder], key=lambda kp: kp[1]):
            name = path.rsplit('/', 1)[1]
            if kind == 'mesh':
                mesh = unreal.load_object(None, '%s.%s' % (path, name))
                if not mesh:
                    continue
                actor = LIB.spawn_actor(world, unreal.StaticMeshActor, unreal.Transform(), name)
                actor.static_mesh_component.set_static_mesh(mesh)
            else:
                cls = load_class('%s.%s_C' % (path, name))
                if not cls or not unreal.MathLibrary.class_is_child_of(cls, unreal.Actor):
                    continue
                actor = LIB.spawn_actor(world, cls, unreal.Transform(), name)
            if not actor:
                continue
            origin, extent = size_of(actor)
            width = max(extent.x * 2, 100.0)
            depth = max(extent.y * 2, 100.0)
            if x > 0 and x + width > ROW_WIDTH:
                y += row_depth + GAP * 2 + 200
                x, row_depth = 0.0, 0.0
            # Sit each item on the ground, its bounds starting at the row's current x.
            offset = actor.get_actor_location() - origin
            actor.set_actor_location(unreal.Vector(x + width / 2, y + depth / 2, extent.z) + offset, False, False)
            actor.set_folder_path(folder[len('/Game/'):])
            label(world, name, unreal.Vector(x + width / 2, y - 60, 20), 24)
            x += width + GAP
            row_depth = max(row_depth, depth)
            placed += 1
        y += row_depth + ROW_GAP
    # Light, so the editor viewport shows something sensible.
    sun = LIB.spawn_actor(world, unreal.DirectionalLight, unreal.Transform(unreal.Vector(0, 0, 1000)), 'Sun')
    sun.set_actor_rotation(unreal.Rotator(roll=0, pitch=-50, yaw=30), False)
    sun.light_component.set_editor_property('mobility', unreal.ComponentMobility.MOVABLE)
    sky = LIB.spawn_actor(world, unreal.SkyLight, unreal.Transform(), 'Sky')
    sky.light_component.set_editor_property('mobility', unreal.ComponentMobility.MOVABLE)
    if not LIB.save_level(world):
        raise RuntimeError('could not save ' + LEVEL)
    log('library: %d items' % placed)
    return {'placed': placed, 'level': LEVEL}


run(main)
