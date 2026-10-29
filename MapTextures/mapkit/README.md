# Map Kit

Edit Lemnis Gate's maps in the Unreal 4.26 editor and play them with friends.

The kit rebuilds a game map as an editable level, with stand-ins for the game's objects. When you build, only the map
files go into `out/SalvageOps_Maps_P.pak`. In game, every object in them loads as the game's real version: real
meshes, materials, flags and gate pods.

## What you need

- Unreal Engine 4.26 (Epic Games Launcher)
- Visual Studio 2019 or 2022 with "Game development with C++" (the kit compiles a small C++ module)
- Python 3.9+
- The texture project built at least once (`python build.py build`), so slots look textured in the editor

## Set up (once, about 15 minutes)

```
python mapkit/kit.py setup
```

This writes the editor project to `_build/MapKit/LemnisGate.uproject` and does the following:

- compiles the stand-in module
- creates stand-ins for the game's 200-odd gameplay Blueprints
- copies the game's meshes so the editor shows real shapes
- lays out the object library

Run it again after a game update.

## Make a map

Modes: CTF, CAP (capture), DM, DST (destroy), EVA (evac), ASN (assassination). A map's mode comes from the game's
map list, not its name.

1. **Start from a map.** Use one of these:
   - **A new map of your own:** `python mapkit/kit.py new SO_Yard --from CAP_Box --title "CAP_SalvageYard (Custom)"`.
     - It's added to the P2P map list under that title.
     - Add `--mode CAP` (or CTF, DM, DST, EVA, ASN) to convert it to another mode:
       - The map's objectives are replaced with that mode's, placed relative to the two gate pods the way that mode's
         `*_Box` map has them.
       - The pods become the right kind for the mode.
       - Objectives are dropped onto the nearest floor.
       - For example, `new SO_ArchesCap --from CTF_Arches --mode CAP` gives Arches with three capture points. Move them
         in the editor if you want them elsewhere.
     - The game's `*_Box` maps are the simplest working setup for each mode.
     - The game only offers maps it registered when it was built. New maps are therefore saved in one of 20 slots: the
       game's registered maps that its menu never lists (ASN_Bases, CAP_Box, EV_Urban and others). This gives you up
       to 20 maps of your own.
   - **Edit one of the game's maps:** `python mapkit/kit.py import CTF_Arches`.
   - **Replace a listed map with another layout:** `python mapkit/kit.py import CAP_Box --as CAP_Crescent`.
   - **Keep only the gameplay:** add `--gameplay-only` to `new` or `import` to keep a map's objectives, spawns, lights
     and sky, without its geometry.
   - **Change only the mode in the list:** `python mapkit/kit.py mode CTF_Fork CAP` plays a map (yours or the game's)
     in another mode without touching its objectives, so use it on maps whose objectives already suit the mode. To
     convert the objectives as well, use `new --mode`.
   - **See your maps:** `python mapkit/kit.py list`. They're stored in `_build/MapKit/maps.json`.
   - **Delete one of your maps:** `python mapkit/kit.py remove SO_Yard`. This frees its slot.
2. **Edit.**
   - Open `_build/MapKit/LemnisGate.uproject` (double-click, or open it from the launcher).
   - Open your level under `Content/Levels/...` and edit it.
   - Save.
3. **Build and install.** Close the game first, then either:
   - click **More ▾ → Build edited maps** in the Texture Studio, or
   - run `python mapkit/kit.py build --install`.

   The build checks that every object the map uses exists in the game. If not, it stops and lists what's missing.
4. **Play.** Start the game with the Salvage Ops shortcut, then **P2P → Create Session** on that map.
5. **Share.** Use **More ▾ → Package for friends** in the Texture Studio. The zip includes your edited maps, and
   everyone in a match needs the same zip.

Every level in the kit is built, so delete the ones you don't want in game from `_build/MapKit/Content/Levels`.

## Object library

Open `Content/MapKit/ObjectLibrary`. It lays out every mesh and gameplay object the game's maps use, in rows by folder,
each with its name. Copy something from there and paste it into your map, or find it by name in the Content Browser.
For example:

- **Gameplay** (`Content/Gameplay/...`):
  - flags (`FlagObjective`) and gate pods (`GatePodCTF`, `GatePod`)
  - capture points (`CapturableObjective`) and destroyable objectives
  - evac zones, jump pads, mines
  - zone limits
  - spawn points (`ConvergenceSpawnPointBP`)
- **Props and architecture** (`Content/Environment/...`): containers, walls, rocks, pipes and the rest of the finished
  maps' meshes.

Materials show as grey in the editor (only the prototype slots have the kit's textures), but the game uses the real
ones.

## Terrain

Any map can have terrain. Create it in the editor:

1. Open **Landscape** mode, then the **New** tab.
2. Set the material to one of the kit's terrain materials in `Content/SalvageOps/Terrain`:
   - `MI_Terrain_Grassland`
   - `MI_Terrain_Desert`
   - `MI_Terrain_Dirt`
   - `MI_Terrain_Snow`
   - `MI_Terrain_Rocky`
3. Click **Create**, then sculpt.

The materials put the ground texture on flat areas and rock on slopes by themselves, so there's nothing to paint.
Change the look per map by making a material instance of `M_Terrain`. Its settings are the flat and slope textures,
`TileSize`, `SlopeStart` and `SlopeWidth`.

Importing a map that has terrain rebuilds its shape from the game's heightmap. The game's own terrain materials can't
be rebuilt, so the import picks the closest kit material (desert for desert maps, and so on). Change it on the
Landscape actor.

The kit's terrain materials and textures go into the maps pak, adding about 45 MB.

## Rules

- **Only use what the game has, plus `/Game/SalvageOps`.**
  - The pak carries your maps plus the kit's own assets under `/Game/SalvageOps`.
  - Other new meshes, materials or Blueprints would be missing in game, and the build refuses them.
  - To make your own assets, put them under `Content/SalvageOps`.
- **Don't press Play in the editor.** The stand-ins don't contain the game's logic, and touching a flag or jump pad in
  the editor would call an event they don't have.
- **Spawn points need a team.** Select one and set **Team Side** to Attacker or Defender. The `*_Box` maps show the
  usual count: five per team, plus two observer spawns.
- **Lighting is dynamic.** Lights work as placed, with no lighting build. The prototype arenas are lit the same way.
  The finished maps (CTF_TheNest, DM_Trident, CAP_Chimera and the others in `Levels/CAPMap`, `CTFMap`, `DSTMap`) use
  baked lighting that the kit doesn't carry over yet, so rebuilt copies of them look flatter.
- **Foliage** is rebuilt as instanced meshes of the game's own plants and rocks (`--no-foliage` / `--no-terrain` leave them out).
- **If the game crashes once while loading a new map** (in `dxilconv`, Windows' DirectX 12 shader converter), try again. It happened once while compiling a new map's shaders and didn't repeat. Adding `-dx11` to the shortcut avoids it.
- **Not wired up yet:** capture turrets and the reset-loop button (their interaction events).

## How it works

- `bpinfo.py` reads the game's cooked Blueprints: classes, parents and component layout.
- `scene.py` reads a cooked map's actors.
- `meshes.py` reads cooked static meshes.
- `ue/` holds editor scripts that run inside UE4Editor-Cmd: they build the stand-ins, the meshes, the library and the
  levels.
- `Source/LemnisGate` is the stand-in C++ module, with the game's native class names and the helpers the scripts call.

The stand-ins replay what the game's construction scripts saved into each level, because the game reads these from
the map instead of running the scripts:

- links to their own components (a jump pad's centre)
- movable parts and team colours
- component event bindings (a flag's pickup trigger)

`verify.py` checks every reference in a cooked map against the game's paks and executable before anything is packed.
