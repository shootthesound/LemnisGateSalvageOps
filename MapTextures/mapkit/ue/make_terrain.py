"""Create the kit's terrain materials (run by kit.py terrain): textures under /Game/SalvageOps/Terrain/Textures, a
master material M_Terrain that puts one texture on flat ground and another on slopes (world-space tiling, so any
landscape works without painting), and an instance per terrain set (MI_Terrain_Grassland, ...).

These are the kit's own assets: the build cooks them into the maps pak along with the levels that use them.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_common import ASSETS, JOB, TOOLS, log, run  # noqa: E402

import unreal  # noqa: E402

ROOT = '/Game/SalvageOps/Terrain'
MEL = unreal.MaterialEditingLibrary
ROLES = {'albedo': ('Albedo', True, unreal.TextureCompressionSettings.TC_DEFAULT),
         'normal': ('Normal', False, unreal.TextureCompressionSettings.TC_NORMALMAP),
         'orm': ('ORM', False, unreal.TextureCompressionSettings.TC_MASKS)}


def import_texture(png, name):
    task = unreal.AssetImportTask()
    task.set_editor_property('filename', png)
    task.set_editor_property('destination_path', ROOT + '/Textures')
    task.set_editor_property('destination_name', name)
    task.set_editor_property('replace_existing', True)
    task.set_editor_property('automated', True)
    task.set_editor_property('save', False)
    TOOLS.import_asset_tasks([task])
    return unreal.load_object(None, '%s/Textures/%s.%s' % (ROOT, name, name))


def textures(texture_id, folder):
    out = {}
    for role, (suffix, srgb, compression) in ROLES.items():
        png = os.path.join(folder, role + '.png')
        if not os.path.exists(png):
            continue
        tex = import_texture(png, '%s_%s' % (texture_id, suffix))
        tex.set_editor_property('srgb', srgb)
        tex.set_editor_property('compression_settings', compression)
        ASSETS.save_loaded_asset(tex, only_if_is_dirty=False)
        out[role] = tex
    return out


def expr(material, cls, x, y, **props):
    e = MEL.create_material_expression(material, cls, x, y)
    for k, v in props.items():
        e.set_editor_property(k, v)
    return e


def link(a, a_out, b, b_in):
    if not MEL.connect_material_expressions(a, a_out, b, b_in):
        raise RuntimeError('could not connect %s.%s -> %s.%s' % (a.get_name(), a_out, b.get_name(), b_in))


def master(defaults):
    path = ROOT + '/M_Terrain'
    if ASSETS.does_asset_exist(path):
        ASSETS.delete_asset(path)
    m = TOOLS.create_asset('M_Terrain', ROOT, unreal.Material, unreal.MaterialFactoryNew())
    # World-space UVs: XY / tile size.
    world = expr(m, unreal.MaterialExpressionWorldPosition, -1400, 0)
    xy = expr(m, unreal.MaterialExpressionComponentMask, -1200, 0, r=True, g=True, b=False, a=False)
    link(world, '', xy, '')
    tile = expr(m, unreal.MaterialExpressionScalarParameter, -1200, 120, parameter_name='TileSize', default_value=400.0)
    uv = expr(m, unreal.MaterialExpressionDivide, -1000, 0)
    link(xy, '', uv, 'A')
    link(tile, '', uv, 'B')
    slope_tile = expr(m, unreal.MaterialExpressionScalarParameter, -1200, 220, parameter_name='SlopeTileSize',
                      default_value=600.0)
    slope_uv = expr(m, unreal.MaterialExpressionDivide, -1000, 160)
    link(xy, '', slope_uv, 'A')
    link(slope_tile, '', slope_uv, 'B')
    # Slope blend: 0 on flat ground, 1 on steep slopes.
    normal_ws = expr(m, unreal.MaterialExpressionVertexNormalWS, -1400, 500)
    nz = expr(m, unreal.MaterialExpressionComponentMask, -1200, 500, r=False, g=False, b=True, a=False)
    link(normal_ws, '', nz, '')
    steep = expr(m, unreal.MaterialExpressionOneMinus, -1050, 500)
    link(nz, '', steep, '')
    start = expr(m, unreal.MaterialExpressionScalarParameter, -1050, 600, parameter_name='SlopeStart', default_value=0.25)
    width = expr(m, unreal.MaterialExpressionScalarParameter, -1050, 700, parameter_name='SlopeWidth', default_value=0.15)
    sub = expr(m, unreal.MaterialExpressionSubtract, -900, 500)
    link(steep, '', sub, 'A')
    link(start, '', sub, 'B')
    div = expr(m, unreal.MaterialExpressionDivide, -750, 500)
    link(sub, '', div, 'A')
    link(width, '', div, 'B')
    alpha = expr(m, unreal.MaterialExpressionSaturate, -600, 500)
    link(div, '', alpha, '')

    samplers = {'albedo': unreal.MaterialSamplerType.SAMPLERTYPE_COLOR,
                'normal': unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL,
                'orm': unreal.MaterialSamplerType.SAMPLERTYPE_MASKS}
    lerps = {}
    y = -600
    for role in ('albedo', 'normal', 'orm'):
        flat = expr(m, unreal.MaterialExpressionTextureSampleParameter2D, -700, y,
                    parameter_name='Flat' + ROLES[role][0], texture=defaults[role], sampler_type=samplers[role])
        slope = expr(m, unreal.MaterialExpressionTextureSampleParameter2D, -700, y + 220,
                     parameter_name='Slope' + ROLES[role][0], texture=defaults[role], sampler_type=samplers[role])
        link(uv, '', flat, 'UVs')
        link(slope_uv, '', slope, 'UVs')
        lerp = expr(m, unreal.MaterialExpressionLinearInterpolate, -350, y + 100)
        link(flat, 'RGB', lerp, 'A')
        link(slope, 'RGB', lerp, 'B')
        link(alpha, '', lerp, 'Alpha')
        lerps[role] = lerp
        y += 450
    MEL.connect_material_property(lerps['albedo'], '', unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(lerps['normal'], '', unreal.MaterialProperty.MP_NORMAL)
    rough = expr(m, unreal.MaterialExpressionComponentMask, -150, 900, r=False, g=True, b=False, a=False)
    ao = expr(m, unreal.MaterialExpressionComponentMask, -150, 1000, r=True, g=False, b=False, a=False)
    link(lerps['orm'], '', rough, '')
    link(lerps['orm'], '', ao, '')
    MEL.connect_material_property(rough, '', unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.connect_material_property(ao, '', unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)
    MEL.recompile_material(m)
    ASSETS.save_loaded_asset(m, only_if_is_dirty=False)
    return m


def main():
    tex = {tid: textures(tid, folder) for tid, folder in JOB['textures'].items()}
    first = tex[sorted(tex)[0]]
    m = master(first)
    made = []
    for name, (flat, slope) in sorted(JOB['sets'].items()):
        path = '%s/MI_Terrain_%s' % (ROOT, name)
        if ASSETS.does_asset_exist(path):
            ASSETS.delete_asset(path)
        mi = TOOLS.create_asset('MI_Terrain_' + name, ROOT, unreal.MaterialInstanceConstant,
                                unreal.MaterialInstanceConstantFactoryNew())
        MEL.set_material_instance_parent(mi, m)
        for role in ROLES:
            if role in tex[flat]:
                MEL.set_material_instance_texture_parameter_value(mi, 'Flat' + ROLES[role][0], tex[flat][role])
            if role in tex[slope]:
                MEL.set_material_instance_texture_parameter_value(mi, 'Slope' + ROLES[role][0], tex[slope][role])
        ASSETS.save_loaded_asset(mi, only_if_is_dirty=False)
        made.append(path)
        log('terrain set %s: %s / %s' % (name, flat, slope))
    return {'materials': made}


run(main)
