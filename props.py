# SPDX-FileCopyrightText: 2026 Kyle Austad
# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


class UNREAL_MHX_PG_mesh_item(PropertyGroup):
    name: StringProperty(name="Object")
    export: BoolProperty(name="Export", default=True)


class UNREAL_MHX_PG_action_item(PropertyGroup):
    name: StringProperty(name="Action")
    export: BoolProperty(name="Export", default=True)


class UNREAL_MHX_PG_settings(PropertyGroup):
    character_name: StringProperty(
        name="Character Name",
        description="Name of the exported skeletal mesh (FBX file name)",
        default="Character",
    )
    export_dir: StringProperty(
        name="Export Folder",
        subtype='DIR_PATH',
        default="//UnrealExport/",
    )

    # skeleton
    include_face: BoolProperty(
        name="Face Bones",
        description="Export facial deform bones (eyes, jaw, tongue, lips, brows ...). "
                    "Disabled: their weights are merged into the head",
        default=True,
    )
    include_toes: BoolProperty(
        name="Toe Bones",
        description="Export individual toe and metatarsal bones. Disabled: merged into foot/ball",
        default=True,
    )
    include_extra: BoolProperty(
        name="Extra Bones",
        description="Export other weighted deform bones (breasts, geografts, props ...). "
                    "Disabled: merged into their nearest exported parent",
        default=True,
    )
    mannequin_axes: BoolProperty(
        name="Mannequin Axes",
        description="Orient humanoid bones like the UE5 Mannequin (as Auto-Rig Pro does). "
                    "Needed for Control Rig / Modular Rig setups that assume Manny's axes. "
                    "Skinning is unaffected either way",
        default=True,
    )
    add_ik_bones: BoolProperty(
        name="IK Bones",
        description="Add ik_foot_root, ik_foot_l/r, ik_hand_root, ik_hand_gun, ik_hand_l/r",
        default=True,
    )
    animate_ik_bones: BoolProperty(
        name="Animated IK Bones",
        description="IK bones follow the feet and hands in exported animations, like Manny's",
        default=True,
    )
    root_motion: BoolProperty(
        name="Root Motion",
        description="Bake the MHX 'master' bone (and rig object) motion onto the root bone",
        default=True,
    )

    # meshes
    export_morphs: BoolProperty(
        name="Morph Targets",
        description="Export shape keys as morph targets and bake their animation as curves",
        default=True,
    )
    bake_rest_morphs: BoolProperty(
        name="Bake Rest Morphs",
        description="Shape keys that are non-zero in the rest pose (dialed body/face shapes) are "
                    "baked into the exported mesh so the character looks the same in Unreal with "
                    "all morph targets at 0. Animation curves are exported relative to that",
        default=True,
    )
    max_influences: IntProperty(
        name="Max Influences",
        description="Bone influences kept per vertex (strongest first, renormalized). DAZ figures "
                    "use up to ~20; Unreal keeps at most 12, so 12 matches Unreal exactly. "
                    "Use 8 or 4 for game/mobile budgets. 0 = keep all",
        default=12,
        min=0,
        max=16,
    )
    embed_textures: BoolProperty(
        name="Embed Textures",
        description="Copy and embed textures in the character FBX",
        default=False,
    )

    # animation
    anim_source: EnumProperty(
        name="Animation",
        items=(
            ('TIMELINE', "Timeline", "Export the scene frame range as it plays (actions, NLA, drivers)"),
            ('ACTIONS', "Actions", "Export each checked action of the MHX rig to its own FBX"),
        ),
        default='TIMELINE',
    )
    anim_name: StringProperty(
        name="Animation Name",
        description="File suffix for timeline exports (Character_<name>.fbx). "
                    "Empty: use the active action name",
        default="",
    )
    anim_include_meshes: BoolProperty(
        name="Include Meshes",
        description="Include the meshes in animation FBX files so morph target curves are imported",
        default=True,
    )

    # advanced
    units_x100: BoolProperty(
        name="Units x100",
        description="Export in centimeters with no scale on the root (Auto-Rig Pro default). "
                    "Required for correct retargeting in Unreal",
        default=True,
    )
    write_retarget_json: BoolProperty(
        name="Skeleton JSON",
        description="Write <Character>_Skeleton.json for the Unreal setup script",
        default=True,
    )
    keep_export_objects: BoolProperty(
        name="Keep Export Objects",
        description="Keep the generated 'root' armature and _UE meshes in the scene for inspection",
        default=False,
    )

    mesh_items: CollectionProperty(type=UNREAL_MHX_PG_mesh_item)
    mesh_index: IntProperty()
    action_items: CollectionProperty(type=UNREAL_MHX_PG_action_item)
    action_index: IntProperty()


def get_settings(context):
    return context.scene.unreal_mhx


classes = (
    UNREAL_MHX_PG_mesh_item,
    UNREAL_MHX_PG_action_item,
    UNREAL_MHX_PG_settings,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.unreal_mhx = PointerProperty(type=UNREAL_MHX_PG_settings)


def unregister():
    del bpy.types.Scene.unreal_mhx
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
