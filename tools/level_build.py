"""PSP-native grass-field level for the Ievan Polkka PV (in the style of the Future Tone stage ns016),
plus the animated leek props, written as one Alchemy .igb with two top-level scenes:

  Scene Root (igGroup)
    1: sceneGraph 'level'  -> shown as the stage via CHANGE_FIELD 1 (static)
    2: sceneGraph 'leeks'  -> shown via EFFECT 2 (effects play their transform animation)

Built for the PSP's limits: everything is finely tessellated (the GE drops whole triangles that reach far off
screen / behind the camera), drawn back-to-front by scene order (sky, clouds, hills, ground, tufts, flowers),
8-bit textures <= 64KB, and vertex colours halved because the game renders with 2x colour doubling.

usage: py -P level_build.py <work dir> <stage textures dir> <template .igb> <proto .igb> <out.igb>
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
from stage_build import Builder, strip_from_triangles, strip_mesh
from igb import IGB
import leeks

RNG = np.random.default_rng(39)        # fixed seed: same level every build
GROUND_R, SKY_R = 220.0, 235.0


def half(rgb):                         # display colour -> vertex colour (2x colour doubling)
    return np.clip(np.asarray(rgb, float) / 2, 0, 255)


def grid_strip(rows):
    """rows: list of vertex-index lists of equal length -> one strip over all bands (degenerate joins)"""
    out = []
    for a, b in zip(rows, rows[1:]):
        band = [v for pair in zip(a, b) for v in pair]
        if out:
            out += [out[-1], band[0]]
        out += band
    return np.array(out)


def quads_to_tris(quads):
    """quads (k,4) vertex indices in order -> triangles"""
    t = []
    for a, b, c, d in quads:
        t += [(a, b, c), (a, c, d)]
    return np.array(t)


class Mesh:
    def __init__(self):
        self.p, self.c, self.uv = [], [], []
    def add(self, p, c, uv):
        self.p.append(p); self.c.append(c); self.uv.append(uv); return len(self.p) - 1
    def arrays(self, idx):
        P = np.array(self.p)[idx]; C = np.array(self.c)[idx]; UV = np.array(self.uv)[idx]
        N = np.tile([0.0, 1.0, 0.0], (len(idx), 1))
        return P, N, C, UV


# --------------------------------------------------------------------------------------------- textures
def tex_ground(src):
    im = Image.open(src).convert('RGB').resize((256, 256), Image.LANCZOS)
    im = ImageEnhance.Color(im).enhance(1.45)
    im = ImageEnhance.Brightness(im).enhance(1.55)
    return im.convert('RGBA')


def tex_tufts(src):
    im = Image.open(src).convert('RGBA').resize((512, 128), Image.LANCZOS)
    rgb = ImageEnhance.Color(im.convert('RGB')).enhance(1.25)
    out = rgb.convert('RGBA'); out.putalpha(im.split()[3])
    return out


def tex_clouds(src):
    return Image.open(src).convert('RGBA').resize((256, 256), Image.LANCZOS)


def tex_flowers():
    """procedural 128x128 atlas, 4 flowers (2x2 cells): pink, yellow, white, lavender, each on a stem"""
    S = 512
    im = Image.new('RGBA', (S, S), (60, 130, 50, 0)); d = ImageDraw.Draw(im)
    cols = [((255, 120, 185), (255, 220, 90)), ((255, 215, 50), (230, 120, 30)),
            ((252, 252, 245), (255, 200, 40)), ((185, 140, 255), (255, 235, 120))]
    for k, (petal, centre) in enumerate(cols):
        ox, oy = (k % 2) * S // 2, (k // 2) * S // 2
        cx, cy, r = ox + S // 4, oy + S // 6 + 20, 52
        d.line([(cx, cy), (cx + 6, oy + S // 2 - 4)], fill=(70, 150, 55, 255), width=14)
        d.ellipse([cx + 8, cy + 90, cx + 60, cy + 120], fill=(80, 165, 60, 255))
        for j in range(6):
            a = j * np.pi / 3
            px, py = cx + np.cos(a) * r * 0.62, cy + np.sin(a) * r * 0.62
            d.ellipse([px - r * 0.48, py - r * 0.48, px + r * 0.48, py + r * 0.48], fill=petal + (255,))
        d.ellipse([cx - r * 0.38, cy - r * 0.38, cx + r * 0.38, cy + r * 0.38], fill=centre + (255,))
    return im.filter(ImageFilter.SMOOTH).resize((128, 128), Image.LANCZOS)


# --------------------------------------------------------------------------------------------- geometry
def sky():
    m = Mesh(); rows = []
    seg = 48
    elev = np.radians([-8, 0, 3, 7, 12, 18, 26, 36, 48, 62, 76, 90])
    top, mid, hor = np.array([52, 118, 232]), np.array([105, 172, 245]), np.array([188, 226, 252])
    for e in elev:
        f = np.clip(e / np.radians(90), 0, 1)
        col = hor + (mid - hor) * min(1, f / 0.25) if f < 0.25 else mid + (top - mid) * ((f - 0.25) / 0.75) ** 0.8
        row = []
        for s in range(seg + 1):
            a = 2 * np.pi * s / seg
            p = SKY_R * np.array([np.cos(e) * np.cos(a), np.sin(e), np.cos(e) * np.sin(a)])
            row.append(m.add(p, [*col, 255], [0, 0]))   # untextured: shown as-is (the dim sky came from halving it)
        rows.append(row)
    return m, grid_strip(rows)


def cloud_band():
    m = Mesh(); rows = []
    seg = 64; r = SKY_R - 6
    elev = np.radians([1.0, 4, 8, 12, 16])
    for k, e in enumerate(elev):
        v = 1 - k / (len(elev) - 1)
        row = []
        for s in range(seg + 1):
            a = 2 * np.pi * s / seg
            p = r * np.array([np.cos(e) * np.cos(a), np.sin(e), np.cos(e) * np.sin(a)])
            row.append(m.add(p, [128, 128, 128, 150 if 0 < k < len(elev) - 1 else 0], [4 * s / seg, v]))
        rows.append(row)
    return m, grid_strip(rows)


def ground():
    m = Mesh(); rows = []
    seg = 96
    radii = [0, 0.75, 1.5, 2.5, 3.5, 4.5, 5.5, 7, 8.5, 10, 12, 14.5, 17.5, 21, 25, 30, 36, 44, 54, 66, 80,
             98, 120, 145, 175, GROUND_R]
    near, far = np.array([172, 172, 142]), np.array([150, 166, 168])      # texture multipliers (128 = x1)
    for r in radii:
        f = np.clip(r / 140, 0, 1) ** 0.8
        col = near + (far - near) * f
        row = []
        for s in range(seg + 1):
            a = 2 * np.pi * s / seg
            p = np.array([r * np.cos(a), 0.0, r * np.sin(a)])
            row.append(m.add(p, [*col, 255], [p[0] / 6.0, p[2] / 6.0]))
        rows.append(row)
    return m, grid_strip(rows)


def hills():
    m = Mesh(); rows = []
    seg = 72
    phase = RNG.uniform(0, 2 * np.pi, 3)
    for k, r in enumerate([146, 170, 190, 212, GROUND_R - 2]):
        row = []
        for s in range(seg + 1):
            a = 2 * np.pi * s / seg
            h = (6 + 4 * np.sin(3 * a + phase[0]) + 3 * np.sin(7 * a + phase[1]) + 1.5 * np.sin(13 * a + phase[2]))
            h = h * [0.0, 0.55, 1.0, 0.85, 0.2][k] - (0.8 if k == 0 else 0.0)   # inner edge tucked under the ground
            p = np.array([r * np.cos(a), h, r * np.sin(a)])
            haze = min(1, k / 3)
            col = np.array([160, 170, 140]) * (1 - haze) + np.array([150, 168, 190]) * haze
            row.append(m.add(p, [*col, 255], [p[0] / 9.0, p[2] / 9.0]))
        rows.append(row)
    return m, grid_strip(rows)


def billboards(n, rmin, rmax, size, uv_cells, colour, avoid=0.0):
    """crossed quads scattered on the ground; uv_cells: list of (u0,v0,u1,v1)"""
    m = Mesh(); quads = []
    for _ in range(n):
        r = np.sqrt(RNG.uniform(rmin ** 2, rmax ** 2)); a = RNG.uniform(0, 2 * np.pi)
        cx, cz = r * np.cos(a), r * np.sin(a)
        w, h = size[0] * RNG.uniform(0.75, 1.25), size[1] * RNG.uniform(0.75, 1.3)
        u0, v0, u1, v1 = uv_cells[RNG.integers(len(uv_cells))]
        shade = np.clip(colour * RNG.uniform(0.9, 1.1), 0, 255)
        rot = RNG.uniform(0, np.pi)
        for k in range(2):
            ang = rot + k * np.pi / 2
            dx, dz = np.cos(ang) * w / 2, np.sin(ang) * w / 2
            ids = [m.add([cx - dx, 0, cz - dz], [*shade, 255], [u0, v1]),
                   m.add([cx + dx, 0, cz + dz], [*shade, 255], [u1, v1]),
                   m.add([cx + dx, h, cz + dz], [*shade, 255], [u1, v0]),
                   m.add([cx - dx, h, cz - dz], [*shade, 255], [u0, v0])]
            quads.append(ids)
    tris = quads_to_tris(quads)
    return m, strip_from_triangles(tris)


# --------------------------------------------------------------------------------------------- build
def build(work, texdir, template, proto, out):
    B = Builder(open(template, 'rb').read(), [open(proto, 'rb').read()])
    textures = []

    def material(name, mesh_idx, tex=None, blend=False):
        mesh, idx = mesh_idx
        P, N, C, UV = mesh.arrays(idx)
        geom, box = B.geometry(name, P, N, C, UV)
        attrs = [B.obj('igCullFaceAttr', s4=False), B.obj('igShadeModelAttr'),
                 B.obj('igMaterialAttr', s5=(0.8, 0.8, 0.8, 1.0)), B.obj('igMaterialModeAttr')]
        if tex is not None:
            t = B.texture(tex, name + '.png'); textures.append(t)
            attrs += [B.obj('igTextureBindAttr', s4=t), B.obj('igTextureStateAttr', s4=True)]
        else:
            attrs += [B.obj('igTextureStateAttr', s4=False)]
        if blend:
            attrs += [B.obj('igBlendFunctionAttr'), B.obj('igBlendStateAttr', s4=True)]
        print(f'  {name:10s} tris~{len(idx) - 2:6d} verts={len(idx):6d} tex={tex.size if tex else "-"} blend={blend}')
        return B.obj('igAttrSet', s2=name, s3=-1, s5=0, s7=B.reflist('igNodeList', [geom]),
                     s8=B.reflist('igAttrList', attrs), s9=False), box

    T = lambda f: os.path.join(texdir, f)
    tuft_cells = [(u, 0.0, u + 0.12, 1.0) for u in np.linspace(0, 0.88, 12)]
    flower_cells = [(0, 0, .5, .5), (.5, 0, 1, .5), (0, .5, .5, 1), (.5, .5, 1, 1)]
    parts = [
        material('sky', sky()),
        material('clouds', cloud_band(), tex_clouds(T('f_diva_stgns016_nk_clouds.png')), blend=True),
        material('hills', hills(), tex_ground(T('f_diva_stgns016_yi_grass02.png'))),
        material('ground', ground(), tex_ground(T('f_diva_stgns016_yi_grass02.png'))),
        material('tufts', billboards(420, 2.0, 48, (1.1, 0.7), tuft_cells, np.array([118, 128, 110])),
                 tex_tufts(T('f_diva_stgns016_yi_grass00.png')), blend=True),
        material('flowers', billboards(360, 1.5, 34, (0.5, 0.5), flower_cells, np.array([150, 150, 150])),
                 tex_flowers(), blend=True),
    ]
    lo = np.min([b[0] for _, b in parts], 0); hi = np.max([b[1] for _, b in parts], 0)
    level = B.obj('igAttrSet', s2='sceneGraph', s3=B.aabox(lo, hi), s5=2,
                  s7=B.reflist('igNodeList', [p for p, _ in parts]), s8=B.reflist('igAttrList', []), s9=False)

    # scenes 2..N: one effect scene per leek section. The DSC switches each on with EFFECT at the section start
    # and off with EFFECT_OFF at its end, so the leeks can never show outside their sections; each scene's
    # animation is keyed from 0 = section start (effects restart their clock when switched on).
    mesh = leeks.leek_mesh()
    props = leeks.props(work)
    segs = sorted({tuple(s) for pr in props for s in pr['segs']})
    groups = []
    for a, b in segs:                                   # merge overlapping right/left windows into one section
        if groups and a <= groups[-1][1] + 0.5:
            groups[-1][1] = max(groups[-1][1], b)
        else:
            groups.append([a, b])
    scenes, sections, duration = [], [], 0
    for gi, (a, b) in enumerate(groups):
        f0, f1 = int(round(a * 30)), int(round(b * 30))
        nodes = []
        for pr in props:
            if not any(s[0] < b and s[1] > a for s in pr['segs']):
                continue
            fr = np.arange(f0, min(f1 + 1, len(pr['all_scale'])))
            geom, _ = B.geometry(f'{pr["name"]}{gi}Shape', *strip_mesh(*mesh))
            attrs = [B.obj('igCullFaceAttr', s4=False), B.obj('igShadeModelAttr'),
                     B.obj('igMaterialAttr', s5=(0.8, 0.8, 0.8, 1.0)), B.obj('igMaterialModeAttr'),
                     B.obj('igTextureStateAttr', s4=False)]
            aset = B.obj('igAttrSet', s2=f'{pr["name"]}{gi}Mat', s3=-1, s5=0, s7=B.reflist('igNodeList', [geom]),
                         s8=B.reflist('igAttrList', attrs), s9=False)
            node, dur = B.animated(f'{pr["name"]}{gi}', [aset], (fr - f0) / 30.0, pr['all_pos'][fr],
                                   pr['all_rotm'][fr], pr['all_scale'][fr])
            nodes.append(node); duration = max(duration, dur)
        scenes.append(B.obj('igAttrSet', s2='sceneGraph', s3=B.aabox(lo, hi), s5=2,
                            s7=B.reflist('igNodeList', nodes), s8=B.reflist('igAttrList', []), s9=False))
        sections.append(dict(effect=gi + 2, start=a, end=b))
        print(f'  leek section {gi + 2}: {a:.2f}-{b:.2f}s, {len(nodes)} leek(s)')
    json.dump(sections, open(os.path.join(work, 'leek_sections.json'), 'w'), indent=1)

    root = B.obj('igGroup', s2='Scene Root', s3=-1, s5=2, s7=B.reflist('igNodeList', [level] + scenes))
    si = B.obj('igSceneInfo', s2='Scene Graph', s5=root, s6=B.reflist('igTextureList', textures),
               s7=B.obj('igGraphPathList', s2=0, s3=0, s4=-1), s8=0, s9=duration, s11=B.reflist('igNodeList', []))
    B.g.root = B.reflist('igInfoList', [si])
    data = B.g.build()
    IGB(data)
    open(out, 'wb').write(data)
    print(f'level + leeks: {len(textures)} textures, {len(data)} bytes -> {out}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    build(*sys.argv[1:6])
