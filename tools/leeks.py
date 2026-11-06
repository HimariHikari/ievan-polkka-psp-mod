"""Leek props for the Ievan Polkka stage: low-poly leek meshes animated to follow Miku's hands.

Visibility comes from the dance itself: a leek is shown while that hand is clenched (Unity finger
"Stretched" muscles averaged, < CLOSE), with hysteresis and minimum durations, popping in over a few frames.
Hand transforms are baked per frame with the same FK the game uses (quaternions stored as conjugates).
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import fk_preview, igbmotion

CLOSE, OPEN = -0.30, -0.05        # curl thresholds (Unity Stretched: +1 open, -1 closed)
MIN_ON, MIN_GAP, POP = 30, 15, 4  # frames
LEEK_LEN_BACK, LEEK_LEN_FWD = 0.9, 2.2   # PSP units from the grip (Miku is ~7.3 tall)


def fk_full(bones, root_t, quats):
    n = len(bones); P = np.zeros((n, 3)); R = [None] * n
    for i, b in enumerate(bones):
        x, y, z, w = quats[i]
        Rl = fk_preview.qmat((-x, -y, -z, w))
        t = np.array(root_t if i == 1 else b['t'])
        if b['parent'] < 0:
            R[i] = Rl; P[i] = t
        else:
            p = b['parent']; R[i] = R[p] @ Rl; P[i] = P[p] + R[p] @ t
    return P, R


def visibility(curl):
    on = np.zeros(len(curl), bool); state = False
    for i, c in enumerate(curl):
        state = (c < OPEN) if state else (c < CLOSE)
        on[i] = state
    # close small gaps, drop short blips
    idx = np.nonzero(np.diff(np.concatenate([[0], on.astype(int), [0]])))[0].reshape(-1, 2)
    segs = []
    for a, b in idx:
        if segs and a - segs[-1][1] < MIN_GAP: segs[-1][1] = b
        else: segs.append([a, b])
    segs = [s for s in segs if s[1] - s[0] >= MIN_ON]
    scale = np.zeros(len(curl))
    for a, b in segs:
        for i in range(a, b):
            scale[i] = min(1.0, (i - a + 1) / POP, (b - i) / POP)
    return np.maximum(scale, 0.001), [(a / 30, b / 30) for a, b in segs]


def leek_mesh():
    """mesh in grip space: leek axis = +z (leaves toward +z / thumb side), grip at the origin"""
    tris = []
    def ring(z, r, k=6):
        return [np.array([r * np.cos(2 * np.pi * j / k), r * np.sin(2 * np.pi * j / k), z]) for j in range(k)]
    white, pale, green, dark, root = (196, 196, 182), (160, 196, 120), (96, 184, 72), (64, 146, 52), (178, 160, 118)
    rings = [(-LEEK_LEN_BACK, 0.075, root), (-LEEK_LEN_BACK + 0.05, 0.095, white), (0.1, 0.095, white),
             (0.55, 0.09, pale), (0.9, 0.08, green)]
    for (z0, r0, c0), (z1, r1, c1) in zip(rings, rings[1:]):
        a, b = ring(z0, r0), ring(z1, r1)
        for j in range(6):
            k = (j + 1) % 6
            tris += [((a[j], a[k], b[j]), (c0, c0, c1)), ((a[k], b[k], b[j]), (c0, c1, c1))]
    end = ring(rings[0][0], rings[0][1])
    for j in range(6):
        tris.append(((np.array([0, 0, rings[0][0] - 0.03]), end[j], end[(j + 1) % 6]), (root, root, root)))
    # three leaves fanning out from the stalk top
    for ang in (0.0, 2.1, 4.2):
        d = np.array([np.cos(ang), np.sin(ang), 0.0]); side = np.array([-np.sin(ang), np.cos(ang), 0.0])
        base = np.array([0, 0, 0.85]); tip = base + np.array([0, 0, LEEK_LEN_FWD - 0.85]) + d * 0.35
        mid = base + np.array([0, 0, (LEEK_LEN_FWD - 0.85) * 0.5]) + d * 0.12
        w0, w1 = 0.11, 0.08
        q = [base - side * w0, base + side * w0, mid + side * w1, mid - side * w1]
        tris += [((q[0], q[1], q[2]), (green, green, green)), ((q[0], q[2], q[3]), (green, green, green)),
                 ((q[3], q[2], tip), (green, green, dark))]
    pos = np.array([v for t, _ in tris for v in t], np.float64)
    col = np.array([(*c, 255) for _, cs in tris for c in cs], np.uint8)
    # per-triangle normals (lighting is uniform-ish anyway)
    nrm = []
    for t, _ in tris:
        n = np.array([0.0, 1.0, 0.0]); nrm += [n, n, n]           # even lighting: the leek stays bright from every side
    return pos.reshape(-1, 3, 3), np.array(nrm).reshape(-1, 3, 3), col.reshape(-1, 3, 4)


def props(work):
    bones = json.load(open(os.path.join(work, 'psp_skeleton.json')))
    names = [b['name'] for b in bones]
    root, quats, fps = igbmotion.load_frames(os.path.join(work, 'ievan_frames.bin'))
    n = len(root)
    out = []
    for side, hand, sign in (('right', 'R_hand', -1), ('left', 'L_hand', 1)):
        curl = np.load(os.path.join(work, f'fist_{side}.npy'))[:n]
        scale, segs = visibility(curl)
        hi = names.index(hand)
        pos = np.zeros((n, 3)); rotm = np.zeros((n, 3, 3))
        grip = np.array([sign * 0.33, -0.06, 0.0])          # fist centre in the hand bone frame (hand points +-x)
        for f in range(n):
            P, R = fk_full(bones, root[f], quats[f])
            pos[f] = P[hi] + R[hi] @ grip
            rotm[f] = R[hi]                                  # leek axis = hand's local +z (thumb side, forward in T-pose)
        # keep keys only around the visible windows (plus first/last frame): hidden stretches hold scale ~0
        keep = scale > 0.002
        keep = keep | np.roll(keep, 1) | np.roll(keep, -1); keep[0] = keep[-1] = True
        k = np.nonzero(keep)[0]
        out.append(dict(name=f'leek_{side}', times=k / fps, pos=pos[k], rotm=rotm[k], scale=scale[k], segs=segs,
                        all_pos=pos, all_rotm=rotm, all_scale=scale))
        print(f'leek_{side}: shown {", ".join(f"{a:.1f}-{b:.1f}s" for a, b in segs)}')
    json.dump({p['name'].split('_')[1]: p['segs'] for p in out}, open(os.path.join(work, 'leek_windows.json'), 'w'))
    return out
