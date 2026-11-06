"""Pack the mod into a small payload for the Windows patcher (only the mod's own data - no game files).

usage: py -P make_payload.py <work dir> <out payload.bin>

Payload (little-endian), the whole thing deflate-compressed after an 8-byte magic:
  'IPMOD001'
  deflate( u32 version
           20-byte sha1 of the original EBOOT.BIN, u32 size     (input check)
           u32 n_afs_entries_expected (DivaDataList), u32 n_script_entries_expected
           u32 n_eboot_patches, then {u32 offset, u32 len, old bytes, new bytes}
           u32 n_files, then {u8 archive (0 = DivaDataList, 1 = DivaScriptList), u32 index,
                              20-byte sha1 of the original entry, u32 size, data} )
"""
import os, sys, struct, hashlib, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import afs

AFS_DIR = 'PSP_GAME/USRDIR/media/afs'


def eboot_patches(orig, new):
    assert len(orig) == len(new)
    out, i = [], 0
    while i < len(orig):
        if orig[i] != new[i]:
            j = i
            while j < len(orig) and (orig[j] != new[j] or (j + 4 < len(orig) and orig[j + 1:j + 4] != new[j + 1:j + 4])):
                j += 1
            out.append((i, orig[i:j], new[i:j])); i = j
        else:
            i += 1
    return out


def main(work, out_path):
    iso_x = os.path.join(work, 'iso')
    tmp = os.path.join(work, 'build_tmp')
    eb_o = open(os.path.join(iso_x, 'PSP_GAME/SYSDIR/EBOOT.BIN'), 'rb').read()
    eb_n = open(os.path.join(tmp, 'EBOOT.BIN'), 'rb').read()
    patches = eboot_patches(eb_o, eb_n)

    files = []
    for arch, name in ((0, 'DivaDataList.afs'), (1, 'DivaScriptList.afs')):
        o, _ = afs.read_full(os.path.join(iso_x, AFS_DIR, name))
        n, _ = afs.read_full(os.path.join(tmp, name))
        assert len(o) == len(n), name
        for i, (a, b) in enumerate(zip(o, n)):
            if a['data'] != b['data']:
                files.append((arch, i, hashlib.sha1(a['data']).digest(), b['data'], a['name']))
        if arch == 0: n_data = len(o)
        else: n_script = len(o)

    body = bytearray()
    body += struct.pack('<I', 1)
    body += hashlib.sha1(eb_o).digest() + struct.pack('<I', len(eb_o))
    body += struct.pack('<II', n_data, n_script)
    body += struct.pack('<I', len(patches))
    for off, old, new in patches:
        body += struct.pack('<II', off, len(old)) + old + new
    body += struct.pack('<I', len(files))
    for arch, idx, sha, data, name in files:
        body += struct.pack('<BI', arch, idx) + sha + struct.pack('<I', len(data)) + data
    blob = b'IPMOD001' + zlib.compress(bytes(body), 9)[2:-4]      # raw deflate stream for .NET DeflateStream
    open(out_path, 'wb').write(blob)
    print(f'EBOOT patches: {[(hex(o), len(a)) for o, a, _ in patches]}')
    for arch, idx, sha, data, name in files:
        print(f'  {["DivaDataList", "DivaScriptList"][arch]}#{idx} {name}: {len(data)} bytes')
    print(f'payload: {len(body)} bytes -> {len(blob)} compressed -> {out_path}')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
