# SPDX-License-Identifier: GPL-2.0-or-later
"""Unit tests for the MHX -> Unreal skeleton plan (no Blender needed).

    python -m unittest discover -s unreal_mhx/tests -p "test_*.py"
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rig_map as rm  # noqa: E402


def mhx_rig(keep_g9_twist=False, with_face=True):
    """Synthetic rig with the MHX deform/helper layout Diffeomorphic produces."""
    bones = {}

    def add(name, parent, deform, head, tail):
        bones[name] = rm.SourceBone(name, parent, deform, head, tail)

    add("master", None, False, (0, 0, 0), (0, 0.2, 0))
    add("hip", "master", False, (0, 0, 0.9), (0, 0, 0.75))
    add("pelvis", "hip", True, (0, 0, 0.9), (0, 0, 0.72))
    add("spine", "hip", True, (0, 0, 0.9), (0, 0, 0.98))
    add("spine-1", "spine", True, (0, 0, 0.98), (0, 0, 1.05))
    add("chest", "spine-1", True, (0, 0, 1.05), (0, 0, 1.18))
    add("chest-1", "chest", True, (0, 0, 1.18), (0, 0, 1.3))
    add("neckParent", "chest-1", False, (0, 0, 1.3), (0, 0, 1.15))
    add("neck", "neckParent", True, (0, 0, 1.3), (0, 0, 1.36))
    add("neck-1", "neck", True, (0, 0, 1.36), (0, 0, 1.41))
    add("head", "neck-1", True, (0, 0, 1.41), (0, 0, 1.45))
    if with_face:
        add("lowerjaw", "head", True, (0, -0.02, 1.42), (0, -0.08, 1.4))
        add("l_browinner(drv)", "head", False, (0.01, -0.09, 1.5), (0.01, -0.1, 1.5))
        add("browinner.L", "l_browinner(drv)", True, (0.01, -0.09, 1.5), (0.01, -0.1, 1.5))
        add("eye.L", "head", True, (0.03, -0.07, 1.46), (0.03, -0.09, 1.46))
    add("pectoral.L", "chest", True, (0.05, -0.08, 1.2), (0.05, -0.12, 1.2))
    add("pelvis2", "pelvis", True, (0, -0.01, 0.78), (0, -0.01, 0.73))
    for S, x in (("L", 1.0), ("R", -1.0)):
        add("clavicle.%s" % S, "chest-1", True, (0.03 * x, 0.03, 1.26), (0.13 * x, 0.04, 1.26))
        add("arm_parent.%s" % S, "hip", False, (0.15 * x, 0.04, 1.25), (0.15 * x, 0.04, 1.35))
        add("upper_arm.%s" % S, "arm_parent.%s" % S, keep_g9_twist, (0.15 * x, 0.04, 1.25), (0.31 * x, 0.04, 1.08))
        add("forearm.%s" % S, "upper_arm.%s" % S, keep_g9_twist, (0.31 * x, 0.04, 1.08), (0.48 * x, -0.02, 0.92))
        if keep_g9_twist:
            add("upper_arm.twist1.%s" % S, "upper_arm.%s" % S, True, (0.2 * x, 0.04, 1.2), (0.25 * x, 0.04, 1.14))
            add("upper_arm.twist2.%s" % S, "upper_arm.twist1.%s" % S, True, (0.25 * x, 0.04, 1.14), (0.31 * x, 0.04, 1.08))
            add("forearm.twist1.%s" % S, "forearm.%s" % S, True, (0.37 * x, 0.02, 1.02), (0.42 * x, 0.0, 0.97))
        else:
            add("upper_arm.bend.%s" % S, "arm_parent.%s" % S, True, (0.15 * x, 0.04, 1.25), (0.23 * x, 0.04, 1.16))
            add("upper_arm.twist.%s" % S, "upper_arm.bend.%s" % S, True, (0.23 * x, 0.04, 1.16), (0.31 * x, 0.04, 1.08))
            add("forearm.bend.%s" % S, "upper_arm.%s" % S, True, (0.31 * x, 0.04, 1.08), (0.4 * x, 0.01, 1.0))
            add("forearm.twist.%s" % S, "forearm.bend.%s" % S, True, (0.4 * x, 0.01, 1.0), (0.48 * x, -0.02, 0.92))
        add("hand.%s" % S, "forearm.%s" % S, False, (0.48 * x, -0.02, 0.92), (0.54 * x, -0.04, 0.87))
        add("hand0.%s" % S, "hand.%s" % S, True, (0.48 * x, -0.02, 0.92), (0.54 * x, -0.04, 0.87))
        add("thumb.01.%s" % S, "hand0.%s" % S, True, (0.485 * x, -0.034, 0.905), (0.493 * x, -0.064, 0.884))
        add("thumb.02.%s" % S, "thumb.01.%s" % S, True, (0.493 * x, -0.064, 0.884), (0.5 * x, -0.08, 0.87))
        for i, finger in enumerate(("index", "middle", "ring", "pinky")):
            off = -0.03 + 0.012 * i
            add("palm_%s.%s" % (finger, S), "hand0.%s" % S, True, (0.487 * x, off, 0.919), (0.53 * x, off, 0.869))
            prev = "palm_%s.%s" % (finger, S)
            for seg in (1, 2, 3):
                name = "f_%s.%02d.%s" % (finger, seg, S)
                z = 0.868 - 0.02 * seg
                add(name, prev, True, (0.53 * x, off, z + 0.02), (0.55 * x, off, z))
                prev = name
        add("leg_parent.%s" % S, "hip", False, (0.08 * x, 0.0, 0.8), (0.08 * x, 0.0, 0.9))
        add("thigh.%s" % S, "leg_parent.%s" % S, False, (0.08 * x, 0.0, 0.8), (0.09 * x, 0.02, 0.43))
        add("thigh.bend.%s" % S, "leg_parent.%s" % S, True, (0.08 * x, 0.0, 0.8), (0.085 * x, 0.01, 0.62))
        add("thigh.twist.%s" % S, "thigh.bend.%s" % S, True, (0.085 * x, 0.01, 0.62), (0.09 * x, 0.02, 0.43))
        add("shin.%s" % S, "thigh.%s" % S, False, (0.09 * x, 0.02, 0.43), (0.11 * x, 0.05, 0.06))
        add("shin.bend.%s" % S, "thigh.%s" % S, True, (0.09 * x, 0.02, 0.43), (0.1 * x, 0.03, 0.25))
        add("shin.twist.%s" % S, "shin.bend.%s" % S, True, (0.1 * x, 0.03, 0.25), (0.11 * x, 0.05, 0.06))
        add("foot.%s" % S, "shin.%s" % S, True, (0.11 * x, 0.05, 0.06), (0.14 * x, -0.06, 0.02))
        add("tarsal.%s" % S, "foot.%s" % S, True, (0.11 * x, 0.045, 0.06), (0.125 * x, -0.02, 0.04))
        add("toe.%s" % S, "foot.%s" % S, True, (0.14 * x, -0.06, 0.02), (0.15 * x, -0.11, 0.02))
        add("big_toe.01.%s" % S, "toe.%s" % S, True, (0.11 * x, -0.075, 0.02), (0.12 * x, -0.1, 0.015))
        add("foot.ik.%s" % S, "master", False, (0.11 * x, 0.05, 0.0), (0.15 * x, -0.11, 0.02))
    return bones


def weighted(bones):
    return {name for name, b in bones.items() if b.deform}


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.bones = mhx_rig()
        self.plan = rm.build_plan(self.bones, weighted(self.bones))

    def parent(self, name):
        return self.plan.get(name).parent

    def test_no_errors(self):
        self.assertEqual(self.plan.errors, [])

    def test_mannequin_hierarchy(self):
        expected = {
            "spine_01": "pelvis", "spine_04": "spine_03", "neck_01": "spine_04",
            "neck_02": "neck_01", "head": "neck_02",
            "clavicle_l": "spine_04", "upperarm_l": "clavicle_l", "lowerarm_l": "upperarm_l",
            "hand_l": "lowerarm_l", "index_metacarpal_l": "hand_l", "index_01_l": "index_metacarpal_l",
            "thumb_01_l": "hand_l", "thigh_r": "pelvis", "calf_r": "thigh_r", "foot_r": "calf_r",
            "ball_r": "foot_r", "upperarm_twist_01_l": "upperarm_l", "calf_twist_01_r": "calf_r",
            "ik_foot_l": rm.IK_FOOT_ROOT, "ik_hand_l": rm.IK_HAND_GUN, "ik_hand_gun": rm.IK_HAND_ROOT,
        }
        for bone, parent in expected.items():
            self.assertEqual(self.parent(bone), parent, bone)
        self.assertIsNone(self.parent("pelvis"))
        self.assertIsNone(self.parent(rm.IK_FOOT_ROOT))

    def test_twist_halves(self):
        plan = self.plan
        self.assertEqual(plan.get("upperarm_l").source, "upper_arm.twist.L")
        self.assertEqual(plan.get("upperarm_twist_01_l").source, "upper_arm.bend.L")
        # main bone starts at the shoulder (bend head), not mid-arm
        self.assertEqual(plan.get("upperarm_l").head, self.bones["upper_arm.bend.L"].head)
        self.assertEqual(plan.weight_map["upper_arm.twist.L"], "upperarm_l")
        self.assertEqual(plan.weight_map["upper_arm.bend.L"], "upperarm_twist_01_l")
        self.assertEqual(plan.get("lowerarm_l").aim, plan.get("hand_l").head)

    def test_every_weighted_bone_is_mapped(self):
        for name in weighted(self.bones):
            self.assertIn(self.plan.weight_map.get(name), self.plan.by_name, name)

    def test_generic_bones(self):
        plan = self.plan
        self.assertEqual(plan.get("jaw").parent, "head")
        self.assertEqual(plan.get("browinner_l").parent, "head")
        self.assertEqual(plan.get("browinner_l").category, rm.CATEGORY_FACE)
        self.assertEqual(plan.get("bigtoe_01_l").parent, "ball_l")
        self.assertEqual(plan.get("bigtoe_01_l").category, rm.CATEGORY_TOE)
        self.assertEqual(plan.get("metatarsal_l").parent, "foot_l")
        self.assertEqual(plan.get("pectoral_l").parent, "spine_03")
        self.assertEqual(plan.get("pelvis2").category, rm.CATEGORY_EXTRA)

    def test_exclusion_merges_weights(self):
        plan = rm.build_plan(self.bones, weighted(self.bones), include_face=False,
                             include_toes=False, include_extra=False)
        self.assertEqual(plan.errors, [])
        self.assertNotIn("jaw", plan.by_name)
        self.assertEqual(plan.weight_map["browinner.L"], "head")
        self.assertEqual(plan.weight_map["big_toe.01.L"], "ball_l")
        self.assertEqual(plan.weight_map["tarsal.L"], "foot_l")
        self.assertEqual(plan.weight_map["pelvis2"], "pelvis")
        self.assertEqual(plan.get("ball_l").parent, "foot_l")

    def test_resolve_helpers(self):
        plan = self.plan
        self.assertEqual(plan.resolve("hand.L"), "hand_l")
        self.assertEqual(plan.resolve("arm_parent.R"), "clavicle_r")
        self.assertEqual(plan.resolve("foot.ik.L"), "pelvis")
        self.assertEqual(plan.resolve("neckParent"), "spine_04")

    def test_chains(self):
        chains = {name: (start, end, goal) for name, start, end, goal in self.plan.chains()}
        self.assertEqual(chains["Spine"], ("spine_01", "spine_04", None))
        self.assertEqual(chains["LeftArm"], ("upperarm_l", "hand_l", "hand_l"))
        self.assertEqual(chains["RightLeg"], ("thigh_r", "foot_r", "foot_r"))
        self.assertEqual(chains["LeftIndex"][0], "index_metacarpal_l")
        self.assertIn("HandGunIK", chains)

    def test_unweighted_twist_falls_back_to_bend(self):
        live = weighted(self.bones) - {"shin.twist.L"}
        plan = rm.build_plan(self.bones, live)
        self.assertEqual(plan.get("calf_l").source, "shin.bend.L")
        self.assertNotIn("calf_twist_01_l", plan.by_name)

    def test_keep_g9_twist(self):
        bones = mhx_rig(keep_g9_twist=True)
        plan = rm.build_plan(bones, weighted(bones))
        self.assertEqual(plan.errors, [])
        self.assertEqual(plan.get("upperarm_l").source, "upper_arm.L")
        self.assertEqual(plan.get("upperarm_twist_02_r").source, "upper_arm.twist2.R")
        self.assertEqual(plan.get("lowerarm_l").parent, "upperarm_l")

    def test_missing_pelvis(self):
        bones = dict(self.bones)
        del bones["pelvis"]
        plan = rm.build_plan(bones, weighted(bones))
        self.assertTrue(plan.errors)

    def test_no_ik(self):
        plan = rm.build_plan(self.bones, weighted(self.bones), add_ik=False)
        self.assertNotIn(rm.IK_FOOT_ROOT, plan.by_name)

    def test_unique_topological_order(self):
        seen = set()
        for pb in self.plan.bones:
            self.assertNotIn(pb.name, seen)
            if pb.parent:
                self.assertIn(pb.parent, seen, pb.name)
            seen.add(pb.name)
        self.assertNotIn(rm.ROOT_NAME, seen)


class NameTests(unittest.TestCase):
    def test_generic_names(self):
        cases = {
            "browinner.L": "browinner_l",
            "lHighTentacleC1": "high_tentacle_c1_l",
            "r_bigtoe1": "bigtoe1_r",
            "labiumMajoraBack": "labium_majora_back",
            "leftMediumTentacleC1": "medium_tentacle_c1_l",
            "lowerjaw": "jaw",
            "small_toe_4.02.R": "littletoe_02_r",
            "lShldrBend(fin)": "shldr_bend_l",
            "tarsal.L": "metatarsal_l",
            "rectum_01": "rectum_01",
        }
        for src, expected in cases.items():
            self.assertEqual(rm.generic_name(src), expected, src)


if __name__ == "__main__":
    unittest.main()
