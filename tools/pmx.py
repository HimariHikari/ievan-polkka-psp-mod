"""Minimal PMX 2.0/2.1 reader: vertices (pos, normal, uv), faces, textures, materials, morphs (names/types)."""
import struct
import numpy as np


class R:
    def __init__(self, d): self.d, self.o = d, 0
    def u(self, fmt):
        v = struct.unpack_from('<' + fmt, self.d, self.o); self.o += struct.calcsize('<' + fmt); return v
    def b(self, n):
        v = self.d[self.o:self.o + n]; self.o += n; return v


def read(path):
    r = R(open(path, 'rb').read())
    assert r.b(4) == b'PMX ', 'not a PMX file'
    ver, = r.u('f')
    n, = r.u('B'); g = r.u(f'{n}B')
    enc, add_uv, vsz, tsz, msz, bsz, mosz, rbsz = g[:8]
    def text():
        ln, = r.u('i'); s = r.b(ln)
        return s.decode('utf-16-le' if enc == 0 else 'utf-8', 'replace')
    idx = {1: 'b', 2: 'h', 4: 'i'}
    vidx = {1: 'B', 2: 'H', 4: 'i'}
    def bi(): return r.u(idx[bsz])[0]
    model = dict(name=text(), name_en=text(), comment=text(), comment_en=text(), version=ver)
    nv, = r.u('i')
    pos = np.zeros((nv, 3), np.float32); nrm = np.zeros((nv, 3), np.float32); uv = np.zeros((nv, 2), np.float32)
    for i in range(nv):
        p = r.u('8f'); pos[i] = p[0:3]; nrm[i] = p[3:6]; uv[i] = p[6:8]
        r.o += 16 * add_uv
        w, = r.u('B')
        if w == 0: bi()
        elif w == 1: bi(); bi(); r.u('f')
        elif w == 2: [bi() for _ in range(4)]; r.u('4f')
        elif w == 3: bi(); bi(); r.u('f'); r.u('9f')
        elif w == 4: [bi() for _ in range(4)]; r.u('4f')
        r.u('f')                                         # edge scale
    nf, = r.u('i')
    faces = np.array(r.u(f'{nf}{vidx[vsz]}'), np.int64).reshape(-1, 3)
    nt, = r.u('i')
    textures = [text() for _ in range(nt)]
    nm, = r.u('i')
    mats = []
    for _ in range(nm):
        name, name_en = text(), text()
        diffuse = r.u('4f'); spec = r.u('4f'); amb = r.u('3f')
        flags, = r.u('B'); edge = r.u('5f')
        tex = r.u(idx[tsz])[0]; sph = r.u(idx[tsz])[0]; sphmode, = r.u('B')
        shared, = r.u('B')
        toon = r.u('B')[0] if shared else r.u(idx[tsz])[0]
        memo = text(); count, = r.u('i')
        mats.append(dict(name=name, name_en=name_en, diffuse=diffuse, ambient=amb, flags=flags,
                         tex=textures[tex] if 0 <= tex < nt else None, faces=count // 3, double_sided=bool(flags & 1)))
    nb, = r.u('i')
    bones = []
    for _ in range(nb):
        name, name_en = text(), text()
        p = r.u('3f'); parent = bi(); layer, = r.u('i'); fl, = r.u('H')
        if fl & 1: bi()
        else: r.u('3f')
        if fl & 0x300: bi(); r.u('f')
        if fl & 0x400: r.u('3f')
        if fl & 0x800: r.u('6f')
        if fl & 0x2000: r.u('i')
        if fl & 0x20:
            bi(); r.u('i'); r.u('f'); nl, = r.u('i')
            for _ in range(nl):
                bi(); lim, = r.u('B')
                if lim: r.u('6f')
        bones.append(dict(name=name, pos=p, parent=parent))
    nmo, = r.u('i')
    morphs = []
    for _ in range(nmo):
        name, name_en = text(), text()
        panel, mtype = r.u('2B'); cnt, = r.u('i')
        offs = []
        for _ in range(cnt):
            if mtype == 1:                               # vertex
                v = r.u(vidx[vsz])[0]; d = r.u('3f'); offs.append((v, d))
            elif mtype in (3, 4, 5, 6, 7):               # uv / additional uv
                v = r.u(vidx[vsz])[0]; d = r.u('4f'); offs.append((v, d))
            elif mtype == 2: bi(); r.u('7f')
            elif mtype == 8: r.u(idx[msz]); r.u('B'); r.u('28f')
            elif mtype in (0, 9): r.u(idx[mosz] if mtype == 0 else idx[mosz]); r.u('f')
            else: raise ValueError(f'morph type {mtype}')
        morphs.append(dict(name=name, type=mtype, count=cnt, offsets=offs))
    model.update(pos=pos, normal=nrm, uv=uv, faces=faces, textures=textures, materials=mats, bones=bones, morphs=morphs)
    return model


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    m = read(sys.argv[1])
    print('name:', m['name'], '| vertices', len(m['pos']), '| triangles', len(m['faces']))
    print('bbox', m['pos'].min(0).round(1), m['pos'].max(0).round(1))
    print('textures:', m['textures'])
    for i, mt in enumerate(m['materials']):
        print(f'  mat{i:2d} {mt["name"]:24s} tris={mt["faces"]:6d} tex={mt["tex"]} diffuse={tuple(round(x, 2) for x in mt["diffuse"])} 2side={mt["double_sided"]}')
    print('bones:', [b['name'] for b in m['bones']])
    from collections import Counter
    print('morphs:', len(m['morphs']), Counter(mo['type'] for mo in m['morphs']), [ (mo['name'], mo['type'], mo['count']) for mo in m['morphs'][:12]])
