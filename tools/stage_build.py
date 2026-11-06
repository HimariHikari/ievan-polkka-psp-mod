"""Convert an MMD stage (.pmx + textures) into a DIVA PSP Alchemy stage .igb, plus optional animated props.

usage: py -P stage_build.py <stage.pmx> <template stage .igb> <out.igb> [--scale 0.37] [--maxtex 256]
                            [--leeks <work dir> <prototype .igb that contains transform sequences>]

Built from scratch with the template only supplying the type dictionary and attribute defaults:
  igInfoList -> igSceneInfo -> igAttrSet 'sceneGraph' -> per-texture igAttrSet (material attrs) -> igGeometry
  -> igGeometryAttr1_5 (triangle strip, non-indexed) -> igVertexArray1_1 (float pos/normal, RGBA8 colour, float uv)
Textures: 8-bit indexed (igImage format 100) + 256-entry RGBA igClut, stored unswizzled, top row first.
Coordinates: MMD (left-handed, units ~8cm) -> PSP: s * (x, y, -z), same as the dance and camera conversion.
Mirroring flips triangle winding, so culling is disabled (the PMX grass is double-sided anyway).
Brightness: the PSP renders with 2x colour doubling, so vertex colour 128 shows a texture as authored.
Props (leeks) are igTransform nodes with per-frame translation/rotation/scale keys (comp 1|2|8, linear).
"""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image
import pmx
from igb import IGB, Obj, Mem
import igbdump as D

BASE_COLOUR = 128
TINT = {'grass02': 118, 'grass00': 122, 'kusa00': 128, 'sky2': 132, 'clouds': 128, 'cloud2s': 128, 'fog': 112}
FOG_ALPHA = 80                         # horizon haze band: this alpha at its bottom edge, 0 at the top


class Builder:
    def __init__(self, template_bytes, proto_bytes=()):
        self.T = IGB(template_bytes)                 # template (read-only source of default field bytes)
        self.P = [IGB(b) for b in proto_bytes]       # extra prototype sources (same Alchemy build)
        g = IGB(template_bytes)
        g.items, g.index = [], []
        self.g = g

    # --- helpers -------------------------------------------------------
    def _proto(self, type_name, pick=None):
        for src in [self.T] + self.P:
            objs = [o for o in src.items if isinstance(o, Obj) and src.typename(o) == type_name]
            if pick: objs = [o for o in objs if pick(o)] or objs
            if objs:
                return list(objs[0].fields)
        raise KeyError('no prototype for ' + type_name)

    def _slot(self, type_name, slot):
        t = self.g.mo_index[type_name]
        for i, (ft, sl, _) in enumerate(self.g.metaobjects[t]['fields']):
            if sl == slot:
                return i, self.g.metafields[ft][0]
        raise KeyError((type_name, slot))

    def obj(self, type_name, pick=None, **slots):
        fields = self._proto(type_name, pick)
        for key, val in slots.items():
            slot = int(key[1:])
            i, ft = self._slot(type_name, slot)
            n = len(fields[i])
            if ft == 'igStringMetaField':
                b = struct.pack('<i', self.g.add_string(val))
            elif ft == 'igFloatMetaField':
                b = struct.pack('<f', val)
            elif ft in ('igVec3fMetaField', 'igVec4fMetaField'):
                b = struct.pack(f'<{len(val)}f', *val)
            elif ft == 'igLongMetaField':
                b = struct.pack('<q', val)
            elif ft == 'igBoolMetaField':
                b = struct.pack('<i', 1 if val else 0)
            elif isinstance(val, (bytes, bytearray)):
                b = bytes(val)
            else:
                b = struct.pack('<i' if val < 0 else '<I', val)
            fields[i] = b.ljust(n, b'\0')[:n]
        return self.g.add_obj(type_name, fields)

    def mem(self, like_type, data, pick=None):
        """memory block with the dir-entry flags (type/pool/alignment) of a template block of that type"""
        proto = None
        for src in [self.T] + self.P:
            cands = [m for m in src.items if isinstance(m, Mem) and src.typename(m) == like_type]
            if pick: cands = [m for m in cands if pick(src.entries[m.entry][1])] or cands
            if cands:
                proto = list(src.entries[cands[0].entry][1]); break
        if proto is None:
            raise KeyError('no memory prototype for ' + like_type)
        memdir = self.g.mo_index['igMemoryDirEntry']
        want = list(proto); want[1] = len(data)
        e = self.g._entry_for(memdir, lambda v: v == want, want)
        ref = len(self.g.items)
        self.g.items.append(Mem(ref, e, bytes(data)))
        self.g.index.append(e)
        return ref

    def reflist(self, type_name, refs, mem_pick=None):
        m = self.mem('mem:igObjectRef', struct.pack(f'<{len(refs)}i', *refs), mem_pick) if refs else -1
        return self.obj(type_name, s2=len(refs), s3=len(refs), s4=m)

    def aabox(self, lo, hi):
        return self.obj('igAABox', s2=tuple(map(float, lo)), s3=tuple(map(float, hi)))

    def animated(self, name, children, times, pos, rotm, scale):
        """igTransform whose translation/rotation/scale follow per-frame keys (linear, comp 1|2|8)"""
        import igbcamera
        q = np.array([igbcamera.quat_from_matrix(R) for R in rotm]); q[:, :3] *= -1   # game stores conjugate
        for k in range(1, len(q)):
            if np.dot(q[k], q[k - 1]) < 0: q[k] = -q[k]
        t_ns = np.array([int(round(float(np.float32(t)) * 1e9)) for t in times], '<i8')
        sc = np.repeat(np.asarray(scale, np.float64)[:, None], 3, 1)
        def lst(type_name, mem_type, arr, dtype):
            m = self.mem(mem_type, np.asarray(arr, dtype).tobytes())
            return self.obj(type_name, s2=len(arr), s3=len(arr), s4=m)
        xl = lst('igVec3fList', 'mem:igVec3f', pos, '<f4')
        ql = lst('igQuaternionfList', 'mem:igVec4f', q, '<f4')
        sl = lst('igVec3fList', 'mem:igVec3f', sc, '<f4')
        tl = lst('igLongList', 'mem:igLong', t_ns, '<i8')
        seq = self.obj('igTransformSequence1_5', s2=xl, s3=ql, s4=sl, s5=-1, s11=tl, s12=-1, s13=-1, s14=-1,
                       s15=struct.pack('<I', 0x0b), s16=bytes([1, 1, 1, 0]), s17=0, s18=int(t_ns[-1]), s19=-1)
        M = np.eye(4, dtype='<f4'); M[:3, :3] = rotm[0].T * scale[0]; M[3, :3] = pos[0]
        kids = self.reflist('igNodeList', children)
        node = self.obj('igTransform', s2=name, s3=-1, s5=2, s7=kids, s8=M.tobytes(), s9=0, s10=seq)
        return node, int(t_ns[-1])

    # --- content -------------------------------------------------------
    def texture(self, img, name):
        """RGBA PIL image -> igTextureAttr ref (8-bit indexed + RGBA clut)"""
        w, h = img.size
        q = img.convert('RGBA').quantize(256, method=Image.Quantize.FASTOCTREE)
        pal = np.array(q.getpalette(rawmode='RGBA')[:1024], np.uint8)
        if pal.size < 1024:
            pal = np.concatenate([pal, np.zeros(1024 - pal.size, np.uint8)])
        idx = np.array(q, np.uint8)
        clut_mem = self.mem('mem:igUnsignedChar', pal.tobytes(), pick=lambda e: e[4] == 0)
        clut = self.obj('igClut', s5=clut_mem)
        img_mem = self.mem('mem:igUnsignedChar', idx.tobytes(), pick=lambda e: e[4] == 1)
        image = self.obj('igImage', s2=w, s3=h, s12=w * h, s13=img_mem, s17=clut, s19=w, s22=name)
        mips = self.obj('igImageMipMapList', s2=0, s3=0, s4=-1)
        return self.obj('igTextureAttr', s12=image, s16=mips)

    def geometry(self, name, pos, nrm, col, uv):
        n = len(pos)
        comps = [-1] * 20
        comps[0] = self.mem('mem:igChar', pos.astype('<f4').tobytes())
        comps[1] = self.mem('mem:igChar', nrm.astype('<f4').tobytes())
        comps[2] = self.mem('mem:igChar', col.astype(np.uint8).tobytes())
        comps[11] = self.mem('mem:igChar', uv.astype('<f4').tobytes())
        cref = self.mem('mem:igMemoryRef', struct.pack('<20i', *comps))
        va = self.obj('igVertexArray1_1', s2=cref, s3=n, s6=struct.pack('<I', 0x00010007))
        plm = self.mem('mem:igUnsignedInt', struct.pack('<I', n))
        pla = self.obj('igPrimLengthArray1_1', s2=plm, s3=1)
        ga = self.obj('igGeometryAttr1_5', s4=va, s5=-1, s6=4, s7=1, s8=0, s13=pla)
        gal = self.reflist('igAttrList', [ga])
        kids = self.reflist('igNodeList', [])
        box = self.aabox(pos.min(0), pos.max(0))
        return self.obj('igGeometry', s2=name, s3=box, s7=kids, s8=gal), (pos.min(0), pos.max(0))


def strip_from_triangles(tris):
    """triangle list (k,3) -> one strip with degenerate joins (winding not preserved; culling is off)"""
    out = []
    for a, b, c in tris:
        if out:
            out += [out[-1], a]
        out += [a, b, c]
    return np.array(out, np.int64)


def strip_mesh(tri_pos, tri_nrm, tri_col):
    """per-triangle arrays (k,3,...) -> strip vertex arrays (pos, nrm, col, uv)"""
    k = len(tri_pos)
    idx = strip_from_triangles(np.arange(3 * k).reshape(k, 3))
    P = tri_pos.reshape(-1, 3)[idx]; N = tri_nrm.reshape(-1, 3)[idx]; C = tri_col.reshape(-1, 4)[idx]
    return P, N, C, np.zeros((len(idx), 2))


def build(pmx_path, template_path, out_path, scale=0.37, maxtex=256, props=(), proto_paths=()):
    m = pmx.read(pmx_path)
    base = os.path.dirname(pmx_path)
    files = {f.lower(): f for f in os.listdir(base)}
    pos_all = m['pos'].astype(np.float64) * scale * np.array([1, 1, -1])
    uv_all = m['uv'].astype(np.float64)

    groups = {}
    start = 0
    for mt in m['materials']:
        tris = m['faces'][start:start + mt['faces']]; start += mt['faces']
        key = (mt['tex'] or '').lower()
        groups.setdefault(key, dict(names=[], tris=[]))
        groups[key]['names'].append(mt['name']); groups[key]['tris'].append(tris)

    B = Builder(open(template_path, 'rb').read(), [open(p, 'rb').read() for p in proto_paths])
    children, textures, lo_all, hi_all = [], [], [], []
    for key, grp in groups.items():
        tris = np.concatenate(grp['tris'])
        if not len(tris): continue
        tex_attr = None; alpha = False; img = None
        if key:
            img = Image.open(os.path.join(base, files[key])).convert('RGBA')
            w, h = img.size
            p2 = lambda x: 1 << int(np.floor(np.log2(x)))
            tw, th = p2(w), p2(h)
            while tw * th > maxtex * maxtex or max(tw, th) > 512:   # PSP: <=512 per side, 8-bit size <= 64KB
                if tw / th >= w / h: tw //= 2
                else: th //= 2
            img = img.resize((max(8, tw), max(8, th)), Image.LANCZOS)
            alpha = np.array(img)[..., 3].min() < 250
            tex_attr = B.texture(img, key)
            textures.append(tex_attr)
        idx = strip_from_triangles(tris)
        pos = pos_all[idx]; uv = uv_all[idx]
        nrm = np.tile([0.0, 1.0, 0.0], (len(idx), 1))         # even lighting (the Future Tone stage is unlit)
        name = os.path.splitext(key)[0] or 'untextured'
        tint = next((v for k, v in TINT.items() if k in name), BASE_COLOUR)
        col = np.full((len(idx), 4), 255, np.uint8); col[:, :3] = tint
        if 'fog' in name:                                      # fade the haze band out towards its top
            y = pos[:, 1]; a = np.clip((y.max() - y) / max(1e-6, y.max() - y.min()), 0, 1)
            col[:, 3] = (a * FOG_ALPHA).astype(np.uint8); alpha = True
        geom, (lo, hi) = B.geometry(name, pos, nrm, col, uv)
        lo_all.append(lo); hi_all.append(hi)
        attrs = [B.obj('igCullFaceAttr', s4=False), B.obj('igShadeModelAttr'),
                 B.obj('igMaterialAttr', s5=(0.8, 0.8, 0.8, 1.0)), B.obj('igMaterialModeAttr')]
        if tex_attr is not None:
            attrs += [B.obj('igTextureBindAttr', s4=tex_attr), B.obj('igTextureStateAttr', s4=True)]
        else:
            attrs += [B.obj('igTextureStateAttr', s4=False)]
        if alpha:
            attrs += [B.obj('igBlendFunctionAttr'), B.obj('igBlendStateAttr', s4=True)]
        al = B.reflist('igAttrList', attrs)
        kids = B.reflist('igNodeList', [geom])
        children.append(B.obj('igAttrSet', s2=name, s3=-1, s5=0, s7=kids, s8=al, s9=False))
        print(f'  {name:32s} tris={len(tris):5d} strip verts={len(idx):6d} '
              f'tex={"%dx%d" % img.size if img else "-"} alpha={alpha} colour={tint}')

    duration = 0
    for pr in props:
        ppos, pnrm, pcol = pr['mesh']
        geom, _ = B.geometry(pr['name'] + 'Shape', *strip_mesh(ppos, pnrm, pcol))
        attrs = [B.obj('igCullFaceAttr', s4=False), B.obj('igShadeModelAttr'),
                 B.obj('igMaterialAttr', s5=(0.8, 0.8, 0.8, 1.0)), B.obj('igMaterialModeAttr'),
                 B.obj('igTextureStateAttr', s4=False)]
        aset = B.obj('igAttrSet', s2=pr['name'] + 'Mat', s3=-1, s5=0, s7=B.reflist('igNodeList', [geom]),
                     s8=B.reflist('igAttrList', attrs), s9=False)
        node, dur = B.animated(pr['name'], [aset], pr['times'], pr['pos'], pr['rotm'], pr['scale'])
        children.append(node); duration = max(duration, dur)
        print(f'  prop {pr["name"]}: {len(ppos)} tris, {len(pr["times"])} keys')

    lo, hi = np.min(lo_all, 0), np.max(hi_all, 0)
    root_kids = B.reflist('igNodeList', children)
    root = B.obj('igAttrSet', s2='sceneGraph', s3=B.aabox(lo, hi), s5=2, s7=root_kids,
                 s8=B.reflist('igAttrList', []), s9=False)
    texlist = B.reflist('igTextureList', textures)
    gpl = B.obj('igGraphPathList', s2=0, s3=0, s4=-1)
    empty = B.reflist('igNodeList', [])
    si = B.obj('igSceneInfo', s2='Scene Graph', s5=root, s6=texlist, s7=gpl, s8=0, s9=duration, s11=empty)
    il = B.reflist('igInfoList', [si])
    B.g.root = il
    data = B.g.build()
    IGB(data)                                          # must re-parse
    open(out_path, 'wb').write(data)
    print(f'stage: {len(children)} nodes, {len(textures)} textures, bounds {lo.round(1)} .. {hi.round(1)}, '
          f'{len(data)} bytes -> {out_path}')
    return data


if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    sc = float(sys.argv[sys.argv.index('--scale') + 1]) if '--scale' in sys.argv else 0.37
    mt = int(sys.argv[sys.argv.index('--maxtex') + 1]) if '--maxtex' in sys.argv else 256
    sys.stdout.reconfigure(encoding='utf-8')
    props, protos = [], []
    if '--diag' in sys.argv:                           # test props: a planted static leek + a leek orbiting Miku
        import leeks
        mesh = leeks.leek_mesh()
        up = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0.0]])  # leek axis (+z) -> world +y
        props.append(dict(name='diag_static', mesh=mesh, times=np.array([0.0, 1.0]), pos=np.array([[2.6, 0.95, 0.4]] * 2),
                          rotm=np.array([up, up]), scale=np.array([1.0, 1.0]), static=True))
        t = np.arange(0, 153, 0.5); ang = t * 2 * np.pi / 8
        props.append(dict(name='diag_orbit', mesh=mesh, times=t,
                          pos=np.stack([4 * np.cos(ang), np.full_like(t, 0.95), 4 * np.sin(ang)], 1),
                          rotm=np.array([up] * len(t)), scale=np.ones(len(t))))
    if '--leeks' in sys.argv:
        import leeks
        k = sys.argv.index('--leeks')
        work, protos = sys.argv[k + 1], [sys.argv[k + 2]]
        a = [x for x in a if x not in (work, protos[0])]
        mesh = leeks.leek_mesh()
        for pr in leeks.props(work):
            pr['mesh'] = mesh; props.append(pr)
    build(a[0], a[1], a[2], sc, mt, props, protos)
