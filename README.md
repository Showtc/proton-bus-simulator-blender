# Proton Bus 3DS Tools (Blender extension)

Standalone 3DS import/export for Proton Bus Simulator mods.

`import_3ds.py` / `export_3ds.py` come from the official Blender Autodesk 3DS add-on 3.0.2, with these changes:
- From PBSU 3DS: object names are no longer cut to 36 characters, and World is part of the default export filter.
- The warning for a mesh too big for 3DS is shown in Blender instead of only in the console.
- Already in 3.0.2 (no patch needed): missing world Background / World Output nodes are created on import, and export with Scene Units or Collection works.
- `Split Large Meshes` export option (off by default): 3DS stores counts as 16-bit numbers, so a mesh object can't have more than 65,535 vertices or faces (counted after triangulation and UV-seam vertex duplication). When ticked, such meshes are split while writing the file into `<name>`, `<name>_2`, `<name>_3`… (the Blender scene is unchanged). When off, they are skipped with a warning.
- `Restore Origins` import option (on by default): 3DS stores mesh vertices in world space plus one matrix per object (its origin, rotation and scale). The official importer ignores that matrix when the file has no keyframe section, which is the case for all Proton Bus files, so every origin ended up at (0,0,0). With this option each object gets its origin, rotation and scale back while the geometry stays in place; parents (exported with Hierarchy) are kept. On export, the object matrix now uses the same scale factor / scene unit as the vertices.
- Kept from the official add-on: the "Images" and "Invisible" export options.

## Features
- `File > Import > Proton Bus 3DS (.3ds)`: copies the 3DS file into the mod's `textures` folder (closest `textures` folder found walking up from the file), imports it from there so textures resolve, then deletes the copy.
- `File > Import > Proton Bus INI (.ini)` (also drag & drop): reads `[config] baseDir` and every `modelsN=` entry, then imports every `.3ds` listed in those model files (paths relative to `baseDir`) through `<baseDir>/textures`. It creates one collection named after the INI, with one sub-collection per 3DS file.
- `File > Import > Proton Bus Map (.map.txt)` (also drag & drop): reads `[map] baseDir`, `modelsDir` and `textures`, then imports every `.3ds` tile in `<baseDir>/tiles/<modelsDir>` through `<baseDir>/<textures>` (each tile is copied into the textures folder, imported, then the copy is deleted). It creates one collection named after the map (e.g. `ageo`), with one sub-collection per tile. Tiles are already in world position.
- `File > Export > Proton Bus 3DS (.3ds)`: exports into the `textures` folder first, copies the result to the chosen destination, then removes the temporary file.

A `Textures Folder` option overrides the auto-detection.

## Default presets
- Import: Image Search, World, Mesh, Light, Camera, Empty, Animation, Constrain Size 0.00, Scene Units, Restore Origins, Y Forward, Z Up.
- Export: World, Mesh, Light, Camera, Empty, Scale Factor 1.00, Scene Units, Apply Transform, Y Forward, Z Up.

## Build / install
```
blender --command extension build --source-dir proton_bus_3ds --output-dir dist
```
Then in Blender, go to *Edit > Preferences > Get Extensions > ⌄ > Install from Disk…* and pick the zip in `dist/`.

## Tests
```
blender -b --factory-startup --python-exit-code 1 --python tests/smoke_test.py
```
Builds small bus and map mods in a temporary folder and checks export, origin restore, INI and map import, mesh splitting and temporary file cleanup.
