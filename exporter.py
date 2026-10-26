# SPDX-FileCopyrightText: 2026 Kyle Austad
# SPDX-License-Identifier: GPL-2.0-or-later
"""Export pipeline: plan -> export rig + meshes -> bake -> FBX.

The user's MHX character is never modified (except for a small custom
property that remembers the rest-pose morph values, so character and
animation exports stay consistent). Everything is built on copies inside a
temporary collection and removed again afterwards.
"""

import os
import re

import bpy
from mathutils import Matrix

from . import bake, fbx_io, meshes, retarget_json, rig_map, skeleton
from .anim_io import action_slot_for, assign_action

EXPORT_COLLECTION = "UnrealMHX_Export"
EXPORT_TAG = "UnrealMhxExport"


class ExportError(RuntimeError):
    pass


class Settings:
    """Plain snapshot of the scene settings used by one export run."""

    def __init__(self, props, scene=None):
        us = scene.unit_settings if scene is not None else None
        # meters per Blender unit (Diffeomorphic normally imports in meters)
        self.meters_per_unit = us.scale_length if us is not None and us.system != 'NONE' else 1.0
        self.character_name = props.character_name.strip() or "Character"
        self.export_dir = bpy.path.abspath(props.export_dir)
        self.include_face = props.include_face
        self.include_toes = props.include_toes
        self.include_extra = props.include_extra
        self.mannequin_axes = props.mannequin_axes
        self.add_ik_bones = props.add_ik_bones
        self.animate_ik_bones = props.animate_ik_bones
        self.root_motion = props.root_motion
        self.export_morphs = props.export_morphs
        self.bake_rest_morphs = props.bake_rest_morphs
        self.max_influences = props.max_influences
        self.embed_textures = props.embed_textures
        self.units_x100 = props.units_x100
        self.anim_include_meshes = props.anim_include_meshes
        self.keep_export_objects = props.keep_export_objects
        self.write_retarget_json = props.write_retarget_json
        self.mesh_filter = {item.name: item.export for item in props.mesh_items}

    @property
    def unit_scale(self):
        """Factor from Blender units to export units (centimeters with Units x100)."""
        return 100.0 * self.meters_per_unit if self.units_x100 else 1.0


def safe_filename(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip().strip(".")
    return name or "Export"


def find_source_rig(context):
    ob = context.object
    if ob is None:
        return None
    if ob.type == 'MESH':
        for mod in ob.modifiers:
            if mod.type == 'ARMATURE' and mod.object:
                ob = mod.object
                break
        else:
            ob = ob.parent if ob.parent and ob.parent.type == 'ARMATURE' else None
    if ob is None or ob.type != 'ARMATURE' or ob.get(EXPORT_TAG):
        return None
    return ob


def is_mhx_rig(rig):
    return bool(rig and rig.type == 'ARMATURE' and rig.get("MhxRig"))


def selected_meshes(rig, settings):
    out = []
    for ob in meshes.bound_meshes(rig):
        if settings.mesh_filter.get(ob.name, True):
            out.append(ob)
    return out


def remove_previous_exports():
    for ob in list(bpy.data.objects):
        if ob.get(EXPORT_TAG):
            data = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            if data is not None and data.users == 0:
                if isinstance(data, bpy.types.Armature):
                    bpy.data.armatures.remove(data)
                elif isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)
    coll = bpy.data.collections.get(EXPORT_COLLECTION)
    if coll is not None and not coll.objects:
        bpy.data.collections.remove(coll)


def collect_weighted(rig, mesh_objects):
    weighted = set()
    deform = {b.name for b in rig.data.bones if b.use_deform}
    for ob in mesh_objects:
        if meshes.is_rigid(ob, rig):
            continue
        weighted |= meshes.weighted_groups(ob) & deform
    return weighted


def make_plan(rig, mesh_objects, settings):
    plan = rig_map.build_plan(
        skeleton.source_bones(rig),
        collect_weighted(rig, mesh_objects),
        include_face=settings.include_face,
        include_toes=settings.include_toes,
        include_extra=settings.include_extra,
        add_ik=settings.add_ik_bones,
    )
    return plan


class ExportSession:
    """Builds the export objects once and exports any number of FBX files."""

    def __init__(self, context, rig, settings, report=None):
        self.context = context
        self.rig = rig
        self.settings = settings
        self.report = report or (lambda level, msg: print("Unreal MHX:", msg))
        self.collection = None
        self.export_rig = None
        self.export_meshes = []
        self.mesh_pairs = []
        self.mesh_infos = []
        self.plan = None
        self.rest_values = {}
        self.created_actions = []
        self.warnings = []
        self._saved = {}

    # ------------------------------------------------------------------
    #   state
    # ------------------------------------------------------------------

    def __enter__(self):
        ctx = self.context
        scene = ctx.scene
        view_layer = ctx.view_layer
        self._saved = {
            "frame": scene.frame_current,
            "range": (scene.frame_start, scene.frame_end),
            "active": view_layer.objects.active,
            "selected": [ob for ob in view_layer.objects if ob.select_get()],
            "pose_position": self.rig.data.pose_position,
            "anim": None,
            "renamed_root": None,
            "mode": ctx.object.mode if ctx.object is not None else 'OBJECT',
        }
        ad = self.rig.animation_data
        if ad is not None:
            self._saved["anim"] = (ad.action, getattr(ad, "action_slot", None), ad.use_nla)
        if ctx.object is not None and ctx.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        self.rig.data.pose_position = 'POSE'
        return self

    def __exit__(self, exc_type, _exc, _tb):
        ctx = self.context
        scene = ctx.scene
        try:
            for action in self.created_actions:
                if action.name in bpy.data.actions and not self.settings.keep_export_objects:
                    bpy.data.actions.remove(action)
            if not self.settings.keep_export_objects:
                self._remove_export_objects()
        finally:
            saved = self._saved
            anim = saved.get("anim")
            ad = self.rig.animation_data
            if anim is not None and ad is not None:
                action, slot, use_nla = anim
                assign_action(self.rig, action, slot)
                ad.use_nla = use_nla
            elif ad is not None and anim is None:
                ad.action = None
            self.rig.data.pose_position = saved.get("pose_position", 'POSE')
            renamed = saved.get("renamed_root")
            if renamed is not None and renamed.name in bpy.data.objects:
                if rig_map.ROOT_NAME not in bpy.data.objects:
                    renamed.name = rig_map.ROOT_NAME
            scene.frame_start, scene.frame_end = saved["range"]
            scene.frame_set(saved["frame"])
            view_layer = ctx.view_layer
            for ob in view_layer.objects:
                ob.select_set(False)
            for ob in saved.get("selected", []):
                if ob.name in view_layer.objects:
                    ob.select_set(True)
            active = saved.get("active")
            if active is not None and active.name in view_layer.objects:
                view_layer.objects.active = active
                if saved.get("mode") == 'POSE' and active.type == 'ARMATURE':
                    bpy.ops.object.mode_set(mode='POSE')
        return False

    def _remove_export_objects(self):
        for ob in self.export_meshes:
            me = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            if me.users == 0:
                bpy.data.meshes.remove(me)
        self.export_meshes = []
        if self.export_rig is not None:
            arm = self.export_rig.data
            bpy.data.objects.remove(self.export_rig, do_unlink=True)
            if arm.users == 0:
                bpy.data.armatures.remove(arm)
            self.export_rig = None
        if self.collection is not None and not self.collection.objects:
            bpy.data.collections.remove(self.collection)
            self.collection = None

    # ------------------------------------------------------------------
    #   build
    # ------------------------------------------------------------------

    def build(self, with_meshes=True):
        ctx = self.context
        settings = self.settings
        remove_previous_exports()

        mesh_objects = selected_meshes(self.rig, settings)
        if with_meshes and not mesh_objects:
            raise ExportError("No meshes bound to %s. Enable meshes in the list." % self.rig.name)
        self.plan = make_plan(self.rig, meshes.bound_meshes(self.rig) if not mesh_objects else mesh_objects,
                              settings)
        if self.plan.errors:
            raise ExportError(" ".join(self.plan.errors))
        self.warnings.extend(self.plan.warnings)
        head = self.plan.get("head")
        height = head.head[2] * self.rig.matrix_world.to_scale()[2] * settings.meters_per_unit
        if not 0.3 < height < 3.0:
            self.warnings.append(
                "The head is %.2f m above the rig origin. Expected a human scale in meters; check the "
                "Diffeomorphic import scale or the scene unit scale." % height)

        self.collection = bpy.data.collections.new(EXPORT_COLLECTION)
        ctx.scene.collection.children.link(self.collection)

        renamed_name = rig_map.ROOT_NAME + ".__umhx_renamed"
        existing = bpy.data.objects.get(rig_map.ROOT_NAME)
        if existing is not None:
            existing.name = renamed_name
        if renamed_name in bpy.data.objects:
            self._saved["renamed_root"] = bpy.data.objects[renamed_name]

        self.export_rig = skeleton.build_armature(
            ctx, self.plan, self.rig, self.collection, settings.unit_scale,
            settings.mannequin_axes, data_name="%s_Skeleton" % settings.character_name)
        if self.export_rig.name != rig_map.ROOT_NAME:
            raise ExportError("Could not name the export armature '%s'." % rig_map.ROOT_NAME)

        if settings.bake_rest_morphs:
            self.rest_values = self._rest_morph_values(mesh_objects)

        if with_meshes:
            for src in mesh_objects:
                ob, info = meshes.make_export_mesh(
                    ctx, src, self.rig, self.export_rig, self.plan, self.collection,
                    settings.unit_scale, self.rest_values.get(src.name))
                ob[EXPORT_TAG] = True
                if not settings.export_morphs and ob.data.shape_keys is not None:
                    ob.shape_key_clear()
                meshes.limit_influences(ob, settings.max_influences)
                self.export_meshes.append(ob)
                self.mesh_infos.append(info)
                if ob.data.shape_keys is not None and src.data.shape_keys is not None:
                    self.mesh_pairs.append((src, ob))
            self.warnings.extend(meshes.summarize(self.mesh_infos))
        return self

    def _rest_morph_values(self, mesh_objects):
        """Rest morph values, remembered on the source meshes for later runs."""
        values = {}
        missing = []
        for ob in mesh_objects:
            stored = ob.get(meshes.REST_MORPHS_PROP)
            if stored is not None:
                values[ob.name] = {k: float(v) for k, v in stored.items()}
            elif ob.data.shape_keys is not None:
                missing.append(ob)
        if missing:
            fresh = meshes.read_rest_morphs(self.context, self.rig, missing)
            for ob in missing:
                vals = fresh.get(ob.name, {})
                ob[meshes.REST_MORPHS_PROP] = vals
                values[ob.name] = vals
        return values

    def refresh_rest_morphs(self, mesh_objects):
        for ob in mesh_objects:
            if meshes.REST_MORPHS_PROP in ob:
                del ob[meshes.REST_MORPHS_PROP]

    # ------------------------------------------------------------------
    #   export
    # ------------------------------------------------------------------

    def character_path(self):
        os.makedirs(self.settings.export_dir, exist_ok=True)
        return os.path.join(self.settings.export_dir, safe_filename(self.settings.character_name) + ".fbx")

    def animation_path(self, anim_name):
        os.makedirs(self.settings.export_dir, exist_ok=True)
        name = "%s_%s" % (self.settings.character_name, anim_name)
        return os.path.join(self.settings.export_dir, safe_filename(name) + ".fbx")

    def export_character(self):
        path = self.character_path()
        objects = [self.export_rig] + self.export_meshes
        self.export_rig.data.pose_position = 'REST'
        try:
            fbx_io.export(self.context, path, objects, self.export_rig, animation=False,
                          embed_textures=self.settings.embed_textures,
                          centimeters=self.settings.units_x100)
        finally:
            self.export_rig.data.pose_position = 'POSE'
        json_path = None
        if self.settings.write_retarget_json:
            json_path = retarget_json.write(path, self.plan, self.settings, self.export_rig)
        return path, json_path

    def bake(self, frames, name, progress=None, start_at_zero=False):
        """Bake frames of the current source animation onto the export objects."""
        baker = bake.Baker(self.rig, self.export_rig, self.plan, self.settings.unit_scale,
                           root_motion=self.settings.root_motion,
                           animate_ik=self.settings.animate_ik_bones)
        morph_pairs = self.mesh_pairs if self.settings.export_morphs else []
        hidden = [self.export_rig] + self.export_meshes
        with bake.HideObjects(hidden), bake.MuteSourceModifiers(meshes.bound_meshes(self.rig)):
            bones, obj, morphs = bake.sample(self.context, baker, frames, morph_pairs,
                                             self.rest_values, progress)
        stretch, bone, frame = baker.max_scale
        if stretch > 0.01:
            self.warnings.append(
                "%s: bone %s is scaled %.0f%% at frame %d (stretchy MHX limbs?). Unreal cannot "
                "reproduce scaled parents exactly; convert without stretch or keep IK in reach."
                % (name, bone, stretch * 100.0, frame))
        key_frames = [f - frames[0] for f in frames] if start_at_zero else frames
        rig_action = bake.write_rig_action(self.export_rig, name, key_frames, bones, obj)
        actions = [rig_action] + bake.write_morph_actions(name, key_frames, morphs)
        for action in actions:
            action[EXPORT_TAG] = True
        self.created_actions.extend(actions)
        return rig_action

    def clear_baked(self):
        for action in self.created_actions:
            if action.name in bpy.data.actions:
                bpy.data.actions.remove(action)
        self.created_actions = []
        if self.export_rig.animation_data:
            self.export_rig.animation_data.action = None
        self.export_rig.location = (0.0, 0.0, 0.0)
        self.export_rig.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        for pbone in self.export_rig.pose.bones:
            pbone.matrix_basis = Matrix.Identity(4)
        for ob in self.export_meshes:
            key = ob.data.shape_keys
            if key is not None and key.animation_data:
                key.animation_data.action = None

    def export_animation(self, anim_name, frames, progress=None):
        scene = self.context.scene
        self.bake(frames, anim_name, progress, start_at_zero=True)
        path = self.animation_path(anim_name)
        objects = [self.export_rig]
        if self.settings.anim_include_meshes:
            objects += self.export_meshes
        scene.frame_start, scene.frame_end = 0, len(frames) - 1
        sources = [self.rig] + meshes.bound_meshes(self.rig)
        skin_mods = [(mod, mod.show_viewport) for ob in self.export_meshes for mod in ob.modifiers]
        # the FBX take (and so the Unreal AnimSequence) is named after the scene
        scene_name = scene.name
        take_name = safe_filename("%s_%s" % (self.settings.character_name, anim_name))
        try:
            if take_name not in bpy.data.scenes:
                scene.name = take_name
            for mod, _state in skin_mods:
                mod.show_viewport = False
            with bake.HideObjects(sources):
                fbx_io.export(self.context, path, objects, self.export_rig, animation=True,
                              embed_textures=False, centimeters=self.settings.units_x100)
        finally:
            scene.name = scene_name
            for mod, state in skin_mods:
                mod.show_viewport = state
        if not self.settings.keep_export_objects:
            self.clear_baked()
        return path

    # ------------------------------------------------------------------
    #   animation sources
    # ------------------------------------------------------------------

    def use_action(self, action):
        """Make an action the only animation of the source rig."""
        ad = self.rig.animation_data or self.rig.animation_data_create()
        if getattr(ad, "use_tweak_mode", False):
            raise ExportError("Exit NLA tweak mode on %s before exporting actions." % self.rig.name)
        ad.use_nla = False
        assign_action(self.rig, action, action_slot_for(action, 'OBJECT', self.rig))


def timeline_frames(scene):
    if scene.use_preview_range:
        return bake.frame_list(scene.frame_preview_start, scene.frame_preview_end)
    return bake.frame_list(scene.frame_start, scene.frame_end)


def action_frames(action):
    start, end = action.frame_range
    return bake.frame_list(int(round(start)), int(round(end)))


def rig_actions(rig):
    """Actions that animate bones or properties of this rig."""
    bone_names = set(rig.data.bones.keys())
    out = []
    for action in bpy.data.actions:
        if action.get(EXPORT_TAG):
            continue
        slots = getattr(action, "slots", None)
        if slots is not None and len(slots) and not any(
                getattr(s, "target_id_type", 'OBJECT') in ('OBJECT', 'UNSPECIFIED') for s in slots):
            continue
        for fc in _fcurves(action):
            path = fc.data_path
            if path.startswith('pose.bones["'):
                bone = path[len('pose.bones["'):].split('"]', 1)[0]
                if bone in bone_names:
                    out.append(action)
                    break
    return out


def _fcurves(action):
    from .anim_io import iter_fcurves
    return iter_fcurves(action)
