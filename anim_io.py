# SPDX-FileCopyrightText: 2026 Kyle Austad
# SPDX-License-Identifier: GPL-2.0-or-later
"""Action helpers for Blender's layered (slotted) action API (4.4+)."""

import bpy

_LINEAR = 1  # index of 'LINEAR' in FCurve keyframe interpolation enum


def iter_fcurves(action):
    """All F-Curves of an action, layered or legacy."""
    layers = getattr(action, "layers", None)
    if layers is not None:
        for layer in layers:
            for strip in layer.strips:
                for bag in getattr(strip, "channelbags", ()):
                    yield from bag.fcurves
        return
    yield from getattr(action, "fcurves", ())


def action_slot_for(action, id_type="OBJECT", animated_id=None):
    """Best slot of an action for an ID, or None."""
    slots = getattr(action, "slots", None)
    if slots is None:
        return None
    if animated_id is not None and animated_id.animation_data:
        ad = animated_id.animation_data
        if ad.action == action and ad.action_slot is not None:
            return ad.action_slot
        for slot in getattr(ad, "action_suitable_slots", ()):
            if slot in slots.values():
                return slot
    for slot in slots:
        if getattr(slot, "target_id_type", id_type) == id_type:
            return slot
    return slots[0] if len(slots) else None


def assign_action(animated_id, action, slot=None):
    ad = animated_id.animation_data or animated_id.animation_data_create()
    ad.action = action
    if action is not None and hasattr(ad, "action_slot"):
        if slot is None:
            slot = action_slot_for(action, animated_id.id_type, animated_id)
        if slot is not None:
            ad.action_slot = slot


class ActionWriter:
    """Create an action and write sampled curves in bulk."""

    def __init__(self, name, id_type, slot_name):
        self.action = bpy.data.actions.new(name)
        self.slot = None
        if hasattr(self.action, "layers"):
            self.slot = self.action.slots.new(id_type=id_type, name=slot_name)
            layer = self.action.layers.new("Layer")
            strip = layer.strips.new(type='KEYFRAME')
            self._fcurves = strip.channelbag(self.slot, ensure=True).fcurves
        else:
            self._fcurves = self.action.fcurves

    def curve(self, data_path, index, frames, values):
        fc = self._fcurves.new(data_path, index=index)
        count = len(frames)
        points = fc.keyframe_points
        points.add(count)
        co = [0.0] * (count * 2)
        co[0::2] = frames
        co[1::2] = values
        points.foreach_set("co", co)
        points.foreach_set("interpolation", [_LINEAR] * count)
        fc.update()
        return fc

    def assign(self, animated_id):
        assign_action(animated_id, self.action, self.slot)
