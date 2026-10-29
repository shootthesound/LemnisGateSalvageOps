"""Screenshot a level from a given camera (kit.py shot): opens the level in the full editor, waits for shaders and
streaming, saves a high-res screenshot and quits. For checking how the kit's levels look without opening the editor.

Job (MAPKIT_SHOT, JSON): level, location [x, y, z], rotation [pitch, yaw, roll], file (a name: it goes to Saved/Screenshots/Windows), report (JSON path), optional select (actor
labels to report the meshes and materials of).
"""
import json
import os

import unreal

JOB = json.load(open(os.environ['MAPKIT_SHOT']))
state = {'ticks': 0, 'shot': False}


def report():
    out = {}
    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        label = actor.get_actor_label()
        if not any(s.lower() in label.lower() for s in JOB.get('select', [])):
            continue
        for comp in actor.get_components_by_class(unreal.StaticMeshComponent):
            mesh = comp.static_mesh
            out['%s.%s' % (label, comp.get_name())] = {
                'mesh': mesh.get_path_name() if mesh else None,
                'materials': [m.get_path_name() if m else None for m in comp.get_materials()]}
    return out


def tick(dt):
    state['ticks'] += 1
    t = state['ticks']
    if t == 5:
        unreal.EditorLevelLibrary.set_level_viewport_camera_info(unreal.Vector(*JOB['location']),
                                                                 unreal.Rotator(roll=JOB['rotation'][2],
                                                                                pitch=JOB['rotation'][0],
                                                                                yaw=JOB['rotation'][1]))
    if t == JOB.get('wait', 900) and not state['shot']:
        state['shot'] = True
        unreal.AutomationLibrary.take_high_res_screenshot(1600, 900, JOB['file'])
    if t == JOB.get('wait', 900) + 120:
        json.dump(report(), open(JOB['report'], 'w'), indent=1)
        unreal.SystemLibrary.quit_editor()


unreal.EditorLevelLibrary.load_level(JOB['level'])
unreal.register_slate_post_tick_callback(tick)
