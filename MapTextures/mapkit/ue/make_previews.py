"""Editor look-alikes of the game's materials (run by kit.py materials): at each material's own path, a material
showing its colour texture and normal map (decoded from the game), or its colour when it has no texture. They replace
the grey placeholders so maps look like the game in the editor and baked lighting picks up the right colours. The
cook never touches them: the game uses its own materials.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_common import ASSETS, JOB, TOOLS, log, run  # noqa: E402

import unreal  # noqa: E402

MEL = unreal.MaterialEditingLibrary
ROOT = '/Game/MapKit/Preview'
MASTER = '/Game/MapKit/M_Preview'
MASKED = '/Game/MapKit/M_PreviewMasked'  # cut-outs (leaves, grass, grates): alpha mask, two-sided


def import_texture(png, name, normal):
    path = '%s/%s' % (ROOT, name)
    if not ASSETS.does_asset_exist(path):
        task = unreal.AssetImportTask()
        task.set_editor_property('filename', png)
        task.set_editor_property('destination_path', ROOT)
        task.set_editor_property('destination_name', name)
        task.set_editor_property('replace_existing', True)
        task.set_editor_property('automated', True)
        task.set_editor_property('save', False)
        TOOLS.import_asset_tasks([task])
        tex = unreal.load_object(None, '%s.%s' % (path, name))
        if normal:
            tex.set_editor_property('srgb', False)
            tex.set_editor_property('compression_settings', unreal.TextureCompressionSettings.TC_NORMALMAP)
        ASSETS.save_loaded_asset(tex, only_if_is_dirty=False)
    return unreal.load_object(None, '%s.%s' % (path, name))


def expr(material, cls, x, y, **props):
    e = MEL.create_material_expression(material, cls, x, y)
    for k, v in props.items():
        e.set_editor_property(k, v)
    return e


def graph(m, base, normal, tint, parameters, masked=False):
    """BaseColor = texture * tint (or just tint), Normal = normal map. As parameters for the master."""
    white = unreal.load_object(None, '/Engine/EngineResources/WhiteSquareTexture.WhiteSquareTexture')
    flat = unreal.load_object(None, '/Engine/EngineMaterials/DefaultNormal.DefaultNormal')
    sample = unreal.MaterialExpressionTextureSampleParameter2D if parameters else unreal.MaterialExpressionTextureSample
    color = expr(m, sample, -600, 0, texture=base or white)
    tint_node = (expr(m, unreal.MaterialExpressionVectorParameter, -600, 250, parameter_name='Tint',
                      default_value=unreal.LinearColor(*(tint or (1, 1, 1)), 1)) if parameters else
                 expr(m, unreal.MaterialExpressionConstant3Vector, -600, 250,
                      constant=unreal.LinearColor(*(tint or (1, 1, 1)), 1)))
    if parameters:
        color.set_editor_property('parameter_name', 'Base')
    mul = expr(m, unreal.MaterialExpressionMultiply, -300, 100)
    MEL.connect_material_expressions(color, 'RGB', mul, 'A')
    MEL.connect_material_expressions(tint_node, '', mul, 'B')
    MEL.connect_material_property(mul, '', unreal.MaterialProperty.MP_BASE_COLOR)
    nrm = expr(m, sample, -600, 400, texture=normal or flat,
               sampler_type=unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
    if parameters:
        nrm.set_editor_property('parameter_name', 'Normal')
    MEL.connect_material_property(nrm, 'RGB', unreal.MaterialProperty.MP_NORMAL)
    if masked:
        m.set_editor_property('blend_mode', unreal.BlendMode.BLEND_MASKED)
        m.set_editor_property('two_sided', True)
        MEL.connect_material_property(color, 'A', unreal.MaterialProperty.MP_OPACITY_MASK)
    rough = expr(m, unreal.MaterialExpressionConstant, -300, 500, r=0.7)
    MEL.connect_material_property(rough, '', unreal.MaterialProperty.MP_ROUGHNESS)
    for flag in ('used_with_static_lighting', 'used_with_instanced_static_meshes', 'used_with_skeletal_mesh',
                 'used_with_spline_meshes'):
        m.set_editor_property(flag, True)
    MEL.recompile_material(m)


def replace(path, cls, factory):
    folder, name = path.rsplit('/', 1)
    if ASSETS.does_asset_exist(path):
        ASSETS.delete_asset(path)
    return TOOLS.create_asset(name, folder, cls, factory)


def main():
    masters = {}
    for path, masked in ((MASTER, False), (MASKED, True)):
        name = path.rsplit('/', 1)[1]
        mat = unreal.load_object(None, '%s.%s' % (path, name)) if ASSETS.does_asset_exist(path) else None
        if not mat:
            mat = replace(path, unreal.Material, unreal.MaterialFactoryNew())
            graph(mat, None, None, None, True, masked)
            ASSETS.save_loaded_asset(mat, only_if_is_dirty=False)
        masters[masked] = mat
    made, failed = 0, []
    for i, m in enumerate(JOB['materials']):
        try:
            base = import_texture(m['base_png'], m['base_name'], False) if m.get('base_png') else None
            normal = import_texture(m['normal_png'], m['normal_name'], True) if m.get('normal_png') else None
            if m.get('parent'):
                mat = replace(m['path'], unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
                name = m['parent'].rsplit('/', 1)[1]
                MEL.set_material_instance_parent(mat, unreal.load_object(None, '%s.%s' % (m['parent'], name)))
                for k, v in m.get('scalars', {}).items():
                    MEL.set_material_instance_scalar_parameter_value(mat, k, v)
                for k, v in m.get('colors', {}).items():
                    MEL.set_material_instance_vector_parameter_value(mat, k, unreal.LinearColor(*v[:4]))
            elif m['class'] == 'Material':
                mat = replace(m['path'], unreal.Material, unreal.MaterialFactoryNew())
                graph(mat, base, normal, None if base else m.get('tint'), False, m.get('masked') and base is not None)
            else:
                mat = replace(m['path'], unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
                MEL.set_material_instance_parent(mat, masters[bool(m.get('masked') and base)])
                if base:
                    MEL.set_material_instance_texture_parameter_value(mat, 'Base', base)
                if normal:
                    MEL.set_material_instance_texture_parameter_value(mat, 'Normal', normal)
                if m.get('tint') and not base:
                    MEL.set_material_instance_vector_parameter_value(mat, 'Tint', unreal.LinearColor(*m['tint'], 1))
            ASSETS.save_loaded_asset(mat, only_if_is_dirty=False)
            made += 1
        except Exception as e:
            failed.append('%s: %s' % (m['path'], str(e).splitlines()[0][:100]))
        if i % 100 == 0:
            log('%d/%d materials' % (i, len(JOB['materials'])))
    return {'made': made, 'failed': failed}


run(main)
