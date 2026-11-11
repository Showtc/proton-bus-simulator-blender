"""Headless smoke test for the Proton Bus 3DS Tools extension.

Run from the repository root:
    blender -b --factory-startup --python-exit-code 1 --python tests/smoke_test.py

It builds small synthetic bus and map mods in a temporary folder (no real mod
files needed) and checks: export through the textures folder, origin restore,
bus INI import, map import, mesh splitting and temporary file cleanup.
"""

import math
import os
import shutil
import sys
import tempfile

import bpy
import mathutils

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import proton_bus_3ds  # noqa: E402

proton_bus_3ds.register()

failures = []


def check(label, condition):
    print(("PASS " if condition else "FAIL ") + label)
    if not condition:
        failures.append(label)


def clear():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    for col in list(bpy.data.collections):
        bpy.data.collections.remove(col)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)


def snapshot():
    bpy.context.view_layer.update()
    result = {}
    for ob in bpy.data.objects:
        if ob.type != 'MESH':
            continue
        mw = ob.matrix_world
        pts = [mw @ v.co for v in ob.data.vertices]
        bounds = tuple(round(f(p[i] for p in pts), 3) for i in range(3) for f in (min, max))
        result[ob.name] = (tuple(round(x, 3) for x in mw.to_translation()),
                           tuple(round(math.degrees(a), 1) for a in mw.to_euler()),
                           bounds)
    return result


def no_temp_files(folder):
    return not [n for n in os.listdir(folder) if n.startswith("__pbs_tmp_")]


root = tempfile.mkdtemp(prefix="pbs3ds_")
try:
    # Synthetic bus mod: <root>/bus.ini, <root>/Bus/{model.txt, models/, textures/}
    bus = os.path.join(root, "Bus")
    os.makedirs(os.path.join(bus, "models", "doors"))
    os.makedirs(os.path.join(bus, "textures"))

    clear()
    bpy.ops.mesh.primitive_cube_add(size=1)
    door = bpy.context.object
    door.name = "Door"
    for v in door.data.vertices:
        v.co.x += 0.5  # origin on the hinge
    door.location = (2, 3, 1)
    door.rotation_euler = (0, math.radians(10), math.radians(30))
    door.scale = (1, 1, 2)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.5, depth=0.3, location=(-1, 4, 0.5))
    bpy.context.object.name = "Wheel"
    reference = snapshot()

    door_3ds = os.path.join(bus, "models", "doors", "door.3ds")
    result = bpy.ops.export_scene.pbs_3ds(filepath=door_3ds)
    check("export finished", result == {'FINISHED'})
    check("export written to destination", os.path.isfile(door_3ds))
    check("no temp file left after export", no_temp_files(os.path.join(bus, "textures")))

    clear()
    bpy.ops.import_scene.pbs_3ds(filepath=door_3ds)
    got = snapshot()
    check("no temp file left after import", no_temp_files(os.path.join(bus, "textures")))
    for name, ref in reference.items():
        g = got.get(name)
        check(f"{name}: imported", g is not None)
        if g:
            check(f"{name}: origin restored", g[0] == ref[0])
            check(f"{name}: rotation restored", g[1] == ref[1])
            check(f"{name}: geometry in place", g[2] == ref[2])

    with open(os.path.join(bus, "model.txt"), "w", encoding="utf-8") as f:
        f.write("[part1_3ds]\nmodel1=models/doors/door.3ds\nmodel2=models/missing.3ds\n\n[speed]\nposX=0\n")
    with open(os.path.join(root, "bus.ini"), "w", encoding="utf-8") as f:
        f.write("[mod]\nname=Test\n\n[config]\nbaseDir=Bus\nmodels1=model.txt\n")
    clear()
    result = bpy.ops.import_scene.pbs_ini(filepath=os.path.join(root, "bus.ini"))
    check("bus INI import finished", result == {'FINISHED'})
    bus_col = bpy.data.collections.get("bus")
    check("bus INI collection created", bus_col is not None)
    check("bus INI sub-collection per 3DS", bus_col is not None and [c.name for c in bus_col.children] == ["door"])

    # Synthetic map: <root>/test.map.txt, <root>/Map/{textures/, tiles/main/*.3ds}
    tiles = os.path.join(root, "Map", "tiles", "main")
    os.makedirs(tiles)
    os.makedirs(os.path.join(root, "Map", "textures"))
    shutil.copy(door_3ds, os.path.join(tiles, "test_t0_0.3ds"))
    shutil.copy(door_3ds, os.path.join(tiles, "test_t1_0.3ds"))
    with open(os.path.join(root, "test.map.txt"), "w", encoding="utf-8") as f:
        f.write("[map]\nbaseDir=Map\nmodelsDir=main\ntextures=textures\n")
    clear()
    result = bpy.ops.import_scene.pbs_map(filepath=os.path.join(root, "test.map.txt"))
    check("map import finished", result == {'FINISHED'})
    map_col = bpy.data.collections.get("test")
    check("map sub-collection per tile",
          map_col is not None and [c.name for c in map_col.children] == ["test_t0_0", "test_t1_0"])
    check("no temp file left after map import", no_temp_files(os.path.join(root, "Map", "textures")))

    # Mesh over the 3DS limit
    clear()
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=300, y_subdivisions=300, size=10)
    bpy.context.object.name = "Big"
    big_3ds = os.path.join(bus, "models", "big.3ds")
    bpy.ops.export_scene.pbs_3ds(filepath=big_3ds, use_split_large=False)
    clear()
    bpy.ops.import_scene.pbs_3ds(filepath=big_3ds)
    check("oversized mesh skipped without Split Large Meshes", "Big" not in bpy.data.objects)

    clear()
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=300, y_subdivisions=300, size=10)
    bpy.context.object.name = "Big"
    bpy.ops.export_scene.pbs_3ds(filepath=big_3ds, use_split_large=True)
    clear()
    bpy.ops.import_scene.pbs_3ds(filepath=big_3ds)
    parts = [ob for ob in bpy.data.objects if ob.name.startswith("Big")]
    tris = 0
    for ob in parts:
        ob.data.calc_loop_triangles()
        tris += len(ob.data.loop_triangles)
    check("oversized mesh split into parts", len(parts) > 1)
    check("split keeps every triangle", tris == 180000)
finally:
    shutil.rmtree(root, ignore_errors=True)

print(f"\n{len(failures)} failure(s)")
if failures:
    raise SystemExit(1)
