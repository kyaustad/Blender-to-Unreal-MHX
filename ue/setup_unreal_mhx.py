# SPDX-FileCopyrightText: 2026 Kyle Austad
# SPDX-License-Identifier: GPL-2.0-or-later
"""Unreal MHX - Unreal Editor setup script (UE 5.6 / 5.7, best effort on 5.4+).

Creates for a character exported with the Unreal MHX Blender add-on:

* IK_<Character>        IK Rig: retarget root, chains, IK goals, Full Body IK
* RTG_<Source>_To_<Character>   IK Retargeter from the Mannequin IK Rig

Usage
-----
1. Enable the plugins "Python Editor Script Plugin" and "IK Rig" (restart).
2. Import <Character>.fbx as a Skeletal Mesh (see the add-on README for settings).
3. Edit the CONFIG block below, then run this file with
   Tools > Execute Python Script...  (or  py "C:/path/setup_unreal_mhx.py"  in the
   Output Log Cmd box).

Re-running is safe: existing IK_/RTG_ assets are updated in place.
"""

import json
import os

import unreal

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
# <Character>_Skeleton.json written next to the FBX by the Blender add-on
SKELETON_JSON = r""

# Content path of the imported skeletal mesh, e.g. "/Game/Characters/Violetta/Violetta".
# Empty: look for a SkeletalMesh named like the character in the JSON.
SKELETAL_MESH = ""

# IK Rig to retarget animation FROM. UE5 Mannequin (Manny/Quinn) by default.
SOURCE_IK_RIG = "/Game/Characters/Mannequins/Rigs/IK_Mannequin"

# Where to create the IK Rig / Retargeter. Empty: "<mesh folder>/Rigs".
OUTPUT_FOLDER = ""

# Prefer Unreal's own auto-characterization (recognises Mannequin-named
# skeletons) and only use the JSON chains when it is unavailable or fails.
USE_UE_AUTO_CHARACTERIZE = True
# ---------------------------------------------------------------------------

asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary


def log(msg):
    unreal.log("[Unreal MHX] " + msg)


def warn(msg):
    unreal.log_warning("[Unreal MHX] " + msg)


def attempt(desc, fn, *args, **kwargs):
    """Call a possibly version-specific API; log and return None on failure."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - editor API differences across versions
        warn("%s failed: %s" % (desc, exc))
        return None


def load_profile():
    if not SKELETON_JSON or not os.path.isfile(SKELETON_JSON):
        raise RuntimeError("Set SKELETON_JSON to the <Character>_Skeleton.json written by Blender.")
    with open(SKELETON_JSON, "r", encoding="utf-8") as handle:
        profile = json.load(handle)
    if profile.get("format") != "unreal_mhx_skeleton":
        raise RuntimeError("%s is not an Unreal MHX skeleton file." % SKELETON_JSON)
    return profile


def find_skeletal_mesh(name):
    if SKELETAL_MESH:
        mesh = EAL.load_asset(SKELETAL_MESH)
        if mesh is None:
            raise RuntimeError("Skeletal mesh not found: %s" % SKELETAL_MESH)
        return mesh
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    flt = unreal.ARFilter(class_paths=[unreal.TopLevelAssetPath("/Script/Engine", "SkeletalMesh")],
                          package_paths=["/Game"], recursive_paths=True)
    for data in registry.get_assets(flt):
        if str(data.asset_name).lower() == name.lower():
            return data.get_asset()
    raise RuntimeError("No SkeletalMesh named '%s' in /Game. Set SKELETAL_MESH." % name)


def get_or_create(folder, name, asset_class, factory):
    path = "%s/%s" % (folder, name)
    if EAL.does_asset_exist(path):
        return EAL.load_asset(path)
    return asset_tools.create_asset(name, folder, asset_class, factory)


def mesh_bones(mesh):
    skeleton = mesh.skeleton
    names = set()
    try:
        ref = skeleton.get_reference_pose()  # 5.4+
        names = {str(n) for n in ref.get_bone_names()}
    except Exception:
        pass
    if not names:
        try:
            names = {str(skeleton.get_bone_name(i)) for i in range(skeleton.get_num_bones())}
        except Exception:
            pass
    return names


def chain_names(ctrl):
    try:
        return {str(c.chain_name) for c in ctrl.get_retarget_chains()}
    except Exception:
        return set()


def setup_ik_rig(ik_rig, mesh, profile, bones):
    ctrl = unreal.IKRigController.get_controller(ik_rig)
    ctrl.set_skeletal_mesh(mesh)

    auto_ok = False
    if USE_UE_AUTO_CHARACTERIZE and hasattr(ctrl, "apply_auto_generated_retarget_definition"):
        attempt("Auto retarget definition", ctrl.apply_auto_generated_retarget_definition)
        found = chain_names(ctrl)
        auto_ok = {"Spine", "LeftArm", "RightArm", "LeftLeg", "RightLeg"} <= found
        log("UE auto-characterize created %d chains%s" % (len(found), "" if auto_ok else " (incomplete)"))

    if not auto_ok:
        log("Building chains from %s" % os.path.basename(SKELETON_JSON))
        for chain in chain_names(ctrl):
            attempt("Remove chain %s" % chain, ctrl.remove_retarget_chain, chain)
        attempt("Set retarget root", ctrl.set_retarget_root, profile["retarget_root"])
        for chain in profile["chains"]:
            if chain["start"] not in bones or chain["end"] not in bones:
                continue
            goal = "%s_Goal" % chain["end"] if chain.get("goal") else ""
            attempt("Add chain %s" % chain["name"], ctrl.add_retarget_chain,
                    chain["name"], chain["start"], chain["end"], goal)

    if hasattr(ctrl, "apply_auto_fbik"):
        attempt("Auto Full Body IK", ctrl.apply_auto_fbik)
    else:
        warn("No apply_auto_fbik(): open the IK Rig and use 'Auto Create IK'.")
    attempt("Save IK Rig", EAL.save_loaded_asset, ik_rig)
    return ctrl


def setup_retargeter(rtg, source_rig, target_rig):
    ctrl = unreal.IKRetargeterController.get_controller(rtg)
    side = unreal.RetargetSourceOrTarget
    attempt("Set source IK Rig", ctrl.set_ik_rig, side.SOURCE, source_rig)
    attempt("Set target IK Rig", ctrl.set_ik_rig, side.TARGET, target_rig)
    if hasattr(ctrl, "add_default_ops"):  # 5.6+ op stack
        try:
            if ctrl.get_num_retarget_ops() == 0:
                ctrl.add_default_ops()
        except Exception:
            attempt("Add default ops", ctrl.add_default_ops)
        if hasattr(ctrl, "assign_ik_rig_to_all_ops"):
            attempt("Assign source rig to ops", ctrl.assign_ik_rig_to_all_ops, side.SOURCE, source_rig)
            attempt("Assign target rig to ops", ctrl.assign_ik_rig_to_all_ops, side.TARGET, target_rig)
    fuzzy = unreal.AutoMapChainType.FUZZY
    if attempt("Auto map chains", ctrl.auto_map_chains, fuzzy, True) is None:
        attempt("Auto map chains (old signature)", ctrl.auto_map_chains, fuzzy)
    if hasattr(ctrl, "auto_align_all_bones"):
        attempt("Auto align target retarget pose", ctrl.auto_align_all_bones, side.TARGET)
    attempt("Save Retargeter", EAL.save_loaded_asset, rtg)


def main():
    profile = load_profile()
    name = profile["character_name"]
    mesh = find_skeletal_mesh(name)
    bones = mesh_bones(mesh)
    if bones and "pelvis" not in bones:
        raise RuntimeError("%s has no 'pelvis' bone; was it exported with Unreal MHX?" % mesh.get_name())
    if bones and len(bones) < profile.get("bone_count", 0):
        warn("Mesh has %d bones, JSON lists %d (+root). Re-import the latest FBX?"
             % (len(bones), profile["bone_count"]))
    folder = OUTPUT_FOLDER or (str(mesh.get_path_name()).rsplit("/", 1)[0] + "/Rigs")

    ik_rig = get_or_create(folder, "IK_" + name, unreal.IKRigDefinition, unreal.IKRigDefinitionFactory())
    setup_ik_rig(ik_rig, mesh, profile, bones)
    log("IK Rig ready: %s" % ik_rig.get_path_name())

    source = EAL.load_asset(SOURCE_IK_RIG) if SOURCE_IK_RIG else None
    if source is None:
        warn("Source IK Rig '%s' not found (add the Third Person template or set SOURCE_IK_RIG). "
             "Skipping the retargeter." % SOURCE_IK_RIG)
        return
    src_name = source.get_name().replace("IK_", "")
    rtg = get_or_create(folder, "RTG_%s_To_%s" % (src_name, name), unreal.IKRetargeter,
                        unreal.IKRetargetFactory())
    setup_retargeter(rtg, source, ik_rig)
    log("Retargeter ready: %s" % rtg.get_path_name())
    log("Open it, check the retarget pose (Edit Pose > Auto Align if arms differ) and use "
        "'Export Selected Animations' or right-click animations > Retarget Animations.")


main()
