# SPDX-FileCopyrightText: 2026 Kyle Austad
# SPDX-License-Identifier: GPL-2.0-or-later
"""Plan an Unreal Mannequin-style skeleton from a Diffeomorphic MHX rig.

Pure Python (no bpy) so the mapping can be unit tested outside Blender.

The MHX deform skeleton is not a clean hierarchy: deform bones hang off
control/helper bones (arm_parent, leg_parent, neckParent, hand.L ...), and
every limb segment is split into a "bend" half (swing only) and a "twist"
half (full rotation). The plan below builds a separate deform-only skeleton:

* Mannequin names and parenting for every humanoid bone, so UE's IK Rig
  auto-characterization and Manny/Quinn retargeting recognise it.
* Main limb bones (upperarm_l, thigh_l ...) take the MHX twist half, which
  carries the full limb rotation, and are placed at the joint. The bend half
  becomes the *_twist_01 child. Exactly like the Manny convention.
* Every other weighted deform bone (face, toes, geografts, breasts ...) is
  kept with a sanitized name and parented to its nearest exported ancestor.

Rest placement of export bones is free: the bake applies
``P_export = P_source @ R_source^-1 @ R_export`` so skinning is identical.
"""

import re

SIDES = (("L", "l"), ("R", "r"))
UP = (0.0, 0.0, 1.0)

SPINE_SOURCES = ("spine", "spine-1", "chest", "chest-1")
NECK_SOURCES = ("neck", "neck-1")

# (MHX segment, UE stem, orientation kind)
ARM_SEGMENTS = (("upper_arm", "upperarm"), ("forearm", "lowerarm"))
LEG_SEGMENTS = (("thigh", "thigh"), ("shin", "calf"))

FINGERS = (
    ("thumb", "thumb"),
    ("f_index", "index"),
    ("f_middle", "middle"),
    ("f_ring", "ring"),
    ("f_pinky", "pinky"),
)
PALMS = (
    ("palm_index", "index"),
    ("palm_middle", "middle"),
    ("palm_ring", "ring"),
    ("palm_pinky", "pinky"),
    ("palm_thumb", "thumb"),
)
# MHX toe chains -> MetaHuman-style toe names
TOES = {
    "big_toe": "bigtoe",
    "small_toe_1": "indextoe",
    "small_toe_2": "middletoe",
    "small_toe_3": "ringtoe",
    "small_toe_4": "littletoe",
}
SPECIAL_NAMES = {
    "lowerjaw": "jaw",
    "lowerJaw": "jaw",
    "tarsal": "metatarsal",
}

IK_FOOT_ROOT = "ik_foot_root"
IK_HAND_ROOT = "ik_hand_root"
IK_HAND_GUN = "ik_hand_gun"
IK_BONE_NAMES = (
    IK_FOOT_ROOT, "ik_foot_l", "ik_foot_r",
    IK_HAND_ROOT, IK_HAND_GUN, "ik_hand_l", "ik_hand_r",
)

# The armature object itself becomes the UE "root" bone (ARP convention).
ROOT_NAME = "root"
RESERVED_NAMES = {ROOT_NAME}

CATEGORY_CORE = "core"
CATEGORY_TWIST = "twist"
CATEGORY_FINGER = "finger"
CATEGORY_FACE = "face"
CATEGORY_TOE = "toe"
CATEGORY_EXTRA = "extra"
CATEGORY_IK = "ik"

DRIVER_SUFFIXES = ("(fin)", "(drv)", "(def)", "(erc)", "(rst)")


class SourceBone:
    """Minimal description of one bone of the source (MHX) armature."""

    __slots__ = ("name", "parent", "deform", "head", "tail")

    def __init__(self, name, parent, deform, head, tail):
        self.name = name
        self.parent = parent
        self.deform = deform
        self.head = tuple(head)
        self.tail = tuple(tail)


class PlanBone:
    """One bone of the export skeleton.

    source  -- MHX bone whose evaluated pose drives this bone (None for IK
               roots and IK copies).
    kind    -- orientation rule used for Mannequin axes (see orient.py).
    head    -- rest head position in source armature space (meters).
    aim     -- point the bone aims at (next joint); defines direction/length.
    copy_of -- for IK goal bones: the export bone whose pose is copied.
    """

    __slots__ = (
        "name", "source", "parent", "kind", "side", "head", "aim",
        "category", "copy_of",
    )

    def __init__(self, name, source, parent, kind, side=None, head=None,
                 aim=None, category=CATEGORY_CORE, copy_of=None):
        self.name = name
        self.source = source
        self.parent = parent
        self.kind = kind
        self.side = side
        self.head = head
        self.aim = aim
        self.category = category
        self.copy_of = copy_of

    def __repr__(self):
        return "PlanBone(%s <- %s, parent=%s)" % (self.name, self.source, self.parent)


class Plan:
    def __init__(self):
        self.bones = []
        self.by_name = {}
        self.weight_map = {}
        self.merged = {}
        self.src_to_export = {}
        self.aliases = {}
        self.source_bones = {}
        self.errors = []
        self.warnings = []
        self.root_motion_source = None

    def get(self, name):
        return self.by_name.get(name)

    def names(self):
        return [b.name for b in self.bones]

    def resolve(self, source_name):
        """Export bone that a source bone (deform or not) follows."""
        name = source_name
        seen = set()
        while name is not None and name not in seen:
            seen.add(name)
            if name in self.weight_map:
                return self.weight_map[name]
            if name in self.src_to_export:
                return self.src_to_export[name]
            if name in self.aliases:
                return self.aliases[name]
            bone = self.source_bones.get(name)
            name = bone.parent if bone else None
        return "pelvis" if "pelvis" in self.by_name else (self.bones[0].name if self.bones else None)

    def chains(self):
        return retarget_chains(self)


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _length(a):
    return (a[0] * a[0] + a[1] * a[1] + a[2] * a[2]) ** 0.5


def _snake(text):
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return re.sub(r"_+", "_", text)


def strip_driver_suffix(name):
    for suffix in DRIVER_SUFFIXES:
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


_SIDE_SUFFIX = re.compile(r"^(?P<base>.+?)[._](?P<side>[LRlr])$")
_SIDE_PREFIX_G9 = re.compile(r"^(?P<side>[lr])_(?P<base>.+)$")
_SIDE_PREFIX_G8 = re.compile(r"^(?P<side>[lr])(?P<base>[A-Z].*)$")
_SIDE_WORD = re.compile(r"^(?P<side>left|right)(?P<base>[A-Z].*)$")
_TOE = re.compile(r"^(?P<toe>big_toe|small_toe_[1-4])\.(?P<idx>\d+)\.(?P<side>[LR])$")


def split_side(name):
    """Return (base, side) where side is 'l', 'r' or None."""
    for pattern in (_SIDE_SUFFIX, _SIDE_PREFIX_G9, _SIDE_PREFIX_G8, _SIDE_WORD):
        match = pattern.match(name)
        if match:
            return match.group("base"), match.group("side")[0].lower()
    return name, None


def generic_name(source_name):
    """Unreal-friendly name for a non-humanoid deform bone."""
    name = strip_driver_suffix(source_name).replace(".twk", "")
    toe = _TOE.match(name)
    if toe:
        return "%s_%02d_%s" % (TOES[toe.group("toe")], int(toe.group("idx")), toe.group("side").lower())
    base, side = split_side(name)
    base = SPECIAL_NAMES.get(base, base)
    stem = _snake(base) or "bone"
    return "%s_%s" % (stem, side) if side else stem


class _Planner:
    def __init__(self, bones, weighted, include_face, include_toes,
                 include_extra, add_ik):
        self.bones = bones
        self.weighted = set(weighted)
        self.include = {
            CATEGORY_FACE: include_face,
            CATEGORY_TOE: include_toes,
            CATEGORY_EXTRA: include_extra,
        }
        self.add_ik = add_ik
        self.plan = Plan()
        self.plan.source_bones = bones
        self.used_names = set(RESERVED_NAMES) | set(IK_BONE_NAMES)
        self.live = {
            name for name in self.weighted
            if name in bones and bones[name].deform
        }

    # ------------------------------------------------------------------
    #   helpers
    # ------------------------------------------------------------------

    def bone(self, name):
        return self.bones.get(name) if name else None

    def pick(self, name):
        """Deforming source bone for an MHX name, preferring tweak bones."""
        base, sep, side = name.rpartition(".")
        if sep and side in ("L", "R"):
            twk = "%s.twk.%s" % (base, side)
        else:
            twk = name + ".twk"
        candidates = [c for c in (twk, name) if c in self.bones and self.bones[c].deform]
        for cand in candidates:
            if cand in self.live:
                return cand
        return candidates[0] if candidates else None

    def add(self, name, source, parent, kind, side=None, head=None, aim=None,
            category=CATEGORY_CORE, copy_of=None):
        if name in self.plan.by_name:
            raise ValueError("Duplicate export bone %s" % name)
        src = self.bone(source)
        if head is None and src is not None:
            head = src.head
        if aim is None and src is not None:
            aim = src.tail
        pb = PlanBone(name, source, parent, kind, side, head, aim, category, copy_of)
        self.plan.bones.append(pb)
        self.plan.by_name[name] = pb
        self.used_names.add(name)
        if source:
            self.plan.src_to_export.setdefault(source, name)
        return pb

    def unique(self, name):
        if name not in self.used_names:
            return name
        idx = 2
        while "%s_%d" % (name, idx) in self.used_names:
            idx += 1
        return "%s_%d" % (name, idx)

    # ------------------------------------------------------------------
    #   core humanoid
    # ------------------------------------------------------------------

    def run(self):
        plan = self.plan
        pelvis = self.pick("pelvis")
        if pelvis is None:
            plan.errors.append("No deforming 'pelvis' bone found. Is this an MHX rig?")
            return plan
        pelvis_bone = self.bone(pelvis)
        self.add("pelvis", pelvis, None, "pelvis",
                 head=pelvis_bone.head,
                 aim=_add(pelvis_bone.head, _scale(UP, max(_length(_sub(pelvis_bone.tail, pelvis_bone.head)), 0.05))))

        spines = [s for s in (self.pick(n) for n in SPINE_SOURCES) if s]
        necks = [s for s in (self.pick(n) for n in NECK_SOURCES) if s]
        head_src = self.pick("head")
        if not spines:
            plan.errors.append("No spine bones (spine, spine-1, chest, chest-1) found.")
        if head_src is None:
            plan.errors.append("No deforming 'head' bone found.")

        parent = "pelvis"
        spine_names = []
        for idx, src in enumerate(spines, start=1):
            name = "spine_%02d" % idx
            self.add(name, src, parent, "spine")
            spine_names.append(name)
            parent = name
        chest = spine_names[-1] if spine_names else "pelvis"
        neck_names = []
        for idx, src in enumerate(necks, start=1):
            name = "neck_%02d" % idx
            self.add(name, src, parent, "spine")
            neck_names.append(name)
            parent = name
        if head_src:
            self.add("head", head_src, parent, "spine")
        # aim each spine/neck bone at the next joint
        column = spine_names + neck_names + (["head"] if head_src else [])
        for cur, nxt in zip(column, column[1:]):
            plan.by_name[cur].aim = plan.by_name[nxt].head

        self.plan.aliases.update({
            "hip": "pelvis",
            "master": "pelvis",
            "neckParent": chest,
        })

        for side_mhx, side in SIDES:
            self.add_arm(side_mhx, side, chest)
            self.add_leg(side_mhx, side)

        self.add_generic()
        if self.add_ik:
            self.add_ik_bones()
        self.finish()
        return plan

    def add_segment(self, seg, stem, side_mhx, side, parent, kind):
        """Add main + twist bones for one MHX limb segment."""
        bend = self.pick("%s.bend.%s" % (seg, side_mhx))
        twist = self.pick("%s.twist.%s" % (seg, side_mhx))
        main = self.pick("%s.%s" % (seg, side_mhx))
        name = "%s_%s" % (stem, side)
        twists = []
        if bend and twist:
            if twist in self.live:
                main_src = twist
                if bend in self.live:
                    twists = [bend]
            else:
                main_src = bend
            head = self.bone(bend).head
            aim = self.bone(twist).tail
        elif main:
            main_src = main
            head = self.bone(main).head
            aim = self.bone(main).tail
            for idx in (1, 2, 3):
                g9 = self.pick("%s.twist%d.%s" % (seg, idx, side_mhx))
                if g9 and g9 in self.live:
                    twists.append(g9)
        elif bend or twist:
            main_src = bend or twist
            head = self.bone(main_src).head
            aim = self.bone(main_src).tail
        else:
            self.plan.errors.append("Missing MHX %s.%s deform bones." % (seg, side_mhx))
            return None
        self.add(name, main_src, parent, kind, side, head=head, aim=aim)
        for helper in (main, "%s.%s" % (seg, side_mhx), bend, twist):
            if helper:
                self.plan.src_to_export.setdefault(helper, name)
        self.plan.aliases["%s.%s" % (seg, side_mhx)] = name
        for idx, src in enumerate(twists, start=1):
            self.add("%s_twist_%02d_%s" % (stem, idx, side), src, name, kind, side,
                     category=CATEGORY_TWIST)
        return name

    def add_arm(self, side_mhx, side, chest):
        plan = self.plan
        clav_src = self.pick("clavicle.%s" % side_mhx)
        parent = chest
        if clav_src:
            parent = self.add("clavicle_%s" % side, clav_src, chest, "arm", side).name
        else:
            plan.warnings.append("No clavicle.%s bone; upper arm parented to chest." % side_mhx)
        plan.aliases["arm_parent.%s" % side_mhx] = parent
        plan.aliases["armSocket.%s" % side_mhx] = parent

        upper = self.add_segment("upper_arm", "upperarm", side_mhx, side, parent, "arm")
        lower = self.add_segment("forearm", "lowerarm", side_mhx, side, upper or parent, "arm")
        hand_src = self.pick("hand0.%s" % side_mhx) or self.pick("hand.%s" % side_mhx)
        if hand_src is None:
            plan.errors.append("Missing MHX hand0.%s deform bone." % side_mhx)
            return
        hand = self.add("hand_%s" % side, hand_src, lower or upper or parent, "hand", side)
        plan.aliases["hand.%s" % side_mhx] = hand.name
        if clav_src and upper:
            plan.by_name["clavicle_%s" % side].aim = plan.by_name[upper].head
        if upper and lower:
            plan.by_name[upper].aim = plan.by_name[lower].head
            for tw in self.twists_of(upper):
                tw.aim = _add(tw.head, _scale(_unit(_sub(plan.by_name[lower].head, plan.by_name[upper].head)),
                                              _length(_sub(tw.aim, tw.head))))
        if lower:
            plan.by_name[lower].aim = hand.head
            for tw in self.twists_of(lower):
                tw.aim = _add(tw.head, _scale(_unit(_sub(hand.head, plan.by_name[lower].head)),
                                              _length(_sub(tw.aim, tw.head))))

        # palms / metacarpals, named after the finger they carry
        finger_first = {}
        for mhx, ue in FINGERS:
            src = self.pick("%s.01.%s" % (mhx, side_mhx))
            if src:
                finger_first[src] = ue
        for palm, default in PALMS:
            src = self.pick("%s.%s" % (palm, side_mhx))
            if not src:
                continue
            carried = [ue for fsrc, ue in finger_first.items() if self.bones[fsrc].parent == src]
            order = [ue for _m, ue in FINGERS]
            carried.sort(key=order.index)
            stem = carried[0] if carried else default
            name = self.unique("%s_metacarpal_%s" % (stem, side))
            heads = [self.bones[fsrc].head for fsrc, _ue in finger_first.items() if self.bones[fsrc].parent == src]
            aim = _scale(_add_all(heads), 1.0 / len(heads)) if heads else None
            self.add(name, src, None, "finger", side, aim=aim, category=CATEGORY_FINGER)

        for mhx, ue in FINGERS:
            prev = None
            for idx in range(1, 5):
                src = self.pick("%s.%02d.%s" % (mhx, idx, side_mhx))
                if not src:
                    break
                kind = "thumb" if ue == "thumb" else "finger"
                pb = self.add("%s_%02d_%s" % (ue, idx, side), src, None, kind, side,
                              category=CATEGORY_FINGER)
                if prev is not None:
                    prev.aim = pb.head
                prev = pb
        middle = plan.by_name.get("middle_01_%s" % side)
        if middle is not None:
            hand.aim = middle.head

    def twists_of(self, main_name):
        return [b for b in self.plan.bones if b.parent == main_name and b.category == CATEGORY_TWIST]

    def add_leg(self, side_mhx, side):
        plan = self.plan
        plan.aliases["leg_parent.%s" % side_mhx] = "pelvis"
        plan.aliases["legSocket.%s" % side_mhx] = "pelvis"
        thigh = self.add_segment("thigh", "thigh", side_mhx, side, "pelvis", "leg")
        calf = self.add_segment("shin", "calf", side_mhx, side, thigh or "pelvis", "leg")
        foot_src = self.pick("foot.%s" % side_mhx)
        if foot_src is None:
            plan.errors.append("Missing MHX foot.%s deform bone." % side_mhx)
            return
        foot = self.add("foot_%s" % side, foot_src, calf or thigh or "pelvis", "foot", side)
        plan.aliases["foot.%s" % side_mhx] = foot.name
        ball_src = self.pick("toe.%s" % side_mhx)
        if ball_src:
            ball = self.add("ball_%s" % side, ball_src, None, "ball", side)
            foot.aim = ball.head
        else:
            plan.warnings.append("No toe.%s bone: ball_%s will be missing." % (side_mhx, side))
        if thigh and calf:
            plan.by_name[thigh].aim = plan.by_name[calf].head
            for tw in self.twists_of(thigh):
                tw.aim = _add(tw.head, _scale(_unit(_sub(plan.by_name[calf].head, plan.by_name[thigh].head)),
                                              _length(_sub(tw.aim, tw.head))))
        if calf:
            plan.by_name[calf].aim = foot.head
            for tw in self.twists_of(calf):
                tw.aim = _add(tw.head, _scale(_unit(_sub(foot.head, plan.by_name[calf].head)),
                                              _length(_sub(tw.aim, tw.head))))

    # ------------------------------------------------------------------
    #   everything else
    # ------------------------------------------------------------------

    def add_generic(self):
        plan = self.plan
        covered = set(plan.src_to_export)
        extras = sorted(name for name in self.live if name not in covered)
        for src in extras:
            name = self.unique(generic_name(src))
            self.add(name, src, None, "keep", split_side(strip_driver_suffix(src))[1],
                     category=CATEGORY_EXTRA)

    def logical_parent(self, pb):
        """Nearest exported ancestor of a bone in the source hierarchy."""
        plan = self.plan
        bone = self.bone(pb.source)
        name = bone.parent if bone else None
        seen = set()
        while name is not None and name not in seen:
            seen.add(name)
            if name in plan.src_to_export and plan.src_to_export[name] != pb.name:
                return plan.src_to_export[name]
            if name in plan.aliases:
                return plan.aliases[name]
            parent = self.bone(name)
            name = parent.parent if parent else None
        return "pelvis"

    def finish(self):
        plan = self.plan
        for pb in plan.bones:
            if pb.parent is None and pb.name != "pelvis" and pb.category != CATEGORY_IK:
                pb.parent = self.logical_parent(pb)

        self.break_cycles()

        # categorise non-humanoid bones by their exported ancestry
        for pb in plan.bones:
            if pb.category != CATEGORY_EXTRA:
                continue
            for anc in self.ancestors(pb):
                if anc == "head":
                    pb.category = CATEGORY_FACE
                    break
                if anc.startswith(("foot_", "ball_")) and plan.by_name[anc].category == CATEGORY_CORE:
                    pb.category = CATEGORY_TOE
                    break

        ordered = self.topo_order()

        # drop excluded categories, merging their weights into the survivor
        kept = []
        target = {}
        owner = {}
        for pb in ordered:
            if pb.category in self.include and not self.include[pb.category]:
                target[pb.name] = target.get(pb.parent, pb.parent)
                if pb.source:
                    plan.merged[pb.source] = target[pb.name]
            else:
                target[pb.name] = pb.name
                kept.append(pb)
            if pb.source:
                owner[pb.source] = target[pb.name]
        for pb in kept:
            if pb.parent is not None:
                pb.parent = target.get(pb.parent, pb.parent)
        plan.bones = kept
        plan.by_name = {pb.name: pb for pb in kept}
        for src, name in list(plan.src_to_export.items()):
            plan.src_to_export[src] = target.get(name, name)
        for alias, name in list(plan.aliases.items()):
            plan.aliases[alias] = target.get(name, name)

        # weights follow the bone whose pose they are baked from
        for src in self.live:
            if src in owner:
                plan.weight_map[src] = owner[src]
            elif src in plan.src_to_export:
                plan.weight_map[src] = plan.src_to_export[src]

        if "master" in self.bones:
            plan.root_motion_source = "master"

    def ancestors(self, pb):
        seen = set()
        name = pb.parent
        while name and name not in seen:
            seen.add(name)
            yield name
            parent = self.plan.by_name.get(name)
            name = parent.parent if parent else None

    def break_cycles(self):
        by_name = self.plan.by_name
        for pb in self.plan.bones:
            seen = {pb.name}
            name = pb.parent
            while name:
                if name in seen or name not in by_name:
                    self.plan.warnings.append("Re-parented %s to pelvis (bad hierarchy)." % pb.name)
                    pb.parent = "pelvis" if pb.name != "pelvis" else None
                    break
                seen.add(name)
                name = by_name[name].parent

    def topo_order(self):
        by_name = self.plan.by_name
        children = {}
        roots = []
        for pb in self.plan.bones:
            if pb.parent and pb.parent in by_name:
                children.setdefault(pb.parent, []).append(pb)
            else:
                roots.append(pb)
        ordered = []
        stack = list(reversed(roots))
        while stack:
            pb = stack.pop()
            ordered.append(pb)
            stack.extend(reversed(children.get(pb.name, [])))
        return ordered

    def add_ik_bones(self):
        plan = self.plan
        size = 0.1
        if "foot_l" in plan.by_name or "foot_r" in plan.by_name:
            self.add(IK_FOOT_ROOT, None, None, "ik_root", head=(0.0, 0.0, 0.0),
                     aim=(0.0, size, 0.0), category=CATEGORY_IK)
            for side in ("l", "r"):
                foot = plan.by_name.get("foot_%s" % side)
                if foot:
                    self.add("ik_foot_%s" % side, None, IK_FOOT_ROOT, "ik_copy", side,
                             head=foot.head, aim=foot.aim, category=CATEGORY_IK, copy_of=foot.name)
        hand_r = plan.by_name.get("hand_r")
        if hand_r:
            self.add(IK_HAND_ROOT, None, None, "ik_root", head=(0.0, 0.0, 0.0),
                     aim=(0.0, size, 0.0), category=CATEGORY_IK)
            self.add(IK_HAND_GUN, None, IK_HAND_ROOT, "ik_copy", "r",
                     head=hand_r.head, aim=hand_r.aim, category=CATEGORY_IK, copy_of="hand_r")
            for side in ("l", "r"):
                hand = plan.by_name.get("hand_%s" % side)
                if hand:
                    self.add("ik_hand_%s" % side, None, IK_HAND_GUN, "ik_copy", side,
                             head=hand.head, aim=hand.aim, category=CATEGORY_IK, copy_of=hand.name)


def _unit(v):
    length = _length(v)
    if length < 1e-9:
        return (0.0, 0.0, 1.0)
    return _scale(v, 1.0 / length)


def _add_all(vectors):
    total = (0.0, 0.0, 0.0)
    for v in vectors:
        total = _add(total, v)
    return total


def build_plan(bones, weighted, include_face=True, include_toes=True,
               include_extra=True, add_ik=True):
    """Build the export skeleton plan.

    bones    -- dict name -> SourceBone for every bone of the source armature
    weighted -- names of vertex groups that carry non-zero weights on the
                exported meshes (only those matching deform bones matter)
    """
    planner = _Planner(bones, weighted, include_face, include_toes, include_extra, add_ik)
    plan = planner.run()
    for required in ("pelvis", "head", "hand_l", "hand_r", "foot_l", "foot_r"):
        if not plan.errors and required not in plan.by_name:
            plan.errors.append("Export skeleton is missing '%s'." % required)
    return plan


# ----------------------------------------------------------------------
#   IK Rig chains (names follow UE's Mannequin IK Rig)
# ----------------------------------------------------------------------

FINGER_CHAIN_NAMES = (
    ("thumb", "Thumb"), ("index", "Index"), ("middle", "Middle"),
    ("ring", "Ring"), ("pinky", "Pinky"),
)


def retarget_chains(plan):
    """Ordered list of (chain name, start bone, end bone, goal bone or None)."""
    names = set(plan.by_name)
    chains = [("Root", ROOT_NAME, ROOT_NAME, None)]

    def span(prefix, count=12):
        return [n for n in ("%s_%02d" % (prefix, i) for i in range(1, count)) if n in names]

    spine = span("spine")
    if spine:
        chains.append(("Spine", spine[0], spine[-1], None))
    neck = span("neck")
    if neck:
        chains.append(("Neck", neck[0], neck[-1], None))
    if "head" in names:
        chains.append(("Head", "head", "head", None))

    for side, label in (("l", "Left"), ("r", "Right")):
        def has(n):
            return ("%s_%s" % (n, side)) in names

        def bone(n):
            return "%s_%s" % (n, side)

        if has("clavicle"):
            chains.append((label + "Clavicle", bone("clavicle"), bone("clavicle"), None))
        if has("upperarm") and has("hand"):
            chains.append((label + "Arm", bone("upperarm"), bone("hand"), bone("hand")))
        for stem, finger_label in FINGER_CHAIN_NAMES:
            segs = [n for n in ("%s_%02d_%s" % (stem, i, side) for i in range(1, 5)) if n in names]
            meta = "%s_metacarpal_%s" % (stem, side)
            start = meta if meta in names else (segs[0] if segs else None)
            if start and segs:
                chains.append((label + finger_label, start, segs[-1], None))
        if has("thigh") and has("foot"):
            chains.append((label + "Leg", bone("thigh"), bone("foot"), bone("foot")))
        if has("ball"):
            chains.append((label + "Ball", bone("ball"), bone("ball"), None))

    for chain, bone_name in (
        ("FootRootIK", IK_FOOT_ROOT), ("LeftFootIK", "ik_foot_l"), ("RightFootIK", "ik_foot_r"),
        ("HandRootIK", IK_HAND_ROOT), ("HandGunIK", IK_HAND_GUN),
        ("LeftHandIK", "ik_hand_l"), ("RightHandIK", "ik_hand_r"),
    ):
        if bone_name in names:
            chains.append((chain, bone_name, bone_name, None))
    return chains
