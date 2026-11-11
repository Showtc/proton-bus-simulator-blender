# SPDX-License-Identifier: GPL-2.0-or-later
"""Proton Bus 3DS Tools.

Standalone 3DS import/export for Proton Bus Simulator mods. The 3DS reader and
writer (import_3ds.py / export_3ds.py) are based on the official Blender
"Autodesk 3DS" add-on 3.0.2, with the PBSU 3DS changes (full-length object
names, World in the default export filter) and oversized-mesh warnings reported
in Blender. On top of that:

* 3DS imports run from a temporary copy placed in the mod's ``textures``
  folder, so textures referenced by file name are found.
* A whole bus can be imported from its INI file (``baseDir`` + ``modelsN``
  model lists), one collection per INI and one sub-collection per 3DS file.
* A whole map can be imported from its ``.map.txt`` file (every 3DS tile in
  ``<baseDir>/tiles/<modelsDir>``), one collection per map and one
  sub-collection per tile.
* 3DS exports are written in the ``textures`` folder first, then copied to
  the requested destination.
"""

import os
import shutil

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    StringProperty,
)
from bpy.types import FileHandler, Operator
from bpy_extras.io_utils import (
    ExportHelper,
    ImportHelper,
    axis_conversion,
    orientation_helper,
    poll_file_object_drop,
)

if "pbs_ini" in locals():
    import importlib
    importlib.reload(pbs_ini)
    importlib.reload(import_3ds)
    importlib.reload(export_3ds)

from . import pbs_ini, import_3ds, export_3ds


TEMP_PREFIX = "__pbs_tmp_"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _unique_temp_path(directory, stem):
    candidate = os.path.join(directory, f"{TEMP_PREFIX}{stem}.3ds")
    i = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{TEMP_PREFIX}{stem}_{i}.3ds")
        i += 1
    return candidate


def _find_layer_collection(layer_collection, collection):
    if layer_collection.collection == collection:
        return layer_collection
    for child in layer_collection.children:
        found = _find_layer_collection(child, collection)
        if found is not None:
            return found
    return None


def _set_active_collection(context, collection):
    lc = _find_layer_collection(context.view_layer.layer_collection, collection)
    if lc is not None:
        context.view_layer.active_layer_collection = lc


def _textures_dir_for(start_dir, override):
    if override:
        path = bpy.path.abspath(override)
        return path if os.path.isdir(path) else None
    return pbs_ini.find_textures_dir(start_dir)


def _import_via_textures(operator, context, src_3ds, textures_dir, target_collection, op_kwargs):
    """Copy src_3ds into textures_dir, import it into target_collection, delete the copy."""
    tmp = _unique_temp_path(textures_dir, os.path.splitext(os.path.basename(src_3ds))[0])
    shutil.copy2(src_3ds, tmp)
    try:
        _set_active_collection(context, target_collection)
        result = import_3ds.load(operator, context, filepath=tmp, use_collection=False, **op_kwargs)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return 'FINISHED' in result


# --------------------------------------------------------------------------
# Shared import options (defaults = requested presets)
# --------------------------------------------------------------------------

OBJECT_FILTER_ITEMS = (
    ('WORLD', "World".rjust(11), "", 'WORLD_DATA', 0x1),
    ('MESH', "Mesh".rjust(11), "", 'MESH_DATA', 0x2),
    ('LIGHT', "Light".rjust(12), "", 'LIGHT_DATA', 0x4),
    ('CAMERA', "Camera".rjust(11), "", 'CAMERA_DATA', 0x8),
    ('EMPTY', "Empty".rjust(11), "", 'EMPTY_AXIS', 0x10),
)


@orientation_helper(axis_forward='Y', axis_up='Z')
class PBS3DSImportOptions:
    textures_dir: StringProperty(
        name="Textures Folder",
        description="Folder the 3DS file is copied to while importing. "
        "Leave empty to auto-detect the closest 'textures' folder",
        subtype='DIR_PATH',
        default="",
    )
    use_image_search: BoolProperty(
        name="Image Search",
        description="Search subdirectories for any associated images (Warning, may be slow)",
        default=True,
    )
    object_filter: EnumProperty(
        name="Object Filter", options={'ENUM_FLAG'},
        items=OBJECT_FILTER_ITEMS,
        description="Object types to import",
        default={'WORLD', 'MESH', 'LIGHT', 'CAMERA', 'EMPTY'},
    )
    use_keyframes: BoolProperty(
        name="Animation",
        description="Read the keyframe data",
        default=True,
    )
    use_cursor: BoolProperty(
        name="Cursor Origin",
        description="Read the 3D cursor location",
        default=False,
    )
    constrain_size: FloatProperty(
        name="Constrain Size",
        description="Scale the model by 10 until it reaches the size constraint (0 to disable)",
        min=0.0, max=1000.0, soft_min=0.0, soft_max=1000.0,
        default=0.0,
    )
    use_scene_unit: BoolProperty(
        name="Scene Units",
        description="Convert to scene unit length settings",
        default=True,
    )
    use_apply_transform: BoolProperty(
        name="Apply Transform",
        description="Workaround for object transformations importing incorrectly",
        default=False,
    )
    use_restore_origins: BoolProperty(
        name="Restore Origins",
        description="Give each object its origin, rotation and scale back from the 3DS object matrix, "
        "keeping the geometry in place. When off, origins are left at the world origin",
        default=True,
    )

    def loader_kwargs(self):
        return dict(
            use_image_search=self.use_image_search,
            object_filter=set(self.object_filter),
            use_keyframes=self.use_keyframes,
            use_cursor=self.use_cursor,
            constrain_size=self.constrain_size,
            use_scene_unit=self.use_scene_unit,
            use_apply_transform=self.use_apply_transform,
            use_restore_origins=self.use_restore_origins,
            global_matrix=axis_conversion(from_forward=self.axis_forward,
                                          from_up=self.axis_up).to_4x4(),
        )

    def draw_import_options(self, layout, extra_include=None):
        layout.use_property_split = True
        layout.use_property_decorate = False

        header, body = layout.panel("PBS3DS_import_paths", default_closed=False)
        header.label(text="Proton Bus")
        if body:
            body.prop(self, "textures_dir")
            if extra_include:
                extra_include(body)

        header, body = layout.panel("PBS3DS_import_include", default_closed=False)
        header.label(text="Include")
        if body:
            body.prop(self, "use_image_search")
            body.column().prop(self, "object_filter")
            body.prop(self, "use_keyframes")
            body.prop(self, "use_cursor")

        header, body = layout.panel("PBS3DS_import_transform", default_closed=False)
        header.label(text="Transform")
        if body:
            body.prop(self, "constrain_size")
            body.prop(self, "use_scene_unit")
            body.prop(self, "use_apply_transform")
            body.prop(self, "use_restore_origins")
            body.prop(self, "axis_forward")
            body.prop(self, "axis_up")


# --------------------------------------------------------------------------
# Import 3DS
# --------------------------------------------------------------------------

class PBS_OT_import_3ds(Operator, ImportHelper, PBS3DSImportOptions):
    """Import 3DS files through the mod textures folder (Proton Bus Simulator)"""
    bl_idname = "import_scene.pbs_3ds"
    bl_label = "Import 3DS (Proton Bus)"
    bl_options = {'REGISTER', 'UNDO', 'PRESET'}

    filename_ext = ".3ds"
    filter_glob: StringProperty(default="*.3ds", options={'HIDDEN'})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})
    directory: StringProperty(subtype='DIR_PATH', options={'HIDDEN', 'SKIP_SAVE'})

    use_collection: BoolProperty(
        name="Collection",
        description="Create a collection named after each 3DS file",
        default=False,
    )

    def draw(self, context):
        self.draw_import_options(self.layout, lambda body: body.prop(self, "use_collection"))

    def execute(self, context):
        if self.files and self.files[0].name:
            paths = [os.path.join(self.directory, f.name) for f in self.files]
        else:
            paths = [self.filepath]

        initial = context.view_layer.active_layer_collection.collection
        kwargs = self.loader_kwargs()
        imported = 0
        try:
            for path in paths:
                if not os.path.isfile(path):
                    self.report({'WARNING'}, f"File not found: {path}")
                    continue
                textures_dir = _textures_dir_for(os.path.dirname(path), self.textures_dir)
                if textures_dir is None:
                    self.report({'ERROR'}, f"No 'textures' folder found for {path}")
                    continue
                target = initial
                if self.use_collection:
                    target = bpy.data.collections.new(os.path.splitext(os.path.basename(path))[0])
                    initial.children.link(target)
                if _import_via_textures(self, context, path, textures_dir, target, kwargs):
                    imported += 1
        finally:
            _set_active_collection(context, initial)

        if imported == 0:
            return {'CANCELLED'}
        self.report({'INFO'}, f"Imported {imported} 3DS file(s)")
        return {'FINISHED'}


# --------------------------------------------------------------------------
# Import a list of 3DS files (shared by bus INI and map imports)
# --------------------------------------------------------------------------

class PBSListImportBase(PBS3DSImportOptions):
    """Imports the 3DS files listed by a description file (bus INI, map .map.txt).

    Subclasses implement ``collect(path)`` returning
    ``(collection_name, textures_dir, [3ds paths])`` or ``None`` on error.
    """

    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})
    directory: StringProperty(subtype='DIR_PATH', options={'HIDDEN', 'SKIP_SAVE'})

    def draw(self, context):
        self.draw_import_options(self.layout)

    def resolve_textures_dir(self, base_dir, default_rel="textures"):
        """Override folder, else <base_dir>/<default_rel>, else closest 'textures' folder."""
        if self.textures_dir:
            return _textures_dir_for(base_dir, self.textures_dir)
        if default_rel:
            candidate = pbs_ini.resolve(base_dir, default_rel)
            if os.path.isdir(candidate):
                return candidate
        return pbs_ini.find_textures_dir(base_dir)

    def _import_list(self, context, root_name, textures_dir, models, kwargs, wm, progress):
        root = bpy.data.collections.new(root_name)
        context.scene.collection.children.link(root)

        imported = failed = 0
        for path in models:
            progress[0] += 1
            wm.progress_update(progress[0])
            if not os.path.isfile(path):
                self.report({'WARNING'}, f"3DS not found: {path}")
                failed += 1
                continue
            sub = bpy.data.collections.new(os.path.splitext(os.path.basename(path))[0])
            root.children.link(sub)
            try:
                ok = _import_via_textures(self, context, path, textures_dir, sub, kwargs)
            except Exception as ex:  # keep importing the other parts
                self.report({'WARNING'}, f"Failed to import {path}: {ex}")
                ok = False
            if ok:
                imported += 1
            else:
                failed += 1
        return imported, failed

    def execute(self, context):
        if self.files and self.files[0].name:
            sources = [os.path.join(self.directory, f.name) for f in self.files]
        else:
            sources = [self.filepath]

        jobs = []
        for src in sources:
            if not os.path.isfile(src):
                self.report({'WARNING'}, f"File not found: {src}")
                continue
            job = self.collect(src)
            if job is not None:
                jobs.append(job)

        initial = context.view_layer.active_layer_collection.collection
        kwargs = self.loader_kwargs()
        wm = context.window_manager
        wm.progress_begin(0, max(1, sum(len(models) for _n, _t, models in jobs)))
        progress = [0]
        total_ok = total_failed = 0
        try:
            for root_name, textures_dir, models in jobs:
                ok, failed = self._import_list(context, root_name, textures_dir, models, kwargs, wm, progress)
                total_ok += ok
                total_failed += failed
        finally:
            wm.progress_end()
            _set_active_collection(context, initial)

        if total_ok == 0:
            self.report({'ERROR'}, "No 3DS file imported")
            return {'CANCELLED'}
        msg = f"Imported {total_ok} 3DS file(s)"
        if total_failed:
            msg += f", {total_failed} missing/failed (see Info log)"
            self.report({'WARNING'}, msg)
        else:
            self.report({'INFO'}, msg)
        return {'FINISHED'}


# --------------------------------------------------------------------------
# Import bus INI
# --------------------------------------------------------------------------

class PBS_OT_import_ini(Operator, ImportHelper, PBSListImportBase):
    """Import every 3DS model referenced by a Proton Bus Simulator bus INI file"""
    bl_idname = "import_scene.pbs_ini"
    bl_label = "Import Bus INI (Proton Bus)"
    bl_options = {'REGISTER', 'UNDO', 'PRESET'}

    filename_ext = ".ini"
    filter_glob: StringProperty(default="*.ini", options={'HIDDEN'})

    def collect(self, ini_path):
        base_dir, model_txts = pbs_ini.read_bus_ini(ini_path)
        if not os.path.isdir(base_dir):
            self.report({'ERROR'}, f"baseDir not found: {base_dir}")
            return None
        if not model_txts:
            self.report({'WARNING'}, f"No 'modelsN=' entry in [config] of {os.path.basename(ini_path)}")
            return None

        textures_dir = self.resolve_textures_dir(base_dir)
        if textures_dir is None:
            self.report({'ERROR'}, f"No 'textures' folder found for {base_dir}")
            return None

        models = []
        seen = set()
        for txt in model_txts:
            if not os.path.isfile(txt):
                self.report({'WARNING'}, f"Model list not found: {txt}")
                continue
            for path in pbs_ini.read_model_list(txt, base_dir):
                key = os.path.normcase(path)
                if key not in seen:
                    seen.add(key)
                    models.append(path)

        return os.path.splitext(os.path.basename(ini_path))[0], textures_dir, models


# --------------------------------------------------------------------------
# Import map (.map.txt)
# --------------------------------------------------------------------------

class PBS_OT_import_map(Operator, ImportHelper, PBSListImportBase):
    """Import every 3DS tile of a Proton Bus Simulator map (.map.txt)"""
    bl_idname = "import_scene.pbs_map"
    bl_label = "Import Map (Proton Bus)"
    bl_options = {'REGISTER', 'UNDO', 'PRESET'}

    filename_ext = ".txt"
    filter_glob: StringProperty(default="*.map.txt", options={'HIDDEN'})

    def collect(self, map_path):
        info = pbs_ini.read_map_txt(map_path)
        if not os.path.isdir(info.base_dir):
            self.report({'ERROR'}, f"baseDir not found: {info.base_dir}")
            return None
        if not os.path.isdir(info.models_dir):
            self.report({'ERROR'}, f"Tiles folder not found: {info.models_dir}")
            return None

        textures_dir = self.resolve_textures_dir(info.base_dir, info.textures_rel)
        if textures_dir is None:
            self.report({'ERROR'}, f"No textures folder found for {info.base_dir}")
            return None

        models = pbs_ini.list_3ds(info.models_dir)
        if not models:
            self.report({'WARNING'}, f"No .3ds file in {info.models_dir}")
            return None
        return pbs_ini.map_name(map_path), textures_dir, models


# --------------------------------------------------------------------------
# Export 3DS
# --------------------------------------------------------------------------

@orientation_helper(axis_forward='Y', axis_up='Z')
class PBS_OT_export_3ds(Operator, ExportHelper):
    """Export to 3DS through the mod textures folder (Proton Bus Simulator)"""
    bl_idname = "export_scene.pbs_3ds"
    bl_label = "Export 3DS (Proton Bus)"
    bl_options = {'REGISTER', 'PRESET'}

    filename_ext = ".3ds"
    filter_glob: StringProperty(default="*.3ds", options={'HIDDEN'})

    textures_dir: StringProperty(
        name="Textures Folder",
        description="Folder the 3DS is exported to before being copied to the destination. "
        "Leave empty to auto-detect the closest 'textures' folder",
        subtype='DIR_PATH',
        default="",
    )
    collection: StringProperty(
        name="Source Collection",
        description="Export objects from this collection",
        default="",
    )
    scale_factor: FloatProperty(
        name="Scale Factor",
        description="Master scale factor for all objects",
        min=0.0, max=100000.0, soft_min=0.0, soft_max=100000.0,
        default=1.0,
    )
    use_scene_unit: BoolProperty(
        name="Scene Units",
        description="Take the scene unit length settings into account",
        default=True,
    )
    use_images: BoolProperty(
        name="Images",
        description="Export all associated images from the scene",
        default=False,
    )
    use_selection: BoolProperty(
        name="Selection",
        description="Export selected objects only",
        default=False,
    )
    object_filter: EnumProperty(
        name="Object Filter", options={'ENUM_FLAG'},
        items=OBJECT_FILTER_ITEMS + (('OTHER', "Other".rjust(12), "", 'MATSHADERBALL', 0x20),),
        description="Object types to export",
        default={'WORLD', 'MESH', 'LIGHT', 'CAMERA', 'EMPTY'},
    )
    use_apply_transform: BoolProperty(
        name="Apply Transform",
        description="Apply matrix transform before export",
        default=True,
    )
    use_invisible: BoolProperty(
        name="Invisible",
        description="Export invisible objects",
        default=False,
    )
    use_keyframes: BoolProperty(
        name="Animation",
        description="Write the keyframe data",
        default=False,
    )
    use_hierarchy: BoolProperty(
        name="Hierarchy",
        description="Export hierarchy chunks",
        default=False,
    )
    use_collection: BoolProperty(
        name="Collection",
        description="Export active collection only",
        default=False,
    )
    use_cursor: BoolProperty(
        name="Cursor Origin",
        description="Save the 3D cursor location",
        default=False,
    )
    use_split_large: BoolProperty(
        name="Split Large Meshes",
        description="Split meshes over the 3DS limit (65535 vertices or faces, after triangulation "
        "and UV seams) into several objects: <name>, <name>_2, <name>_3... "
        "When off, such meshes are skipped with a warning",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        header, body = layout.panel("PBS3DS_export_paths", default_closed=False)
        header.label(text="Proton Bus")
        if body:
            body.prop(self, "textures_dir")

        header, body = layout.panel("PBS3DS_export_include", default_closed=False)
        header.label(text="Include")
        if body:
            body.prop(self, "use_images")
            body.prop(self, "use_invisible")
            body.prop(self, "use_selection")
            body.prop(self, "use_collection")
            body.column().prop(self, "object_filter")
            body.prop(self, "use_keyframes")
            body.prop(self, "use_hierarchy")
            body.prop(self, "use_cursor")
            body.prop(self, "use_split_large")

        header, body = layout.panel("PBS3DS_export_transform", default_closed=False)
        header.label(text="Transform")
        if body:
            body.prop(self, "scale_factor")
            body.prop(self, "use_scene_unit")
            body.prop(self, "use_apply_transform")
            body.prop(self, "axis_forward")
            body.prop(self, "axis_up")

    def execute(self, context):
        dest = bpy.path.ensure_ext(bpy.path.abspath(self.filepath), ".3ds")
        dest_dir = os.path.dirname(dest)
        textures_dir = _textures_dir_for(dest_dir, self.textures_dir)
        if textures_dir is None:
            self.report({'ERROR'}, f"No 'textures' folder found above {dest_dir}; set 'Textures Folder'")
            return {'CANCELLED'}

        tmp = _unique_temp_path(textures_dir, os.path.splitext(os.path.basename(dest))[0])
        try:
            result = export_3ds.save(
                self, context,
                filepath=tmp,
                collection=self.collection,
                scale_factor=self.scale_factor,
                use_scene_unit=self.use_scene_unit,
                use_images=self.use_images,
                use_selection=self.use_selection,
                object_filter=set(self.object_filter),
                use_apply_transform=self.use_apply_transform,
                use_invisible=self.use_invisible,
                use_keyframes=self.use_keyframes,
                use_hierarchy=self.use_hierarchy,
                use_collection=self.use_collection,
                use_cursor=self.use_cursor,
                use_split_large=self.use_split_large,
                global_matrix=axis_conversion(to_forward=self.axis_forward,
                                              to_up=self.axis_up).to_4x4(),
            )
            if 'FINISHED' not in result or not os.path.isfile(tmp):
                self.report({'ERROR'}, "3DS export failed")
                return {'CANCELLED'}
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(tmp, dest)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

        self.report({'INFO'}, f"Exported {dest}")
        return {'FINISHED'}


# --------------------------------------------------------------------------
# Drag & drop / menus / registration
# --------------------------------------------------------------------------

class PBS_FH_3ds(FileHandler):
    bl_idname = "PBS_FH_3ds"
    bl_label = "Proton Bus 3DS"
    bl_import_operator = "import_scene.pbs_3ds"
    bl_export_operator = "export_scene.pbs_3ds"
    bl_file_extensions = ".3ds;.3DS"

    @classmethod
    def poll_drop(cls, context):
        return poll_file_object_drop(context)


class PBS_FH_map(FileHandler):
    bl_idname = "PBS_FH_map"
    bl_label = "Proton Bus Map"
    bl_import_operator = "import_scene.pbs_map"
    bl_file_extensions = ".map.txt"

    @classmethod
    def poll_drop(cls, context):
        return poll_file_object_drop(context)


class PBS_FH_ini(FileHandler):
    bl_idname = "PBS_FH_ini"
    bl_label = "Proton Bus INI"
    bl_import_operator = "import_scene.pbs_ini"
    bl_file_extensions = ".ini;.INI"

    @classmethod
    def poll_drop(cls, context):
        return poll_file_object_drop(context)


def menu_func_import(self, context):
    self.layout.operator(PBS_OT_import_3ds.bl_idname, text="Proton Bus 3DS (.3ds)")
    self.layout.operator(PBS_OT_import_ini.bl_idname, text="Proton Bus INI (.ini)")
    self.layout.operator(PBS_OT_import_map.bl_idname, text="Proton Bus Map (.map.txt)")


def menu_func_export(self, context):
    self.layout.operator(PBS_OT_export_3ds.bl_idname, text="Proton Bus 3DS (.3ds)")


classes = (
    PBS_OT_import_3ds,
    PBS_OT_import_ini,
    PBS_OT_import_map,
    PBS_OT_export_3ds,
    PBS_FH_3ds,
    PBS_FH_ini,
    PBS_FH_map,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
