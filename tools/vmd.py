"""MikuMikuDance .vmd reader (camera keyframes) + per-frame sampling with MMD's bezier interpolation."""
import struct
import numpy as np


def _cstr(b):
    return b.split(b'\0')[0].decode('shift_jis', 'replace')


def read(path):
    d = open(path, 'rb').read()
    sig = d[:30]
    assert sig.startswith(b'Vocaloid Motion Data'), sig
    name_len = 20 if b'0002' in sig else 10
    o = 30 + name_len
    model = _cstr(d[30:30 + name_len])
    nbone = struct.unpack_from('<I', d, o)[0]; o += 4 + nbone * 111
    nmorph = struct.unpack_from('<I', d, o)[0]; o += 4 + nmorph * 23
    cams = []
    if o + 4 <= len(d):
        ncam = struct.unpack_from('<I', d, o)[0]; o += 4
        for _ in range(ncam):
            frame, dist, px, py, pz, rx, ry, rz = struct.unpack_from('<I7f', d, o)
            interp = struct.unpack_from('<24B', d, o + 32)
            fov, persp = struct.unpack_from('<IB', d, o + 56)
            cams.append(dict(frame=frame, dist=dist, pos=(px, py, pz), rot=(rx, ry, rz),
                             interp=interp, fov=fov, persp=persp))
            o += 61
    cams.sort(key=lambda k: k['frame'])
    return dict(model=model, bones=nbone, morphs=nmorph, camera=cams)


def _bezier(x1, x2, y1, y2, t):
    """MMD bezier: control points (x1,y1),(x2,y2) in 0..127; returns eased progress for linear t."""
    if x1 == y1 and x2 == y2:
        return t
    x1, x2, y1, y2 = x1 / 127, x2 / 127, y1 / 127, y2 / 127
    lo, hi = 0.0, 1.0
    for _ in range(30):                               # solve x(u) = t
        u = (lo + hi) / 2
        x = 3 * (1 - u) ** 2 * u * x1 + 3 * (1 - u) * u * u * x2 + u ** 3
        if x < t: lo = u
        else: hi = u
    u = (lo + hi) / 2
    return 3 * (1 - u) ** 2 * u * y1 + 3 * (1 - u) * u * u * y2 + u ** 3


def sample_camera(cams, nframes):
    """-> dict of arrays per frame: target[n,3], rot[n,3], dist[n], fov[n] (MMD units/radians/degrees)."""
    out = dict(target=np.zeros((nframes, 3)), rot=np.zeros((nframes, 3)), dist=np.zeros(nframes), fov=np.zeros(nframes))
    k = 0
    for f in range(nframes):
        while k + 1 < len(cams) and cams[k + 1]['frame'] <= f:
            k += 1
        a = cams[k]
        if k + 1 >= len(cams) or f <= a['frame']:
            b, t = a, 0.0
        else:
            b = cams[k + 1]
            t = (f - a['frame']) / (b['frame'] - a['frame'])
        ip = b['interp']                              # the curve stored on the END key drives the segment
        def ease(ch):                                 # ch: 0 x, 1 y, 2 z, 3 rotation, 4 distance, 5 fov
            x1, x2, y1, y2 = ip[ch * 4: ch * 4 + 4]
            return _bezier(x1, x2, y1, y2, t)
        for c in range(3):
            e = ease(c)
            out['target'][f, c] = a['pos'][c] + (b['pos'][c] - a['pos'][c]) * e
        e = ease(3)
        out['rot'][f] = [a['rot'][c] + (b['rot'][c] - a['rot'][c]) * e for c in range(3)]
        out['dist'][f] = a['dist'] + (b['dist'] - a['dist']) * ease(4)
        out['fov'][f] = a['fov'] + (b['fov'] - a['fov']) * ease(5)
    return out


if __name__ == '__main__':
    import sys
    v = read(sys.argv[1])
    c = v['camera']
    print('model:', repr(v['model']), 'bones:', v['bones'], 'morphs:', v['morphs'], 'camera keys:', len(c))
    if c:
        print('frames', c[0]['frame'], '..', c[-1]['frame'], f'({c[-1]["frame"] / 30:.2f}s @30fps)')
        for k in c[:8]:
            print(' ', k['frame'], round(k['dist'], 2), [round(x, 2) for x in k['pos']], [round(x, 3) for x in k['rot']], k['fov'], k['persp'], k['interp'][:8])
