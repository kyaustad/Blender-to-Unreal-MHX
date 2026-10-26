# SPDX-FileCopyrightText: 2026 Kyle Austad
# SPDX-License-Identifier: GPL-2.0-or-later
"""Sample the evaluated MHX rig and bake it onto the export skeleton.

For an export bone E driven by source bone S (armature space, rest R, pose P):

    P_E = P_S @ R_S^-1 @ R_E

which deforms the skin exactly like S does, whatever rest orientation or
hierarchy E has. Everything is evaluated in the source armature space and
converted to the export unit scale by conjugating with a uniform scale.
"""

import numpy as np
from mathutils import Matrix, Quaternion

from .anim_io import ActionWriter


class MuteSourceModifiers:
    """Temporarily disable mesh modifiers on the source meshes while sampling.

    Shape-key drivers still evaluate, but the costly armature deform and
    subdivision of a DAZ character are skipped.
    """

    def __init__(self, meshes):
        self.saved = [(mod, mod.show_viewport) for ob in meshes for mod in ob.modifiers]

    def __enter__(self):
        for mod, _state in self.saved:
            mod.show_viewport = False
        return self

    def __exit__(self, *_exc):
        for mod, state in self.saved:
            mod.show_viewport = state
        return False


class HideObjects:
    def __init__(self, objects):
        self.saved = [(ob, ob.hide_viewport) for ob in objects]

    def __enter__(self):
        for ob, _state in self.saved:
            ob.hide_viewport = True
        return self

    def __exit__(self, *_exc):
        for ob, state in self.saved:
            ob.hide_viewport = state
        return False


class Baker:
    def __init__(self, source, export_rig, plan, unit_scale, root_motion=True,
                 animate_ik=True):
        self.source = source
        self.export_rig = export_rig
        self.plan = plan
        self.u = unit_scale
        self.animate_ik = animate_ik
        self.scale = Matrix.Scale(unit_scale, 4)
        self.scale_inv = Matrix.Scale(1.0 / unit_scale, 4)
        src_bones = source.data.bones
        self.src_rest_inv = {
            pb.source: src_bones[pb.source].matrix_local.inverted()
            for pb in plan.bones if pb.source
        }
        self.master = None
        if root_motion and plan.root_motion_source in src_bones:
            self.master = plan.root_motion_source
            self.master_rest_inv = src_bones[self.master].matrix_local.inverted()
        self.world0_inv = source.matrix_world.inverted()

        ebones = export_rig.data.bones
        self.order = [pb for pb in plan.bones if pb.name in ebones]
        self.rest = {pb.name: ebones[pb.name].matrix_local.copy() for pb in self.order}
        self.rest_inv = {name: m.inverted() for name, m in self.rest.items()}
        self.parent = {pb.name: (ebones[pb.name].parent.name if ebones[pb.name].parent else None)
                       for pb in self.order}

    def pose_matrices(self, depsgraph):
        """Export-armature-space pose matrices for the current frame."""
        ev = self.source.evaluated_get(depsgraph)
        pbones = ev.pose.bones
        root = Matrix.Identity(4)
        if self.master:
            root = pbones[self.master].matrix @ self.master_rest_inv
        root_inv = root.inverted_safe()
        to_cm = self.scale
        from_cm = self.scale_inv
        poses = {}
        for pb in self.order:
            if pb.source:
                deform = root_inv @ pbones[pb.source].matrix @ self.src_rest_inv[pb.source]
                poses[pb.name] = to_cm @ deform @ from_cm @ self.rest[pb.name]
            elif pb.copy_of and self.animate_ik and pb.copy_of in poses:
                poses[pb.name] = poses[pb.copy_of]
            elif self.parent[pb.name] and self.parent[pb.name] in poses:
                par = self.parent[pb.name]
                poses[pb.name] = poses[par] @ self.rest_inv[par] @ self.rest[pb.name]
            else:
                poses[pb.name] = self.rest[pb.name]
        world = self.world0_inv @ ev.matrix_world @ root
        return poses, to_cm @ world @ from_cm

    def local_transforms(self, poses):
        out = {}
        inv_cache = {}
        for pb in self.order:
            name = pb.name
            par = self.parent[name]
            if par:
                pinv = inv_cache.get(par)
                if pinv is None:
                    pinv = inv_cache[par] = poses[par].inverted_safe()
                basis = self.rest_inv[name] @ self.rest[par] @ pinv @ poses[name]
            else:
                basis = self.rest_inv[name] @ poses[name]
            out[name] = basis.decompose()
        return out


def frame_list(frame_start, frame_end):
    if frame_end < frame_start:
        frame_start, frame_end = frame_end, frame_start
    return list(range(int(frame_start), int(frame_end) + 1))


def sample(context, baker, frames, morph_sources=(), rest_values=None, progress=None):
    """Evaluate every frame once; return bone channels, object channels, morph values.

    morph_sources -- list of (source mesh, export mesh) pairs with shape keys
    """
    scene = context.scene
    rest_values = rest_values or {}
    bones = {pb.name: ([], [], []) for pb in baker.order}
    obj = ([], [])
    morphs = []
    for src, dst in morph_sources:
        key = src.data.shape_keys
        names = [kb.name for kb in key.key_blocks]
        offsets = np.array([rest_values.get(src.name, {}).get(n, 0.0) for n in names])
        morphs.append([src, dst, names, offsets, []])

    prev_quat = {}
    prev_obj_quat = None
    baker.max_scale = (0.0, None, None)
    for i, frame in enumerate(frames):
        scene.frame_set(frame)
        depsgraph = context.evaluated_depsgraph_get()
        poses, object_matrix = baker.pose_matrices(depsgraph)
        for name, (loc, quat, scl) in baker.local_transforms(poses).items():
            stretch = max(abs(s - 1.0) for s in scl)
            if stretch > baker.max_scale[0]:
                baker.max_scale = (stretch, name, frame)
            last = prev_quat.get(name)
            if last is not None and last.dot(quat) < 0.0:
                quat.negate()
            prev_quat[name] = quat
            chan = bones[name]
            chan[0].append(loc)
            chan[1].append(quat)
            chan[2].append(scl)
        loc, quat, _scl = object_matrix.decompose()
        if prev_obj_quat is not None and prev_obj_quat.dot(quat) < 0.0:
            quat.negate()
        prev_obj_quat = quat
        obj[0].append(loc)
        obj[1].append(quat)
        for entry in morphs:
            src, _dst, names, offsets, rows = entry
            blocks = src.data.shape_keys.key_blocks
            row = np.empty(len(names))
            blocks.foreach_get("value", row)
            rows.append(row - offsets)
        if progress:
            progress(i, len(frames))
    out_morphs = []
    for src, dst, names, _offsets, rows in morphs:
        table = np.array(rows).T if rows else np.zeros((len(names), 0))
        out_morphs.append((src, dst, names[1:], table[1:]))
    return bones, obj, out_morphs


def _varies(values, ref, eps=1e-5):
    return any(abs(v - ref) > eps for v in values)


def write_rig_action(export_rig, name, frames, bones, obj):
    writer = ActionWriter(name, 'OBJECT', export_rig.name)
    for bone_name, (locs, quats, scales) in bones.items():
        base = 'pose.bones["%s"].' % bone_name
        for axis in range(3):
            writer.curve(base + "location", axis, frames, [v[axis] for v in locs])
        for axis in range(4):
            writer.curve(base + "rotation_quaternion", axis, frames, [q[axis] for q in quats])
        for axis in range(3):
            vals = [s[axis] for s in scales]
            if _varies(vals, 1.0):
                writer.curve(base + "scale", axis, frames, vals)
    locs, quats = obj
    identity = Quaternion()
    moving = any(v.length > 1e-4 for v in locs) or any(
        abs(abs(q.dot(identity)) - 1.0) > 1e-7 for q in quats)
    if moving:
        export_rig.rotation_mode = 'QUATERNION'
        for axis in range(3):
            writer.curve("location", axis, frames, [v[axis] for v in locs])
        for axis in range(4):
            writer.curve("rotation_quaternion", axis, frames, [q[axis] for q in quats])
    writer.assign(export_rig)
    return writer.action


def write_morph_actions(name, frames, morphs):
    actions = []
    for _src, dst, names, table in morphs:
        key = dst.data.shape_keys
        if key is None:
            continue
        animated = [(n, vals.tolist()) for n, vals in zip(names, table)
                    if n in key.key_blocks and np.abs(vals).max(initial=0.0) > 1e-5]
        if not animated:
            continue
        writer = ActionWriter("%s_%s" % (name, dst.name), 'KEY', key.name)
        for shape, vals in animated:
            writer.curve('key_blocks["%s"].value' % shape.replace('"', '\\"'), 0, frames, vals)
        writer.assign(key)
        actions.append(writer.action)
    return actions
