"""Reader/writer for Alchemy IGB files (version 8, as used by Project DIVA on PSP).

Layout (all little-endian):
  header            12 x u32
  strings           [size][count] {[len][bytes]}       instance/type names referenced by igString fields
  metafields        count x (len, major, minor) + names
  alignment         [size][?][count][lens][names]       (kept raw)
  metaobjects       count x (len, major, minor, nfields, parent, slots) + {name + nfields x (type, slot, size)}
  externals         [size] ...                          (kept raw)
  memory pools      [size][count] names                 (kept raw)
  dir entries       count x ([type][size][fields...])
  index             [size][count] u16 x count          ref -> dir entry
  root ref          u32
  objects           ([type][size][fields...]) in ref order
  memory blocks     raw bytes in ref order
"""
import struct

U32 = struct.Struct('<I')


def _u32(b, o):
    return U32.unpack_from(b, o)[0]


class Obj:
    """A serialized object: meta type + list of raw field values."""
    __slots__ = ('ref', 'type', 'fields')

    def __init__(self, ref, type_, fields):
        self.ref, self.type, self.fields = ref, type_, fields


class Mem:
    __slots__ = ('ref', 'entry', 'data')

    def __init__(self, ref, entry, data):
        self.ref, self.entry, self.data = ref, entry, data


class IGB:
    def __init__(self, data):
        self.raw = data
        h = struct.unpack_from('<12I', data, 0)
        self.header = list(h)
        (ent_size, ent_count, mo_size, mo_count, obj_size, obj_count,
         mem_size, mem_count, mf_size, mf_count, magic, version) = h
        assert magic == 0xFADA, hex(magic)
        assert version & 0xFFFF == 8, hex(version)
        o = 0x30

        # strings
        size, count = struct.unpack_from('<II', data, o)
        p = o + 8
        self.strings = []
        self.strings_raw = []
        for _ in range(count):
            n = _u32(data, p); p += 4
            self.strings.append(data[p:p + n].rstrip(b'\0').decode('latin-1'))
            self.strings_raw.append(data[p:p + n]); p += n
        self.strings_trailer = data[p:o + size]
        o += size

        # meta fields
        heads = [struct.unpack_from('<3I', data, o + 12 * i) for i in range(mf_count)]
        p = o + 12 * mf_count
        self.metafields = []
        for n, ma, mi in heads:
            self.metafields.append((data[p:p + n].rstrip(b'\0').decode(), ma, mi)); p += n
        assert p == o + mf_size, (p, o + mf_size)
        o = p

        # alignment section (raw)
        size = _u32(data, o)
        self.align_raw = data[o:o + size]
        o += size

        # meta objects
        heads = [struct.unpack_from('<6i', data, o + 24 * i) for i in range(mo_count)]
        p = o + 24 * mo_count
        self.metaobjects = []
        for n, ma, mi, nf, parent, slots in heads:
            name = data[p:p + n].rstrip(b'\0').decode(); p += n
            fields = [struct.unpack_from('<3H', data, p + 6 * k) for k in range(nf)]
            p += 6 * nf
            self.metaobjects.append(dict(name=name, major=ma, minor=mi, parent=parent,
                                         slots=slots, fields=fields, namelen=n))
        assert p == o + mo_size, (p, o + mo_size)
        o = p

        # externals (raw)
        size = _u32(data, o)
        self.ext_raw = data[o:o + size]
        o += size
        # memory pool names (raw)
        size = _u32(data, o)
        self.pool_raw = data[o:o + size]
        o += size

        # dir entries
        self.entries = []
        p = o
        for _ in range(ent_count):
            t, s = struct.unpack_from('<II', data, p)
            vals = list(struct.unpack_from(f'<{(s - 8) // 4}i', data, p + 8))
            self.entries.append((t, vals))
            p += s
        assert p == o + ent_size, (p, o + ent_size)
        o = p

        # index
        size, count = struct.unpack_from('<II', data, o)
        assert count == obj_count + mem_count, (count, obj_count, mem_count)
        self.index = list(struct.unpack_from(f'<{count}H', data, o + 8))
        assert size == 8 + 2 * count
        o += size
        self.root = _u32(data, o)
        o += 4

        # objects + memory in ref order
        self.mo_index = {m['name']: i for i, m in enumerate(self.metaobjects)}
        objdir = self.mo_index['igObjectDirEntry']
        memdir = self.mo_index['igMemoryDirEntry']
        self.items = []
        po = o
        pm = o + obj_size
        for ref, e in enumerate(self.index):
            et, ev = self.entries[e]
            if et == objdir:
                t, s = struct.unpack_from('<II', data, po)
                assert t == ev[1], (ref, t, ev)
                self.items.append(Obj(ref, t, self._parse_fields(t, data, po + 8, po + s)))
                po += s
            else:
                assert et == memdir, et
                n = ev[1]
                self.items.append(Mem(ref, e, data[pm:pm + n]))
                pm += n
                pm += (-pm + o + obj_size) % self._mem_align(ev)
        assert po == o + obj_size, (po, o + obj_size)
        self.tail = data[pm:]
        assert pm == o + obj_size + mem_size and not self.tail, (pm, o + obj_size + mem_size, len(data))

    @staticmethod
    def _mem_align(ev):
        return 1

    # field (type, slot, size) -> number of bytes in file
    def _field_len(self, ftype, fsize):
        return (fsize + 3) & ~3

    def _parse_fields(self, t, data, p, end):
        out = []
        for ftype, slot, fsize in self.metaobjects[t]['fields']:
            n = self._field_len(ftype, fsize)
            out.append(data[p:p + n])
            p += n
        assert p == end, (self.metaobjects[t]['name'], p, end)
        return out

    # ---------- convenience ----------
    def field_names(self, t):
        return [f'{self.metafields[ft][0].replace("MetaField", "")}@{slot}' for ft, slot, _ in self.metaobjects[t]['fields']]

    def typename(self, item):
        if isinstance(item, Obj):
            return self.metaobjects[item.type]['name']
        return 'mem:' + self.metafields[self.entries[item.entry][1][2]][0].replace('MetaField', '')

    def get(self, item, k, fmt='<i'):
        return struct.unpack(fmt, item.fields[k][:struct.calcsize(fmt)])[0]

    def set(self, item, k, value, fmt='<i'):
        b = bytearray(item.fields[k])
        struct.pack_into(fmt, b, 0, value)
        item.fields[k] = bytes(b)

    def mem_entry(self, item):
        return self.entries[item.entry][1]

    # ---------- building new content ----------
    def add_string(self, s):
        """index of string s in the string table (added if missing); igString fields store this index"""
        if s in self.strings:
            return self.strings.index(s)
        self.strings.append(s)
        self.strings_raw.append(s.encode('latin-1') + b'\0')
        return len(self.strings) - 1

    def _entry_for(self, etype, vals_match, vals_new):
        for k, (t, v) in enumerate(self.entries):
            if t == etype and vals_match(v):
                return k
        self.entries.append((etype, list(vals_new)))
        return len(self.entries) - 1

    def add_obj(self, type_name, fields):
        """append an object (fields: list of raw field bytes in meta order) -> its ref"""
        t = self.mo_index[type_name]
        objdir = self.mo_index['igObjectDirEntry']
        proto = next(v for et, v in self.entries if et == objdir)
        e = self._entry_for(objdir, lambda v: v[1] == t, [proto[0], t, proto[2]])
        ref = len(self.items)
        self.items.append(Obj(ref, t, list(fields)))
        self.index.append(e)
        return ref

    def add_mem(self, like_ref, data):
        """append a memory block with the same memory type/flags as block `like_ref` -> its ref"""
        memdir = self.mo_index['igMemoryDirEntry']
        proto = self.entries[self.items[like_ref].entry][1]
        want = list(proto); want[1] = len(data)
        e = self._entry_for(memdir, lambda v: v == want, want)
        ref = len(self.items)
        self.items.append(Mem(ref, e, bytes(data)))
        self.index.append(e)
        return ref

    def set_mem(self, ref, data):
        """replace a memory block's bytes (re-pointing it at a dir entry of the right size)"""
        memdir = self.mo_index['igMemoryDirEntry']
        m = self.items[ref]
        want = list(self.entries[m.entry][1]); want[1] = len(data)
        e = self._entry_for(memdir, lambda v: v == want, want)
        m.entry = e; m.data = bytes(data); self.index[ref] = e

    def field_index(self, item, slot):
        return next(i for i, (ft, sl, _) in enumerate(self.metaobjects[item.type]['fields']) if sl == slot)

    # ---------- writer ----------
    def build(self):
        out = bytearray()
        # strings
        s = bytearray()
        for k, st in enumerate(self.strings):
            if k < len(self.strings_raw) and self.strings_raw[k].rstrip(b'\0').decode('latin-1') == st:
                b = self.strings_raw[k]
            else:
                b = st.encode('latin-1') + b'\0'
            s += U32.pack(len(b)) + b
        s += self.strings_trailer
        strings = struct.pack('<II', 8 + len(s), len(self.strings)) + s
        # meta fields
        mf = bytearray()
        for n, ma, mi in self.metafields:
            mf += struct.pack('<3I', len(n) + 1, ma, mi)
        for n, _, _ in self.metafields:
            mf += n.encode() + b'\0'
        # meta objects
        mo_h = bytearray(); mo_b = bytearray()
        for m in self.metaobjects:
            nb = m['name'].encode() + b'\0'
            nb += b'\0' * (m['namelen'] - len(nb))
            mo_h += struct.pack('<6i', len(nb), m['major'], m['minor'], len(m['fields']), m['parent'], m['slots'])
            mo_b += nb
            for f in m['fields']:
                mo_b += struct.pack('<3H', *f)
        mo = mo_h + mo_b
        # entries
        ent = bytearray()
        for t, vals in self.entries:
            ent += struct.pack(f'<II{len(vals)}i', t, 8 + 4 * len(vals), *vals)
        # index
        idx = struct.pack('<II', 8 + 2 * len(self.index), len(self.index)) + struct.pack(f'<{len(self.index)}H', *self.index)
        # objects / memory
        objb = bytearray(); memb = bytearray()
        nobj = nmem = 0
        for it in self.items:
            if isinstance(it, Obj):
                body = b''.join(it.fields)
                objb += struct.pack('<II', it.type, 8 + len(body)) + body
                nobj += 1
            else:
                memb += it.data
                nmem += 1
        h = list(self.header)
        h[0], h[1] = len(ent), len(self.entries)
        h[2], h[3] = len(mo), len(self.metaobjects)
        h[4], h[5] = len(objb), nobj
        h[6], h[7] = len(memb), nmem
        h[8], h[9] = len(mf), len(self.metafields)
        out += struct.pack('<12I', *h)
        out += strings + mf + self.align_raw + mo + self.ext_raw + self.pool_raw + ent + idx
        out += U32.pack(self.root) + objb + memb
        return bytes(out)


if __name__ == '__main__':
    import sys
    d = open(sys.argv[1], 'rb').read()
    g = IGB(d)
    rt = g.build()
    print('roundtrip identical:', rt == d, len(rt), len(d))
    from collections import Counter
    print(Counter(g.typename(i) for i in g.items).most_common())
