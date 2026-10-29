"""Read a cooked map's foliage: each InstancedFoliageActor component's mesh, materials and instance transforms, so the
Map Kit can rebuild it as instanced meshes of the game's own meshes.

A cooked (Foliage/Hierarchical)InstancedStaticMeshComponent keeps its instances after its properties as an array of
FInstancedStaticMeshInstanceData: one 4x4 float matrix (row vectors) each, relative to the component.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mapgeo import Reader  # noqa: E402

INSTANCED = ('FoliageInstancedStaticMeshComponent', 'HierarchicalInstancedStaticMeshComponent',
             'InstancedStaticMeshComponent')


def instances(pkg, i, expected):
    """The component's instance matrices: [16 floats]. Found by its array header (element size 64, count)."""
    e = pkg.exports[i - 1]
    r = Reader(pkg.b, e['offset'])
    pkg._props(r)
    end = e['offset'] + e['size']
    for o in range(r.o, min(r.o + 256, end - 8)):
        size, count = struct.unpack_from('<ii', pkg.b, o)
        if size == 64 and count == expected and o + 8 + 64 * count <= end:
            return [struct.unpack_from('<16f', pkg.b, o + 8 + 64 * k) for k in range(count)]
    raise ValueError('%s: instance data not found' % e['name'])


def foliage(sc):
    """[{mesh, materials, instances, cull: (start, end), component transform}] for every foliage component."""
    pkg = sc.pkg
    owners = {i for i, e in enumerate(pkg.exports, 1) if e['class'] == 'InstancedFoliageActor' and e['outer'] == sc.level}
    out = []
    for i, e in enumerate(pkg.exports, 1):
        if e['outer'] not in owners or e['class'] not in INSTANCED:
            continue
        props = sc.tagged(i)
        mesh = props.get('StaticMesh', (None, None))[1]
        count = props.get('NumBuiltInstances', props.get('InstanceCountToRender', (None, 0)))[1]
        if not mesh or not count:
            continue
        mats = props.get('OverrideMaterials', (None, []))[1] or []
        out.append({
            'mesh': mesh['path'],
            'materials': ['%s.%s' % (m['path'], m.get('object') or m['path'].rsplit('/', 1)[1]) if m else None
                          for m in mats],
            'instances': instances(pkg, i, count),
            'cull': (props.get('InstanceStartCullDistance', (None, 0))[1],
                     props.get('InstanceEndCullDistance', (None, 0))[1]),
            'location': props.get('RelativeLocation', (None, (0, 0, 0)))[1],
            # The game's foliage is all NoCollision; default to that when a component doesn't say.
            'collision': (pkg.properties(e).get('BodyInstance') or {}).get('CollisionProfileName') or 'NoCollision',
        })
    return out


if __name__ == '__main__':
    import build
    import kit
    import pakfile
    import scene
    paks = pakfile.game_paks(build.find_game())
    for f in foliage(scene.Scene(paks, kit.map_path(paks, sys.argv[1]))):
        m = f['instances'][0]
        print(f['mesh'].rsplit('/', 1)[1], len(f['instances']), 'first at', m[12:15], 'scale', m[0], f['cull'])
