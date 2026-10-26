# SPDX-FileCopyrightText: 2026 Kyle Austad
# SPDX-License-Identifier: GPL-2.0-or-later
"""Unreal MHX: export Diffeomorphic MHX characters as Unreal Mannequin-style skeletons."""

if "bpy" in locals():
    import importlib
    for _mod in (rig_map, orient, anim_io, skeleton, meshes, bake, fbx_io,  # noqa: F821
                 retarget_json, exporter, props, operators, ui):
        importlib.reload(_mod)
else:
    from . import (
        rig_map, orient, anim_io, skeleton, meshes, bake, fbx_io,
        retarget_json, exporter, props, operators, ui,
    )

import bpy  # noqa: E402,F401

_modules = (props, operators, ui)


def register():
    for mod in _modules:
        mod.register()


def unregister():
    for mod in reversed(_modules):
        mod.unregister()
