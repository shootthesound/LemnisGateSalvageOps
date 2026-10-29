"""Export the actors of a cooked Lemnis Gate map as JSON the Map Kit's editor script rebuilds the level from."""
import collections
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mapgeo  # noqa: E402
import pakfile  # noqa: E402
from mapgeo import Reader  # noqa: E402

# Editor/cinematic actors the kit does not recreate.
SKIP = {'LevelScriptActor', 'LevelSequenceActor', 'CineCameraActor', 'CameraActor', 'Brush', 'DefaultPhysicsVolume',
        'LandscapeGizmoActiveActor', 'GameplayDebuggerPlayerManager', 'AbstractNavData', 'NavigationData',
        'ParticleEventManager'} | {'Landscape', 'LandscapeStreamingProxy', 'InstancedFoliageActor'}
# Rebuilt separately (terrain.py) or not yet (foliage): import_map warns about the latter.
UNSUPPORTED = ('InstancedFoliageActor',)
TRANSFORM = ('RelativeLocation', 'RelativeRotation', 'RelativeScale3D')


def ue_text(ptype, value):
    """A property value in Unreal's text form (what FProperty::ImportText reads)."""
    if isinstance(value, bool):
        return 'True' if value else 'False'
    if ptype in ('EnumProperty', 'ByteProperty') and isinstance(value, str):
        return value.split('::')[-1]
    if ptype == 'Vector':
        return '(X=%r,Y=%r,Z=%r)' % tuple(value)
    if ptype == 'Rotator':
        return '(Pitch=%r,Yaw=%r,Roll=%r)' % tuple(value)
    if ptype == 'LinearColor':
        return '(R=%r,G=%r,B=%r,A=%r)' % tuple(value)
    if ptype == 'Color':
        return '(B=%d,G=%d,R=%d,A=%d)' % (value[2], value[1], value[0], value[3])
    if isinstance(value, dict) and 'path' in value:
        return '%s.%s' % (value['path'], value.get('object') or value['path'].rsplit('/', 1)[1])
    if isinstance(value, dict):
        return '(%s)' % ','.join('%s=%s' % (k, ue_text(None, v)) for k, v in value.items())
    return str(value)


# Serialization bookkeeping, references between exports and transforms (placed separately): not copied as values.
NOT_VALUES = {'UCSSerializationIndex', 'bNetAddressable', 'CreationMethod', 'UCSModifiedProperties', 'AttachParent',
              'LightGuid', 'MapBuildDataId', 'RelativeLocation', 'RelativeRotation', 'RelativeScale3D', 'BodyInstance',
              'VisualizeComponent', 'PreviewInfluenceRadius', 'BlueprintCreatedComponents'}


class Scene:
    def __init__(self, paks, umap):
        self.pkg = pkg = mapgeo.Package(pakfile.find(paks, umap), pakfile.find(paks, umap[:-5] + '.uexp'))
        self.level = next(i for i, e in enumerate(pkg.exports, 1) if e['class'] == 'Level')

    @classmethod
    def of(cls, pkg):
        """Property reading for any package (e.g. a Blueprint's)."""
        sc = cls.__new__(cls)
        sc.pkg, sc.level = pkg, None
        return sc

    def values(self, j):
        """Export j's saved property values in Unreal text form, skipping bookkeeping and references."""
        out = {}
        for k, (t, v) in self.tagged(j).items():
            if k not in NOT_VALUES and '[' not in k and not (isinstance(v, dict) and 'export' in v) and                     not isinstance(v, list):
                out[k] = ue_text(t, v)
        return out

    def raw_tags(self, i):
        """Export i's property tags as (name, index, type, extra, value offset, size)."""
        pkg = self.pkg
        r = Reader(pkg.b, pkg.exports[i - 1]['offset'])
        while True:
            name = pkg.fname(r)
            if name == 'None':
                return
            ptype = pkg.fname(r)
            size, index = r.i32(), r.i32()
            extra = None
            if ptype == 'StructProperty':
                extra = pkg.fname(r)
                r.raw(16)
            elif ptype == 'BoolProperty':
                extra = r.raw(1)[0]
            elif ptype in ('ByteProperty', 'EnumProperty', 'ArrayProperty', 'SetProperty'):
                extra = pkg.fname(r)
            elif ptype == 'MapProperty':
                extra = (pkg.fname(r), pkg.fname(r))
            if r.raw(1)[0]:
                r.raw(16)
            yield name, index, ptype, extra, r.o, size
            r.o += size

    def tagged(self, i):
        """Tagged properties of export i as {name: (type, value)} with references resolved to paths."""
        out = {}
        for name, index, ptype, extra, start, size in self.raw_tags(i):
            try:
                value = self._value(Reader(self.pkg.b, start), ptype, extra)
            except Exception:
                value = None
            if value is not None:
                out[name if not index else '%s[%d]' % (name, index)] = (ptype if ptype != 'StructProperty' else extra, value)
        return out

    def events(self, i, owner):
        """Export i's multicast delegates bound to functions of `owner` (its actor): {property: [function, ...]}.
        These are the Blueprint's component events (BndEvt__...), saved in the level."""
        out = {}
        for name, _, ptype, _, start, _ in self.raw_tags(i):
            if ptype not in ('MulticastSparseDelegateProperty', 'MulticastInlineDelegateProperty'):
                continue
            r = Reader(self.pkg.b, start)
            for _ in range(r.i32()):
                obj, function = r.i32(), self.pkg.fname(r)
                if obj == owner:
                    out.setdefault(name, []).append(function)
        return out

    def _value(self, r, ptype, extra):
        pkg = self.pkg
        if ptype == 'BoolProperty':
            return bool(extra)
        if ptype == 'FloatProperty':
            return r.floats(1)[0]
        if ptype == 'IntProperty':
            return r.i32()
        if ptype == 'EnumProperty' or (ptype == 'ByteProperty' and extra != 'None'):
            return pkg.fname(r)
        if ptype == 'NameProperty':
            return pkg.fname(r)
        if ptype == 'ObjectProperty':
            return self.ref(r.i32())
        if ptype == 'StructProperty' and extra in ('Vector', 'Rotator', 'LinearColor'):
            return mapgeo.NATIVE[extra](r)
        if ptype == 'StructProperty' and extra == 'Color':
            b, g, rr, a = r.raw(4)
            return (rr, g, b, a)
        if ptype == 'ArrayProperty' and extra == 'ObjectProperty':
            return [self.ref(r.i32()) for _ in range(r.i32())]
        return None

    def ref(self, i):
        """An imported asset as {'path', 'class'}; exports as {'export': i}; None for null."""
        pkg = self.pkg
        if i < 0:
            imp = pkg.imports[-i - 1]
            chain, o = [imp['name']], imp['outer']
            while o < 0:
                chain.append(pkg.imports[-o - 1]['name'])
                o = pkg.imports[-o - 1]['outer']
            return {'path': chain[-1], 'object': '.'.join(reversed(chain[:-1])), 'class': imp['class']}
        if i > 0:
            return {'export': i}
        return None

    def class_path(self, export):
        """Script path of an actor's class: /Script/Engine.StaticMeshActor or /Game/X/Y.Y_C."""
        pkg = self.pkg
        for imp in pkg.imports:
            if imp['name'] == export['class'] and imp['class'] in ('Class', 'BlueprintGeneratedClass'):
                o = pkg.imports[-imp['outer'] - 1]['name']
                return '%s.%s' % (o, imp['name'])
        return None

    def brush_size(self, i):
        """Box size of a volume's brush. Cooked brushes are default cubes (+-100) scaled by the component, so read the
        most common round coordinate in the Model's points."""
        pkg = self.pkg
        model = next((j for j, e in enumerate(pkg.exports, 1) if e['class'] == 'Model' and e['outer'] == i), None)
        if not model:
            return [200, 200, 200]
        e = pkg.exports[model - 1]
        data = pkg.b[e['offset']:e['offset'] + min(e['size'], 2048)]
        seen = collections.Counter()
        for k in range(0, len(data) - 4):
            v = struct.unpack_from('<f', data, k)[0]
            if 1 <= abs(v) <= 1e6 and abs(v - round(v)) < 1e-3:
                seen[abs(round(v))] += 1
        half = seen.most_common(1)[0][0] if seen else 100
        return [half * 2] * 3

    def component_refs(self, i, props):
        """Actor variables pointing at the actor's own components ({name: (component, class path)}), e.g. the jump
        pad's Centre -> Jump_Pad_Centre. The game's code uses them and they are only set in the saved level, so a
        level without them crashes the game."""
        out = {}
        for k, (_, v) in props.items():
            if k in ('RootComponent', 'BlueprintCreatedComponents') or not (isinstance(v, dict) and 'export' in v):
                continue
            c = self.pkg.exports[v['export'] - 1]
            if c['outer'] == i:
                out[k] = (c['name'], self.class_path(c))
        return out

    def construction_values(self, j):
        """Component values the actor's construction script set ({property: Unreal text}), as the component's
        UCSModifiedProperties lists them. Transforms are left to the import, which places components itself."""
        pkg = self.pkg
        try:
            raw = pkg.properties(pkg.exports[j - 1])
        except Exception:
            return {}
        names = [u.get('MemberName') for u in raw.get('UCSModifiedProperties') or [] if isinstance(u, dict)]
        typed = self.tagged(j)
        out = {}
        for name in names:
            if not name or name.startswith('Relative'):
                continue
            if name in typed:
                out[name] = ue_text(*typed[name])
            elif isinstance(raw.get(name), dict):
                out[name] = ue_text(None, raw[name])
        return out

    def atmosphere(self, j):
        """An AtmosphericFogComponent's precomputed tables (transmittance, irradiance, inscatter), saved inline after
        its properties. The editor only computes them while rendering, and without them the sky is black, so is the
        sky light's capture of it, and the level is lit by little more than gunfire."""
        pkg = self.pkg
        r = Reader(pkg.b, pkg.exports[j - 1]['offset'])
        pkg._props(r)
        r.o += 4  # no object GUID
        out = []
        for _ in range(3):
            flags, _count, size = struct.unpack_from('<Iii', pkg.b, r.o)
            r.o += 20
            if flags & 1:  # BULKDATA_PayloadAtEndOfFile: not inline, not in the game's maps
                return None
            out.append(pkg.b[r.o:r.o + size])
            r.o += size
        return out

    def actors(self):
        pkg = self.pkg
        out = []
        for i, e in enumerate(pkg.exports, 1):
            if e['outer'] != self.level or e['class'] in SKIP or e['class'] in ('Model', 'Level'):
                continue
            cls = self.class_path(e)
            if not cls:
                continue
            props = self.tagged(i)
            actor = {'name': e['name'], 'class': cls, 'props': {}, 'components': {},
                     'component_refs': {k: name for k, (name, _) in self.component_refs(i, props).items()}}
            root = props.get('RootComponent', (None, None))[1]
            for k, (t, v) in props.items():
                if not (isinstance(v, dict) and 'export' in v) and k not in ('BlueprintCreatedComponents',):
                    actor['props'][k] = (t, v)
            for prop, functions in self.events(i, i).items():
                actor.setdefault('events', {})[prop] = ','.join(functions)
            # Components owned by this actor, by name; the root's transform places the actor.
            for j, c in enumerate(pkg.exports, 1):
                if c['outer'] == i and c['class'] != 'Model':
                    cprops = {k: (t, v) for k, (t, v) in self.tagged(j).items()
                              if not (isinstance(v, dict) and 'export' in v)}
                    actor['components'][c['name']] = {'class': c['class'], 'props': cprops}
                    if root and root.get('export') == j:
                        actor['root'] = c['name']
                    for prop, functions in self.events(j, i).items():
                        actor.setdefault('events', {})['%s.%s' % (c['name'], prop)] = ','.join(functions)
                    if c['class'] == 'AtmosphericFogComponent':
                        actor['atmosphere'] = self.atmosphere(j)
                    for prop, text in self.construction_values(j).items():
                        actor.setdefault('construction_values', {})['%s.%s' % (c['name'], prop)] = text
                    for prop, text in self.values(j).items():
                        actor.setdefault('component_values', {})['%s.%s' % (c['name'], prop)] = text
            if 'Volume' in e['class'] or cls.endswith('Volume'):
                actor['brush'] = self.brush_size(i)
            out.append(actor)
        return out


def export(paks, umap):
    sc = Scene(paks, umap)
    missing = sorted({e['class'] for e in sc.pkg.exports if e['outer'] == sc.level and e['class'] in UNSUPPORTED})
    return {'map': umap, 'actors': sc.actors(), 'not_rebuilt': missing}


if __name__ == '__main__':
    import json
    import build
    paks = pakfile.game_paks(build.find_game())
    print(json.dumps(export(paks, sys.argv[1]), indent=1, default=lambda b: '<%d bytes>' % len(b)))
