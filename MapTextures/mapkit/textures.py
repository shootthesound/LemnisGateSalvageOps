"""Decode the game's cooked textures to images, so the Map Kit's editor can show look-alike materials.

A cooked Texture2D holds its mips after its properties: each an FByteBulkData either inline, at the end of the
package, or in the package's .ubulk file (the big ones). Block-compressed formats decode with Pillow's BCn decoder.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mapgeo  # noqa: E402
import pakfile  # noqa: E402
from mapgeo import Reader  # noqa: E402

BCN = {'PF_DXT1': 1, 'PF_DXT3': 2, 'PF_DXT5': 3, 'PF_BC4': 4, 'PF_BC5': 5, 'PF_BC7': 7}


def package(paks, game_path):
    asset = 'LemnisGate/Content/' + game_path[len('/Game/'):]
    pkg = mapgeo.Package(pakfile.find(paks, asset + '.uasset'), pakfile.find(paks, asset + '.uexp'))
    try:
        ubulk = pakfile.find(paks, asset + '.ubulk')
    except KeyError:
        ubulk = None
    return pkg, ubulk


def mips(pkg, i):
    """(format, [(width, height, flags, size, offset, inline data offset or None)], properties) of export i."""
    e = pkg.exports[i - 1]
    r = Reader(pkg.b, e['offset'])
    props = pkg._props(r)
    r.raw(4 + 2 + 2 + 4)  # no GUID, two strip flags, bCooked
    pkg.fname(r)          # pixel format name
    r.raw(8)              # skip offset
    width, height = r.i32(), r.i32()
    r.i32()
    n = r.i32()
    fmt = r.raw(n)[:-1].decode('ascii')
    r.i32()               # first mip to serialize
    out = []
    for _ in range(r.i32()):
        r.i32()           # bCooked
        flags, _count, size = struct.unpack_from('<Iii', pkg.b, r.o)
        offset = struct.unpack_from('<q', pkg.b, r.o + 12)[0]
        r.raw(20)
        inline = None
        if not flags & 0x101:  # neither in the .ubulk nor at the end of the package
            inline = r.o
            r.raw(size)
        w, h = r.i32(), r.i32()
        r.i32()           # depth
        out.append((w, h, flags, size, offset, inline))
    return fmt, out, props


def decode(paks, game_path, max_size=1024):
    """The texture as a PIL image (its largest mip no bigger than max_size that can be read), or None."""
    from PIL import Image
    pkg, ubulk = package(paks, game_path)
    i = next(k for k, e in enumerate(pkg.exports, 1) if e['class'] in ('Texture2D', 'LightMapTexture2D'))
    fmt, levels, props = mips(pkg, i)
    for w, h, flags, size, offset, inline in levels:
        if max(w, h) > max_size and (w, h) != levels[-1][:2]:
            continue
        if inline is not None:
            data = pkg.b[inline:inline + size]
        elif flags & 0x100 and ubulk is not None and offset + size <= len(ubulk):
            data = ubulk[offset:offset + size]
        else:
            continue
        try:
            if fmt in BCN:
                bw, bh = max(4, (w + 3) // 4 * 4), max(4, (h + 3) // 4 * 4)
                mode = {4: 'L', 5: 'RGB'}.get(BCN[fmt], 'RGBA')
                img = Image.frombytes(mode, (bw, bh), data, 'bcn', BCN[fmt]).crop((0, 0, w, h))
                if BCN[fmt] == 5:  # normal map: rebuild blue from red and green
                    r_, g_, _ = img.split()
                    img = Image.merge('RGB', (r_, g_, Image.new('L', img.size, 255)))
                return img
            if fmt == 'PF_B8G8R8A8':
                b, g, r_, a = Image.frombytes('RGBA', (w, h), data).split()
                return Image.merge('RGBA', (r_, g, b, a))
            if fmt == 'PF_G8':
                return Image.frombytes('L', (w, h), data)
        except Exception:
            continue
        return None
    return None


def kind(paks, game_path):
    """'normal', 'mask' or 'color' from the texture's compression settings and sRGB flag."""
    pkg, _ = package(paks, game_path)
    i, e = next((k, e) for k, e in enumerate(pkg.exports, 1) if e['class'] in ('Texture2D', 'LightMapTexture2D'))
    if mips(pkg, i)[0] == 'PF_BC5':  # Unreal stores normal maps as BC5
        return 'normal'
    props = pkg.properties(e)
    comp = str(props.get('CompressionSettings') or '')
    if 'Normal' in comp:
        return 'normal'
    if props.get('SRGB') is False or any(k in comp for k in ('Masks', 'Grayscale', 'Alpha', 'Displacement')):
        return 'mask'
    return 'color'


if __name__ == '__main__':
    import build
    paks = pakfile.game_paks(build.find_game())
    for p in sys.argv[1:]:
        img = decode(paks, p)
        print(p, kind(paks, p), img and img.size, img and img.mode)
        if img:
            img.save(os.path.join(build.BUILD, p.rsplit('/', 1)[1] + '.png'))
