"""Build the v1.1 installer payload from the v1.0 one (pulled out of the v1.0 release exe), replacing only the
files that changed, and check every replaced file against the modded ISO in the project folder.

usage: py -P make_payload_v11.py   -> payload.bin (+ checks)
"""
import os, struct, sys, zlib, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import isotool as T, isopatch

HERE = os.path.dirname(os.path.abspath(__file__))
ISO = os.path.join(HERE, '..', 'Hatsune Miku - Project Diva (English) - Ievan Polkka dance.iso')
V10_EXE = os.path.join(HERE, 'v10', 'Ievan Polkka PV mod (Project DIVA PSP)', 'IevanPolkkaPatcher.exe')
NEW_FILES = {(0, 926): 'pve_27_v14.igb', (1, 78): 'pv_27_easy.dsc', (1, 79): 'pv_27_normal.dsc', (1, 80): 'pv_27_hard.dsc'}
ARCH = {0: 'DivaDataList.afs', 1: 'DivaScriptList.afs'}


def parse(b):
    o = 0
    def u32():
        nonlocal o; v = struct.unpack_from('<I', b, o)[0]; o += 4; return v
    ver = u32(); esha = b[o:o + 20]; o += 20; esize = u32(); nd = u32(); ns = u32()
    patches = []
    for _ in range(u32()):
        off = u32(); ln = u32(); old = b[o:o + ln]; o += ln; new = b[o:o + ln]; o += ln; patches.append([off, old, new])
    files = []
    for _ in range(u32()):
        arch = b[o]; o += 1; idx = u32(); sha = b[o:o + 20]; o += 20; sz = u32(); data = b[o:o + sz]; o += sz
        files.append([arch, idx, sha, data])
    assert o == len(b)
    return dict(ver=ver, esha=esha, esize=esize, nd=nd, ns=ns, patches=patches, files=files)


def build(d):
    b = bytearray(struct.pack('<I', d['ver']) + d['esha'] + struct.pack('<III', d['esize'], d['nd'], d['ns']))
    b += struct.pack('<I', len(d['patches']))
    for off, old, new in d['patches']: b += struct.pack('<II', off, len(old)) + old + new
    b += struct.pack('<I', len(d['files']))
    for arch, idx, sha, data in d['files']: b += struct.pack('<BI', arch, idx) + sha + struct.pack('<I', len(data)) + data
    return bytes(b)


if __name__ == '__main__':
    os.chdir(HERE)
    exe = open(V10_EXE, 'rb').read()
    p = exe.find(b'IPMOD001'); n = struct.unpack_from('<I', exe, p - 4)[0]
    body = zlib.decompress(exe[p + 8:p + n], -15)
    d = parse(body); assert build(d) == body
    v10 = parse(body)
    for f in d['files']:
        key = (f[0], f[1])
        if key in NEW_FILES: f[3] = open(NEW_FILES[key], 'rb').read()
    # every replaced file must equal what is in the tested ISO; every EBOOT patch must be applied there
    for arch, idx, sha, data in d['files']:
        assert T.read_entry(ISO, ARCH[arch], idx) == data, (arch, idx)
    with open(ISO, 'rb') as f:
        base = isopatch.find(f, 'PSP_GAME/SYSDIR/EBOOT.BIN')['ext'] * 2048
        for off, old, new in d['patches']:
            f.seek(base + off); assert f.read(len(new)) == new, hex(off)
    changed = [(a[0], a[1]) for a, b in zip(v10['files'], d['files']) if a[3] != b[3]]
    print('changed vs v1.0:', changed, '| original-file hashes unchanged:', all(a[2] == b[2] for a, b in zip(v10['files'], d['files'])),
          '| EBOOT patches unchanged:', v10['patches'] == d['patches'])
    print('all', len(d['files']), 'files and', len(d['patches']), 'EBOOT patches match the modded ISO')
    nb = build(d)
    open('payload.bin', 'wb').write(b'IPMOD001' + zlib.compress(nb, 9)[2:-4])
    print('payload.bin', os.path.getsize('payload.bin'), 'bytes')
