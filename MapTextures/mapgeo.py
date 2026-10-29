"""Extract the box/plane geometry of a cooked Lemnis Gate map for the studio's fly-through preview.

The prototype maps are built from the engine's basic Cube and Plane meshes, so each StaticMeshComponent becomes
one shape with a world transform and the slot its material belongs to.
"""
import math
import struct

import pakfile

SHAPES = {'Cube': 'cube', 'Plane': 'plane', 'Cylinder': 'cylinder', 'Sphere': 'sphere', 'Cone': 'cone'}
NATIVE = {
    'Vector': lambda r: r.floats(3), 'Rotator': lambda r: r.floats(3), 'Vector4': lambda r: r.floats(4),
    'Quat': lambda r: r.floats(4), 'LinearColor': lambda r: r.floats(4), 'Color': lambda r: r.raw(4),
    'Guid': lambda r: r.raw(16), 'Vector2D': lambda r: r.floats(2), 'IntPoint': lambda r: r.raw(8),
    'Box': lambda r: (r.floats(3), r.floats(3), r.raw(1)),
}


class Reader:
    def __init__(self, b, o=0):
        self.b, self.o = b, o

    def i32(self):
        v = struct.unpack_from('<i', self.b, self.o)[0]
        self.o += 4
        return v

    def raw(self, n):
        v = self.b[self.o:self.o + n]
        self.o += n
        return v

    def floats(self, n):
        v = struct.unpack_from('<%df' % n, self.b, self.o)
        self.o += 4 * n
        return v


class Package:
    """Cooked .umap/.uasset + .uexp with tagged (versioned) properties, UE 4.26."""

    def __init__(self, header, body):
        self.b = header + body
        d = header
        o = 20
        o += 4 + 20 * struct.unpack_from('<i', d, o)[0]
        self.header_size = struct.unpack_from('<i', d, o)[0]
        o += 4
        _, o = pakfile._fstring(d, o)
        o += 4 + 8 + 8
        ec, eo, ic, io = struct.unpack_from('<iiii', d, o)
        self.names = [s for _, s, _ in pakfile.name_table(d)]
        self.imports = []
        for k in range(ic):
            p = io + k * 28
            self.imports.append({'class': self.name_at(p + 8), 'outer': struct.unpack_from('<i', d, p + 16)[0],
                                 'name': self.name_at(p + 20)})
        self.exports = []
        for k in range(ec):
            p = eo + k * 104
            cls, sup, tmpl, outer = struct.unpack_from('<iiii', d, p)
            size, offset = struct.unpack_from('<qq', d, p + 28)
            self.exports.append({'class': self.ref_name(cls), 'outer': outer, 'name': self.name_at(p + 16),
                                 'size': size, 'offset': offset})

    def name_at(self, off):
        i, n = struct.unpack_from('<ii', self.b, off)
        return self.names[i] + ('_%d' % (n - 1) if n else '')

    def fname(self, r):
        i, n = struct.unpack_from('<ii', r.b, r.o)
        r.o += 8
        return self.names[i] + ('_%d' % (n - 1) if n else '')

    def ref_name(self, i):
        if i < 0:
            return self.imports[-i - 1]['name']
        if i > 0:
            return self.exports[i - 1]['name'] if i - 1 < len(getattr(self, 'exports', [])) else '#%d' % i
        return None

    def import_path(self, i):
        """Full object path of an import, e.g. /Game/.../MI_X.MI_X -> returns the package path."""
        imp = self.imports[-i - 1]
        while imp['outer'] < 0:
            imp = self.imports[-imp['outer'] - 1]
        return imp['name']

    def properties(self, export):
        return self._props(Reader(self.b, export['offset']))

    def _props(self, r):
        out = {}
        while True:
            name = self.fname(r)
            if name == 'None':
                return out
            ptype = self.fname(r)
            size = r.i32()
            r.i32()  # array index
            extra = None
            if ptype == 'StructProperty':
                extra = self.fname(r)
                r.raw(16)
            elif ptype == 'BoolProperty':
                extra = r.raw(1)[0]
            elif ptype in ('ByteProperty', 'EnumProperty', 'ArrayProperty', 'SetProperty'):
                extra = self.fname(r)
            elif ptype == 'MapProperty':
                self.fname(r)
                self.fname(r)
            if r.raw(1)[0]:
                r.raw(16)
            end = r.o + size
            try:
                out[name] = self._value(r, ptype, extra)
            except Exception:
                out[name] = None
            r.o = end

    def _value(self, r, ptype, extra):
        if ptype == 'BoolProperty':
            return bool(extra)
        if ptype == 'FloatProperty':
            return r.floats(1)[0]
        if ptype == 'IntProperty':
            return r.i32()
        if ptype == 'ObjectProperty':
            return ('ref', r.i32())
        if ptype == 'NameProperty' or ptype == 'EnumProperty':
            return self.fname(r)
        if ptype == 'ByteProperty':  # an enum stored by name (e.g. EBlendMode::BLEND_Masked), else a plain byte
            return self.fname(r) if extra and extra != 'None' else r.raw(1)[0]
        if ptype == 'StructProperty':
            return NATIVE[extra](r) if extra in NATIVE else self._props(r)
        if ptype == 'ArrayProperty':
            n = r.i32()
            if extra == 'ObjectProperty':
                return [('ref', r.i32()) for _ in range(n)]
            if extra == 'StructProperty':
                self.fname(r)
                self.fname(r)
                r.i32()
                r.i32()
                sname = self.fname(r)
                r.raw(17)
                return [NATIVE[sname](r) if sname in NATIVE else self._props(r) for _ in range(n)]
            return None
        return None


# ---------------------------------------------------------------- transforms

def rot_matrix(pitch, yaw, roll):
    """FRotationMatrix in UE's convention (degrees). Rows are the rotated X, Y, Z axes."""
    p, y, r = (math.radians(a) for a in (pitch, yaw, roll))
    sp, cp, sy, cy, sr, cr = math.sin(p), math.cos(p), math.sin(y), math.cos(y), math.sin(r), math.cos(r)
    return [[cp * cy, cp * sy, sp],
            [sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp],
            [-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp]]


def compose(child, parent):
    """World transform of `child` (relative to `parent`). Each is (location, rotation rows, scale)."""
    cl, cr, cs = child
    pl, pr, ps = parent
    scaled = [cl[i] * ps[i] for i in range(3)]
    loc = [pl[j] + sum(scaled[i] * pr[i][j] for i in range(3)) for j in range(3)]
    rot = [[sum(cr[i][k] * pr[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    scale = [cs[i] * ps[i] for i in range(3)]  # exact for the axis-aligned scales used in greybox maps
    return loc, rot, scale


def map_geometry(paks, umap_path, slot_assets):
    """Shapes in a map: [{shape, slot, loc, rot (3x3 rows), scale}] in Unreal units (cm, Z up)."""
    pkg = Package(pakfile.find(paks, umap_path), pakfile.find(paks, umap_path[:-5] + '.uexp'))
    components = {}
    for i, e in enumerate(pkg.exports, 1):
        if e['class'] in ('StaticMeshComponent', 'SceneComponent', 'CapsuleComponent', 'BoxComponent',
                          'SphereComponent', 'ChildActorComponent') or e['class'].endswith('Component'):
            try:
                components[i] = (e, pkg.properties(e))
            except Exception:
                pass

    cache = {}

    def world(i, depth=0):
        if i in cache:
            return cache[i]
        e, props = components.get(i, (None, {}))
        local = (list(props.get('RelativeLocation') or (0, 0, 0)),
                 rot_matrix(*(props.get('RelativeRotation') or (0, 0, 0))),
                 list(props.get('RelativeScale3D') or (1, 1, 1)))
        parent = props.get('AttachParent')
        if parent and parent[1] > 0 and parent[1] in components and depth < 32:
            result = compose(local, world(parent[1], depth + 1))
        else:
            result = local
        cache[i] = result
        return result

    shapes = []
    for i, (e, props) in components.items():
        if e['class'] != 'StaticMeshComponent':
            continue
        mesh = props.get('StaticMesh')
        if not mesh or mesh[1] >= 0:
            continue
        shape = SHAPES.get(pkg.imports[-mesh[1] - 1]['name'])
        if not shape:
            continue
        slot = None
        for m in props.get('OverrideMaterials') or []:
            if m and m[1] < 0:
                slot = slot_assets.get(pkg.import_path(m[1]))
                break
        loc, rot, scale = world(i)
        if props.get('bVisible') is False or props.get('bHiddenInGame') is True:
            continue
        shapes.append({'shape': shape, 'slot': slot, 'loc': [round(v, 2) for v in loc],
                       'rot': [[round(v, 5) for v in row] for row in rot], 'scale': [round(v, 4) for v in scale]})
    return shapes
