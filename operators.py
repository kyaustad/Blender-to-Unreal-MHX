# SPDX-FileCopyrightText: 2026 Kyle Austad
# SPDX-License-Identifier: GPL-2.0-or-later

import traceback

import bpy
from bpy.props import EnumProperty
from bpy.types import Operator

from . import exporter, meshes
from .props import get_settings

# Diffeomorphic "Convert To MHX" options that suit a game export: no stretchy
# limbs (clean joint lengths for UE IK), bend/twist split, no extra IK helpers.
UE_MHX_PRESET = {
    "usePoleTargets": False,
    "useStretch": False,
    "useSplitShin": True,
    "useTweakBones": False,
    "useSpineIk": False,
    "useAnkleIk": False,
    "useFingerIk": False,
    "keepG9Twist": False,
    "keepRig": False,
    "useRaiseError": True,
}

REPORT_TEXT = "UnrealMHX_Report"


def _diffeo_convert_available():
    return hasattr(bpy.ops, "daz") and hasattr(bpy.ops.daz, "convert_to_mhx")


def refresh_lists(context, rig):
    settings = get_settings(context)
    old_meshes = {item.name: item.export for item in settings.mesh_items}
    settings.mesh_items.clear()
    for ob in meshes.bound_meshes(rig):
        item = settings.mesh_items.add()
        item.name = ob.name
        item.export = old_meshes.get(ob.name, True)
    old_actions = {item.name: item.export for item in settings.action_items}
    settings.action_items.clear()
    for action in exporter.rig_actions(rig):
        item = settings.action_items.add()
        item.name = action.name
        item.export = old_actions.get(action.name, True)


class UNREAL_MHX_OT_convert_to_mhx(Operator):
    bl_idname = "unreal_mhx.convert_to_mhx"
    bl_label = "Convert to MHX (UE Preset)"
    bl_description = ("Run Diffeomorphic's Convert To MHX with options suited for Unreal: "
                      "no stretchy limbs, split bend/twist bones, no extra IK helpers")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.object
        return (_diffeo_convert_available() and ob is not None and ob.type == 'ARMATURE'
                and not exporter.is_mhx_rig(ob))

    def execute(self, context):
        op = bpy.ops.daz.convert_to_mhx
        available = {p.identifier for p in op.get_rna_type().properties}
        kwargs = {k: v for k, v in UE_MHX_PRESET.items() if k in available}
        try:
            result = op('EXEC_DEFAULT', **kwargs)
        except Exception as exc:
            self.report({'ERROR'}, "Convert To MHX failed: %s" % exc)
            return {'CANCELLED'}
        if 'FINISHED' not in result or not exporter.is_mhx_rig(context.object):
            self.report({'WARNING'}, "Convert To MHX did not produce an MHX rig.")
            return {'CANCELLED'}
        refresh_lists(context, context.object)
        self.report({'INFO'}, "Converted %s to MHX." % context.object.name)
        return {'FINISHED'}


class UNREAL_MHX_OT_refresh(Operator):
    bl_idname = "unreal_mhx.refresh"
    bl_label = "Refresh"
    bl_description = "Refresh the mesh and action lists from the active MHX rig"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return exporter.find_source_rig(context) is not None

    def execute(self, context):
        refresh_lists(context, exporter.find_source_rig(context))
        return {'FINISHED'}


class UNREAL_MHX_OT_reset_rest_morphs(Operator):
    bl_idname = "unreal_mhx.reset_rest_morphs"
    bl_label = "Re-read Rest Morphs"
    bl_description = ("Forget the remembered rest-pose morph values so they are read again on the "
                      "next export. Use after changing body shape dials, then re-export the "
                      "character and its animations")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return exporter.find_source_rig(context) is not None

    def execute(self, context):
        rig = exporter.find_source_rig(context)
        count = 0
        for ob in meshes.bound_meshes(rig):
            if meshes.REST_MORPHS_PROP in ob:
                del ob[meshes.REST_MORPHS_PROP]
                count += 1
        self.report({'INFO'}, "Cleared rest morph values on %d mesh(es)." % count)
        return {'FINISHED'}


def _format_report(rig, plan, settings, mesh_objects):
    lines = ["Unreal MHX skeleton plan for %s" % rig.name, ""]
    if plan.errors:
        lines.append("ERRORS:")
        lines += ["  " + e for e in plan.errors]
        lines.append("")
    if plan.warnings:
        lines.append("Warnings:")
        lines += ["  " + w for w in plan.warnings]
        lines.append("")
    cats = {}
    for pb in plan.bones:
        cats.setdefault(pb.category, []).append(pb)
    lines.append("%d export bones: %s" % (
        len(plan.bones), ", ".join("%d %s" % (len(v), k) for k, v in sorted(cats.items()))))
    lines.append("Meshes: %s" % ", ".join(ob.name for ob in mesh_objects))
    lines.append("")
    lines.append("%-24s %-24s %-22s %s" % ("export bone", "MHX source", "parent", "category"))
    for pb in plan.bones:
        lines.append("%-24s %-24s %-22s %s" % (pb.name, pb.source or "-", pb.parent or "root", pb.category))
    if plan.merged:
        lines.append("")
        lines.append("Merged (excluded) bones:")
        for src, target in sorted(plan.merged.items()):
            lines.append("  %s -> %s" % (src, target))
    lines.append("")
    lines.append("IK Rig chains:")
    for name, start, end, goal in plan.chains():
        lines.append("  %-14s %s .. %s%s" % (name, start, end, ("  goal " + goal) if goal else ""))
    return "\n".join(lines)


class UNREAL_MHX_OT_check(Operator):
    bl_idname = "unreal_mhx.check"
    bl_label = "Check Rig"
    bl_description = ("Plan the Unreal skeleton without exporting and write the mapping to the "
                      "'%s' text block" % REPORT_TEXT)

    @classmethod
    def poll(cls, context):
        return exporter.is_mhx_rig(exporter.find_source_rig(context))

    def execute(self, context):
        rig = exporter.find_source_rig(context)
        settings = exporter.Settings(get_settings(context), context.scene)
        mesh_objects = exporter.selected_meshes(rig, settings) or meshes.bound_meshes(rig)
        plan = exporter.make_plan(rig, mesh_objects, settings)
        text = bpy.data.texts.get(REPORT_TEXT) or bpy.data.texts.new(REPORT_TEXT)
        text.clear()
        text.write(_format_report(rig, plan, settings, mesh_objects))
        if plan.errors:
            for err in plan.errors:
                self.report({'ERROR'}, err)
            return {'CANCELLED'}
        for warning in plan.warnings:
            self.report({'WARNING'}, warning)
        self.report({'INFO'}, "%d export bones planned. Details in the '%s' text block."
                    % (len(plan.bones), REPORT_TEXT))
        return {'FINISHED'}


class UNREAL_MHX_OT_export(Operator):
    bl_idname = "unreal_mhx.export"
    bl_label = "Export to Unreal"
    bl_description = "Export the MHX character and/or its animations as Unreal-ready FBX files"
    bl_options = {'REGISTER'}

    mode: EnumProperty(
        name="Mode",
        items=(
            ('CHARACTER', "Character", "Skeletal mesh with morph targets (rest pose)"),
            ('ANIMATION', "Animation", "Animation FBX file(s) for the exported skeleton"),
            ('ALL', "Character + Animation", "Both, in one pass"),
            ('PREVIEW', "Preview", "Build and bake the export rig in the scene without writing files"),
        ),
        default='ALL',
    )

    @classmethod
    def description(cls, _context, properties):
        return {
            'CHARACTER': "Export the skeletal mesh (rest pose, morph targets) and the skeleton JSON",
            'ANIMATION': "Export animation FBX file(s) baked from the MHX rig",
            'ALL': "Export the character and its animation(s) in one pass",
            'PREVIEW': ("Build the Unreal skeleton and meshes in the scene and bake the timeline, "
                        "to compare with the MHX character before exporting"),
        }.get(properties.mode, cls.bl_description)

    @classmethod
    def poll(cls, context):
        return exporter.is_mhx_rig(exporter.find_source_rig(context))

    def animations(self, context, session):
        settings = get_settings(context)
        scene = context.scene
        if settings.anim_source == 'TIMELINE':
            name = settings.anim_name.strip()
            if not name:
                ad = session.rig.animation_data
                name = ad.action.name if ad and ad.action else "Anim"
            return [(name, exporter.timeline_frames(scene), None)]
        out = []
        for item in settings.action_items:
            action = bpy.data.actions.get(item.name)
            if item.export and action is not None:
                out.append((action.name, exporter.action_frames(action), action))
        if not out:
            raise exporter.ExportError("No actions checked. Refresh the action list and tick some.")
        return out

    def execute(self, context):
        rig = exporter.find_source_rig(context)
        props = get_settings(context)
        if not props.mesh_items:
            refresh_lists(context, rig)
        settings = exporter.Settings(props, context.scene)
        if self.mode == 'PREVIEW':
            settings.keep_export_objects = True
        wm = context.window_manager
        written = []
        try:
            with exporter.ExportSession(context, rig, settings) as session:
                need_meshes = self.mode in ('CHARACTER', 'ALL', 'PREVIEW') or settings.anim_include_meshes
                session.build(with_meshes=need_meshes)
                if self.mode in ('CHARACTER', 'ALL'):
                    path, json_path = session.export_character()
                    written.append(path)
                    if json_path:
                        written.append(json_path)
                if self.mode in ('ANIMATION', 'ALL'):
                    anims = self.animations(context, session)
                    for idx, (name, frames, action) in enumerate(anims):
                        if action is not None:
                            session.use_action(action)
                        wm.progress_begin(0, len(frames))
                        try:
                            written.append(session.export_animation(
                                name, frames, progress=lambda i, _n: wm.progress_update(i)))
                        finally:
                            wm.progress_end()
                if self.mode == 'PREVIEW':
                    session.bake(exporter.timeline_frames(context.scene), "UnrealMHX_Preview")
                for warning in session.warnings[:12]:
                    self.report({'WARNING'}, warning)
        except exporter.ExportError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        except Exception as exc:
            traceback.print_exc()
            self.report({'ERROR'}, "Export failed: %s (see console)" % exc)
            return {'CANCELLED'}
        if self.mode == 'PREVIEW':
            self.report({'INFO'}, "Preview built in the '%s' collection." % exporter.EXPORT_COLLECTION)
        else:
            for path in written:
                print("Unreal MHX: wrote", path)
            self.report({'INFO'}, "Exported %d file(s) to %s" % (len(written), settings.export_dir))
        return {'FINISHED'}


class UNREAL_MHX_OT_clear_preview(Operator):
    bl_idname = "unreal_mhx.clear_preview"
    bl_label = "Remove Preview"
    bl_description = "Delete the kept 'root' export armature, _UE meshes and their baked actions"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, _context):
        for action in list(bpy.data.actions):
            if action.get(exporter.EXPORT_TAG):
                bpy.data.actions.remove(action)
        exporter.remove_previous_exports()
        renamed = bpy.data.objects.get("root.__umhx_renamed")
        if renamed is not None and "root" not in bpy.data.objects:
            renamed.name = "root"
        return {'FINISHED'}


classes = (
    UNREAL_MHX_OT_convert_to_mhx,
    UNREAL_MHX_OT_refresh,
    UNREAL_MHX_OT_reset_rest_morphs,
    UNREAL_MHX_OT_check,
    UNREAL_MHX_OT_export,
    UNREAL_MHX_OT_clear_preview,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
