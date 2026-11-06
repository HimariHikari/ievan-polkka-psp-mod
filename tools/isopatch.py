"""Replace files inside an ISO9660 image (PSP UMD) without a full rebuild.
Files that still fit their original sector allocation are overwritten in place; larger files are
appended at the end of the image and their directory record (extent + size) is updated."""
import struct, shutil, os

SECTOR = 2048


def _dir_records(f, lba, size):
    f.seek(lba * SECTOR)
    data = f.read(size)
    o = 0
    while o < len(data):
        ln = data[o]
        if ln == 0:                                   # padding to next sector
            o = (o // SECTOR + 1) * SECTOR
            continue
        rec = data[o:o + ln]
        ext = struct.unpack_from('<I', rec, 2)[0]
        sz = struct.unpack_from('<I', rec, 10)[0]
        flags = rec[25]
        nlen = rec[32]
        name = rec[33:33 + nlen].decode('ascii', 'replace').split(';')[0]
        yield dict(abs=lba * SECTOR + o, ext=ext, size=sz, dir=bool(flags & 2), name=name)
        o += ln


def find(f, path):
    f.seek(16 * SECTOR)
    pvd = f.read(SECTOR)
    assert pvd[1:6] == b'CD001'
    root = pvd[156:156 + 34]
    lba, size = struct.unpack_from('<I', root, 2)[0], struct.unpack_from('<I', root, 10)[0]
    rec = None
    for part in path.strip('/').split('/'):
        rec = next((r for r in _dir_records(f, lba, size) if r['name'].upper() == part.upper()), None)
        if rec is None:
            raise FileNotFoundError(path)
        lba, size = rec['ext'], rec['size']
    return rec


def patch(src_iso, dst_iso, replacements):
    """replacements: {iso_path: local_file_path}"""
    if os.path.abspath(src_iso) != os.path.abspath(dst_iso):
        shutil.copyfile(src_iso, dst_iso)
    with open(dst_iso, 'r+b') as f:
        f.seek(0, 2)
        end = f.tell()
        assert end % SECTOR == 0
        for iso_path, local in replacements.items():
            rec = find(f, iso_path)
            data = open(local, 'rb').read()
            alloc = (rec['size'] + SECTOR - 1) // SECTOR * SECTOR
            if len(data) <= alloc:
                lba = rec['ext']
                where = 'in place'
            else:
                lba = end // SECTOR
                end += (len(data) + SECTOR - 1) // SECTOR * SECTOR
                where = 'appended'
            f.seek(lba * SECTOR)
            f.write(data)
            pad = (-len(data)) % SECTOR
            if pad:
                f.write(b'\0' * pad)
            # directory record: extent (LE+BE) at +2, size (LE+BE) at +10
            f.seek(rec['abs'] + 2)
            f.write(struct.pack('<I', lba) + struct.pack('>I', lba) + struct.pack('<I', len(data)) + struct.pack('>I', len(data)))
            print(f'  {iso_path}: {len(data)} bytes {where} at LBA {lba}')
        f.seek(0, 2)
        total = f.tell() // SECTOR
        f.seek(16 * SECTOR + 80)
        f.write(struct.pack('<I', total) + struct.pack('>I', total))
    return total
