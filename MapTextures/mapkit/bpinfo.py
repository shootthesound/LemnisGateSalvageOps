"""Read the component layout of the game's cooked Blueprints, so the Map Kit can build editor stand-ins with the
same class names, parents and component names. A map cooked against the stand-ins then loads the real ones in-game.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mapgeo  # noqa: E402
import pakfile  # noqa: E402
import scene  # noqa: E402
from mapgeo import Reader  # noqa: E402

# Template properties copied onto the stand-in components, so they sit and look where the real ones do.
TEMPLATE_KEYS = ('RelativeLocation', 'RelativeRotation', 'RelativeScale3D', 'SphereRadius', 'CapsuleHalfHeight',
                 'CapsuleRadius', 'BoxExtent', 'StaticMesh', 'bHiddenInGame', 'bVisible')


def content_path(game_path):
    """/Game/X/Y -> LemnisGate/Content/X/Y.uasset"""
    return 'LemnisGate/Content/' + game_path[len('/Game/'):] + '.uasset'


class Blueprint:
    def __init__(self, paks, game_path):
        self.path = game_path
        asset = content_path(game_path)
        self.pkg = pkg = mapgeo.Package(pakfile.find(paks, asset), pakfile.find(paks, asset[:-7] + '.uexp'))
        self.cls = next(e for e in pkg.exports if e['class'] == 'BlueprintGeneratedClass')
        r = Reader(pkg.b, self.cls['offset'])
        props = pkg._props(r)
        # UObject trailer (no GUID flag), then UStruct::SuperStruct.
        self.parent = self.ref(struct.unpack_from('<i', pkg.b, r.o + 4)[0])
        self.nodes = self._scs(props.get('SimpleConstructionScript'))
        self.overrides = self._ich(props.get('InheritableComponentHandler'))
        self.native_components, self.root = self._native_components()

    def ref(self, i):
        """An object reference as {'name', 'package'} (imports) or {'name', 'export'} (this package)."""
        pkg = self.pkg
        if i < 0:
            return {'name': pkg.imports[-i - 1]['name'], 'package': pkg.import_path(i)}
        if i > 0:
            return {'name': pkg.exports[i - 1]['name'], 'export': i}
        return None

    def _template(self, ref):
        if not ref or ref[1] <= 0:
            return {}
        props = self.pkg.properties(self.pkg.exports[ref[1] - 1])
        out = {k: props[k] for k in TEMPLATE_KEYS if k in props}
        # Everything else as text: stand-in templates must match the game's so levels save the same differences.
        out['values'] = scene.Scene.of(self.pkg).values(ref[1])
        if isinstance(out.get('StaticMesh'), tuple):
            m = self.ref(out['StaticMesh'][1])
            out['StaticMesh'] = m and m.get('package')
        return out

    def _scs(self, scs_ref):
        if not scs_ref or scs_ref[1] <= 0:
            return []
        pkg = self.pkg
        nodes, parent_of = [], {}
        scs = pkg.properties(pkg.exports[scs_ref[1] - 1])
        all_refs = [x[1] for x in scs.get('AllNodes') or []]
        props = {i: pkg.properties(pkg.exports[i - 1]) for i in all_refs if i > 0}
        for i, p in props.items():
            for c in p.get('ChildNodes') or []:
                parent_of[c[1]] = p.get('InternalVariableName')
        for i in all_refs:
            p = props.get(i)
            if not p:
                continue
            cls = self.ref(p['ComponentClass'][1]) if p.get('ComponentClass') else None
            nodes.append({
                'name': p.get('InternalVariableName'),
                'class': cls and cls['name'], 'class_package': cls and cls.get('package'),
                'parent': parent_of.get(i) or p.get('ParentComponentOrVariableName'),
                'parent_inherited': i not in parent_of and bool(p.get('ParentComponentOrVariableName')),
                'template': self._template(p.get('ComponentTemplate')),
            })
        return nodes

    def _ich(self, ich_ref):
        """Components of parent Blueprints this one overrides (InheritableComponentHandler records)."""
        if not ich_ref or ich_ref[1] <= 0:
            return []
        pkg = self.pkg
        out = []
        for i, e in enumerate(pkg.exports, 1):
            if e['outer'] == ich_ref[1]:
                name = e['name'][:-len('_GEN_VARIABLE')] if e['name'].endswith('_GEN_VARIABLE') else e['name']
                try:
                    tmpl = self._template(('ref', i))
                except Exception:
                    tmpl = {}
                out.append({'name': name, 'class': e['class'], 'template': tmpl})
        return out

    def _native_components(self):
        """Components created by the native parent class: subobjects of the class default object."""
        pkg = self.pkg
        cdo = next((i for i, e in enumerate(pkg.exports, 1) if e['name'] == 'Default__' + self.cls['name']), None)
        if not cdo:
            return [], None
        cdo_props = pkg.properties(pkg.exports[cdo - 1])
        root = cdo_props.get('RootComponent')
        out = []
        for i, e in enumerate(pkg.exports, 1):
            if e['outer'] == cdo:
                props = pkg.properties(e)
                parent = props.get('AttachParent')
                out.append({'name': e['name'], 'class': e['class'],
                            'parent': self.ref(parent[1])['name'] if parent and parent[1] else None,
                            'template': self._template(('ref', i))})
        root_name = self.ref(root[1])['name'] if root and root[1] else None
        return out, root_name

    def info(self):
        return {'path': self.path, 'class': self.cls['name'], 'parent': self.parent, 'root': self.root,
                'nodes': self.nodes, 'overrides': self.overrides, 'native_components': self.native_components}


def catalog(paks, roots):
    """Blueprints `roots` (game paths) plus every Blueprint parent and component class they depend on."""
    out, todo = {}, list(roots)
    while todo:
        path = todo.pop()
        if path in out:
            continue
        try:
            bp = Blueprint(paks, path).info()
        except KeyError:
            out[path] = None
            continue
        out[path] = bp
        deps = [bp['parent']] + [{'package': n['class_package']} for n in bp['nodes']]
        todo += [d['package'] for d in deps if d and (d.get('package') or '').startswith('/Game/')]
    return out


if __name__ == '__main__':
    import json
    import build
    paks = pakfile.game_paks(build.find_game())
    print(json.dumps(catalog(paks, sys.argv[1:]), indent=1, default=str))
