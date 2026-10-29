"""Read the game's cooked static meshes (Unreal 4.26), so the Map Kit's editor shows real shapes instead of cubes.

Only the editor sees these copies: the cooked map references the game's own mesh by path, as with the stand-ins.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mapgeo  # noqa: E402
import pakfile  # noqa: E402
from mapgeo import Reader  # noqa: E402


def half(h):
    return struct.unpack('<e', struct.pack('<H', h))[0]


def bulk_array(r):
    """TResourceArray::BulkSerialize: element size, count, data."""
    elem, count = r.i32(), r.i32()
    return elem, count, r.raw(elem * count)


class Mesh:
    """LOD 0 of a cooked StaticMesh: positions, normals, UV0, triangle indices and material sections."""

    def __init__(self, paks, game_path):
        self.path = game_path
        asset = 'LemnisGate/Content/' + game_path[len('/Game/'):]
        pkg = mapgeo.Package(pakfile.find(paks, asset + '.uasset'), pakfile.find(paks, asset + '.uexp'))
        self.pkg = pkg
        e = next(e for e in pkg.exports if e['class'] == 'StaticMesh')
        r = Reader(pkg.b, e['offset'])
        props = pkg._props(r)
        self.slots = [m.get('MaterialSlotName') or 'Slot%d' % i for i, m in enumerate(props.get('StaticMaterials') or [])]
        self.materials = [self._material(m.get('MaterialInterface')) for m in props.get('StaticMaterials') or []]
        # Baked lighting maps onto this UV channel at this resolution (the game's meshes all have one).
        self.lightmap_index = props.get('LightMapCoordinateIndex') or 0
        self.lightmap_resolution = props.get('LightMapResolution') or 4
        r.o += 4      # no object GUID
        r.raw(2)      # strip flags
        r.raw(4 * 3)  # bCooked, BodySetup, NavCollision
        r.raw(16)     # LightingGuid
        for _ in range(r.i32()):  # sockets
            r.i32()
        lods = r.i32()
        if lods < 1:
            raise ValueError('no LODs')
        self._lod(r, pkg, asset)

    def _material(self, ref):
        if not ref or ref[1] >= 0:
            return None
        return '%s.%s' % (self.pkg.import_path(ref[1]), self.pkg.imports[-ref[1] - 1]['name'])

    def _lod(self, r, pkg, asset):
        r.raw(2)  # strip flags
        self.sections = []
        for _ in range(r.i32()):
            material, first, tris, _vmin, _vmax = struct.unpack_from('<iIIII', pkg.b, r.o)
            r.raw(36)
            self.sections.append((material, first, tris))
        r.raw(4)  # MaxDeviation
        cooked_out, inlined = r.i32(), r.i32()
        if cooked_out:
            raise ValueError('LOD 0 cooked out')
        if not inlined:
            # Streamed LOD: an FByteBulkData whose payload (in the .ubulk) is the same buffer stream.
            flags, _count, size = struct.unpack_from('<Iii', pkg.b, r.o)
            offset = struct.unpack_from('<q', pkg.b, r.o + 12)[0]
            if flags & 0x40:  # BULKDATA_Size64Bit is not used by this game
                raise ValueError('64-bit bulk data')
            bulk = pakfile.find(self._paks, asset + '.ubulk')
            r = Reader(bulk[offset:offset + size])
        self._buffers(r)

    def _buffers(self, r):
        r.raw(2)  # strip flags
        stride, count = r.i32(), r.i32()
        _, n, data = bulk_array(r)
        self.positions = [struct.unpack_from('<3f', data, i * 12) for i in range(n)]
        # FStaticMeshVertexBuffer
        r.raw(2)
        uv_count, n2 = r.i32(), r.i32()
        full_uvs, high_tangents = r.i32(), r.i32()
        _, _, tangents = bulk_array(r)
        _, _, uvs = bulk_array(r)
        if n2 != n:
            raise ValueError('vertex count mismatch %d/%d' % (n, n2))
        self.normals = []
        tsize = 16 if high_tangents else 8
        for i in range(n):
            if high_tangents:
                z = struct.unpack_from('<4h', tangents, i * tsize + 8)
                self.normals.append(tuple(v / 32767.0 for v in z[:3]))
            else:
                z = tangents[i * tsize + 4:i * tsize + 8]
                self.normals.append(tuple((b - 127.5) / 127.5 for b in z[:3]))
        usize = 8 if full_uvs else 4
        self.uv_channels = []  # [[(u, v) per vertex] per channel]
        for ch in range(uv_count):
            channel = []
            for i in range(n):
                o = (i * uv_count + ch) * usize
                if full_uvs:
                    channel.append(struct.unpack_from('<2f', uvs, o))
                else:
                    channel.append(tuple(half(h) for h in struct.unpack_from('<2H', uvs, o)))
            self.uv_channels.append(channel)
        self.uvs = self.uv_channels[0]
        # FColorVertexBuffer
        r.raw(2)
        cstride, cn = r.i32(), r.i32()
        if cn:
            bulk_array(r)
        # FRawStaticIndexBuffer
        wide = r.i32()
        _, nbytes, data = bulk_array(r)
        fmt = '<%d%s' % (nbytes // (4 if wide else 2), 'I' if wide else 'H')
        self.indices = list(struct.unpack_from(fmt, data))
        if len(self.indices) < sum(t for _, _, t in self.sections) * 3 or (self.indices and max(self.indices) >= n):
            raise ValueError('index buffer does not match the vertices')

    def write(self, path):
        """Simple binary file MapKitLibrary.ImportMesh reads (all little-endian):
        vertex count, positions (3f), normals (3f); UV channel count, per channel UVs (2f); lightmap UV channel and
        resolution; slot count, per slot name (int length + UTF-8) and material path; section count, per section
        (material slot, first index, triangle count); index count, indices."""
        out = [struct.pack('<i', len(self.positions))]
        out += [struct.pack('<3f', *p) for p in self.positions]
        out += [struct.pack('<3f', *v) for v in self.normals]
        out.append(struct.pack('<i', len(self.uv_channels)))
        for channel in self.uv_channels:
            out += [struct.pack('<2f', *uv) for uv in channel]
        out.append(struct.pack('<ii', self.lightmap_index, self.lightmap_resolution))

        def text(s):
            b = (s or '').encode('utf-8')
            return struct.pack('<i', len(b)) + b

        out.append(struct.pack('<i', len(self.slots)))
        for name, material in zip(self.slots, self.materials):
            out += [text(name), text(material)]
        out.append(struct.pack('<i', len(self.sections)))
        out += [struct.pack('<iII', *s) for s in self.sections]
        out.append(struct.pack('<i', len(self.indices)))
        out.append(struct.pack('<%dI' % len(self.indices), *self.indices))
        open(path, 'wb').write(b''.join(out))


def read(paks, game_path):
    Mesh._paks = paks
    return Mesh(paks, game_path)


if __name__ == '__main__':
    import build
    paks = pakfile.game_paks(build.find_game())
    for p in sys.argv[1:]:
        m = read(paks, p)
        lo = [min(v[k] for v in m.positions) for k in range(3)]
        hi = [max(v[k] for v in m.positions) for k in range(3)]
        print(p, len(m.positions), 'verts', len(m.indices) // 3, 'tris', m.sections, m.slots, 'bounds', lo, hi)
