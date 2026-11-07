# Building the mod

Only needed if you change something. Players just use the installer from the [releases page](https://github.com/HimariHikari/ievan-polkka-psp-mod/releases/latest).

## Folder layout

| Folder | What's in it |
|---|---|
| `game/original/` | The English-patched Project DIVA ISO (input; not in the repo) |
| `game/modded/` | The built mod ISO (not in the repo) |
| `release/` | The zip that gets shared (not in the repo; attached to GitHub releases) |
| `assets/dance/` | Unity project with the Ievan Polkka dance motion (not in the repo) |
| `assets/camera/` | `ievan_camera.vmd`, the MMD camera motion (not in the repo) |
| `assets/stage/` | PDAFT Field stage textures (not in the repo) |
| `tools/` | Python build scripts |
| `installer/` | The installer: `IevanPolkkaPatcher.cs` and the player README. `payload.bin` and the `.exe` are built locally |
| `work/` | Build files made by the tools. `work/unity_bake/Assets/Editor/PspBake.cs` is the Unity bake script |

## Requirements

Python 3 with numpy and Pillow, 7-Zip, and Unity 6000.3.1f1 (only for the dance bake). Run the commands below from the project root in Git Bash.

## Steps

**0. Extract the game files.** `work/iso` isn't kept, so do this before any rebuild:

```bash
"/c/Program Files/7-Zip/7z.exe" x -y -o"work/iso" "game/original/Hatsune Miku - Project Diva (English v1.0).iso"
py -P tools/afs.py work/iso/PSP_GAME/USRDIR/media/afs/DivaDataList.afs work/data
py -P tools/afs.py work/iso/PSP_GAME/USRDIR/media/afs/DivaScriptList.afs work/dsc
```

**1. Dance.** Unity bakes the motion headlessly to `work/ievan_frames.bin`, using `work/psp_skeleton.json`; then convert it to PSP motion files:

```bash
"/c/Program Files/Unity/Hub/Editor/6000.3.1f1/Editor/Unity.exe" -batchmode -nographics -projectPath work/unity_bake -executeMethod PspBake.Run -logFile work/debug/unity_bake.log -skel work/psp_skeleton.json -clip Assets/Clip/IevanPolkkaPD.anim -out work/ievan_frames.bin -fps 30
py -P tools/build_motion.py work
```

**2. Camera:**

```bash
py -P tools/camera_convert.py assets/camera/ievan_camera.vmd work
```

**3. Level and leeks:**

```bash
py -P tools/level_build.py work assets/stage work/data/0465_fst00_00_59.igb work/data/0475_field_pv_03.igb work/out/stage_ievan.igb
```

**4. Lip sync:**

```bash
py -P tools/lipsync.py "assets/dance/Assets/Ievan Polkka Project Diva Fixed Motion/Ievan Polkka Project Diva.anim" work
```

**5. ISO.** This also remakes `work/build_tmp`, which step 6 needs:

```bash
cd work && py -P ../tools/build_iso.py "../game/original/Hatsune Miku - Project Diva (English v1.0).iso" . "../game/modded/Hatsune Miku - Project Diva (English) - Ievan Polkka dance.iso"
```

**6. Installer:**

```bash
cd work && py -P ../tools/make_payload.py . ../installer/payload.bin
cd ../installer && /c/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe -nologo -optimize+ -target:winexe -out:IevanPolkkaPatcher.exe -resource:payload.bin,payload.bin -r:System.Windows.Forms.dll -r:System.Drawing.dll IevanPolkkaPatcher.cs
```

Then zip `IevanPolkkaPatcher.exe`, `README.txt` and `IevanPolkkaPatcher.cs` (inside a `source/` folder) into `release/`.

`work/psp_skeleton.json`, `work/fist_left.npy`, `work/fist_right.npy` and the `work/unity_bake/` project came from one-off steps. Keep them; the commands above don't remake them.

## How it works (short version)

- **Data:** the game hangs on "Now Loading" if `DivaDataList.afs` has more than 1757 entries, so the mod reuses slots instead of adding files:
  - motion goes in songSG #304–307;
  - the level and leeks go in `pve_27` #926;
  - extra cameras go into `sgc00_00_00` #986.
- **Scripts:** the PV scripts (`pv_27_*.dsc`) get camera cuts, the level and leek effects, mouth and hand commands. The original note charts are kept.
- **Stage:** `pve_27` is PV 27's field (`CHANGE_FIELD 1`). A field draws every scene in the file on the song clock, so the leek sections (scenes 2–4) are keyed in song time: a hidden key at 0 s, the section's frames at their real times, and a hidden key at 160 s, the way the game's own `field_pv_05` is keyed. Only the first leek part (54-66 s) is ever shown; the later sections stay in the file, hidden. The `EFFECT`/`EFFECT_OFF` pairs use their own slots (the last `EFFECT` value is the slot that `EFFECT_OFF` names).
- **EBOOT:** one byte unlocks the song on a new save, and PV 27's field list (originally its 25 slideshow pictures) points at `pve_27`.
- **Installer:** it carries only the replaced archive entries and the EBOOT byte patches. It checks SHA-1 hashes of the player's files before patching.
