# SPDX-FileCopyrightText: 2026 Kyle Austad
# SPDX-License-Identifier: GPL-2.0-or-later
"""Unreal Mannequin bone axes for the export skeleton.

Blender's FBX exporter (forward -Z, up Y, primary bone axis Y) and Unreal's
importer together map Blender space to Unreal space as a Y mirror. Under that
mirror a Blender bone frame (X, Y, Z) shows up in Unreal as (X, -Y, Z)
measured in character directions (up / forward / right). The frames below
are therefore the Mannequin frames with their Y axis negated.

Mannequin conventions reproduced here (Unreal axes, character directions):

  spine/pelvis/neck/head  X along chain (up),   Y forward,  Z right
  left arm                X toward child,       Y forward,  Z up
  right arm               X toward parent,      Y back,     Z down
  left hand/fingers       X toward child,       Y up,       Z back
  right hand/fingers      X toward parent,      Y down,     Z forward
  left thumb              X toward child,       Y forward,  Z up (back of hand)
  right thumb             X toward parent,      Y back,     Z down
  left leg                X up (toward parent), Y forward,  Z inside
  right leg               X down (to child),    Y back,     Z outside
  left foot               X up,                 Y forward,  Z inside
  right foot              X down,               Y back,     Z outside
  left ball               X forward,            Y down,     Z inside
  right ball              X back,               Y up,       Z outside

The source character must face -Y in Blender (Diffeomorphic default).
"""

from mathutils import Matrix, Vector

UP = Vector((0.0, 0.0, 1.0))
DOWN = -UP
FORWARD = Vector((0.0, -1.0, 0.0))
BACK = -FORWARD
RIGHT = Vector((-1.0, 0.0, 0.0))  # character's right when facing -Y
LEFT = -RIGHT

MANNEQUIN_KINDS = {"pelvis", "spine", "arm", "hand", "finger", "thumb", "leg", "foot", "ball"}

_AXES = "XYZ"


def _orthogonal(vec, axis):
    out = vec - axis * vec.dot(axis)
    if out.length < 1e-6:
        return None
    return out.normalized()


def _fallback_secondary(primary):
    for cand in (BACK, UP, LEFT):
        out = _orthogonal(cand, primary)
        if out is not None:
            return out
    return Vector((1.0, 0.0, 0.0))


def basis(primary_axis, primary, secondary_axis, secondary):
    """Right-handed 3x3 matrix whose columns are the X, Y, Z axes."""
    p = Vector(primary)
    if p.length < 1e-9:
        p = UP.copy()
    p.normalize()
    s = _orthogonal(Vector(secondary), p) or _fallback_secondary(p)
    axes = {primary_axis: p, secondary_axis: s}
    third = next(a for a in _AXES if a not in axes)
    i = _AXES.index(third)
    nxt = axes[_AXES[(i + 1) % 3]]
    nxt2 = axes[_AXES[(i + 2) % 3]]
    axes[third] = nxt.cross(nxt2).normalized()
    return Matrix((axes["X"], axes["Y"], axes["Z"])).transposed()


def _flatten(vec, keep_z=0.05):
    out = Vector((vec.x, vec.y, vec.z * keep_z))
    return out.normalized() if out.length > 1e-9 else FORWARD.copy()


def _horizontal(vec):
    out = Vector((vec.x, vec.y, 0.0))
    return out.normalized() if out.length > 1e-9 else FORWARD.copy()


def mannequin_frame(kind, side, head, aim, palm_up=None):
    """3x3 rest rotation for a bone of the given kind in Blender armature space."""
    d = Vector(aim) - Vector(head)
    d = d.normalized() if d.length > 1e-9 else UP.copy()
    left = side != "r"
    n = Vector(palm_up) if palm_up is not None else UP

    if kind == "pelvis":
        return basis("X", UP, "Y", BACK)
    if kind == "spine":
        return basis("X", d, "Y", BACK)
    if kind == "arm":
        if left:
            return basis("X", d, "Y", BACK)
        return basis("X", -d, "Y", FORWARD)
    if kind in ("hand", "finger"):
        if left:
            return basis("X", d, "Y", -n)
        return basis("X", -d, "Y", n)
    if kind == "thumb":
        # the thumb curls about the back-of-hand normal, not across the palm
        if left:
            return basis("X", d, "Z", n)
        return basis("X", -d, "Z", -n)
    if kind == "leg":
        if left:
            return basis("X", -d, "Y", BACK)
        return basis("X", d, "Y", FORWARD)
    if kind == "foot":
        if left:
            return basis("Y", _flatten(-d), "Z", RIGHT)
        return basis("Y", _flatten(d), "Z", RIGHT)
    if kind == "ball":
        if left:
            return basis("Y", UP, "X", _horizontal(d))
        return basis("Y", DOWN, "X", -_horizontal(d))
    raise ValueError("No Mannequin frame for kind %r" % kind)


def palm_normal(hand_head, hand_aim, index_head, pinky_head):
    """Back-of-hand normal (points up in A/T pose) for one hand."""
    h = Vector(hand_aim) - Vector(hand_head)
    across = Vector(index_head) - Vector(pinky_head)
    n = h.cross(across)
    if n.length < 1e-9:
        return UP.copy()
    n.normalize()
    if n.dot(UP) < 0.0:
        n.negate()
    return n
