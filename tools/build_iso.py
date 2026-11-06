"""Build a patched Project DIVA (PSP, ULJM-05472, English v1.0) ISO where PV 27 (Ievan Polkka)
gets a real 3D Miku dance converted from the Unity humanoid motion, unlocked on a new save.

usage: py -P build_iso.py <original.iso> <work dir> <out.iso> [--no-notes]

  --no-notes   TEST ONLY: strip the rhythm-game notes from PV 27 so the whole PV plays without
               failing (lets you watch the full dance without playing).

What it changes (and nothing else):
  * DivaDataList.afs  slots #304-#307 (songSG body + 3 heads, the motion PV 27 already loads)
                      -> new Ievan Polkka body/hair motion. File count stays 1757: the game hangs
                      on "Now Loading" if files are appended past the original count.
                      The slideshow PVs 29-32 also load songSG but never show Miku; the new files
                      keep the result-screen clips they use.
  * DivaScriptList.afs pv_27_{easy,normal,hard}.dsc -> show Miku, start the dance, drop the
                      illustration slideshow. Miku is moved in front of PV 27's existing camera
                      (sgc00_00_00, shared with PVs 29-32, left untouched).
  * EBOOT.BIN         new-save unlock table: PV 27 unlocked from the start.
"""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import afs, dsc, isopatch
import numpy as np

AFS_DIR = 'PSP_GAME/USRDIR/media/afs'
IEVAN_PV = 27
SONGSG_SLOTS = (304, 305, 306, 307)     # songSG_anim_body + 3 heads (PV 27's motion slot in the EBOOT PV table)
PV_MODE_TABLE = 0x320CB0               # EBOOT.BIN file offset: per-song table right after easy/normal (1 for PVs 1-14, 17)
UNLOCK_TABLE = 0x320C44                 # EBOOT.BIN file offset of the 36-byte "unlocked on a new save" table
PATCH_PV_MODE = '--pv-mode' in sys.argv
UNLOCK_DEFAULT = bytes([0,1,0,0,0,1,0,0,0,0,1,0,0,0,0,1,1,0,0,0,0,1] + [0] * 14)
PV_TABLE_MOTION_PV1 = 0x36380C          # EBOOT.BIN file offset of PV 1's motion field; 1000-byte records

# The slideshow camera (camera_01 at z=+2.76 looking down -z, eye height 0). Putting Miku 14.5 units in
# front of it and 3.8 units below the eye line frames her full body. MIKU_MOVE is in 1/1000 units.
MIKU_OFFSET = (0, -3800, -11740)
SLIDESHOW_CAMERA = 986                  # sgc00_00_00.igb: PV 27's camera file (shared with PVs 29-32)
CAMERA_NPZ = 'ievan_camera.npz'         # from camera_convert.py; when present, PV 27 gets the converted cameras
STAGE_IGB = 'out/stage_ievan.igb'       # from stage_build.py; when present, it becomes PV 27's stage
PVE27_SLOT = 926                        # pve_27.igb: PV 27's own effect file (slideshow overlay), reused for the stage
FIELD_LIST_REL = -520                   # PV record: field list, relative to the motion field
RIGHT_HAND = 1                          # HAND_ANIM hand index for Miku's right hand (to be confirmed in game)
FIST_POSE = 1                           # HAND_ANIM pose used for gripping a leek (to be confirmed in game)
LEEK_SECTIONS = []                      # [{effect, start, end}] from level_build.py
MOUTH_EVENTS = []                       # [(time s, mouth id)] from lipsync.py
HAND_FISTS = []                         # [(hand index, [(start s, end s), ...])], filled from the leek windows


def patch_dsc(raw, no_notes=False, animated_camera=False, camera_cuts=(), stage=False):
    cmds = dsc.parse(raw)
    out = []
    for t, name, args in cmds:
        if name in ('CHANGE_FIELD', 'FADEOUT_FIELD'):
            continue                                    # illustration slideshow would cover Miku
        if no_notes and name == 'TARGET':
            continue
        if name == 'DATA_CAMERA' and t == 0 and animated_camera:
            continue                                            # replaced by the lens cuts below
        if stage and name in ('EFFECT', 'EFFECT_OFF'):
            continue                                            # pve_27 now holds the stage, not the slideshow overlay
        if name == 'MIKU_DISP' and t == 0:
            move = (0, 0, 0) if animated_camera else MIKU_OFFSET
            out += [(0, 'MIKU_DISP', (1,)), (0, 'MIKU_MOVE', move), (0, 'MIKU_ROT', (0,)),
                    (0, 'SET_PLAYDATA', (1,)), (0, 'SET_MOTION', (1, 0)),
                    (0, 'MIKU_SHADOW', (0,))]           # no floor yet -> no floating shadow
            continue
        out.append((t, name, args))
    extra = [(int(round(t * 100000)), 'DATA_CAMERA', (0, int(cid))) for t, cid in camera_cuts]
    for t, mouth in MOUTH_EVENTS:                                # lip sync from the Unity clip's mouth blendshapes
        extra.append((int(round(t * 100000)), 'MOUTH_ANIM', (int(mouth), 100)))
    for hand, segs in HAND_FISTS:                                # close the fist while a leek is held
        for a, b in segs:
            extra += [(int(round(a * 100000)), 'HAND_ANIM', (hand, FIST_POSE)),
                      (int(round(b * 100000)), 'HAND_ANIM', (hand, 0))]
    if stage:
        extra.append((0, 'CHANGE_FIELD', (1,)))            # scene 1 of pve_27: the level (static stage)
        for sec in LEEK_SECTIONS:                            # scenes 2..N of pve_27: one leek section each
            extra.append((int(round(sec['start'] * 100000)), 'EFFECT', (sec['effect'], 0, 0, 0, 1)))
            extra.append((int(round(sec['end'] * 100000)), 'EFFECT_OFF', (sec['effect'],)))
    return dsc.write(dsc.merge(out, extra))


def main(src_iso, work, out_iso, no_notes=False):
    import json
    ls = os.path.join(work, 'leek_sections.json')
    if os.path.exists(ls):
        LEEK_SECTIONS[:] = json.load(open(ls))
    me = os.path.join(work, 'mouth_events.json')
    if os.path.exists(me):
        MOUTH_EVENTS[:] = json.load(open(me))
    lw = os.path.join(work, 'leek_windows.json')
    if os.path.exists(lw):
        w = json.load(open(lw))
        HAND_FISTS[:] = [(RIGHT_HAND, w['right']), (1 - RIGHT_HAND, w['left'])]
    tmp = os.path.join(work, 'build_tmp'); os.makedirs(tmp, exist_ok=True)
    iso_x = os.path.join(work, 'iso')

    # ---- data archive
    data_ents, data_meta = afs.read_full(os.path.join(iso_x, AFS_DIR, 'DivaDataList.afs'))
    count = len(data_ents)
    new_files = ['out/song27_anim_body.igb', 'out/song27_anim_head1.igb',
                 'out/song27_anim_head2.igb', 'out/song27_anim_head3.igb']
    for slot, p in zip(SONGSG_SLOTS, new_files):
        assert data_ents[slot]['name'].startswith('songSG_anim_'), data_ents[slot]['name']
        data_ents[slot]['data'] = open(os.path.join(work, p), 'rb').read()
    cam_npz = os.path.join(work, CAMERA_NPZ)
    animated_camera = os.path.exists(cam_npz)
    camera_cuts = []
    if animated_camera:
        import igbcamera
        c = np.load(cam_npz)
        old = data_ents[SLIDESHOW_CAMERA]['data']
        assert data_ents[SLIDESHOW_CAMERA]['name'].startswith('sgc00_00_00'), data_ents[SLIDESHOW_CAMERA]['name']
        cam_file = old
        for cid, fh in zip(c['track_ids'], c['track_fov_h']):
            fv = c['track_fov_v'][list(c['track_ids']).index(cid)]
            frames = np.nonzero(c['fov'] == fv)[0]
            cam_file = igbcamera.add_camera(cam_file, f'camera_{cid:02d}', c['times'][frames], c['pos'][frames],
                                            c['rotm'][frames], fov_h=float(fh), near=0.5, far=800.0)
            print(f'  + camera_{cid:02d}: {len(frames)} keys, horizontal FOV {fh:.1f}')
        data_ents[SLIDESHOW_CAMERA]['data'] = cam_file
        camera_cuts = list(zip(c['cut_times'].tolist(), c['cut_cams'].tolist()))
        print(f'  sgc00_00_00.igb: camera_01 untouched, {len(camera_cuts)} lens cuts: '
              f'{len(old)} -> {len(cam_file)} bytes')
    stage_path = os.path.join(work, STAGE_IGB)
    stage_file = open(stage_path, 'rb').read() if os.path.exists(stage_path) else None
    if stage_file is not None:
        assert data_ents[PVE27_SLOT]['name'].startswith('pve_27'), data_ents[PVE27_SLOT]['name']
        data_ents[PVE27_SLOT]['data'] = stage_file
        print(f'  pve_27.igb (#{PVE27_SLOT}) <- stage {STAGE_IGB} ({len(stage_file)} bytes)')
    assert len(data_ents) == count
    data_afs = os.path.join(tmp, 'DivaDataList.afs')
    afs.write_full(data_afs, data_ents, data_meta)
    print(f'DivaDataList.afs: {count} files, slots {SONGSG_SLOTS} <- Ievan Polkka motion')

    # ---- script archive: pv_27 easy/normal/hard = entries 78..80
    scr_ents, scr_meta = afs.read_full(os.path.join(iso_x, AFS_DIR, 'DivaScriptList.afs'))
    for i in (78, 79, 80):
        assert scr_ents[i]['name'].startswith('pv_27_'), scr_ents[i]['name']
        old = scr_ents[i]['data']
        scr_ents[i]['data'] = patch_dsc(old, no_notes, animated_camera, camera_cuts, stage_file is not None)
        print(f'  {scr_ents[i]["name"]}: {len(old)} -> {len(scr_ents[i]["data"])} bytes{" (notes removed)" if no_notes else ""}')
    scr_afs = os.path.join(tmp, 'DivaScriptList.afs')
    afs.write_full(scr_afs, scr_ents, scr_meta)

    # ---- EBOOT: unlock on a new save (PV table already points PV 27 at slot 304)
    eb = bytearray(open(os.path.join(iso_x, 'PSP_GAME/SYSDIR/EBOOT.BIN'), 'rb').read())
    motion_field = PV_TABLE_MOTION_PV1 + (IEVAN_PV - 1) * 1000
    assert struct.unpack_from('<i', eb, motion_field)[0] == SONGSG_SLOTS[0]
    assert bytes(eb[UNLOCK_TABLE:UNLOCK_TABLE + 36]) == UNLOCK_DEFAULT
    eb[UNLOCK_TABLE + IEVAN_PV - 1] = 1
    if PATCH_PV_MODE:
        assert eb[PV_MODE_TABLE + IEVAN_PV - 1] == 0
        eb[PV_MODE_TABLE + IEVAN_PV - 1] = 1
        print(f'  EBOOT: PV {IEVAN_PV} PV-mode table @ {PV_MODE_TABLE:#x} set')
    if stage_file is not None:
        fl = motion_field + FIELD_LIST_REL                     # PV 27's field list (CHANGE_FIELD N -> entry N-1)
        old_list = struct.unpack_from('<26i', eb, fl)
        assert old_list[0] == 624 and old_list[25] == -1, old_list   # SGI00_99_00.png ... terminator
        struct.pack_into('<2i', eb, fl, PVE27_SLOT, -1)
        print(f'  EBOOT: PV {IEVAN_PV} field list -> [{PVE27_SLOT}] (was 25 illustration PNGs)')
    eboot = os.path.join(tmp, 'EBOOT.BIN')
    open(eboot, 'wb').write(eb)
    print(f'  EBOOT: PV {IEVAN_PV} unlocked on a new save (table @ {UNLOCK_TABLE:#x})')

    print(f'writing {out_iso} ...')
    isopatch.patch(src_iso, out_iso, {
        'PSP_GAME/SYSDIR/EBOOT.BIN': eboot,
        AFS_DIR + '/DivaScriptList.afs': scr_afs,
        AFS_DIR + '/DivaDataList.afs': data_afs,
    })
    print('done:', out_iso, os.path.getsize(out_iso))


if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    main(a[0], a[1], a[2], no_notes='--no-notes' in sys.argv)
