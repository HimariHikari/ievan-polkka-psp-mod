"""In-place ISO patch helpers for the Ievan Polkka mod (no full rebuild needed).

- replace AFS entries inside the ISO when the new data fits the entry's padded slot (updates the TOC size only;
  the name table's last field is not a size in these archives)
- patch bytes in a file inside the ISO, checking the old bytes first
"""
import os, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'repo', 'tools'))
import afs, dsc, isopatch
from igb import IGB
import igbdump as D

AFS_DIR = 'PSP_GAME/USRDIR/media/afs/'


def read_entry(iso, archive, idx):
    with open(iso, 'rb') as f:
        base = isopatch.find(f, AFS_DIR + archive)['ext'] * 2048
        f.seek(base + 8 + 8 * idx); off, size = struct.unpack('<II', f.read(8))
        f.seek(base + off); return f.read(size)


def replace_entries(iso, archive, new):
    """new = {idx: bytes}; each must fit before the next entry"""
    with open(iso, 'r+b') as f:
        base = isopatch.find(f, AFS_DIR + archive)['ext'] * 2048
        f.seek(base); hdr = f.read(8); assert hdr[:4] == b'AFS\0'
        count = struct.unpack_from('<I', hdr, 4)[0]
        f.seek(base + 8); toc = [struct.unpack('<II', f.read(8)) for _ in range(count)]
        for idx, data in new.items():
            off, size = toc[idx]
            room = (toc[idx + 1][0] - off) if idx + 1 < count else size
            assert len(data) <= room, (archive, idx, len(data), room)
            f.seek(base + off); f.write(data + b'\0' * (max(room, size) - len(data) if idx + 1 < count else 0))
            f.seek(base + 8 + 8 * idx + 4); f.write(struct.pack('<I', len(data)))


def patch_file_bytes(iso, path, offset, old, new):
    with open(iso, 'r+b') as f:
        pos = isopatch.find(f, path)['ext'] * 2048 + offset
        f.seek(pos); cur = f.read(len(old))
        assert cur in (old, new), (path, hex(offset), cur.hex())
        f.seek(pos); f.write(new)


def replace_last_file(iso, path, data):
    """rewrite the ISO's LAST file at its current extent (it may grow or shrink); fixes the dir record + PVD size"""
    S = isopatch.SECTOR
    with open(iso, 'r+b') as f:
        rec = isopatch.find(f, path)
        f.seek(0, 2); end = f.tell()
        alloc = (rec['size'] + S - 1) // S * S
        assert rec['ext'] * S + alloc == end, 'not the last file in the image'
        f.seek(rec['ext'] * S); f.write(data); f.write(b'\0' * ((-len(data)) % S))
        f.truncate()
        f.seek(rec['abs'] + 10); f.write(struct.pack('<I', len(data)) + struct.pack('>I', len(data)))
        f.seek(0, 2); total = f.tell() // S
        f.seek(16 * S + 80); f.write(struct.pack('<I', total) + struct.pack('>I', total))
    return total


def no_notes(dsc_bytes):
    """test-only: drop the rhythm-game targets so the song always plays to the end"""
    return dsc.write([c for c in dsc.parse(dsc_bytes) if c[1] != 'TARGET'])


def geometry_box(g, name):
    geo = [o for o in D.by_type(g, 'igGeometry') if D.obj(g, o).get('igString@2') == name][0]
    return g.items[D.obj(g, geo)['igObjectRef@3']]


def set_box(g, box, lo, hi):
    box.fields[g.field_index(box, 2)] = struct.pack('<3f', *lo)
    box.fields[g.field_index(box, 3)] = struct.pack('<3f', *hi)
