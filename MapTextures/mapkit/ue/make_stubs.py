"""Create editor stand-ins for the game's gameplay Blueprints (run by kit.py setup inside the editor).

Each stand-in has the game Blueprint's path, parent class and construction-script components (same names, classes,
attachment and placement), so a level cooked with it references the real Blueprint's classes and component
templates. Instance-edited variables are added too. (No editor-only marker components: cooking strips
them but leaves an empty entry in the actor's BlueprintCreatedComponents, which the game's actors don't have.)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_common import ASSETS, JOB, LIB, convert, load, load_class, log, run, snake  # noqa: E402

import unreal  # noqa: E402

TEMPLATE_TYPES = {'RelativeLocation': 'Vector', 'RelativeRotation': 'Rotator', 'RelativeScale3D': 'Vector',
                  'BoxExtent': 'Vector'}


def class_path(ref):
    return '%s.%s' % (ref['package'], ref['name'])


def order(catalog):
    """Blueprints sorted so parents and component Blueprints come before the Blueprints that use them."""
    done, out = set(), []

    def visit(path):
        if path in done or path not in catalog or not catalog[path]:
            return
        done.add(path)
        bp = catalog[path]
        deps = [bp['parent'].get('package')] + [n['class_package'] for n in bp['nodes']]
        for d in deps:
            if d and d.startswith('/Game/'):
                visit(d)
        out.append(path)

    for p in sorted(catalog):
        visit(p)
    return out


def chain(path):
    """A Blueprint and its Blueprint parents."""
    out = []
    while path in JOB['catalog'] and JOB['catalog'][path]:
        out.append(JOB['catalog'][path])
        path = JOB['catalog'][path]['parent'].get('package')
    return out


def node_order(nodes):
    own = {n['name'] for n in nodes}
    placed, out = set(), []
    pending = list(nodes)
    while pending:
        progress = False
        for n in list(pending):
            if not n['parent'] or n['parent'] not in own or n['parent'] in placed:
                out.append(n)
                placed.add(n['name'])
                pending.remove(n)
                progress = True
        if not progress:
            out += pending
            break
    return out


def set_template(tmpl, values):
    for key, text in values.get('values', {}).items():
        if key not in values:
            LIB.set_property_text(tmpl, key, text)
    for key, value in values.items():
        if key == 'values':
            continue
        if key == 'StaticMesh':
            mesh = load(value) if value and ASSETS.does_asset_exist(value) else None
            if mesh:
                tmpl.set_editor_property('static_mesh', mesh)
            continue
        try:
            tmpl.set_editor_property(snake(key), convert(TEMPLATE_TYPES.get(key), value))
        except Exception as e:
            log('  template %s.%s: %s' % (tmpl.get_name(), key, str(e).splitlines()[0][:100]))


# Stand-ins of plain actors derive from the kit's actor class, which re-links component variables on construction.
# The parent class never reaches the cooked level, which only names the Blueprint's own class.
PARENTS = {'/Script/Engine.Actor': '/Script/LemnisGate.MapKitActor'}


def make(path, bp):
    parent_path = class_path(bp['parent'])
    parent = load_class(PARENTS.get(parent_path, parent_path))
    if not parent:
        raise RuntimeError('%s: parent %s not found' % (path, bp['parent']))
    if ASSETS.does_asset_exist(path):
        ASSETS.delete_asset(path)
    blueprint = LIB.create_blueprint(path, parent)
    for n in node_order(bp['nodes']):
        cls = load_class('%s.%s' % (n['class_package'], n['class'])) if n['class_package'] else None
        if not cls:
            log('  %s: component class %s.%s not available, skipping %s' % (path, n['class_package'], n['class'], n['name']))
            continue
        tmpl = LIB.add_component(blueprint, cls, n['name'], n['parent'] or '')
        if tmpl:
            set_template(tmpl, n['template'])
    # Components are variables too (their own name), so only add the ones that are not.
    components = {n['name'] for b in chain(path) for n in b['nodes']}
    for name, ptype in sorted(bp.get('variables', {}).items()):
        if name not in components and not LIB.has_property(parent, name):
            if not LIB.add_variable(blueprint, name, ptype):
                log('  %s: could not add variable %s (%s)' % (path, name, ptype))
    if not LIB.compile(blueprint):
        log('  %s: compiled with errors' % path)
    if bp.get('links') or bp.get('construction_values') or bp.get('events'):
        cdo = unreal.get_default_object(ASSETS.load_blueprint_class(path))
        if LIB.has_property(cdo.get_class(), 'ComponentLinks'):
            cdo.set_editor_property('component_links', {unreal.Name(k): unreal.Name(v) for k, v in bp['links'].items()})
            cdo.set_editor_property('construction_values', bp.get('construction_values', {}))
            cdo.set_editor_property('component_events', bp.get('events', {}))
    ASSETS.save_loaded_asset(blueprint, only_if_is_dirty=False)


def main():
    catalog = JOB['catalog']
    made, failed = [], {}
    paths = order(catalog)
    for path in paths:
        try:
            make(path, catalog[path])
            made.append(path)
        except Exception as e:
            failed[path] = str(e)
            log('FAILED %s: %s' % (path, e))
    log('made %d stand-ins, %d failed' % (len(made), len(failed)))
    return {'made': made, 'failed': failed}


run(main)
