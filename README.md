# Unreal MHX

Blender add-on that exports Diffeomorphic **MHX** characters (DAZ Genesis 3/8/9
imported with the DAZ Importer and converted to MHX) as Unreal Engine 5
skeletal meshes with a **UE5 Mannequin-style skeleton**: same bone names,
hierarchy, bone axes, IK bones and root as Manny/Quinn, the way Auto-Rig Pro's
UE5 export does it. Manny/Quinn animations retarget onto it through UE's IK
Retargeter, and Control Rig / IK setups made for Mannequin-like skeletons
work.

It does **not** convert the character to the Manny skeleton. Proportions and
bind pose stay the DAZ ones, and every DAZ deform bone, morph and weight is
kept.

## How it works

You keep working on the MHX rig as usual (Diffeomorphic morphs, MHX FK/IK,
actions, NLA). On export the add-on:

1. Plans a clean deform-only skeleton from the MHX rig. The MHX helper bones
   (`arm_parent`, `leg_parent`, `neckParent`, `hand.L` ...) are dropped and
   the deform bones get Mannequin names and parents:
   `root > pelvis > spine_01..04 > neck_01..02 > head`,
   `clavicle_l > upperarm_l > lowerarm_l > hand_l > fingers`,
   `pelvis > thigh_l > calf_l > foot_l > ball_l`, plus `ik_foot_root`,
   `ik_foot_l/r`, `ik_hand_root`, `ik_hand_gun`, `ik_hand_l/r`.
2. MHX splits every limb in a *bend* half (swing only) and a *twist* half
   (full rotation). The twist half becomes the main bone (`upperarm_l`,
   carrying the full limb rotation, placed at the joint) and the bend half
   becomes `upperarm_twist_01_l`. Same convention as Manny.
3. Face, toe, breast, geograft and any other weighted deform bones are kept
   with sanitized names (`jaw`, `eye_l`, `bigtoe_01_l`, `pectoral_l` ...),
   parented to their nearest exported bone.
4. Bones are oriented with the UE5 Mannequin axes (verified against Auto-Rig
   Pro's UE5 export).
5. Meshes are copied, re-skinned to the new bone names and built in
   centimeters ("Units x100"). The armature object itself is named `root` and
   becomes Unreal's root bone, so there is no scale anywhere in the hierarchy.
6. Animation is baked from the *evaluated* MHX rig (IK, constraints, drivers,
   NLA) with `P_export = P_mhx @ R_mhx^-1 @ R_export`, so the exported mesh
   deforms exactly like the MHX mesh (within 0.002 mm on a Genesis 9
   character). The MHX `master` bone becomes root motion. Morph values
   (expressions, JCMs, FACS) are baked as morph target curves.

Your character is never modified. Everything is built on copies in a
temporary collection and removed after the export. The only exception is a
small custom property that remembers rest-pose morph values (see *Bake Rest
Morphs*).

## Requirements

* Blender 4.4+ (developed and tested on 5.1)
* Diffeomorphic DAZ Importer (only needed for the *Convert to MHX* button)
* MHX Runtime System is optional. The exporter does not need it.
* Unreal Engine 5.6 / 5.7 for the setup script (export works with any UE5)

## Install

Blender: *Edit > Preferences > Get Extensions > Install from Disk...* and pick
`dist/unreal_mhx-1.0.0.zip`. To build the zip yourself:

```bash
blender -b --factory-startup --command extension build --source-dir unreal_mhx --output-dir dist
```

The panel lives in the 3D Viewport sidebar (N) under **Unreal MHX**.

## Workflow

### 1. Import and convert

1. Import the DAZ character with the DAZ Importer (default meter scale).
2. Select the armature. In **Unreal MHX** click **Convert to MHX (UE Preset)**.
   It runs Diffeomorphic's *Convert To MHX* with game-friendly options: no
   stretchy limbs, split bend/twist bones, no extra IK helpers. A rig converted
   with Diffeomorphic's own button works too. Stretchy limbs then produce bone
   scale that Unreal cannot reproduce exactly, and the export warns about it.
3. Edit, add morphs, pose and animate with MHX as usual.

### 2. Export

* **Character**: set the name and folder, tick the meshes, then **Export
  Character**. This writes `<Name>.fbx` (skeletal mesh, rest pose, morph
  targets) and `<Name>_Skeleton.json` (for the Unreal script).
* **Animation**: choose
  * **Timeline**: the scene frame range as it plays (active action, NLA,
    drivers). Writes `<Name>_<AnimName>.fbx`.
  * **Actions**: every ticked action in the list, each to its own
    `<Name>_<Action>.fbx` (NLA is muted while baking).
* **Export Both** does character + animation in one pass.
* **Check Rig** writes the full bone mapping to the `UnrealMHX_Report` text
  block without exporting.
* **Preview** builds the export skeleton and meshes in the scene and bakes the
  timeline, so you can scrub and compare them with the MHX character. Remove
  them with **Remove Preview**.

Animation files contain the meshes too (option *Include Meshes*) so Unreal
imports the morph target curves.

### 3. Import into Unreal

Character FBX (`<Name>.fbx`): drag into the Content Browser.

* Import as **Skeletal Mesh**, Skeleton **none** (a new `<Name>_Skeleton`
  is created).
* **Import Morph Targets** on.
* **Use T0 As Reference Pose** off, **Force Front X Axis** off, uniform scale 1.
* Import Animations off.

Animation FBX: import with **Skeleton = `<Name>_Skeleton`**, mesh import off
(animation only). Morph curves come along.

You get a 1:1 scale character (cm), root bone `root`, facing +Y like Manny.

### 4. Retarget Manny / Quinn animations

**Quick way (no script)**: right-click Manny/Quinn animations > *Retarget
Animations*, pick the character as target. UE's auto-characterization
recognises the Mannequin names and builds the IK Rigs and retargeter.

**Scripted, reusable assets**: `unreal_mhx/ue/setup_unreal_mhx.py` (also in
the add-on zip) creates `IK_<Name>` (retarget root `pelvis`, chains, IK goals,
Full Body IK) and `RTG_Mannequin_To_<Name>`.

1. Enable the *Python Editor Script Plugin* and *IK Rig* plugins.
2. Edit the CONFIG block: `SKELETON_JSON` = path of `<Name>_Skeleton.json`,
   optionally `SKELETAL_MESH` and `SOURCE_IK_RIG` (default
   `/Game/Characters/Mannequins/Rigs/IK_Mannequin` from the Third Person
   template).
3. *Tools > Execute Python Script...* and pick the file.
4. Open the retargeter, check the retarget pose (DAZ is an A-pose like Manny;
   use *Auto Align* if the arms differ), and export or batch-retarget.

The script prefers UE's own auto-characterization and falls back to the chain
list in the JSON. Every editor API call is guarded, and anything that fails on
your UE version is logged with `[Unreal MHX]` in the Output Log.

### 5. Animating in Unreal

The Mannequin names and axes mean Control Rig setups for Mannequin-like
skeletons apply directly. That includes UE 5.5+ *Modular Control Rig*, foot
IK, and Two Bone IK on `upperarm/lowerarm/hand` and `thigh/calf/foot`. The
`ik_*` bones are animated like Manny's (option *Animated IK Bones*).

## Options

| Option | Default | Notes |
|---|---|---|
| Face / Toe / Extra Bones | on | Off merges their weights into the parent bone (head, foot/ball, nearest bone). |
| Mannequin Axes | on | UE5 Mannequin bone orientation. Skinning is identical either way. |
| IK Bones / Animated IK Bones | on / on | Manny's `ik_foot_*` / `ik_hand_*` bones, following feet and hands. |
| Root Motion | on | MHX `master` bone (and rig object) motion is baked onto the root. |
| Morph Targets | on | Shape keys become morph targets, and their animation becomes curves. |
| Bake Rest Morphs | on | Shape keys that are non-zero in rest pose (dialed body or face shapes) are baked into the mesh, so the character looks right in UE with every morph at 0. Animation curves are exported relative to that. The values are remembered on the meshes; use *Re-read Rest Morphs* after changing dials and re-export both. |
| Max Influences | 12 | DAZ uses up to ~20 per vertex. Unreal keeps 12, so 12 makes Blender match Unreal. Use 8 or 4 for game/mobile budgets. |
| Units x100 | on | Centimeters with no root scale (ARP default). Leave on. |

## Known limitations

* **Corrective morphs (JCMs) on retargeted animations**: JCMs are baked as
  curves into animations exported from Blender. Animations retargeted inside
  Unreal do not drive them. That needs a UE pose-driver setup, which is not
  part of this version.
* **Twist bones on retargeted animations** follow their parent, same as with
  Auto-Rig Pro. Animations baked from Blender carry the exact MHX twist.
* **Preserve Volume**: Diffeomorphic enables dual-quaternion skinning on the
  Armature modifier. Unreal skins linearly, so shoulders and elbows look
  slightly different from Blender. Untick *Preserve Volume* on the modifier to
  preview the Unreal result. The export warns about this.
* **Stretchy limbs**: bone scale on a parent cannot be reproduced exactly by
  Unreal (or FBX). Use the UE preset (no stretch) or keep IK targets in reach.
* Mesh modifiers other than Armature (Subdivision, Geometry Nodes ...) are not
  exported. Hair curves/particles are not exported.
* Materials export as plain FBX materials. Rebuild DAZ shaders in Unreal.

## Repository layout

```
unreal_mhx/            the add-on (extension package)
  rig_map.py           MHX -> Mannequin skeleton plan (pure Python, unit tested)
  orient.py            Mannequin bone axes
  skeleton.py          builds the export armature
  meshes.py            mesh copies, re-skinning, rest morph baking
  bake.py              samples the MHX rig and bakes actions
  exporter.py          export session (build, export, restore)
  fbx_io.py            FBX settings
  ue/setup_unreal_mhx.py   Unreal Editor setup script
  tests/               unit tests and a headless Blender end-to-end test
_archive/unreal_mhx_0.6/   the previous version, kept for reference
reference/             Auto-Rig Pro and Diffeomorphic sources (study only, not shipped)
```

See [TESTING.md](TESTING.md) for the automated tests and the Unreal checklist.
