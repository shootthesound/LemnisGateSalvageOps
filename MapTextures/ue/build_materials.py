# Runs inside UE4Editor-Cmd (-run=pythonscript). Reads the job written by build.py
# and creates the textures, the triplanar material and the overriding instances.
import json
import os
import traceback

import unreal

JOB = json.load(open(os.environ['SALVAGE_JOB']))
MEL = unreal.MaterialEditingLibrary
EAL = unreal.EditorAssetLibrary
TOOLS = unreal.AssetToolsHelpers.get_asset_tools()

# Shared HLSL for the Custom nodes: world-aligned (triplanar) projection.
# UE is left-handed (X forward, Y right, Z up). Planes: X faces map (-y, -z),
# Y faces map (x, -z), Z faces map (y, -x); u is mirrored by the facing sign so
# text reads correctly from outside on every side.
# Surface-aware: the Z plane of upward-facing surfaces samples the floor set (TexF, TileF);
# everything else, including undersides, samples the wall set (TexW, TileW).
TRIPLANAR = '''
float3 n = normalize(N);
float3 w = pow(abs(n), Sharp); w /= max(w.x + w.y + w.z, 1e-5);
float3 s = float3(n.x < 0 ? -1.0 : 1.0, n.y < 0 ? -1.0 : 1.0, n.z < 0 ? -1.0 : 1.0);
float up = n.z > 0 ? 1.0 : 0.0;
float3 pw = WP / max(TileW, 1.0);
float3 pf = WP / max(TileF, 1.0);
float4 cX = TexW.Sample(TexWSampler, float2(-pw.y * s.x, -pw.z));
float4 cY = TexW.Sample(TexWSampler, float2(pw.x * s.y, -pw.z));
float4 cZw = TexW.Sample(TexWSampler, float2(pw.y * s.z, -pw.x));
float4 cZf = TexF.Sample(TexFSampler, float2(pf.y * s.z, -pf.x));
float wf = w.z * up;
float ww = 1 - wf;
'''

# Tint is linear in the colour, so the wall and floor parts are tinted separately and summed.
ALBEDO = TRIPLANAR + '''
float3 lum = float3(0.2126, 0.7152, 0.0722);
float3 cw = cX.rgb * w.x + cY.rgb * w.y + cZw.rgb * w.z * (1 - up);
float3 cf = cZf.rgb * wf;
cw = lerp(cw, Color * dot(cw, lum) / max(MeanW, 0.01), TintW);
cf = lerp(cf, Color * dot(cf, lum) / max(MeanF, 0.01), TintF);
return cw + cf;
'''

# Tangent-space (DirectX) normals per plane, rebuilt in world space from the
# plane's u/v directions; z reconstructed because BC5 drops it.
NORMAL = TRIPLANAR + '''
float4 cZ = lerp(cZw, cZf, up);
float strZ = lerp(StrW, StrF, up);
float3 tX = float3((cX.xy * 2 - 1) * StrW, 0); tX.z = sqrt(saturate(1 - dot(tX.xy, tX.xy)));
float3 tY = float3((cY.xy * 2 - 1) * StrW, 0); tY.z = sqrt(saturate(1 - dot(tY.xy, tY.xy)));
float3 tZ = float3((cZ.xy * 2 - 1) * strZ, 0); tZ.z = sqrt(saturate(1 - dot(tZ.xy, tZ.xy)));
float3 nX = tX.x * float3(0, -s.x, 0) + tX.y * float3(0, 0, -1) + tX.z * n;
float3 nY = tY.x * float3(s.y, 0, 0) + tY.y * float3(0, 0, -1) + tY.z * n;
float3 nZ = tZ.x * float3(0, s.z, 0) + tZ.y * float3(-1, 0, 0) + tZ.z * n;
return normalize(nX * w.x + nY * w.y + nZ * w.z);
'''

ORM = TRIPLANAR + '''
float3 c = cX.rgb * w.x + cY.rgb * w.y + lerp(cZw.rgb, cZf.rgb, up) * w.z;
return float3(c.r, c.g * (RoughW * ww + RoughF * wf), c.b * (MetalW * ww + MetalF * wf));
'''

USAGE_FLAGS = ('used_with_instanced_static_meshes', 'used_with_spline_meshes', 'used_with_skeletal_mesh',
               'used_with_static_lighting', 'used_with_morph_targets')


def split(path):
    return path.rsplit('/', 1)


def import_texture(t):
    task = unreal.AssetImportTask()
    folder, name = split(t['dest'])
    for k, v in (('filename', t['src']), ('destination_path', folder), ('destination_name', name),
                 ('automated', True), ('replace_existing', True), ('save', False)):
        task.set_editor_property(k, v)
    TOOLS.import_asset_tasks([task])
    tex = unreal.load_asset(t['dest'])
    if tex is None:
        raise RuntimeError('Texture import failed: ' + t['src'])
    if t['kind'] == 'normal':
        tex.set_editor_property('compression_settings', unreal.TextureCompressionSettings.TC_NORMALMAP)
        tex.set_editor_property('srgb', False)
    elif t['kind'] == 'orm':
        tex.set_editor_property('compression_settings', unreal.TextureCompressionSettings.TC_MASKS)
        tex.set_editor_property('srgb', False)
    EAL.save_loaded_asset(tex)


def node(mat, cls, x, y, **props):
    e = MEL.create_material_expression(mat, cls, x, y)
    for k, v in props.items():
        e.set_editor_property(k, v)
    return e


def scalar(mat, name, value, y):
    return node(mat, unreal.MaterialExpressionScalarParameter, -900, y, parameter_name=name, default_value=value)


def custom(mat, code, inputs, y, desc):
    c = node(mat, unreal.MaterialExpressionCustom, -400, y, code=code, description=desc,
             output_type=unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    pins = []
    for name in inputs:
        pin = unreal.CustomInput()
        pin.set_editor_property('input_name', name)
        pins.append(pin)
    c.set_editor_property('inputs', pins)
    for name, src in inputs.items():
        if not MEL.connect_material_expressions(src, '', c, name):
            raise RuntimeError('Could not connect %s on %s' % (name, desc))
    return c


def build_triplanar(path, p):
    """Full triplanar material at `path`; `p` holds parameter defaults and texture paths."""
    folder, name = split(path)
    mat = TOOLS.create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())
    mat.set_editor_property('tangent_space_normal', False)
    for flag in USAGE_FLAGS:
        try:
            mat.set_editor_property(flag, True)
        except Exception:
            unreal.log_warning('Usage flag not available: ' + flag)

    def tex_param(pname, key, sampler, y):
        return node(mat, unreal.MaterialExpressionTextureObjectParameter, -900, y, parameter_name=pname,
                    texture=unreal.load_asset(p[key]), sampler_type=sampler)

    f = p['floor']
    sampler = {'albedo': unreal.MaterialSamplerType.SAMPLERTYPE_COLOR, 'normal': unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL,
               'orm': unreal.MaterialSamplerType.SAMPLERTYPE_MASKS}
    names = {'albedo': 'Albedo', 'normal': 'Normal', 'orm': 'ORM'}
    tex = {k: tex_param(names[k], k, sampler[k], -900 + i * 150) for i, k in enumerate(('albedo', 'normal', 'orm'))}
    ftex = {k: node(mat, unreal.MaterialExpressionTextureObjectParameter, -1200, -900 + i * 150, parameter_name='Floor' + names[k],
                    texture=unreal.load_asset(f[k]), sampler_type=sampler[k]) for i, k in enumerate(('albedo', 'normal', 'orm'))}
    color = node(mat, unreal.MaterialExpressionVectorParameter, -900, 300, parameter_name='Color',
                 default_value=unreal.LinearColor(*p['color'], 1.0))
    sharp = scalar(mat, 'BlendSharpness', p['blend_sharpness'], 400)
    y = 500
    # Wall parameters keep their original names (child materials of M_Painted_Metal set Color/Roughness by name).
    surface = {}
    for key, pname in (('tile_size', 'TileSize'), ('tint_strength', 'TintStrength'), ('tint_mean', 'TintMean'),
                       ('normal_strength', 'NormalStrength'), ('roughness', 'Roughness'), ('metallic', 'Metallic')):
        surface[key] = (scalar(mat, pname, p[key], y), scalar(mat, 'Floor' + pname, f[key], y + 50))
        y += 120
    wp = node(mat, unreal.MaterialExpressionWorldPosition, -900, y + 100)
    vn = node(mat, unreal.MaterialExpressionVertexNormalWS, -900, y + 200)

    common = {'WP': wp, 'N': vn, 'TileW': surface['tile_size'][0], 'TileF': surface['tile_size'][1], 'Sharp': sharp}
    c_albedo = custom(mat, ALBEDO, dict(common, TexW=tex['albedo'], TexF=ftex['albedo'], Color=color,
                                        TintW=surface['tint_strength'][0], TintF=surface['tint_strength'][1],
                                        MeanW=surface['tint_mean'][0], MeanF=surface['tint_mean'][1]), -500, 'TriplanarAlbedo')
    c_normal = custom(mat, NORMAL, dict(common, TexW=tex['normal'], TexF=ftex['normal'],
                                        StrW=surface['normal_strength'][0], StrF=surface['normal_strength'][1]), -100, 'TriplanarNormal')
    c_orm = custom(mat, ORM, dict(common, TexW=tex['orm'], TexF=ftex['orm'], RoughW=surface['roughness'][0],
                                  RoughF=surface['roughness'][1], MetalW=surface['metallic'][0], MetalF=surface['metallic'][1]),
                   300, 'TriplanarORM')

    MEL.connect_material_property(c_albedo, '', unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(c_normal, '', unreal.MaterialProperty.MP_NORMAL)
    for ch, prop, y in (('r', unreal.MaterialProperty.MP_AMBIENT_OCCLUSION, 250),
                        ('g', unreal.MaterialProperty.MP_ROUGHNESS, 350),
                        ('b', unreal.MaterialProperty.MP_METALLIC, 450)):
        mask = node(mat, unreal.MaterialExpressionComponentMask, -100, y, r=ch == 'r', g=ch == 'g', b=ch == 'b')
        MEL.connect_material_expressions(c_orm, '', mask, '')
        MEL.connect_material_property(mask, '', prop)

    MEL.recompile_material(mat)
    EAL.save_loaded_asset(mat)
    return mat


def build_stub(path, s):
    """Editor-only stand-in for a game material so passthrough instances can be cooked against it."""
    folder, name = split(path)
    mat = TOOLS.create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())
    y = 0
    for pname in s['scalars']:
        e = scalar(mat, pname, 0.0, y)
        if pname == 'Roughness':
            MEL.connect_material_property(e, '', unreal.MaterialProperty.MP_ROUGHNESS)
        y += 100
    for pname in s['vectors']:
        e = node(mat, unreal.MaterialExpressionVectorParameter, -900, y, parameter_name=pname)
        if pname == 'Color':
            MEL.connect_material_property(e, '', unreal.MaterialProperty.MP_BASE_COLOR)
        y += 100
    MEL.recompile_material(mat)
    EAL.save_loaded_asset(mat)


def build_instance(path, parent, scalars, vectors, textures):
    folder, name = split(path)
    mi = TOOLS.create_asset(name, folder, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    MEL.set_material_instance_parent(mi, unreal.load_asset(parent))
    for k, v in scalars.items():
        MEL.set_material_instance_scalar_parameter_value(mi, k, v)
    for k, v in vectors.items():
        MEL.set_material_instance_vector_parameter_value(mi, k, unreal.LinearColor(*(list(v) + [1.0])[:4]))
    for k, v in textures.items():
        MEL.set_material_instance_texture_parameter_value(mi, k, unreal.load_asset(v))
    MEL.update_material_instance(mi)
    EAL.save_loaded_asset(mi)


def main():
    for t in JOB['textures']:
        import_texture(t)
    for path, s in JOB['stubs'].items():
        build_stub(path, s)
    build_triplanar(JOB['parent_material'], JOB['parent_defaults'])
    for m in JOB['materials']:
        build_triplanar(m['asset'], m['params'])
    for i in JOB['instances']:
        p, f = i['params'], i['params']['floor']
        scalars = {'BlendSharpness': p['blend_sharpness']}
        for key, pname in (('tile_size', 'TileSize'), ('tint_strength', 'TintStrength'), ('tint_mean', 'TintMean'),
                           ('normal_strength', 'NormalStrength'), ('roughness', 'Roughness'), ('metallic', 'Metallic')):
            scalars[pname] = p[key]
            scalars['Floor' + pname] = f[key]
        textures = {'Albedo': p['albedo'], 'Normal': p['normal'], 'ORM': p['orm'],
                    'FloorAlbedo': f['albedo'], 'FloorNormal': f['normal'], 'FloorORM': f['orm']}
        build_instance(i['asset'], JOB['parent_material'], scalars, {'Color': p['color']}, textures)
    for t in JOB['passthroughs']:
        build_instance(t['asset'], t['parent'], t['scalars'], t['vectors'], {})


result = {'ok': False}
try:
    main()
    result['ok'] = True
except Exception:
    result['error'] = traceback.format_exc()
    unreal.log_error(result['error'])
json.dump(result, open(JOB['result_file'], 'w'))
