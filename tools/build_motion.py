"""Build Ievan Polkka motion files (body + 3 heads) for PV 27 from the Unity bake.

usage: py -P build_motion.py <work dir>
in : <work>/ievan_frames.bin (from Unity PspBake), <work>/data/0300..0303 song28 templates
out: <work>/out/song27_anim_body.igb, song27_anim_head{1,2,3}.igb
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import igbdump as D, igbmotion as M
from igb import IGB

def qmean(q):
    q = q.copy(); q[(q @ q[0]) < 0] *= -1
    m = q.mean(0); return m / np.linalg.norm(m)

def main(work):
    out = os.path.join(work, 'out'); os.makedirs(out, exist_ok=True)
    root, quats, fps = M.load_frames(os.path.join(work, 'ievan_frames.bin'))
    nf = len(root)
    print(f'bake: {nf} frames @ {fps} fps = {(nf - 1) / fps:.3f}s')

    # ---- body
    tpl = os.path.join(work, 'data', '0300_song28_anim_bod')
    g = IGB(open(tpl, 'rb').read())
    names = M.skeleton_names(g)
    _, ref_q, _ = M.extract(g, 'miku_song00')                 # template dance, for secondary-bone rest poses
    ref01 = IGB(open(os.path.join(work, 'data', '0196_song01_anim_bod'), 'rb').read())
    _, ref01_q, _ = M.extract(ref01, 'miku_song00')
    for i, n in enumerate(names):
        if n in ('tie_00', 'tie_01'):
            quats[:, i] = qmean(ref_q[:, i])
        elif n.startswith('Skrt_'):
            quats[:, i] = qmean(ref01_q[:, i])
    touched, dur = M.replace_clip(g, 'miku_song00', root, quats, fps, names)
    data = g.build()
    p = os.path.join(out, 'song27_anim_body.igb'); open(p, 'wb').write(data)
    print(f'body: {len(touched)} tracks replaced, dur={dur/1e9:.3f}s, {len(data)} bytes -> {p}')
    # verify by re-reading
    g2 = IGB(data); r2, q2, _ = M.extract(g2, 'miku_song00')
    err = np.abs(np.abs(np.einsum('fbc,fbc->fb', q2, quats.astype(np.float32))) - 1).max()
    print(f'  verify: frames={len(q2)} max quat mismatch={err:.2e} root mismatch={np.abs(r2 - root).max():.2e}')

    # ---- heads (hair): steady average pose from song28's own hair motion
    for k, idx in enumerate((301, 302, 303), 1):
        tpl = [f for f in os.listdir(os.path.join(work, 'data')) if f.startswith(f'{idx:04d}_')][0]
        g = IGB(open(os.path.join(work, 'data', tpl), 'rb').read())
        hn = M.skeleton_names(g)
        _, hq, _ = M.extract(g, 'miku_song00')
        hrest = np.stack([qmean(hq[:, i]) for i in range(len(hn))])
        hquats = np.tile(hrest[None], (nf, 1, 1))
        hroot = np.zeros((nf, 3))
        touched, dur = M.replace_clip(g, 'miku_song00', hroot, hquats, fps, hn)
        data = g.build()
        p = os.path.join(out, f'song27_anim_head{k}.igb'); open(p, 'wb').write(data)
        IGB(data)  # re-parse check
        print(f'head{k}: tracks {touched}, dur={dur/1e9:.3f}s, {len(data)} bytes')

if __name__ == '__main__':
    main(sys.argv[1])
