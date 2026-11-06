"""Minimal CRI AFS archive reader/writer for Project DIVA (PSP)."""
import struct, sys, os

def read_afs(path):
    with open(path, 'rb') as f:
        hdr = f.read(8)
        assert hdr[:4] == b'AFS\0', hdr
        count = struct.unpack('<I', hdr[4:8])[0]
        toc = [struct.unpack('<II', f.read(8)) for _ in range(count)]
        # filename table pointer: right after TOC, or just before first file
        nt_off, nt_size = struct.unpack('<II', f.read(8))
        if nt_off == 0:
            f.seek(toc[0][0] - 8)
            nt_off, nt_size = struct.unpack('<II', f.read(8))
        names = [None] * count
        if nt_off:
            f.seek(nt_off)
            for i in range(count):
                e = f.read(48)
                if len(e) < 48: break
                names[i] = e[:32].split(b'\0')[0].decode('ascii', 'replace')
    return [(i, names[i] or f'{i:05d}.bin', o, s) for i, (o, s) in enumerate(toc)]

def extract(afs_path, indices, outdir):
    os.makedirs(outdir, exist_ok=True)
    ents = read_afs(afs_path)
    out = []
    with open(afs_path, 'rb') as f:
        for i in indices:
            _, n, o, s = ents[i]
            f.seek(o)
            p = os.path.join(outdir, f'{i:04d}_{n}')
            with open(p, 'wb') as g:
                g.write(f.read(s))
            out.append(p)
    return out


def read_full(path):
    """-> (entries, meta) where entries = [dict(name, data, raw_name_entry)]"""
    with open(path, 'rb') as f:
        blob = f.read()
    count = struct.unpack_from('<I', blob, 4)[0]
    toc = [struct.unpack_from('<II', blob, 8 + 8 * i) for i in range(count)]
    nt_off, nt_size = struct.unpack_from('<II', blob, 8 + 8 * count)
    first = toc[0][0]
    ents = []
    for i, (o, s) in enumerate(toc):
        raw = blob[nt_off + 48 * i: nt_off + 48 * i + 48] if nt_off else b''
        ents.append(dict(name=raw[:32].split(b'\0')[0].decode('ascii', 'replace') if raw else f'{i:05d}',
                         data=blob[o:o + s], raw_name=raw))
    return ents, dict(first=first, align=0x800, has_names=bool(nt_off))


def name_entry(name, size, date=(2009, 5, 10, 0, 0, 0)):
    nb = name.encode('ascii')[:31]
    return nb + b'\0' * (32 - len(nb)) + struct.pack('<6HI', *date, size)


def write_full(path, ents, meta):
    align = meta['align']
    count = len(ents)
    first = max(meta['first'], (8 + 8 * count + 8 + align - 1) // align * align)
    out = bytearray(first)
    out[0:8] = b'AFS\0' + struct.pack('<I', count)
    toc = []
    for e in ents:
        o = len(out)
        toc.append((o, len(e['data'])))
        out += e['data']
        out += b'\0' * ((-len(out)) % align)
    nt_off = len(out)
    if meta['has_names']:
        for e in ents:
            out += e['raw_name'] if e.get('raw_name') else name_entry(e['name'], len(e['data']))
        nt_size = 48 * count
        out += b'\0' * ((-len(out)) % align)
    else:
        nt_off = nt_size = 0
    for i, (o, s) in enumerate(toc):
        struct.pack_into('<II', out, 8 + 8 * i, o, s)
    struct.pack_into('<II', out, 8 + 8 * count, nt_off, nt_size)
    with open(path, 'wb') as f:
        f.write(out)
    return toc


if __name__ == '__main__':
    # afs.py <archive.afs>            -> list the entries
    # afs.py <archive.afs> <out dir>  -> extract every entry as NNNN_<name>
    ents = read_afs(sys.argv[1])
    if len(sys.argv) > 2:
        print(f'{len(extract(sys.argv[1], range(len(ents)), sys.argv[2]))} files -> {sys.argv[2]}')
    else:
        for i, n, o, s in ents:
            print(f'{i:5d} {o:#011x} {s:10d} {n}')
