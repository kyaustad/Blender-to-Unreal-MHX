# SPDX-FileCopyrightText: 2026 Kyle Austad
# SPDX-License-Identifier: GPL-2.0-or-later
"""FBX export with Unreal-friendly settings.

With "Units x100" the export objects are built in centimeters and the scene
unit scale is set to 0.01 for the duration of the export. The FBX file then
has a unit factor of 1 cm and no scale anywhere in the hierarchy: the root
bone, every bone and every animation curve come in at scale 1 in Unreal,
which is what IK Rig retargeting against Manny/Quinn expects.
"""

import bpy


class UnitScale:
    def __init__(self, scene, scale_length):
        self.scene = scene
        self.scale_length = scale_length
        self.saved = None

    def __enter__(self):
        us = self.scene.unit_settings
        self.saved = (us.system, us.scale_length)
        if self.scale_length is not None:
            us.system = 'METRIC'
            us.scale_length = self.scale_length
        return self

    def __exit__(self, *_exc):
        us = self.scene.unit_settings
        # restoring the system first: changing it can reset the other fields
        us.system = self.saved[0]
        try:
            us.scale_length = self.saved[1]
        except (AttributeError, TypeError):
            pass
        return False


def _operator_properties():
    try:
        return {p.identifier for p in bpy.ops.export_scene.fbx.get_rna_type().properties}
    except Exception:
        return None


def export(context, filepath, objects, active, animation=False, embed_textures=False,
           centimeters=True):
    view_layer = context.view_layer
    for ob in view_layer.objects:
        ob.select_set(False)
    for ob in objects:
        ob.select_set(True)
    view_layer.objects.active = active

    kwargs = dict(
        filepath=filepath,
        check_existing=False,
        use_selection=True,
        use_visible=False,
        use_active_collection=False,
        object_types={'ARMATURE', 'MESH'},
        use_custom_props=False,
        global_scale=1.0,
        apply_unit_scale=True,
        apply_scale_options='FBX_SCALE_NONE',
        use_space_transform=True,
        bake_space_transform=False,
        axis_forward='-Z',
        axis_up='Y',
        use_mesh_modifiers=False,
        use_mesh_modifiers_render=False,
        mesh_smooth_type='FACE',
        use_subsurf=False,
        use_mesh_edges=False,
        use_tspace=False,
        use_triangles=False,
        use_armature_deform_only=True,
        add_leaf_bones=False,
        primary_bone_axis='Y',
        secondary_bone_axis='X',
        armature_nodetype='NULL',
        bake_anim=animation,
        bake_anim_use_all_bones=True,
        bake_anim_use_nla_strips=False,
        bake_anim_use_all_actions=False,
        bake_anim_force_startend_keying=True,
        bake_anim_step=1.0,
        bake_anim_simplify_factor=0.0,
        path_mode='COPY' if embed_textures else 'AUTO',
        embed_textures=embed_textures,
        batch_mode='OFF',
        use_metadata=True,
    )
    available = _operator_properties()
    if available is not None:
        kwargs = {k: v for k, v in kwargs.items() if k in available}

    # objects are already built in centimeters: 1 Blender unit = 1 cm in the file
    with UnitScale(context.scene, 0.01 if centimeters else None):
        result = bpy.ops.export_scene.fbx(**kwargs)
    if 'FINISHED' not in result:
        raise RuntimeError("FBX export failed for %s" % filepath)
