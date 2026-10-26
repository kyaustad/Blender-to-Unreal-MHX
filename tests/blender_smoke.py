# SPDX-License-Identifier: GPL-2.0-or-later
"""Headless end-to-end test of the exporter.

    blender -b --enable-autoexec <character.blend> --python unreal_mhx/tests/blender_smoke.py -- <out_dir>

The .blend must contain a Diffeomorphic character (MHX or not yet
converted). The script never saves the .blend. It:

1. converts the rig to MHX if needed,
2. keys a short test animation (IK hand/foot, spine, root motion, a morph),
3. exports character + animation with the export objects kept,
4. checks that the exported meshes deform exactly like the MHX meshes,
5. re-imports the FBX files and prints the skeleton for inspection.
"""

import os
import sys
import time
import traceback

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

import unreal_mhx  # noqa: E402
from unreal_mhx import exporter, meshes  # noqa: E402

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else os.path.join(HERE, "_out")
os.makedirs(OUT, exist_ok=True)
FAILURES = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILURES.append(msg)


def find_rig():
    rigs = [ob for ob in bpy.data.objects if ob.type == 'ARMATURE' and not ob.get("UnrealMhxExport")]
    return rigs[0]


def activate(ob):
    vl = bpy.context.view_layer
    for o in vl.objects:
        o.select_set(False)
    vl.objects.active = ob
    ob.select_set(True)


def key_test_animation(rig):
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 24
    pb = rig.pose.bones
    keys = [
        ("hand.ik.L", "location", [(1, (0, 0, 0)), (12, (0.05, -0.25, 0.35)), (24, (0, 0, 0))]),
        ("foot.ik.R", "location", [(1, (0, 0, 0)), (12, (0.0, -0.2, 0.15)), (24, (0, 0, 0))]),
        ("master", "location", [(1, (0, 0, 0)), (24, (0.0, -0.6, 0.0))]),
    ]
    for bone, path, frames in keys:
        if bone not in pb:
            print("  (no %s)" % bone)
            continue
        for frame, value in frames:
            setattr(pb[bone], path, value)
            pb[bone].keyframe_insert(path, frame=frame)
    for bone, axis, angle in (("chest", 0, 0.35), ("neck", 2, 0.4), ("hand.fk.R", 0, 0.5)):
        if bone not in pb:
            continue
        p = pb[bone]
        p.rotation_mode = 'XYZ'
        for frame, a in ((1, 0.0), (12, angle), (24, 0.0)):
            rot = [0.0, 0.0, 0.0]
            rot[axis] = a
            p.rotation_euler = rot
            p.keyframe_insert("rotation_euler", frame=frame)
    for prop in ("facs_ctrl_Happy", "facs_bs_JawOpen"):
        if prop in rig.keys():
            for frame, v in ((1, 0.0), (12, 1.0), (24, 0.0)):
                rig[prop] = v
                rig.keyframe_insert('["%s"]' % prop, frame=frame)
    rig.animation_data.action.name = "SmokeTest"


def world_coords(ob, depsgraph):
    ev = ob.evaluated_get(depsgraph)
    me = ev.to_mesh()
    mw = ev.matrix_world
    out = [mw @ v.co for v in me.vertices]
    ev.to_mesh_clear()
    return out


def deformation_error(rig, export_rig, pairs, frames, unit_scale):
    scene = bpy.context.scene
    saved = [(m, m.show_viewport) for src, _dst in pairs for m in src.modifiers if m.type != 'ARMATURE']
    for m, _s in saved:
        m.show_viewport = False
    # Unreal skins linearly; compare against Blender's linear skinning too
    dqs = [m for src, _dst in pairs for m in src.modifiers
           if m.type == 'ARMATURE' and m.use_deform_preserve_volume]
    print("  source armature modifiers using Preserve Volume:", len(dqs))
    for m in dqs:
        m.use_deform_preserve_volume = False
    world0_inv = rig.matrix_world.inverted()
    worst = 0.0
    try:
        for frame in frames:
            scene.frame_set(frame)
            dg = bpy.context.evaluated_depsgraph_get()
            for src, dst in pairs:
                a = world_coords(src, dg)
                b = world_coords(dst, dg)
                if len(a) != len(b):
                    FAILURES.append("vertex count mismatch %s" % src.name)
                    continue
                scale = Matrix.Scale(unit_scale, 4) @ world0_inv
                err = max(((scale @ pa) - pb).length for pa, pb in zip(a, b)) if a else 0.0
                worst = max(worst, err)
                print("    frame %3d %-34s max error %.5f cm" % (frame, src.name, err))
    finally:
        for m, s in saved:
            m.show_viewport = s
        for m in dqs:
            m.use_deform_preserve_volume = True
    return worst


def main():
    t0 = time.time()
    unreal_mhx.register()
    rig = find_rig()
    activate(rig)
    if not exporter.is_mhx_rig(rig):
        print("Converting to MHX ...")
        bpy.ops.unreal_mhx.convert_to_mhx()
        rig = find_rig()
    check(exporter.is_mhx_rig(rig), "rig is MHX")

    key_test_animation(rig)
    activate(rig)
    settings = bpy.context.scene.unreal_mhx
    settings.character_name = "SmokeChar"
    settings.export_dir = OUT
    settings.keep_export_objects = False
    settings.anim_name = "SmokeTest"
    settings.max_influences = 0  # exact comparison with the MHX meshes

    print("Check rig ...")
    check('FINISHED' in bpy.ops.unreal_mhx.check(), "check operator")
    scene = bpy.context.scene
    before = (scene.name, scene.frame_start, scene.frame_end, scene.frame_current,
              rig.animation_data.action.name, len(bpy.data.objects), len(bpy.data.actions))
    t1 = time.time()
    result = bpy.ops.unreal_mhx.export(mode='ALL')
    print("Export took %.1fs" % (time.time() - t1))
    for line in bpy.data.texts["UnrealMHX_Report"].as_string().splitlines()[:6]:
        print("  report:", line)
    check('FINISHED' in result, "export operator finished")
    after = (scene.name, scene.frame_start, scene.frame_end, scene.frame_current,
             rig.animation_data.action.name, len(bpy.data.objects), len(bpy.data.actions))
    check(before == after, "scene restored after export %s" % (after,))

    check('FINISHED' in bpy.ops.unreal_mhx.export(mode='PREVIEW'), "preview built")
    export_rig = bpy.data.objects.get("root")
    check(export_rig is not None and export_rig.get("UnrealMhxExport"), "export armature named 'root'")
    names = set(export_rig.data.bones.keys())
    for bone in ("pelvis", "spine_01", "neck_01", "head", "clavicle_l", "upperarm_l", "lowerarm_l",
                 "hand_l", "thigh_r", "calf_r", "foot_r", "ball_r", "index_01_l",
                 "upperarm_twist_01_l", "ik_foot_root", "ik_hand_gun", "ik_hand_l"):
        check(bone in names, "bone %s" % bone)
    check(export_rig.data.bones["upperarm_l"].parent.name == "clavicle_l", "upperarm_l parent clavicle_l")
    check(export_rig.data.bones["thigh_l"].parent.name == "pelvis", "thigh_l parent pelvis")
    check(export_rig.data.bones["pelvis"].parent is None, "pelvis is top bone")

    pairs = []
    for ob in bpy.data.objects:
        if ob.get("UnrealMhxExport") and ob.type == 'MESH':
            src = bpy.data.objects.get(ob.name[:-3])
            if src is not None:
                pairs.append((src, ob))
    check(len(pairs) > 0, "export meshes kept")
    worst = deformation_error(rig, export_rig, pairs, (1, 8, 12, 18), 100.0)
    check(worst < 0.05, "exported meshes deform like MHX (worst %.4f cm)" % worst)

    for name in ("SmokeChar.fbx", "SmokeChar_SmokeTest.fbx", "SmokeChar_Skeleton.json"):
        path = os.path.join(OUT, name)
        check(os.path.isfile(path) and os.path.getsize(path) > 1000, "wrote %s" % name)

    # re-import into an empty scene
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=os.path.join(OUT, "SmokeChar.fbx"))
    arms = [ob for ob in bpy.data.objects if ob.type == 'ARMATURE']
    check(len(arms) == 1, "re-imported one armature")
    if arms:
        arm = arms[0]
        print("  imported armature %s scale %s bones %d" % (arm.name, tuple(round(s, 4) for s in arm.scale),
                                                           len(arm.data.bones)))
        tops = [b.name for b in arm.data.bones if b.parent is None]
        print("  top-level bones:", tops)
        check(set(tops) <= {"pelvis", "ik_foot_root", "ik_hand_root"}, "top bones are pelvis + IK roots")
        sk = [ob for ob in bpy.data.objects if ob.type == 'MESH' and ob.data.shape_keys]
        print("  meshes with morphs:", [(ob.name, len(ob.data.shape_keys.key_blocks) - 1) for ob in sk])
    bpy.ops.import_scene.fbx(filepath=os.path.join(OUT, "SmokeChar_SmokeTest.fbx"))
    acts = [(a.name, tuple(a.frame_range)) for a in bpy.data.actions]
    print("  imported actions:", acts[:8])
    check(any(r[1] - r[0] >= 20 for _n, r in acts), "animation re-imported")
    print("Total %.1fs" % (time.time() - t0))


try:
    main()
except Exception:
    traceback.print_exc()
    FAILURES.append("exception")
print("RESULT:", "PASS" if not FAILURES else "FAIL %s" % FAILURES)
