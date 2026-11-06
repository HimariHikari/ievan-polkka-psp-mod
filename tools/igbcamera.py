"""Add an animated camera (e.g. 'camera_02') to a DIVA PSP camera .igb, leaving the existing cameras alone.

The game finds cameras by name ("camera_NNShape"); DSC `DATA_CAMERA 0 N` uses camera N of the PV's first
camera file. Built by cloning camera_01's transform/shape objects and giving the clone its own keyframes:
translation + quaternion (game convention = conjugate of the usual column-vector rotation) + unit scale,
linear interpolation, comp flags 0x0b (1 translate | 2 quaternion | 8 scale; 4 would be Euler degrees).
"""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from igb import IGB
import igbdump as D


def _obj_of(g, t, name):
    return next(o for o in D.by_type(g, t) if D.obj(g, o).get('igString@2') == name)


def _clone(g, src, type_name=None):
    return g.add_obj(type_name or g.metaobjects[src.type]['name'], list(src.fields))


def _list(g, like_list_ref, arr, fmt):
    """new igDataList-derived object (same type as like_list_ref) holding arr"""
    like = g.items[like_list_ref]
    mref_like = g.get(like, 2)
    data = np.asarray(arr, dtype='<' + fmt).tobytes()
    mref = g.add_mem(mref_like, data)
    ref = _clone(g, like)
    o = g.items[ref]
    n = len(arr)
    g.set(o, 0, n); g.set(o, 1, n); g.set(o, 2, mref)
    return ref


def _append_ref(g, nodelist_ref, new_ref):
    """append an object ref to an igNodeList/igObjectList (memory block of refs)"""
    lst = g.items[nodelist_ref]
    n = g.get(lst, 0); mref = g.get(lst, 2)
    refs = list(struct.unpack(f'<{n}i', g.items[mref].data[:4 * n])) if n else []
    refs.append(new_ref)
    g.set_mem(mref, struct.pack(f'<{len(refs)}i', *refs))
    g.set(lst, 0, len(refs)); g.set(lst, 1, len(refs))


def _ref_list(g, like_list_ref, refs):
    """new igNodeList (same type as like_list_ref) holding object refs"""
    like = g.items[like_list_ref]
    mref = g.add_mem(g.get(like, 2), struct.pack(f'<{len(refs)}i', *refs))
    ref = _clone(g, like)
    o = g.items[ref]
    g.set(o, 0, len(refs)); g.set(o, 1, len(refs)); g.set(o, 2, mref)
    return ref


def quat_from_matrix(R):
    """column-vector rotation matrix -> quaternion (x,y,z,w)"""
    m = R
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        w = 0.25 * s; x = (m[2, 1] - m[1, 2]) / s; y = (m[0, 2] - m[2, 0]) / s; z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        w = (m[2, 1] - m[1, 2]) / s; x = 0.25 * s; y = (m[0, 1] + m[1, 0]) / s; z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        w = (m[0, 2] - m[2, 0]) / s; x = (m[0, 1] + m[1, 0]) / s; y = 0.25 * s; z = (m[1, 2] + m[2, 1]) / s
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        w = (m[1, 0] - m[0, 1]) / s; x = (m[0, 2] + m[2, 0]) / s; y = (m[1, 2] + m[2, 1]) / s; z = 0.25 * s
    q = np.array([x, y, z, w]); return q / np.linalg.norm(q)


def add_camera(data, name, times_s, pos, rotm, fov_h=None, near=None, far=None):
    """pos[n,3] camera world position; rotm[n,3,3] camera->world rotation (column vectors, camera looks down -z)."""
    g = IGB(data)
    t1 = _obj_of(g, 'igTransform', 'camera_01')
    c1 = _obj_of(g, 'igCamera', 'camera_01Shape')
    s1 = g.items[D.obj(g, t1)['igObjectRef@10']]
    sv = D.obj(g, s1)

    n = len(times_s)
    q = np.array([quat_from_matrix(R) for R in rotm])
    q[:, :3] *= -1                                     # game stores the conjugate
    for k in range(1, n):
        if np.dot(q[k], q[k - 1]) < 0: q[k] = -q[k]
    times = np.array([int(round(float(np.float32(t)) * 1e9)) for t in times_s], dtype='<i8')
    dur = int(times[-1])

    # shape
    c2 = _clone(g, c1)
    co = g.items[c2]
    g.set(co, 0, g.add_string(name + 'Shape'))
    if fov_h is not None:
        g.set(co, g.field_index(co, 8), fov_h, '<f')
    if near is not None or far is not None:
        nr = near if near is not None else g.get(co, g.field_index(co, 9), '<f')
        fr = far if far is not None else g.get(co, g.field_index(co, 10), '<f')
        fh = g.get(co, g.field_index(co, 8), '<f')
        ext_x = nr * np.tan(np.radians(fh) / 2)
        ext_y = ext_x / 1.5
        for slot, v in ((9, nr), (10, fr), (12, -ext_x), (13, ext_x), (14, ext_y), (15, -ext_y)):
            g.set(co, g.field_index(co, slot), float(v), '<f')

    # keyframe lists + sequence
    xl = _list(g, sv['igObjectRef@2'], pos.astype(np.float32), 'f4')
    ql = _list(g, sv['igObjectRef@3'], q.astype(np.float32), 'f4')
    sl = _list(g, sv['igObjectRef@4'], np.ones((n, 3), np.float32), 'f4')
    tl = _list(g, sv['igObjectRef@11'], times, 'i8')
    s2 = _clone(g, s1)
    so = g.items[s2]
    for slot, v in ((2, xl), (3, ql), (4, sl), (11, tl)):
        g.set(so, g.field_index(so, slot), v)
    g.set(so, g.field_index(so, 17), 0, '<q')
    g.set(so, g.field_index(so, 18), dur, '<q')

    # transform node
    kids = _ref_list(g, D.obj(g, t1)['igObjectRef@7'], [c2])
    t2 = _clone(g, t1)
    to = g.items[t2]
    g.set(to, 0, g.add_string(name))
    g.set(to, g.field_index(to, 7), kids)
    g.set(to, g.field_index(to, 10), s2)
    M = np.eye(4, dtype='<f4'); M[:3, :3] = rotm[0].T; M[3, :3] = pos[0]   # row-vector matrix, translation in last row
    to.fields[g.field_index(to, 8)] = M.tobytes()

    # hang it under the scene graph root and register a graph path root/camera/shape
    root = _obj_of(g, 'igAttrSet', 'sceneGraph')
    _append_ref(g, D.obj(g, root)['igObjectRef@7'], t2)
    gpl = D.by_type(g, 'igGraphPathList')[0]
    gp1 = g.items[D.mem_ints(g, D.obj(g, gpl)['igMemoryRef@4'])[0]]
    path_nodes = _ref_list(g, D.obj(g, gp1)['igObjectRef@2'], [root.ref, t2, c2])
    gp2 = _clone(g, gp1)
    g.set(g.items[gp2], 0, path_nodes)
    _append_ref(g, gpl.ref, gp2)

    # scene duration
    si = D.by_type(g, 'igSceneInfo')[0]
    k9 = g.field_index(si, 9)
    if g.get(si, k9, '<q') < dur:
        g.set(si, k9, dur, '<q')
    return g.build()
