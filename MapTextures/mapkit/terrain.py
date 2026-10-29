"""Read a cooked map's terrain (Landscape) as one heightmap, so the Map Kit can rebuild it in the editor.

A cooked Landscape keeps its heights in B8G8R8A8 textures inside the map package (height = R << 8 | G, 32768 = zero),
one region per component, located by the component's HeightmapScaleBias. Neighbouring subsections repeat their shared
edge in the texture.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mapgeo import Reader  # noqa: E402


def texture_mip0(pkg, i, ubulk=None):
    """(width, height, BGRA bytes) of an uncompressed cooked Texture2D export's first mip (`ubulk`: the package's
    .ubulk file, where larger maps keep it)."""
    e = pkg.exports[i - 1]
    r = Reader(pkg.b, e['offset'])
    pkg._props(r)
    r.raw(4 + 2 + 2 + 4)  # no GUID, two strip flags, bCooked
    pkg.fname(r)          # pixel format name
    r.raw(8)              # skip offset
    width, height = r.i32(), r.i32()
    r.i32()               # packed slice count / cubemap bit
    n = r.i32()
    fmt = r.raw(n)[:-1].decode('ascii')
    if fmt != 'PF_B8G8R8A8':
        raise ValueError('heightmap format %s' % fmt)
    r.i32()               # first mip to serialize
    if r.i32() < 1:
        raise ValueError('no mips')
    r.i32()               # bCooked
    flags, count, size = struct.unpack_from('<Iii', pkg.b, r.o)
    offset = struct.unpack_from('<q', pkg.b, r.o + 12)[0]
    r.raw(20)
    if flags & 0x100:     # BULKDATA_PayloadInSeperateFile: in the .ubulk
        if ubulk is None:
            raise ValueError('heightmap is in the .ubulk file')
        data = ubulk[offset:offset + size]
    elif flags & 0x01:    # end of the .uexp (not used for the game's heightmaps)
        raise ValueError('heightmap stored at the end of the package')
    else:
        data = r.raw(size)
    if len(data) != width * height * 4:
        raise ValueError('heightmap size')
    return width, height, data


def allocations(sc, i):
    """A LandscapeComponent's weightmap layers: [(layer info object name, texture index, channel)]."""
    pkg = sc.pkg
    out = []
    for name, _, _, _, start, _ in sc.raw_tags(i):
        if name != 'WeightmapLayerAllocations':
            continue
        r = Reader(pkg.b, start)
        n = r.i32()
        pkg.fname(r); pkg.fname(r); r.i32(); r.i32(); pkg.fname(r); r.raw(17)  # inner struct tag
        for _ in range(n):
            layer, tex, channel = None, 0, 0
            while True:
                field = pkg.fname(r)
                if field == 'None':
                    break
                ftype = pkg.fname(r)
                size = r.i32()
                r.i32()
                if ftype == 'ByteProperty':
                    pkg.fname(r)
                r.raw(1)
                if field == 'LayerInfo':
                    ref = struct.unpack_from('<i', pkg.b, r.o)[0]
                    layer = pkg.imports[-ref - 1]['name'] if ref < 0 else pkg.exports[ref - 1]['name'] if ref else None
                elif field == 'WeightmapTextureIndex':
                    tex = pkg.b[r.o]
                elif field == 'WeightmapTextureChannel':
                    channel = pkg.b[r.o]
                r.o += size
            out.append((layer, tex, channel))
    return out


# Texture channel (R, G, B, A) -> byte in a B8G8R8A8 texel.
CHANNEL_BYTE = (2, 1, 0, 3)


def landscapes(sc, ubulk=None):
    """Each Landscape in scene `sc` as {name, transform props, grid size, heights (row-major uint16 list), ...}."""
    pkg = sc.pkg
    out = []
    for i, e in enumerate(pkg.exports, 1):
        if e['class'] not in ('Landscape', 'LandscapeStreamingProxy') or e['outer'] != sc.level:
            continue
        props = sc.tagged(i)
        comps = [c['export'] for c in props.get('LandscapeComponents', (None, []))[1] or [] if c]
        quads = props['ComponentSizeQuads'][1]
        sub_quads, subs = props['SubsectionSizeQuads'][1], props['NumSubsections'][1]
        sections = []
        for c in comps:
            cp = sc.tagged(c)
            bias = None
            for name, _, _, _, start, size in sc.raw_tags(c):
                if name == 'HeightmapScaleBias':
                    bias = struct.unpack_from('<4f', pkg.b, start)
            wbias = None
            for name, _, _, _, start, size in sc.raw_tags(c):
                if name == 'WeightmapScaleBias':
                    wbias = struct.unpack_from('<4f', pkg.b, start)
            weightmaps = [w['export'] for w in (cp.get('WeightmapTextures', (None, []))[1] or []) if w and 'export' in w]
            hole = next(((weightmaps[t], ch) for layer, t, ch in allocations(sc, c)
                         if layer == 'DataLayer' and t < len(weightmaps)), None)
            sections.append((cp['SectionBaseX'][1] if 'SectionBaseX' in cp else 0,
                             cp['SectionBaseY'][1] if 'SectionBaseY' in cp else 0,
                             cp['HeightmapTexture'][1]['export'], bias, hole, wbias))
        if not sections:
            continue
        min_x = min(s[0] for s in sections)
        min_y = min(s[1] for s in sections)
        max_x = max(s[0] for s in sections) + quads
        max_y = max(s[1] for s in sections) + quads
        w, h = max_x - min_x + 1, max_y - min_y + 1
        heights = [32768] * (w * h)
        holes = None
        textures = {}

        def texels(tex, bias):
            """(texture data, width, vertex (x, y) in the component -> byte offset of its texel)."""
            if tex not in textures:
                textures[tex] = texture_mip0(pkg, tex, ubulk)
            tw, th, data = textures[tex]
            ox, oy = int(bias[2] * tw), int(bias[3] * th)  # weightmaps are biased half a texel

            def at(x, y):
                sy = min(y // sub_quads, subs - 1)
                sx = min(x // sub_quads, subs - 1)
                return ((oy + sy * (sub_quads + 1) + y - sy * sub_quads) * tw + ox + sx * (sub_quads + 1) + x - sx * sub_quads) * 4
            return data, at

        for bx, by, tex, bias, hole, wbias in sections:
            data, at = texels(tex, bias)
            for y in range(quads + 1):
                for x in range(quads + 1):
                    p = at(x, y)
                    heights[(by - min_y + y) * w + (bx - min_x + x)] = data[p + 2] << 8 | data[p + 1]
            if hole and wbias:
                holes = holes or [0] * (w * h)
                wdata, wat = texels(hole[0], wbias)
                byte = CHANNEL_BYTE[hole[1]]
                for y in range(quads + 1):
                    for x in range(quads + 1):
                        holes[(by - min_y + y) * w + (bx - min_x + x)] = wdata[wat(x, y) + byte]
        root = props.get('RootComponent', (None, None))[1]
        transform = sc.tagged(root['export']) if root else {}
        material = props.get('LandscapeMaterial', (None, None))[1]
        out.append({'name': e['name'], 'min': (min_x, min_y), 'size': (w, h), 'heights': heights, 'holes': holes,
                    'quads': quads, 'subsection_quads': sub_quads, 'subsections': subs,
                    'location': transform.get('RelativeLocation', (None, (0, 0, 0)))[1],
                    'rotation': transform.get('RelativeRotation', (None, (0, 0, 0)))[1],
                    'scale': transform.get('RelativeScale3D', (None, (1, 1, 1)))[1],
                    'material': material and material.get('path')})
    return out


if __name__ == '__main__':
    import build
    import kit
    import pakfile
    import scene
    paks = pakfile.game_paks(build.find_game())
    umap = kit.map_path(paks, sys.argv[1])
    sc = scene.Scene(paks, umap)
    try:
        ubulk = pakfile.find(paks, umap[:-5] + '.ubulk')
    except KeyError:
        ubulk = None
    for land in landscapes(sc, ubulk):
        hs = land['heights']
        print(land['name'], land['size'], 'min', land['min'], 'quads', land['quads'], land['subsections'],
              'x', land['subsection_quads'], 'heights', min(hs), max(hs), 'at', land['location'], land['scale'],
              land['material'], 'holes', sum(1 for v in land['holes'] or [] if v > 127))
