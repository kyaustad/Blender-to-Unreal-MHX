# Testing Unreal MHX

## Automated (no Unreal needed)

### Unit tests: skeleton mapping

Plain Python, no Blender:

```bash
python -m unittest discover -s unreal_mhx/tests -p "test_*.py"
```

### End-to-end test in headless Blender

Needs a `.blend` with a Diffeomorphic character (MHX or not yet converted; it
is converted in memory with the UE preset). The `.blend` is never saved.

```bash
blender -b --enable-autoexec "C:/Users/Watak/Documents/Blender/Violetta_Plugin_Test.blend" --python unreal_mhx/tests/blender_smoke.py -- "C:/Users/Watak/Documents/Blender/Unreal_MHX/smoke"
```

It keys a short test animation (IK hand and foot, chest, neck, root motion,
FACS morphs), exports character + animation, and checks:

* bone names and Mannequin hierarchy, `root` armature, IK bones
* the scene is restored after export (scene name, frame range, current frame,
  action, object and action counts)
* exported meshes deform like the MHX meshes on animated frames, with linear
  skinning on both sides (expected under 0.001 cm)
* the FBX files re-import: one armature, top bones `pelvis`, `ik_foot_root`,
  `ik_hand_root`, morph targets present, animation take present

Last result on the Genesis 9 test character (Blender 5.1.2): **PASS**, 267
bones, 408 body morphs, worst deformation error 0.00015 cm, export about 6 s
for 24 frames.

## Manual checklist in Unreal (5.6 / 5.7)

1. **Import** `<Name>.fbx` (Skeletal Mesh, Import Morph Targets on, Use T0 as
   Ref Pose off).
   * The Skeleton tree starts `root > pelvis`, with `ik_foot_root` and
     `ik_hand_root` under `root`.
   * Character height in cm (about 160-180), root bone scale 1, facing +Y.
   * The Morph Target preview lists the DAZ morphs. The character looks like
     Blender with every morph at 0.
2. **Import** `<Name>_<Anim>.fbx` onto `<Name>_Skeleton`. It plays like
   Blender: hands and feet where the MHX IK put them, face curves moving,
   root motion on `root`.
3. **Run** `unreal_mhx/ue/setup_unreal_mhx.py` with `SKELETON_JSON` set.
   * `IK_<Name>`: retarget root `pelvis`, chains Spine/Neck/Head/Left-RightArm
     /Leg/fingers, Full Body IK solver with hand and foot goals.
   * `RTG_Mannequin_To_<Name>`: chains auto-mapped.
4. **Retarget** a Manny run/idle. Feet plant, hands follow, no exploded
   bones. Note anything that needs a retarget pose tweak.
5. **Control Rig**: create a Modular Control Rig for the mesh (UE 5.5+) and
   check that the spine/arm/leg modules pick up the bones.

Report anything off together with the Output Log lines starting with
`[Unreal MHX]` and the `UnrealMHX_Report` text from *Check Rig* in Blender.
