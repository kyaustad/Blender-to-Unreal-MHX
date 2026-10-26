# SPDX-FileCopyrightText: 2026 Kyle Austad
# SPDX-License-Identifier: GPL-2.0-or-later
"""Sidecar JSON describing the exported skeleton for the Unreal setup script."""

import json
import os

from .rig_map import CATEGORY_CORE, CATEGORY_FINGER, CATEGORY_IK, CATEGORY_TWIST, ROOT_NAME

FORMAT = "unreal_mhx_skeleton"
FORMAT_VERSION = 2


def profile(plan, settings, export_rig):
    bones = []
    for pb in plan.bones:
        bones.append({
            "name": pb.name,
            "parent": pb.parent or ROOT_NAME,
            "source": pb.source,
            "category": pb.category,
        })
    chains = [
        {"name": name, "start": start, "end": end, "goal": goal}
        for name, start, end, goal in plan.chains()
    ]
    goals = [c for c in chains if c["goal"]]
    humanoid = {CATEGORY_CORE, CATEGORY_FINGER, CATEGORY_TWIST, CATEGORY_IK}
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "character_name": settings.character_name,
        "skeleton_root": ROOT_NAME,
        "retarget_root": "pelvis",
        "units": "centimeters" if settings.units_x100 else "meters",
        "mannequin_axes": settings.mannequin_axes,
        "bone_count": len(plan.bones),
        "chains": chains,
        "goals": [{"name": "%s_Goal" % c["end"], "bone": c["end"], "chain": c["name"]} for c in goals],
        "twist_bones": [pb.name for pb in plan.bones if pb.category == CATEGORY_TWIST],
        "extra_bones": [pb.name for pb in plan.bones if pb.category not in humanoid],
        "bones": bones,
    }


def write(fbx_path, plan, settings, export_rig):
    path = os.path.splitext(fbx_path)[0] + "_Skeleton.json"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(profile(plan, settings, export_rig), handle, indent=2)
        handle.write("\n")
    return path
