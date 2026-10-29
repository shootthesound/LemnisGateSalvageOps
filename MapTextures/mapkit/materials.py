"""Work out what the game's materials look like (colour texture, normal map, tint), so the Map Kit's editor can show
look-alikes instead of grey. Cooked materials keep no node graph, so this goes by what they reference: a material
instance's texture and colour parameters (and its parents'), or a material's own textures, chosen by name.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mapgeo  # noqa: E402
import pakfile  # noqa: E402

COLOR = re.compile(r'(base_?colou?r|albedo|diffuse|_d$|_bc$|_alb|_col(or)?$|_c$|^t_.*_d\b|colou?r)', re.I)
NORMAL = re.compile(r'(normal|_n$|_nrm|_nor$|_norm)', re.I)
NOT_COLOR = re.compile(r'(mask|orm|rma|arm|rough|metal|_r$|_m$|_ao|occlusion|emissive|_e$|height|disp|opacity|'
                       r'alpha|noise|detail|cloud|flow|gradient|_h$|specular|_s$)', re.I)
TINT = re.compile(r'(colou?r|tint|albedo|base)', re.I)


def ref_path(pkg, ref):
    if not ref or ref[1] >= 0:
        return None
    return pkg.import_path(ref[1])


def load(paks, game_path):
    asset = 'LemnisGate/Content/' + game_path[len('/Game/'):]
    return mapgeo.Package(pakfile.find(paks, asset + '.uasset'), pakfile.find(paks, asset + '.uexp'))


def describe(paks, game_path, depth=0):
    """{'class', 'textures': [(parameter name or '', texture path)], 'colors': {name: rgba}, 'parent'}."""
    pkg = load(paks, game_path)
    e = next(e for e in pkg.exports if e['outer'] == 0 and not e['name'].startswith('Default__'))
    out = {'class': e['class'], 'textures': [], 'colors': {}, 'parent': None}
    try:
        props = pkg.properties(e)
    except Exception:
        props = {}
    # Cut-out (leaves, grates) and two-sided: on the material, or overridden on an instance.
    over = props.get('BasePropertyOverrides') or {}
    blend = over.get('BlendMode') if over.get('bOverride_BlendMode') else props.get('BlendMode')
    if blend:
        out['blend'] = str(blend).split('::')[-1]
    two = over.get('TwoSided') if over.get('bOverride_TwoSided') else props.get('TwoSided')
    if two is not None:
        out['two_sided'] = bool(two)
    for p in props.get('TextureParameterValues') or []:
        name = (p.get('ParameterInfo') or {}).get('Name') or ''
        path = ref_path(pkg, p.get('ParameterValue'))
        if path:
            out['textures'].append((name, path))
    out['scalars'] = {(p.get('ParameterInfo') or {}).get('Name'): p.get('ParameterValue')
                      for p in props.get('ScalarParameterValues') or []
                      if (p.get('ParameterInfo') or {}).get('Name') and isinstance(p.get('ParameterValue'), float)}
    for p in props.get('VectorParameterValues') or []:
        name = (p.get('ParameterInfo') or {}).get('Name') or ''
        v = p.get('ParameterValue')
        if isinstance(v, dict):
            out['colors'][name] = [v.get(c, 0.0) for c in 'RGBA']
        elif isinstance(v, (list, tuple)) and len(v) >= 3:
            out['colors'][name] = list(v)
    parent = ref_path(pkg, props.get('Parent'))
    if parent:
        out['parent'] = parent
    # Textures the material (or instance) references at all, for when parameters don't say.
    out['referenced'] = sorted({pkg.import_path(-i - 1) for i, imp in enumerate(pkg.imports) if imp['class'] == 'Texture2D'})
    return out


def pick(paks, game_path, texture_kind):
    """{'base', 'normal', 'tint'} for a material, following its parents for anything it doesn't set."""
    seen, chain, path = set(), [], game_path
    while path and path not in seen and path.startswith('/Game/') and len(chain) < 8:
        seen.add(path)
        try:
            d = describe(paks, path)
        except (KeyError, StopIteration):
            break
        chain.append(d)
        path = d['parent']
    base = normal = tint = None
    for d in chain:  # the instance's own settings win over its parents'
        for name, tex in d['textures']:
            label = name + ' ' + tex.rsplit('/', 1)[1]
            if normal is None and (NORMAL.search(name) or NORMAL.search(tex.rsplit('/', 1)[1])):
                normal = tex
            elif base is None and COLOR.search(label) and not NOT_COLOR.search(name or tex.rsplit('/', 1)[1]):
                base = tex
        for name, rgba in d['colors'].items():
            if tint is None and TINT.search(name):
                tint = rgba[:3]
    if base is None or normal is None:
        refs = [t for d in chain for t in d['referenced'] if t.startswith('/Game/')]
        for tex in refs:
            leaf = tex.rsplit('/', 1)[1]
            k = texture_kind(tex)
            if normal is None and (k == 'normal' or NORMAL.search(leaf)):
                normal = tex
            elif base is None and k == 'color' and not NOT_COLOR.search(leaf) and not NORMAL.search(leaf):
                base = tex
    ancestors = [d['parent'] for d in chain if d['parent']]
    blend = next((d['blend'] for d in chain if 'blend' in d), None)
    two_sided = next((d['two_sided'] for d in chain if 'two_sided' in d), False)
    return {'class': chain[0]['class'] if chain else None, 'base': base, 'normal': normal, 'tint': tint,
            'masked': blend in ('BLEND_Masked', 'BLEND_Translucent', 'BLEND_AlphaComposite'), 'two_sided': two_sided,
            'ancestors': ancestors, 'scalars': chain[0].get('scalars', {}) if chain else {},
            'colors': chain[0]['colors'] if chain else {}}


if __name__ == '__main__':
    import build
    import json
    import textures
    paks = pakfile.game_paks(build.find_game())
    kinds = {}

    def kind(t):
        if t not in kinds:
            try:
                kinds[t] = textures.kind(paks, t)
            except Exception:
                kinds[t] = None
        return kinds[t]
    for m in sys.argv[1:] or json.load(open(os.path.join(build.BUILD, 'mapkit_materials.json')))[:40]:
        r = pick(paks, m.split('.')[0], kind)
        print('%-60s %-26s base=%s normal=%s tint=%s' % (m.split('.')[0][-60:], r['class'],
              r['base'] and r['base'].rsplit('/', 1)[1], r['normal'] and r['normal'].rsplit('/', 1)[1], r['tint']))
