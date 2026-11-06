"""Read / replace the per-bone dance clip ('miku_song00') in DIVA PSP motion .igb files."""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from igb import IGB, Obj, Mem
import igbdump as D

def tracks_of(g, anim_name):
    anim = next(a for a in D.by_type(g, 'igAnimation') if D.obj(g, a)['igString@2'] == anim_name)
    v = D.obj(g, anim)
    tl = D.obj(g, g.items[v['igObjectRef@5']])
    return anim, [g.items[r] for r in D.mem_ints(g, tl['igMemoryRef@4'])[:tl['igInt@2']]]

def extract(g, anim_name='miku_song00'):
    """-> (root_t[nf,3], quats[nf,nbones,4], fps) in skeleton bone order"""
    anim, tracks = tracks_of(g, anim_name)
    sk = D.by_type(g, 'igSkeleton')[0]; sv = D.obj(g, sk)
    bil = D.obj(g, g.items[sv['igObjectRef@4']])
    names = [D.obj(g, g.items[r])['igString@2'] for r in D.mem_ints(g, bil['igMemoryRef@4'])[:bil['igInt@2']]]
    trans = D.mem_floats(g, sv['igMemoryRef@3'], 3)
    fps = 30.0
    data = {}; tmax = 0
    for t in tracks:
        tv = D.obj(g, t); nm = tv['igString@2']; src = tv['igObjectRef@3']
        if src < 0: data[nm] = ('const', tv['igVec4f@4'], tv['igVec3f@5']); continue
        sv2 = D.obj(g, g.items[src])
        q = np.array(D.datalist(g, sv2['igObjectRef@3'], '4f'))
        x = D.datalist(g, sv2['igObjectRef@2'], '3f')
        tl = D.datalist(g, sv2['igObjectRef@11'], 'q')
        ts = np.array([v[0] for v in tl], dtype=np.float64) / 1e9 if tl else np.arange(len(q)) / fps
        data[nm] = ('seq', q, np.array(x) if x else None, ts); tmax = max(tmax, ts[-1])
    nf = int(round(tmax * fps)) + 1
    grid = np.arange(nf) / fps
    root = np.tile(np.array(trans[1]), (nf, 1)); quats = np.zeros((nf, len(names), 4)); quats[..., 3] = 1
    for i, nm in enumerate(names):
        k = data.get(nm)
        if not k: continue
        if k[0] == 'const': quats[:, i] = k[1]; continue
        _, q, x, ts = k
        q = q.copy()
        for j in range(1, len(q)):
            if np.dot(q[j], q[j - 1]) < 0: q[j] = -q[j]
        qi = np.stack([np.interp(grid, ts, q[:, c]) for c in range(4)], 1)
        quats[:, i] = qi / np.linalg.norm(qi, axis=1, keepdims=True)
        if nm == 'root' and x is not None:
            root = np.stack([np.interp(grid, ts, x[:, c]) for c in range(3)], 1)
    return root, quats, fps

def write_frames(path, root, quats, fps):
    nf, nb = quats.shape[:2]
    with open(path, 'wb') as f:
        f.write(struct.pack('<iif', nf, nb, fps))
        f.write(np.concatenate([root.reshape(nf, 3), quats.reshape(nf, nb * 4)], 1).astype('<f4').tobytes())

if __name__ == '__main__':
    g = IGB(open(sys.argv[1], 'rb').read())
    r, q, fps = extract(g)
    write_frames(sys.argv[2], r, q, fps)
    print('frames', q.shape)


def _f32ns(sec):
    return int(round(float(np.float32(sec)) * 1e9))


def _set_mem(g, ref, data):
    """Replace a memory block's bytes, giving it a dir entry of the right size (entries are shared)."""
    m = g.items[ref]
    old = g.entries[m.entry]
    vals = list(old[1]); vals[1] = len(data)
    key = (old[0], tuple(vals))
    idx = next((k for k, e in enumerate(g.entries) if (e[0], tuple(e[1])) == key), None)
    if idx is None:
        g.entries.append((old[0], vals)); idx = len(g.entries) - 1
    m.entry = idx; m.data = bytes(data)
    g.index[ref] = idx


def _set_list(g, list_ref, arr, fmt):
    lst = g.items[list_ref]
    n = len(arr)
    g.set(lst, 0, n); g.set(lst, 1, n)                       # _count, _capacity
    mref = g.get(lst, 2)
    _set_mem(g, mref, np.asarray(arr, dtype='<' + fmt).tobytes())


def replace_clip(g, anim_name, root, quats, fps, bone_names, keep_const=()):
    """root[nf,3] (PSP units, absolute root local position), quats[nf,nb,4] game convention, in skeleton order."""
    nf = quats.shape[0]
    times = np.array([_f32ns(i / fps) for i in range(nf)], dtype='<i8')
    dur = _f32ns((nf - 1) / fps)
    anim, tracks = tracks_of(g, anim_name)
    names = {n: i for i, n in enumerate(bone_names)}
    done_time = set(); touched = []
    for t in tracks:
        tv = D.obj(g, t); nm = tv['igString@2']; src = tv['igObjectRef@3']
        if src < 0 or nm not in names or nm in keep_const:
            continue
        seq = g.items[src]; sv = D.obj(g, seq)
        q = quats[:, names[nm]].astype(np.float32)
        # keep quaternion signs continuous (linear interpolation in the engine)
        for k in range(1, nf):
            if np.dot(q[k], q[k - 1]) < 0: q[k] = -q[k]
        _set_list(g, sv['igObjectRef@3'], q, 'f4')
        if sv['igObjectRef@2'] >= 0:                         # translation channel (root)
            _set_list(g, sv['igObjectRef@2'], root.astype(np.float32), 'f4')
        tl = sv['igObjectRef@11']
        if tl not in done_time:
            _set_list(g, tl, times, 'i8'); done_time.add(tl)
        k17 = [i for i, (ft, slot, _) in enumerate(g.metaobjects[seq.type]['fields']) if slot == 17][0]
        k18 = [i for i, (ft, slot, _) in enumerate(g.metaobjects[seq.type]['fields']) if slot == 18][0]
        g.set(seq, k17, 0, '<q'); g.set(seq, k18, dur, '<q')
        touched.append(nm)
    k9 = [i for i, (ft, slot, _) in enumerate(g.metaobjects[anim.type]['fields']) if slot == 9][0]
    g.set(anim, k9, dur, '<q')
    return touched, dur


def skeleton_names(g):
    sk = D.by_type(g, 'igSkeleton')[0]; sv = D.obj(g, sk)
    bil = D.obj(g, g.items[sv['igObjectRef@4']])
    return [D.obj(g, g.items[r])['igString@2'] for r in D.mem_ints(g, bil['igMemoryRef@4'])[:bil['igInt@2']]]


def load_frames(path):
    d = open(path, 'rb').read()
    nf, nb = struct.unpack_from('<ii', d, 0); fps = struct.unpack_from('<f', d, 8)[0]
    a = np.frombuffer(d, '<f4', offset=12).reshape(nf, 3 + 4 * nb)
    return a[:, :3].copy(), a[:, 3:].reshape(nf, nb, 4).copy(), fps
