"""Dump skeleton + animation summary from a DIVA PSP motion .igb"""
import sys, struct
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from igb import IGB, Obj, Mem

def load(path):
    return IGB(open(path, 'rb').read())

def by_type(g, name):
    t = g.mo_index[name]
    return [i for i in g.items if isinstance(i, Obj) and i.type == t]

def fval(g, it, k):
    ft = g.metaobjects[it.type]['fields'][k][0]
    n = g.metafields[ft][0]
    b = it.fields[k]
    if n in ('igObjectRefMetaField', 'igMemoryRefMetaField', 'igIntMetaField', 'igEnumMetaField'):
        return struct.unpack('<i', b)[0]
    if n == 'igStringMetaField':
        v = struct.unpack('<i', b)[0]
        return g.strings[v] if 0 <= v < len(g.strings) else v
    if n == 'igLongMetaField': return struct.unpack('<q', b)[0]
    if n == 'igDoubleMetaField': return struct.unpack('<d', b)[0]
    if n == 'igFloatMetaField': return struct.unpack('<f', b)[0]
    if n == 'igVec3fMetaField': return struct.unpack('<3f', b)
    if n == 'igVec4fMetaField': return struct.unpack('<4f', b)
    return b.hex()

def obj(g, it):
    return {f'{g.metafields[ft][0].replace("MetaField","")}@{slot}': fval(g, it, k)
            for k, (ft, slot, _) in enumerate(g.metaobjects[it.type]['fields'])}

def mem_floats(g, ref, n=4):
    m = g.items[ref]
    a = struct.unpack(f'<{len(m.data)//4}f', m.data)
    return [a[i:i+n] for i in range(0, len(a), n)]

def mem_ints(g, ref, fmt='i'):
    m = g.items[ref]
    sz = struct.calcsize(fmt)
    return list(struct.unpack(f'<{len(m.data)//sz}{fmt}', m.data))

def datalist(g, ref, fmt='4f'):
    if ref < 0: return None
    lst = g.items[ref]
    v = obj(g, lst)
    cnt, mref = v['igInt@2'], v['igMemoryRef@4']
    data = g.items[mref].data
    sz = struct.calcsize('<' + fmt)
    return [struct.unpack_from('<' + fmt, data, i * sz) for i in range(cnt)]

if __name__ == '__main__':
    g = load(sys.argv[1])
    for t in ('igAnimationDatabase', 'igSkeleton'):
        for it in by_type(g, t): print(t, it.ref, obj(g, it))
    sk = by_type(g, 'igSkeleton')[0]
    sv = obj(g, sk)
    trans = mem_floats(g, sv['igMemoryRef@3'], 3)
    inv = mem_floats(g, sv['igMemoryRef@5'], 16) if sv['igMemoryRef@5'] >= 0 else []
    bil = obj(g, g.items[sv['igObjectRef@4']])
    brefs = mem_ints(g, bil['igMemoryRef@4'])[:bil['igInt@2']]
    print('bones:')
    for k, r in enumerate(brefs):
        b = obj(g, g.items[r])
        print(f'  {k:2d} {b["igString@2"]:12s} parent={b["igInt@3"]:3d} bm={b["igInt@4"]:3d} flags={b["igInt@5"]} t=({", ".join(f"{x:.4f}" for x in trans[k])})')
    print('anims:')
    for a in by_type(g, 'igAnimation'):
        v = obj(g, a)
        tl = obj(g, g.items[v['igObjectRef@5']])
        trefs = mem_ints(g, tl['igMemoryRef@4'])[:tl['igInt@2']]
        print(f'  {v["igString@2"]:15s} start={v["igLong@8"]/1e9:.3f}s dur={v["igLong@9"]/1e9:.3f}s tracks={len(trefs)} {v}')
        if '-v' in sys.argv:
            for r in trefs:
                tv = obj(g, g.items[r])
                src = tv['igObjectRef@3']
                if src < 0:
                    print(f'     {tv["igString@2"]:12s} const q={tv["igVec4f@4"]} t={tv["igVec3f@5"]}'); continue
                sv2 = obj(g, g.items[src])
                q = datalist(g, sv2['igObjectRef@3'], '4f')
                x = datalist(g, sv2['igObjectRef@2'], '3f')
                tq = datalist(g, sv2['igObjectRef@11'], 'q')
                print(f'     {tv["igString@2"]:12s} {g.metaobjects[g.items[src].type]["name"]} nq={len(q) if q else 0} nx={len(x) if x else 0} '
                      f'times={len(tq) if tq else 0} comp={sv2.get("igUnsignedChar@15")} interp={sv2.get("igUnsignedCharArray@16")} '
                      f'refs={[sv2[k] for k in ("igObjectRef@2","igObjectRef@3","igObjectRef@4","igObjectRef@5","igObjectRef@11","igObjectRef@12","igObjectRef@13","igObjectRef@14","igObjectRef@19")]} '
                      f'd={sv2.get("igDouble@6")} longs={sv2.get("igLong@17")},{sv2.get("igLong@18")} '
                      f'q0={tuple(round(c,4) for c in q[0]) if q else None} t0..={[round(t[0]/1e9,3) for t in tq[:4]] if tq else None}')
