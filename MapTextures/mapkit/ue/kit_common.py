"""Shared helpers for the Map Kit's editor scripts (run inside UE4Editor with -run=pythonscript)."""
import json
import os
import re
import traceback

import unreal

import sys  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scene import ue_text  # noqa: E402

TEXT_STRUCTS = ('Vector', 'Rotator', 'LinearColor', 'Color')
JOB = json.load(open(os.environ['MAPKIT_JOB']))
ASSETS = unreal.EditorAssetLibrary
TOOLS = unreal.AssetToolsHelpers.get_asset_tools()
LIB = unreal.MapKitLibrary


def log(msg):
    unreal.log_warning('[MapKit] ' + msg)  # plain log lines are hidden in commandlet output


def finish(ok, error=None, **extra):
    json.dump(dict(extra, ok=ok, error=error), open(JOB['result_file'], 'w'), indent=1)


def run(main):
    try:
        finish(True, **(main() or {}))
    except Exception:
        log(traceback.format_exc())
        finish(False, traceback.format_exc())


def snake(name):
    """Unreal property name -> Python name: bHiddenInGame -> hidden_in_game, RelativeLocation -> relative_location."""
    if re.match(r'b[A-Z]', name):
        name = name[1:]
    name = name.replace('3D', '3d')  # RelativeScale3D -> relative_scale3d
    name = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', name)
    name = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', name)
    return name.lower()


def load(ref):
    """Load an asset reference {'path', 'object'} (or a path string)."""
    if isinstance(ref, dict):
        path = ref['path'] + '.' + (ref.get('object') or ref['path'].rsplit('/', 1)[1])
    else:
        path = ref
    return unreal.load_object(None, path)


def load_class(path):
    """/Script/Engine.Actor or /Game/X/Y.Y_C -> class."""
    if path.startswith('/Game/'):
        return unreal.load_object(None, path)
    return unreal.load_class(None, path)


def convert(ptype, value):
    """A value from scene.py/bpinfo.py JSON -> an unreal value (or raise)."""
    if ptype == 'Vector':
        return unreal.Vector(*value)
    if ptype == 'Rotator':
        return unreal.Rotator(roll=value[2], pitch=value[0], yaw=value[1])
    if ptype == 'LinearColor':
        return unreal.LinearColor(*value)
    if ptype == 'Color':
        return unreal.Color(r=value[0], g=value[1], b=value[2], a=value[3])
    if ptype in ('EnumProperty', 'ByteProperty') and isinstance(value, str) and '::' in value:
        enum, member = value.split('::')
        enum_type = getattr(unreal, enum[1:] if enum.startswith('E') else enum)
        return getattr(enum_type, snake(member).upper())
    if ptype == 'ObjectProperty':
        return load(value) if value else None
    if ptype == 'ArrayProperty':
        return [load(v) if v else None for v in value]
    return value


def set_prop(obj, name, ptype, value):
    try:
        obj.set_editor_property(snake(name), convert(ptype, value))
        return True
    except Exception as e:
        # Python can't reach some properties (Blueprint variables named with spaces, protected ones): set them from
        # Unreal's text form instead.
        if not isinstance(value, (list, dict)) or ptype in TEXT_STRUCTS or (isinstance(value, dict) and 'path' in value):
            if LIB.set_property_text(obj, name, ue_text(ptype, value)):
                return True
        log('  skip %s.%s: %s' % (obj.get_name(), name, str(e).splitlines()[0][:120]))
        return False
