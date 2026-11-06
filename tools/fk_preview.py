"""Forward-kinematics stick-figure preview of PSP-convention motion data (sanity check)."""
import sys, json, struct
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def qmat(q):
    """standard (column-vector) rotation matrix from quaternion (x,y,z,w)"""
    x, y, z, w = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])

def load_frames(path):
    d = open(path, 'rb').read()
    nf, nb = struct.unpack_from('<ii', d, 0); fps = struct.unpack_from('<f', d, 8)[0]
    a = np.frombuffer(d, '<f4', offset=12).reshape(nf, 3 + 4 * nb)
    return a[:, :3], a[:, 3:].reshape(nf, nb, 4), fps

def fk(bones, root_t, quats):
    """quats in PSP game convention (conjugate) -> world positions"""
    n = len(bones); P = np.zeros((n, 3)); R = [None] * n
    for i, b in enumerate(bones):
        x, y, z, w = quats[i]
        Rl = qmat((-x, -y, -z, w))          # game stores conjugate
        t = np.array(root_t if i == 1 else b['t'])
        if b['parent'] < 0:
            R[i] = Rl; P[i] = t
        else:
            p = b['parent']; R[i] = R[p] @ Rl; P[i] = P[p] + R[p] @ t
    return P

def draw(ax, bones, P, view):
    i0, i1 = view
    for i, b in enumerate(bones):
        if b['parent'] > 0:
            c = 'tab:red' if b['name'].startswith('L_') else 'tab:blue' if b['name'].startswith('R_') else 'k'
            if b['name'].startswith('Skrt'): c = 'tab:gray'
            ax.plot([P[b['parent'], i0], P[i, i0]], [P[b['parent'], i1], P[i, i1]], c, lw=2)
    ax.set_aspect('equal'); ax.set_xlim(-5, 5); ax.set_ylim(-0.5, 8.5)
    ax.axhline(0, color='0.8', lw=1)

if __name__ == '__main__':
    bones = json.load(open(sys.argv[1]))
    root, quats, fps = load_frames(sys.argv[2])
    times = [float(t) for t in sys.argv[4].split(',')]
    fig, axs = plt.subplots(2, len(times), figsize=(2.2 * len(times), 7))
    for k, t in enumerate(times):
        f = min(int(round(t * fps)), len(root) - 1)
        P = fk(bones, root[f], quats[f])
        P[:, 0] -= root[f][0]; P[:, 2] -= root[f][2]          # keep centred
        draw(axs[0, k], bones, P, (0, 1)); axs[0, k].set_title(f'{t:.1f}s front')
        draw(axs[1, k], bones, P, (2, 1)); axs[1, k].set_title('side (+z = facing)')
        axs[0, k].invert_xaxis()                               # camera in front of Miku: her left (+x) on screen right
    plt.tight_layout(); plt.savefig(sys.argv[3], dpi=70)
    print('saved', sys.argv[3])
