# SPDX-FileCopyrightText: 2026 Kyle Austad
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from bpy.types import Panel, UIList

from . import exporter
from .props import get_settings


class UNREAL_MHX_UL_items(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        icon = 'MESH_DATA' if self.list_id == "meshes" else 'ACTION'
        exists = (bpy.data.objects.get(item.name) if self.list_id == "meshes"
                  else bpy.data.actions.get(item.name)) is not None
        row = layout.row(align=True)
        row.prop(item, "export", text="")
        row.label(text=item.name, icon=icon if exists else 'ERROR')


class _Base:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Unreal MHX"


class _Sub(_Base):
    bl_parent_id = "UNREAL_MHX_PT_main"

    @classmethod
    def poll(cls, context):
        return exporter.is_mhx_rig(exporter.find_source_rig(context))


class UNREAL_MHX_PT_main(_Base, Panel):
    bl_label = "Unreal MHX"

    def draw(self, context):
        layout = self.layout
        rig = exporter.find_source_rig(context)
        if rig is None:
            layout.label(text="Select the character armature", icon='INFO')
            return
        if exporter.is_mhx_rig(rig):
            layout.label(text=rig.name, icon='ARMATURE_DATA')
            return
        layout.label(text="%s is not an MHX rig" % rig.name, icon='ERROR')
        if hasattr(bpy.ops, "daz") and hasattr(bpy.ops.daz, "convert_to_mhx"):
            layout.operator("unreal_mhx.convert_to_mhx", icon='OUTLINER_OB_ARMATURE')
        else:
            layout.label(text="Enable the Diffeomorphic DAZ Importer to convert it")


class UNREAL_MHX_PT_character(_Sub, Panel):
    bl_label = "Character"

    def draw(self, context):
        settings = get_settings(context)
        layout = self.layout
        layout.prop(settings, "character_name")
        layout.prop(settings, "export_dir")
        row = layout.row()
        row.label(text="Meshes")
        row.operator("unreal_mhx.refresh", text="", icon='FILE_REFRESH')
        layout.template_list("UNREAL_MHX_UL_items", "meshes", settings, "mesh_items",
                             settings, "mesh_index", rows=3)


class UNREAL_MHX_PT_skeleton(_Sub, Panel):
    bl_label = "Skeleton"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        settings = get_settings(context)
        layout = self.layout
        col = layout.column(heading="Include")
        col.prop(settings, "include_face")
        col.prop(settings, "include_toes")
        col.prop(settings, "include_extra")
        col = layout.column(heading="Unreal")
        col.prop(settings, "mannequin_axes")
        col.prop(settings, "add_ik_bones")
        sub = col.row()
        sub.enabled = settings.add_ik_bones
        sub.prop(settings, "animate_ik_bones")
        col.prop(settings, "root_motion")


class UNREAL_MHX_PT_meshes(_Sub, Panel):
    bl_label = "Morphs & Skinning"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        settings = get_settings(context)
        layout = self.layout
        layout.prop(settings, "export_morphs")
        layout.prop(settings, "bake_rest_morphs")
        layout.operator("unreal_mhx.reset_rest_morphs", icon='SHAPEKEY_DATA')
        layout.prop(settings, "max_influences")
        layout.prop(settings, "embed_textures")


class UNREAL_MHX_PT_animation(_Sub, Panel):
    bl_label = "Animation"

    def draw(self, context):
        settings = get_settings(context)
        layout = self.layout
        layout.row().prop(settings, "anim_source", expand=True)
        if settings.anim_source == 'TIMELINE':
            scene = context.scene
            if scene.use_preview_range:
                frames = (scene.frame_preview_start, scene.frame_preview_end)
            else:
                frames = (scene.frame_start, scene.frame_end)
            layout.prop(settings, "anim_name")
            layout.label(text="Frames %d - %d" % frames, icon='TIME')
        else:
            row = layout.row()
            row.label(text="Actions")
            row.operator("unreal_mhx.refresh", text="", icon='FILE_REFRESH')
            layout.template_list("UNREAL_MHX_UL_items", "actions", settings, "action_items",
                                 settings, "action_index", rows=4)
        layout.prop(settings, "anim_include_meshes")


class UNREAL_MHX_PT_export(_Sub, Panel):
    bl_label = "Export"

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("unreal_mhx.export", text="Export Character", icon='OUTLINER_OB_ARMATURE').mode = 'CHARACTER'
        col.operator("unreal_mhx.export", text="Export Animation", icon='ACTION').mode = 'ANIMATION'
        col.operator("unreal_mhx.export", text="Export Both", icon='EXPORT').mode = 'ALL'
        row = layout.row(align=True)
        row.operator("unreal_mhx.check", icon='VIEWZOOM')
        row.operator("unreal_mhx.export", text="Preview", icon='HIDE_OFF').mode = 'PREVIEW'
        if bpy.data.collections.get(exporter.EXPORT_COLLECTION):
            layout.operator("unreal_mhx.clear_preview", icon='TRASH')


class UNREAL_MHX_PT_advanced(_Sub, Panel):
    bl_label = "Advanced"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        settings = get_settings(context)
        layout = self.layout
        layout.prop(settings, "units_x100")
        if not settings.units_x100:
            layout.label(text="Root bone will carry a x100 scale in Unreal", icon='ERROR')
        layout.prop(settings, "write_retarget_json")
        layout.prop(settings, "keep_export_objects")


classes = (
    UNREAL_MHX_UL_items,
    UNREAL_MHX_PT_main,
    UNREAL_MHX_PT_character,
    UNREAL_MHX_PT_skeleton,
    UNREAL_MHX_PT_meshes,
    UNREAL_MHX_PT_animation,
    UNREAL_MHX_PT_export,
    UNREAL_MHX_PT_advanced,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
