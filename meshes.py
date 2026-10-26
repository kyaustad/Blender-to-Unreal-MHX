# SPDX-FileCopyrightText: 2026 Kyle Austad
# SPDX-License-Identifier: GPL-2.0-or-later
"""Collect, copy and re-skin the character meshes for export."""

import bpy
import numpy as np
from mathutils import Matrix

REST_MORPHS_PROP = "UnrealMhxRestMorphs"


def armature_modifier(ob, rig):
    for mod in ob.modifiers:
        if mod.type == 'ARMATURE' and mod.object == rig:
            return mod
    return None


def bound_meshes(rig):
    """Meshes deformed by, or parented to, the rig."""
    out = []
    for ob in bpy.data.objects:
        if ob.type != 'MESH' or ob.data is None or len(ob.data.vertices) == 0:
            continue
        if armature_modifier(ob, rig) or ob.parent == rig:
            out.append(ob)
    out.sort(key=lambda ob: ob.name)
    return out


def is_rigid(ob, rig):
    return armature_modifier(ob, rig) is None and ob.parent == rig


def weighted_groups(ob):
    """Names of vertex groups with any non-zero weight."""
    used = set()
    for v in ob.data.vertices:
        for g in v.groups:
            if g.weight > 1e-6:
                used.add(g.group)
    names = {vg.index: vg.name for vg in ob.vertex_groups}
    return {names[i] for i in used if i in names}


def rest_world_matrix(ob, rig):
    """World matrix of a mesh with the rig in its rest pose."""
    if ob.parent == rig and ob.parent_type == 'BONE' and ob.parent_bone in rig.data.bones:
        bone = rig.data.bones[ob.parent_bone]
        tail = Matrix.Translation((0.0, bone.length, 0.0))
        return rig.matrix_world @ bone.matrix_local @ tail @ ob.matrix_parent_inverse @ ob.matrix_basis
    return ob.matrix_world.copy()


def _key_array(kb, count):
    arr = np.empty(count * 3, dtype=np.float32)
    kb.data.foreach_get("co", arr)
    return arr


def read_rest_morphs(context, rig, meshes):
    """Shape-key values with the rig in rest pose, per mesh (non-zero only)."""
    old = rig.data.pose_position
    rig.data.pose_position = 'REST'
    context.view_layer.update()
    try:
        values = {}
        for ob in meshes:
            key = ob.data.shape_keys
            if key is None:
                continue
            vals = {kb.name: kb.value for kb in key.key_blocks[1:]
                    if not kb.mute and abs(kb.value) > 1e-5}
            values[ob.name] = vals
    finally:
        rig.data.pose_position = old
        context.view_layer.update()
    return values


def _group_weights(ob, name, count):
    vg = ob.vertex_groups.get(name)
    weights = np.zeros(count, dtype=np.float32)
    if vg is None:
        return weights
    index = vg.index
    for v in ob.data.vertices:
        for g in v.groups:
            if g.group == index:
                weights[v.index] = g.weight
                break
    return weights


def bake_rest_morphs(ob, rest_values):
    """Fold non-zero rest morph values into the base shape of a mesh copy.

    Every key is offset by the same delta, so morph target deltas stay
    unchanged. Returns {name: value} actually baked.
    """
    me = ob.data
    key = me.shape_keys
    if key is None or not rest_values:
        return {}
    count = len(me.vertices)
    delta = np.zeros(count * 3, dtype=np.float32)
    baked = {}
    cache = {}

    def coords(kb):
        if kb.name not in cache:
            cache[kb.name] = _key_array(kb, count)
        return cache[kb.name]

    for kb in key.key_blocks[1:]:
        value = rest_values.get(kb.name, 0.0)
        if abs(value) < 1e-5 or kb.relative_key == kb:
            continue
        d = (coords(kb) - coords(kb.relative_key)) * value
        if kb.vertex_group:
            d *= np.repeat(_group_weights(ob, kb.vertex_group, count), 3)
        delta += d
        baked[kb.name] = value
    if not baked:
        return {}
    for kb in key.key_blocks:
        arr = _key_array(kb, count) + delta
        kb.data.foreach_set("co", arr)
    basis = _key_array(key.key_blocks[0], count)
    me.vertices.foreach_set("co", basis)
    me.update()
    return baked


def remap_vertex_groups(ob, weight_map):
    """Rename/merge vertex groups to export bone names; drop the rest."""
    # Blender hands out a new Python wrapper on every access, so groups are
    # tracked by name, never by identity.
    by_target = {}
    for vg in ob.vertex_groups:
        target = weight_map.get(vg.name)
        if target:
            by_target.setdefault(target, []).append(vg.name)

    groups = ob.vertex_groups
    merges = {t: names for t, names in by_target.items() if len(names) > 1}
    if merges:
        index_keep = {}
        for names in merges.values():
            for name in names[1:]:
                index_keep[groups[name].index] = names[0]
        adds = {}
        for v in ob.data.vertices:
            for g in v.groups:
                keep = index_keep.get(g.group)
                if keep is not None and g.weight > 0.0:
                    adds[(keep, v.index)] = adds.get((keep, v.index), 0.0) + g.weight
        for (name, index), weight in adds.items():
            groups[name].add([index], weight, 'ADD')

    keep_names = {names[0]: target for target, names in by_target.items()}
    for name in [vg.name for vg in groups if vg.name not in keep_names]:
        groups.remove(groups[name])
    for i, name in enumerate(list(keep_names)):
        groups[name].name = "__umhx_tmp_%04d" % i
    for i, target in enumerate(keep_names.values()):
        groups["__umhx_tmp_%04d" % i].name = target


def make_export_mesh(context, src, rig, export_rig, plan, collection, unit_scale,
                     rest_values=None):
    """Copy a source mesh into export space, skinned to the export rig.

    Returns (object, info dict).
    """
    info = {"source": src.name, "baked_morphs": {}, "rigid_bone": None, "ignored_modifiers": [],
            "preserve_volume": False, "unweighted": 0}
    ob = src.copy()
    ob.data = src.data.copy()
    ob.name = src.name + "_UE"
    ob.animation_data_clear()
    for coll in list(ob.users_collection):
        coll.objects.unlink(ob)
    collection.objects.link(ob)

    rigid = is_rigid(src, rig)
    to_export = (Matrix.Scale(unit_scale, 4)
                 @ rig.matrix_world.inverted()
                 @ rest_world_matrix(src, rig))
    ob.parent = None
    ob.matrix_world = Matrix.Identity(4)
    ob.data.transform(to_export, shape_keys=True)
    if to_export.is_negative:
        ob.data.flip_normals()

    info["ignored_modifiers"] = sorted({m.type for m in ob.modifiers if m.type != 'ARMATURE'})
    src_mod = armature_modifier(src, rig)
    info["preserve_volume"] = bool(src_mod is not None and src_mod.use_deform_preserve_volume)
    ob.modifiers.clear()
    ob.constraints.clear()

    key = ob.data.shape_keys
    if key is not None:
        key.animation_data_clear()
        if rest_values:
            info["baked_morphs"] = bake_rest_morphs(ob, rest_values)
        values = [0.0] * len(key.key_blocks)
        key.key_blocks.foreach_set("value", values)

    if rigid:
        target = plan.resolve(src.parent_bone) if src.parent_type == 'BONE' else "pelvis"
        info["rigid_bone"] = target
        for vg in list(ob.vertex_groups):
            ob.vertex_groups.remove(vg)
        vg = ob.vertex_groups.new(name=target)
        vg.add(list(range(len(ob.data.vertices))), 1.0, 'REPLACE')
    else:
        remap_vertex_groups(ob, plan.weight_map)

    ob.parent = export_rig
    ob.matrix_parent_inverse = Matrix.Identity(4)
    mod = ob.modifiers.new("Armature", 'ARMATURE')
    mod.object = export_rig
    mod.use_vertex_groups = True
    mod.use_bone_envelopes = False
    mod.use_deform_preserve_volume = False

    info["unweighted"] = sum(1 for v in ob.data.vertices if not v.groups)
    return ob, info


def summarize(infos):
    """One warning per kind of problem across all exported meshes."""
    out = []
    dqs = [i["source"] for i in infos if i["preserve_volume"]]
    if dqs:
        out.append("Preserve Volume skinning is on for %s. Unreal skins linearly, so shoulders and "
                   "elbows differ slightly from Blender; turn it off on the Armature modifier to "
                   "preview the Unreal result." % ", ".join(dqs))
    mods = sorted({m for i in infos for m in i["ignored_modifiers"]})
    if mods:
        out.append("Ignored mesh modifiers (not exported): %s." % ", ".join(mods))
    for i in infos:
        if i["unweighted"]:
            out.append("%s: %d vertices have no bone weights; they stay at the root in Unreal."
                       % (i["source"], i["unweighted"]))
    baked = sorted({name for i in infos for name in i["baked_morphs"]})
    if baked:
        out.append("Baked %d non-zero rest morph(s) into the mesh: %s%s" % (
            len(baked), ", ".join(baked[:6]), " ..." if len(baked) > 6 else ""))
    return out


def limit_influences(ob, limit):
    """Keep the strongest `limit` weights per vertex and renormalize them."""
    if limit <= 0:
        return 0
    removals = {}
    renormalize = []
    for v in ob.data.vertices:
        weights = sorted(((g.weight, g.group) for g in v.groups if g.weight > 0.0), reverse=True)
        if len(weights) <= limit:
            continue
        keep = weights[:limit]
        total = sum(w for w, _g in keep)
        for _w, group in weights[limit:]:
            removals.setdefault(group, []).append(v.index)
        if total > 0.0:
            renormalize.append((v.index, [(group, w / total) for w, group in keep]))
    by_index = {vg.index: vg for vg in ob.vertex_groups}
    for group, verts in removals.items():
        by_index[group].remove(verts)
    for index, pairs in renormalize:
        for group, weight in pairs:
            by_index[group].add([index], weight, 'REPLACE')
    return len(renormalize)
