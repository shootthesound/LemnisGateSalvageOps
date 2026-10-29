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
TRIPLANAR = '''
float3 n = normalize(N);
float3 w = pow(abs(n), Sharp); w /= max(w.x + w.y + w.z, 1e-5);
float3 p = WP / max(Tile, 1.0);
float3 s = float3(n.x < 0 ? -1.0 : 1.0, n.y < 0 ? -1.0 : 1.0, n.z < 0 ? -1.0 : 1.0);
float2 uvX = float2(-p.y * s.x, -p.z);
float2 uvY = float2(p.x * s.y, -p.z);
float2 uvZ = float2(p.y * s.z, -p.x);
float4 cX = Tex.Sample(TexSampler, uvX);
float4 cY = Tex.Sample(TexSampler, uvY);
float4 cZ = Tex.Sample(TexSampler, uvZ);
'''

ALBEDO = TRIPLANAR + '''
float3 c = cX.rgb * w.x + cY.rgb * w.y + cZ.rgb * w.z;
float l = dot(c, float3(0.2126, 0.7152, 0.0722));
return lerp(c, Color * l / max(TintMean, 0.01), TintStrength);
'''

# Tangent-space (DirectX) normals per plane, rebuilt in world space from the
# plane's u/v directions; z reconstructed because BC5 drops it.
NORMAL = TRIPLANAR + '''
float3 tX = float3((cX.xy * 2 - 1) * Strength, 0); tX.z = sqrt(saturate(1 - dot(tX.xy, tX.xy)));
float3 tY = float3((cY.xy * 2 - 1) * Strength, 0); tY.z = sqrt(saturate(1 - dot(tY.xy, tY.xy)));
float3 tZ = float3((cZ.xy * 2 - 1) * Strength, 0); tZ.z = sqrt(saturate(1 - dot(tZ.xy, tZ.xy)));
float3 nX = tX.x * float3(0, -s.x, 0) + tX.y * float3(0, 0, -1) + tX.z * n;
float3 nY = tY.x * float3(s.y, 0, 0) + tY.y * float3(0, 0, -1) + tY.z * n;
float3 nZ = tZ.x * float3(0, s.z, 0) + tZ.y * float3(-1, 0, 0) + tZ.z * n;
return normalize(nX * w.x + nY * w.y + nZ * w.z);
'''

ORM = TRIPLANAR + '''
float3 c = cX.rgb * w.x + cY.rgb * w.y + cZ.rgb * w.z;
return float3(c.r, c.g * Rough, c.b * Metal);
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

    albedo = tex_param('Albedo', 'albedo', unreal.MaterialSamplerType.SAMPLERTYPE_COLOR, -600)
    normal = tex_param('Normal', 'normal', unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL, -300)
    orm = tex_param('ORM', 'orm', unreal.MaterialSamplerType.SAMPLERTYPE_MASKS, 0)
    color = node(mat, unreal.MaterialExpressionVectorParameter, -900, 300, parameter_name='Color',
                 default_value=unreal.LinearColor(*p['color'], 1.0))
    tile = scalar(mat, 'TileSize', p['tile_size'], 450)
    sharp = scalar(mat, 'BlendSharpness', p['blend_sharpness'], 550)
    tint = scalar(mat, 'TintStrength', p['tint_strength'], 650)
    tint_mean = scalar(mat, 'TintMean', p['tint_mean'], 700)
    strength = scalar(mat, 'NormalStrength', p['normal_strength'], 750)
    rough = scalar(mat, 'Roughness', p['roughness'], 850)
    metal = scalar(mat, 'Metallic', p['metallic'], 950)
    wp = node(mat, unreal.MaterialExpressionWorldPosition, -900, 1100)
    vn = node(mat, unreal.MaterialExpressionVertexNormalWS, -900, 1200)

    common = {'WP': wp, 'N': vn, 'Tile': tile, 'Sharp': sharp}
    c_albedo = custom(mat, ALBEDO, dict(common, Tex=albedo, Color=color, TintStrength=tint, TintMean=tint_mean), -500, 'TriplanarAlbedo')
    c_normal = custom(mat, NORMAL, dict(common, Tex=normal, Strength=strength), -100, 'TriplanarNormal')
    c_orm = custom(mat, ORM, dict(common, Tex=orm, Rough=rough, Metal=metal), 300, 'TriplanarORM')

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
        p = i['params']
        build_instance(i['asset'], JOB['parent_material'],
                       {'TileSize': p['tile_size'], 'BlendSharpness': p['blend_sharpness'],
                        'TintStrength': p['tint_strength'], 'TintMean': p['tint_mean'], 'NormalStrength': p['normal_strength'],
                        'Roughness': p['roughness'], 'Metallic': p['metallic']},
                       {'Color': p['color']},
                       {'Albedo': p['albedo'], 'Normal': p['normal'], 'ORM': p['orm']})
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
