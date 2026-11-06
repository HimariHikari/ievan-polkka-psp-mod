"""Convert an MMD camera motion (.vmd) into PSP-space camera keyframes for the Ievan Polkka PV.

usage: py -P camera_convert.py <camera.vmd> <work dir> [--frames N] [--offset F]
writes <work>/ievan_camera.npz (times, pos, rotm) and <work>/camera_preview.png (stick-figure contact sheet)

MMD camera key = look-at target, signed distance (negative = behind target), euler rotation (rad), vertical FOV
(deg). MMD is left-handed with the model facing -z; PSP is right-handed with Miku facing +z, so a point maps as
s * (x, y, -z). MMD zoom (FOV) is turned into an equivalent camera distance because the PSP camera's FOV is fixed.
Rotation convention follows three.js MMDLoader; MMD->PSP scale ~0.37 (MMD Miku ~20 units tall, PSP Miku ~7.3).
"""
import os, sys, json, itertools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import vmd, fk_preview, igbmotion

PSP_HFOV = 54.43                       # igCamera field of view of the slideshow camera (horizontal, degrees)
PSP_VFOV = 35.6                        # measured from the in-game framing test


def rot(axis, a):
    c, s = np.cos(a), np.sin(a)
    return {'x': np.array([[1, 0, 0], [0, c, -s], [0, s, c]]),
            'y': np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]]),
            'z': np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])}[axis]


def mmd_rot(r, order, signs):
    a = {'x': signs[0] * r[0], 'y': signs[1] * r[1], 'z': signs[2] * r[2]}
    R = np.eye(3)
    for ax in order:
        R = R @ rot(ax, a[ax])
    return R


def to_psp(v):
    return np.array([v[0], v[1], -v[2]])


def camera_frames_mmd(cam, s, subject=None):
    """MMD camera -> PSP camera, using the same conversion as three.js's MMDLoader:
    right-handed point = (x, y, -z); camera rotation = Rx(rx) Ry(ry) Rz(-rz); camera looks down its -z;
    camera position = target + R (0, 0, -distance). The PSP camera FOV is fixed, so each MMD zoom is replaced by
    moving the camera along its view line so the subject (closest point to Miku's chest) keeps its framing."""
    n = len(cam['dist'])
    pos = np.zeros((n, 3)); rotm = np.zeros((n, 3, 3)); dsub = np.zeros(n)
    for f in range(n):
        rx, ry, rz = cam['rot'][f]
        R = rot('x', rx) @ rot('y', ry) @ rot('z', -rz)
        fwd = R @ np.array([0, 0, -1.0])
        c = to_psp(cam['target'][f]) * s + R @ np.array([0, 0, -cam['dist'][f] * s])
        k = np.tan(np.radians(cam['fov'][f]) / 2) / np.tan(np.radians(PSP_VFOV) / 2)
        if subject is not None:
            d = float(np.dot(subject[f] - c, fwd))
            if d > 0.5:
                q = c + fwd * d
                c = q - fwd * d * k
            dsub[f] = d
        pos[f] = c; rotm[f] = R
    return pos, rotm, dsub


def project(pos, rotm, pts):
    if rotm.ndim == 3:                               # batched: pos[f,3], rotm[f,3,3], pts[f,k,3]
        pc = np.einsum('fkc,fcd->fkd', pts - pos[:, None], rotm)
    else:
        pc = (pts - pos) @ rotm                      # camera-space coordinates
    zc = -pc[..., 2]
    with np.errstate(divide='ignore', invalid='ignore'):
        xs = pc[..., 0] / (zc * np.tan(np.radians(PSP_HFOV) / 2))
        ys = pc[..., 1] / (zc * np.tan(np.radians(PSP_VFOV) / 2))
    return xs, ys, zc


def miku_points(work, n):
    bones = json.load(open(os.path.join(work, 'psp_skeleton.json')))
    root, quats, fps = igbmotion.load_frames(os.path.join(work, 'ievan_frames.bin'))
    names = [b['name'] for b in bones]
    idx = [names.index(k) for k in ('head', 'root', 'L_foot', 'R_foot')]
    P = np.zeros((n, len(idx), 3)); full = []; fwd = np.zeros((n, 3))
    for f in range(n):
        k = min(f, len(root) - 1)
        W = fk_preview.fk(bones, root[k], quats[k])
        P[f] = W[idx]; full.append(W)
        x, y, z, w = quats[k][names.index('root')]
        fwd[f] = fk_preview.qmat((-x, -y, -z, w)) @ np.array([0, 0, 1.0])
    return P, full, bones, fwd


def score(pos, rotm, P, fwd):
    """framing + tie-breakers that framing alone can't decide: dance cameras mostly look at Miku's front
    (yaw sign) and sit above the floor (pitch sign)"""
    xs, ys, zc = project(pos, rotm, P)
    inside = (zc > 0.5) & (np.abs(xs) < 1.05) & (np.abs(ys) < 1.05)
    framed = inside[:, :2].all(1).mean()             # head and root visible
    to_cam = pos - P[:, 1]
    front = (np.einsum('fc,fc->f', to_cam[:, [0, 2]], fwd[:, [0, 2]]) > 0).mean()
    above = (pos[:, 1] > 0.3).mean()
    return framed + 0.3 * front + 0.3 * above, framed, front, above


ASPECT = 1.6          # horizontal/vertical tangent ratio measured in game (hfov 54.43 <-> vfov ~35.6)


def main(path, work, nframes=None, offset=0, scale=0.37):
    """One PSP camera per distinct MMD zoom (FOV) value; the DSC cuts between them where the zoom changes."""
    v = vmd.read(path)
    keys = v['camera']
    if not keys:
        raise SystemExit('no camera keyframes in ' + path)
    n = nframes or 4578
    cam = vmd.sample_camera([dict(k, frame=k['frame'] - offset) for k in keys], n)
    P, full, bones, fwd = miku_points(work, n)
    pos, rotm, _ = camera_frames_mmd(cam, scale, None)          # true camera path, no zoom compensation
    fov = np.round(cam['fov']).astype(int)
    values = [35] + sorted(set(fov.tolist()) - {35})              # camera_02 = default lens
    cams = {fv: 2 + i for i, fv in enumerate(values)}
    cuts = [(0.0, cams[int(fov[0])])]
    for f in range(1, n):
        if fov[f] != fov[f - 1]:
            cuts.append((f / 30.0, cams[int(fov[f])]))
    tracks = []
    for fv, ci in cams.items():
        frames = np.nonzero(fov == fv)[0]
        hfov = float(np.degrees(2 * np.arctan(np.tan(np.radians(fv) / 2) * ASPECT)))
        tracks.append(dict(name=f'camera_{ci:02d}', fov_v=fv, fov_h=hfov, frames=frames))
        print(f'camera_{ci:02d}: MMD fov {fv:2d} -> PSP horizontal fov {hfov:5.1f}, {len(frames)} keyframes')
    # framing check with each frame's real lens
    xs, ys, zc = project(pos, rotm, P)
    scalev = np.tan(np.radians(PSP_VFOV) / 2) / np.tan(np.radians(fov) / 2)
    ys = ys * scalev[:, None]; xs = xs * scalev[:, None]
    head_in = ((zc[:, 0] > 0.3) & (np.abs(xs[:, 0]) < 1) & (np.abs(ys[:, 0]) < 1)).mean()
    print(f'{len(cuts)} lens cuts; head on screen {head_in * 100:.1f}% of frames (scale {scale})')
    times = np.arange(n) / 30.0
    np.savez(os.path.join(work, 'ievan_camera.npz'), times=times, pos=pos, rotm=rotm, scale=scale,
             fov=fov, cut_times=np.array([c[0] for c in cuts]), cut_cams=np.array([c[1] for c in cuts]),
             track_fov_v=np.array([t['fov_v'] for t in tracks]), track_fov_h=np.array([t['fov_h'] for t in tracks]),
             track_ids=np.array([int(t['name'][-2:]) for t in tracks]))
    return tracks, cuts


def contact_sheet(path, bones, full, pos, rotm, cols=6, rows=4):
    import matplotlib; matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    n = len(pos)
    fig, axs = plt.subplots(rows, cols, figsize=(cols * 2.4, rows * 1.6))
    for i, ax in enumerate(axs.flat):
        f = int(i * (n - 1) / (cols * rows - 1))
        W = full[f]
        xs, ys, zc = project(pos[f], rotm[f], W)
        for b_i, b in enumerate(bones):
            p = b['parent']
            if p > 0 and zc[b_i] > 0 and zc[p] > 0:
                c = 'tab:red' if b['name'].startswith('L_') else 'tab:blue' if b['name'].startswith('R_') else 'k'
                ax.plot([xs[p], xs[b_i]], [ys[p], ys[b_i]], c, lw=1.5)
        ax.set_xlim(-1, 1); ax.set_ylim(-1, 1); ax.set_aspect(272 / 480 * 480 / 272)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_title(f'{f / 30:.1f}s', fontsize=7)
    plt.tight_layout(); plt.savefig(path, dpi=70)
    print('preview:', path)


if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    nf = int(sys.argv[sys.argv.index('--frames') + 1]) if '--frames' in sys.argv else None
    off = int(sys.argv[sys.argv.index('--offset') + 1]) if '--offset' in sys.argv else 0
    sc = float(sys.argv[sys.argv.index('--scale') + 1]) if '--scale' in sys.argv else 0.37
    main(a[0], a[1], nf, off, sc)
