"""Retime the leek animations in pve_27 to SONG time, the way the game's own fields are keyed.

pve_27 is loaded as PV 27's field (CHANGE_FIELD 1), and a field draws every scene in its file on a clock that
runs with the song (field_pv_05: keys at 0 s, then at 114 s, 116 s ..., last key at 183.33 s = song end, scene
duration 183.33 s; uneven key spacing is normal). v1.0 keyed each leek section from 0 to ~11 s, so in the field
those short animations looped all song long.

Same number of keys, same file size (in-place patch):
  key 0          t = 0                  hidden (scale 0.001)
  key 1          t = start + 1/30 s     hidden (so nothing grows in from t = 0)
  keys 2..n-3    t = start + k/30 s     unchanged poses
  key n-2        t = start + (n-2)/30   hidden (so nothing lingers until END)
  key n-1        t = END                hidden
plus sequence end + scene duration = END, and every leek's base matrix hidden.
The EFFECT commands stay as they are: an effect copy is either hidden (clock from 0) or identical to the field copy.

usage: py -P make_v13.py   (reads pve_27_v1.igb + pv_27_normal.dsc here, writes pve_27_v13.igb)
"""
import os, struct, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import isotool as T, igbdump as D, dsc
from igb import IGB

FPS = 30
HIDE = 0.001
END = 160.0          # s, past the end of the PV (last script command ~147 s)


def ns(t):
    return int(round(float(np.float32(t)) * 1e9))


def retime(src, starts):
    g = IGB(src)
    assert g.build() == src
    si = D.by_type(g, 'igSceneInfo')[0]
    root = g.items[D.obj(g, si)['igObjectRef@5']]
    rl = D.obj(g, g.items[D.obj(g, root)['igObjectRef@7']])
    scenes = D.mem_ints(g, rl['igMemoryRef@4'])[:rl['igInt@2']]
    assert len(scenes) == 1 + len(starts)
    report = []
    for k, (sref, start) in enumerate(zip(scenes[1:], starts)):
        sv = D.obj(g, g.items[sref]); lst = D.obj(g, g.items[sv['igObjectRef@7']])
        for r in D.mem_ints(g, lst['igMemoryRef@4'])[:lst['igInt@2']]:
            node = g.items[r]; nv = D.obj(g, node)
            seq = g.items[nv['igObjectRef@10']]; qv = D.obj(g, seq)
            tl = D.obj(g, g.items[qv['igObjectRef@11']]); sl = D.obj(g, g.items[qv['igObjectRef@4']])
            t = np.frombuffer(g.items[tl['igMemoryRef@4']].data, '<i8')[:tl['igInt@2']].copy()
            sc = np.frombuffer(g.items[sl['igMemoryRef@4']].data, '<f4').reshape(-1, 3)[:sl['igInt@2']].copy()
            n = len(t); assert len(sc) == n and n >= 4
            assert np.allclose(np.diff(t) / 1e9, 1 / FPS, atol=2e-6)
            new_t = np.array([ns(start + i / FPS) for i in range(n)], '<i8')
            new_t[0] = 0
            new_t[-1] = ns(END)
            sc[0] = sc[1] = sc[-2] = sc[-1] = HIDE   # hidden on both sides of the stretched first/last gaps
            assert np.all(np.diff(new_t) > 0)
            g.set_mem(tl['igMemoryRef@4'], new_t.tobytes() + g.items[tl['igMemoryRef@4']].data[8 * n:])
            g.set_mem(sl['igMemoryRef@4'], sc.astype('<f4').tobytes() + g.items[sl['igMemoryRef@4']].data[12 * n:])
            g.set(seq, g.field_index(seq, 18), int(new_t[-1]), '<q')
            mk = g.field_index(node, 8)
            M = np.frombuffer(node.fields[mk], '<f4').reshape(4, 4).copy()
            M[:3, :3] *= HIDE / np.linalg.norm(M[0, :3])
            node.fields[mk] = M.astype('<f4').tobytes()
            vis = np.nonzero(sc[:, 0] > 0.01)[0]
            report.append(f'  {nv["igString@2"]:12s} {n:3d} keys  shown {new_t[vis[0]] / 1e9:6.2f}-{new_t[vis[-1]] / 1e9:6.2f}s'
                          f'  (keys at 0, {new_t[1] / 1e9:.2f} ... {new_t[-2] / 1e9:.2f}, {new_t[-1] / 1e9:.0f}s)')
    g.set(si, g.field_index(si, 9), ns(END), '<q')
    out = g.build()
    return out, report


if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    ref = dsc.parse(open('pv_27_normal.dsc', 'rb').read())
    starts = [t / 1e5 for t, n, a in ref if n == 'EFFECT' and a[0] in (2, 3, 4)]
    src = open('pve_27_v1.igb', 'rb').read()
    out, report = retime(src, starts)
    print('section starts', starts)
    print('\n'.join(report))
    assert len(out) == len(src), (len(out), len(src))
    open('pve_27_v13.igb', 'wb').write(out)
    print('pve_27_v13.igb', len(out), 'bytes (same size as v1.0), bytes changed', sum(a != b for a, b in zip(src, out)))
