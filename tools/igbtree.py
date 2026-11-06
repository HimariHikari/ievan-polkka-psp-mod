"""Print an Alchemy scene graph (nodes, attributes, geometry, textures) from a DIVA PSP .igb"""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from igb import IGB, Obj, Mem
import igbdump as D

def refs_in_list(g, ref):
    if ref < 0: return []
    v = D.obj(g, g.items[ref])
    n = v.get('igInt@2', 0); m = v.get('igMemoryRef@4', -1)
    if m < 0 or not n or g.typename(g.items[m]) != 'mem:igObjectRef': return []
    return D.mem_ints(g, m)[:n]

def short(g, it):
    v = D.obj(g, it)
    return {k: (val if not isinstance(val, str) or len(val) < 40 else val[:40] + '..') for k, val in v.items()}

def walk(g, ref, depth, seen, out):
    if ref < 0 or ref in seen: return
    seen.add(ref)
    it = g.items[ref]
    t = g.typename(it)
    v = D.obj(g, it)
    out.append('  ' * depth + f'{t} #{ref} ' + str(short(g, it)))
    mo = g.metaobjects[it.type]
    for k, (ft, slot, _) in enumerate(mo['fields']):
        fn = g.metafields[ft][0]
        if fn == 'igObjectRefMetaField':
            r = struct.unpack('<i', it.fields[k])[0]
            if r < 0: continue
            sub = g.items[r]
            if isinstance(sub, Obj) and refs_in_list(g, r):
                kids = refs_in_list(g, r)
                out.append('  ' * (depth + 1) + f'[{g.typename(sub)} #{r}: {len(kids)}]')
                for c in kids: walk(g, c, depth + 2, seen, out)
            else:
                walk(g, r, depth + 1, seen, out)

if __name__ == '__main__':
    g = IGB(open(sys.argv[1], 'rb').read())
    out = []
    il = [i for i in g.items if isinstance(i, Obj) and g.typename(i) == 'igInfoList'][0]
    for r in refs_in_list(g, il.ref):
        walk(g, r, 0, set(), out)
    sys.stdout.reconfigure(encoding='utf-8')
    lim = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    print('\n'.join(out[:lim]))
    from collections import Counter
    print(Counter(g.typename(i) for i in g.items).most_common())
