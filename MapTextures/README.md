# Map Textures

Adds textures to the 90 untextured prototype maps (`Levels/Playable`) that developer mode unlocks.

Those maps share about a dozen flat-colour greybox materials. This tool builds replacement materials at the same asset paths and packs them into one `_P.pak`. The game loads it in place of the originals, so every prototype map using that material is retextured at once. Deleting the pak restores the original look.

The replacements use **world-aligned (triplanar) mapping**, because greybox geometry has no usable UVs. By default each texture is tinted with the material's original colour, so the colour coding (orange/green team areas, etc.) is preserved.

## Requirements
- **Unreal Engine 4.26**, installed from the Epic Games Launcher (Unreal Engine → Library → `+` → 4.26). The game runs on 4.26, so its materials must be cooked with that version.
- Python 3.8+
- Developer mode enabled in the game ([EASY_P2P.md](../EASY_P2P.md)) so the prototype maps appear
- The game started **without EasyAntiCheat**, because EasyAntiCheat stops the game loading extra paks. Launching through Steam starts EasyAntiCheat, so either:
  - put a `steam_appid.txt` containing `950180` in `<game>/LemnisGate/Binaries/Win64/`, then, with Steam running, start `LemnisGate-Win64-Shipping.exe` from that folder, or
  - install the full Salvage Ops mod, whose launcher skips EasyAntiCheat.

  Everyone in a match should launch the same way.

## Usage
```
python build.py init                  # creates textures/<Slot>/ folders (already done in the repo)
python build.py list                  # shows each slot, how many maps use it, and what you've added
python build.py build --install       # builds the pak and copies it into the game
python build.py uninstall             # removes it from the game
```

Put images in `textures/<Slot>/`:

| File | Required | Content |
|---|---|---|
| `albedo.png` | yes | Colour texture. Any of png/jpg/tga/bmp/psd/exr. |
| `normal.png` | no | DirectX-style (green-down) normal map |
| `orm.png` | no | R = ambient occlusion, G = roughness, B = metallic |

A slot with no `albedo` is left unchanged. Seamless (tileable) textures work best.

Optional `textures/<Slot>/settings.json`:
```json
{ "tile_size": 200, "tint_strength": 1.0, "normal_strength": 1.0,
  "roughness": 0.4, "metallic": 0.0, "blend_sharpness": 4, "color": [0.47, 0.15, 0.0] }
```
- `tile_size`: world size of one texture repeat, in cm (200 = 2 m).
- `tint_strength`: 1 recolours the texture to the slot's original colour, keeping its detail. 0 uses the texture's own colours.
- `roughness` / `metallic`: used as values when there is no ORM texture, and as multipliers when there is one.

The installed pak goes to `<game>/LemnisGate/Content/Paks/SalvageOps_MapTextures_P.pak`.

To see which slot covers which surface, build the labelled debug textures:
```
python make_debug_textures.py
python build.py build --textures _build/debug_textures --allow-shared --install
``` To share it, give your friends that file. It only changes visuals.

## Sharing with friends
`python build.py package` creates `out/SalvageOps_MapTextures.zip`, containing the built pak and a double-click installer. Your friends don't need Python or Unreal. They unzip it, run `Install.bat` and pick their Lemnis Gate folder. The installer:
- copies the pak into the game,
- adds `steam_appid.txt`,
- turns on developer mode in `Game.ini`,
- creates a **Lemnis Gate (Salvage Ops)** desktop shortcut that starts the game without EasyAntiCheat.

`Uninstall.bat` reverses everything except developer mode.

## Slots

| Slot | Prototype maps | Also affects |
|---|---|---|
| White | 78 | **Shared**: wall panels in every shipped map |
| SolidGray | 69 | one ceiling ring in the main menu scene |
| Ground | 67 | — |
| Orange | 53 | lockers, chessboard prop and tile panels in some shipped maps |
| Green | 53 | — |
| Red | 53 | main menu scene |
| Yellow | 49 | — |
| BaseGray | 39 | — |
| Black | 36 | one Training Center target |
| Grey | 30 | a ceiling light in Chimera / Iridium Plains |
| SolidDarkGray | 19 | ceiling rings in the menu and tutorial |
| Grey2 | 19 | glass wall frames in the Training Center |
| DarkGrey | 13 | **Shared**: hangar ceilings, containers and props in shipped maps |
| PaintedMetalBase | 53 | **Shared**: parent of ~20 painted-metal materials in shipped maps |

**Shared** slots are skipped unless you pass `--allow-shared`.

Several shipped materials inherit from Orange and DarkGrey (for example, the white panels inherit from Orange). When you texture one of those slots, the tool also writes those inheriting materials back with their original settings, so they keep their original look.

## How it works
1. `build.py` creates a throwaway UE 4.26 project named `LemnisGate` in `_build/`, copying the game's renderer settings so shader permutations match.
2. `ue/build_materials.py` runs inside the editor. It imports the textures, builds `M_SalvageTriplanar` (Custom HLSL nodes for triplanar albedo, normal and ORM), and creates instances at the original greybox asset paths.
3. The project is cooked for `WindowsNoEditor` and packed with `UnrealPak`. Logs are in `_build/logs/`.
