# SPDX-FileCopyrightText: 2026 Kyle Austad
# SPDX-License-Identifier: GPL-2.0-or-later
"""Build the clean Unreal export armature from a plan."""

import bpy
from mathutils import Matrix, Vector

from . import orient
from .rig_map import ROOT_NAME, SourceBone


def source_bones(rig):
    """rig_map.SourceBone description of every bone of an armature."""
    return {
        b.name: SourceBone(
            b.name,
            b.parent.name if b.parent else None,
            b.use_deform,
            tuple(b.head_local),
            tuple(b.tail_local),
        )
        for b in rig.data.bones
    }


def _palm_normals(plan):
    normals = {}
    for side in ("l", "r"):
        hand = plan.get("hand_%s" % side)
        index = plan.get("index_01_%s" % side) or plan.get("index_metacarpal_%s" % side)
        pinky = plan.get("pinky_01_%s" % side) or plan.get("pinky_metacarpal_%s" % side)
        if hand and index and pinky:
            normals[side] = orient.palm_normal(hand.head, hand.aim, index.head, pinky.head)
    return normals


def rest_matrices(plan, source_rig, mannequin_axes):
    """Rest matrix (armature space, meters) and length of every export bone."""
    src_bones = source_rig.data.bones
    palms = _palm_normals(plan)
    rests = {}
    for pb in plan.bones:
        head = Vector(pb.head)
        aim = Vector(pb.aim) if pb.aim is not None else head + Vector((0.0, 0.05, 0.0))
        length = max((aim - head).length, 0.005)
        if pb.kind == "ik_root":
            rot = Matrix.Identity(3)
        elif pb.kind == "ik_copy":
            base, length = rests[pb.copy_of]
            rot = base.to_3x3()
            head = base.translation.copy()
        elif mannequin_axes and pb.kind in orient.MANNEQUIN_KINDS:
            rot = orient.mannequin_frame(pb.kind, pb.side, head, aim, palms.get(pb.side))
        else:
            rot = src_bones[pb.source].matrix_local.to_3x3()
            if pb.kind == "keep":
                length = src_bones[pb.source].length
        mat = rot.to_4x4()
        mat.translation = head
        rests[pb.name] = (mat, length)
    return rests


def build_armature(context, plan, source_rig, collection, unit_scale, mannequin_axes,
                   data_name="Skeleton"):
    """Create the export armature object (named ROOT_NAME) in edit mode.

    Returns the object. Bone rest matrices are read back from the object
    afterwards so the bake works with exactly what Blender stored.
    """
    rests = rest_matrices(plan, source_rig, mannequin_axes)
    arm = bpy.data.armatures.new(data_name)
    arm.display_type = 'STICK'
    rig = bpy.data.objects.new(ROOT_NAME, arm)
    collection.objects.link(rig)
    rig.show_in_front = True

    view_layer = context.view_layer
    for ob in view_layer.objects:
        ob.select_set(False)
    view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        ebones = arm.edit_bones
        for pb in plan.bones:
            mat, length = rests[pb.name]
            eb = ebones.new(pb.name)
            eb.head = (0.0, 0.0, 0.0)
            eb.tail = (0.0, 1.0, 0.0)
            scaled = mat.copy()
            scaled.translation = mat.translation * unit_scale
            eb.matrix = scaled
            eb.length = length * unit_scale
            eb.use_deform = True
            eb.use_connect = False
            eb.inherit_scale = 'FULL'
            eb.use_local_location = True
            eb.use_inherit_rotation = True
            if pb.parent:
                eb.parent = ebones[pb.parent]
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')

    for pbone in rig.pose.bones:
        pbone.rotation_mode = 'QUATERNION'
    rig["UnrealMhxExport"] = True
    return rig
