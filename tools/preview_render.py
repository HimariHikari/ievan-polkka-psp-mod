"""Software preview: stage .igb (read back from the built file) + Miku skeleton through the converted camera.
usage: py -P preview_render.py <stage.igb> <work dir> <out.png> [t1,t2,...]"""
import os, sys, json, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image, ImageDraw
import igbdump as D
from igb import IGB
import camera_convert as CC, fk_preview, igbmotion

W, H = 480, 272


def load_stage(path):
    g = IGB(open(path, 'rb').read())
    tris = []                                        # (verts[3,3], color rgba)
    for aset in D.by_type(g, 'igAttrSet'):
        v = D.obj(g, aset)
        al = D.obj(g, g.items[v['igObjectRef@8']])
        attrs = D.mem_ints(g, al['igMemoryRef@4'])[:al['igInt@2']] if al['igInt@2'] else []
        tex = None
        for a in attrs:
            if g.typename(g.items[a]) == 'igTextureBindAttr':
                ta = D.obj(g, g.items[D.obj(g, g.items[a])['igObjectRef@4']])
                im = D.obj(g, g.items[ta['igObjectRef@12']])
                w = struct.unpack('<I', bytes.fromhex(im['igUnsignedInt@2']))[0]; h = struct.unpack('<I', bytes.fromhex(im['igUnsignedInt@3']))[0]
                cl = D.obj(g, g.items[im['igObjectRef@17']])
                pal = np.frombuffer(g.items[cl['igMemoryRef@5']].data, np.uint8).reshape(-1, 4)
                tex = pal[np.frombuffer(g.items[im['igMemoryRef@13']].data, np.uint8)].reshape(h, w, 4)
        kids = D.obj(g, g.items[v['igObjectRef@7']])
        for k in (D.mem_ints(g, kids['igMemoryRef@4'])[:kids['igInt@2']] if kids['igInt@2'] else []):
            if g.typename(g.items[k]) != 'igGeometry': continue
            gal = D.obj(g, g.items[D.obj(g, g.items[k])['igObjectRef@8']])
            ga = D.obj(g, g.items[D.mem_ints(g, gal['igMemoryRef@4'])[0]])
            va = D.obj(g, g.items[ga['igObjectRef@4']])
            comps = D.mem_ints(g, va['igMemoryRef@2'])
            pos = np.frombuffer(g.items[comps[0]].data, '<f4').reshape(-1, 3)
            uv = np.frombuffer(g.items[comps[11]].data, '<f4').reshape(-1, 2) if comps[11] >= 0 else np.zeros((len(pos), 2))
            vc = np.frombuffer(g.items[comps[2]].data, np.uint8).reshape(-1, 4).astype(float) if comps[2] >= 0 else np.full((len(pos), 4), 255.0)
            for i in range(2, len(pos)):
                tri = pos[i - 2:i + 1]
                if np.linalg.norm(np.cross(tri[1] - tri[0], tri[2] - tri[0])) < 1e-9: continue   # degenerate
                v = vc[i - 2:i + 1].mean(0)
                if tex is not None:
                    c = uv[i - 2:i + 1].mean(0)
                    tx = int((c[0] % 1) * (tex.shape[1] - 1)); ty = int((c[1] % 1) * (tex.shape[0] - 1))
                    t = tex[ty, tx].astype(float)
                    col = np.concatenate([np.clip(t[:3] * v[:3] / 128, 0, 255), [t[3] * v[3] / 255]])
                else:
                    col = np.concatenate([np.clip(v[:3] * 2, 0, 255), [v[3]]])
                tris.append((tri.copy(), col))
    return tris


def render(tris, pos, rotm, skel_pts, bones):
    img = Image.new('RGB', (W, H), (20, 20, 30)); dr = ImageDraw.Draw(img, 'RGBA')
    def proj(p):
        xs, ys, zc = CC.project(pos, rotm, p)
        return np.stack([(xs + 1) * W / 2, (1 - ys) * H / 2], -1), zc
    items = []
    for tri, col in tris:
        sp, zc = proj(tri)
        if (zc < 0.3).any(): continue
        if (sp[:, 0] < -W).all() or (sp[:, 0] > 2 * W).all() or (sp[:, 1] < -H).all() or (sp[:, 1] > 2 * H).all(): continue
        items.append((zc.mean(), sp, col))
    items.sort(key=lambda x: -x[0])
    for _, sp, col in items:
        if col[3] < 40: continue
        dr.polygon([tuple(p) for p in sp], fill=tuple(int(c) for c in col[:3]) + (int(col[3]),))
    sp, zc = proj(skel_pts)
    for i, b in enumerate(bones):
        p = b['parent']
        if p > 0 and zc[i] > 0.3 and zc[p] > 0.3:
            c = (230, 40, 40) if b['name'].startswith('L_') else (40, 90, 230) if b['name'].startswith('R_') else (255, 255, 255)
            dr.line([tuple(sp[p]), tuple(sp[i])], fill=c, width=3)
    return img


if __name__ == '__main__':
    stage, work, out = sys.argv[1:4]
    times = [float(t) for t in sys.argv[4].split(',')] if len(sys.argv) > 4 else [0, 12, 30, 50, 70, 90, 110, 140]
    tris = load_stage(stage)
    c = np.load(os.path.join(work, 'ievan_camera.npz'))
    bones = json.load(open(os.path.join(work, 'psp_skeleton.json')))
    root, quats, fps = igbmotion.load_frames(os.path.join(work, 'ievan_frames.bin'))
    tiles = []
    for t in times:
        f = min(int(t * 30), len(c['pos']) - 1)
        W_ = fk_preview.fk(bones, root[min(f, len(root) - 1)], quats[min(f, len(root) - 1)])
        im = render(tris, c['pos'][f], c['rotm'][f], W_, bones)
        ImageDraw.Draw(im).text((4, 4), f'{t:.0f}s', fill=(255, 255, 0))
        tiles.append(im)
    cols = 4; rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * W, rows * H))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * W, (i // cols) * H))
    sheet.save(out); print('saved', out, len(tris), 'triangles')
