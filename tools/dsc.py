"""Project DIVA (PSP, PD1) DSC script reader. Opcode table from nastys/Open-PD-Script-Editor (info_PSP1)."""
import struct, sys
OPS = [("END",0),("TIME",1),("MIKU_MOVE",3),("MIKU_ROT",1),("MIKU_DISP",1),("MIKU_SHADOW",1),("TARGET",7),
("SET_MOTION",2),("SET_PLAYDATA",1),("EFFECT",5),("FADEIN_FIELD",2),("EFFECT_OFF",1),("SET_CAMERA",6),
("DATA_CAMERA",2),("CHANGE_FIELD",1),("HIDE_FIELD",1),("MOVE_FIELD",3),("FADEOUT_FIELD",2),("EYE_ANIM",2),
("MOUTH_ANIM",2),("HAND_ANIM",2),("LOOK_ANIM",3),("EXPRESSION",1),("LOOK_CAMERA",4),("LYRIC",1),
("MUSIC_PLAY",0),("MODE_SELECT",1),("EDIT_MOTION",2),("BAR_TIME_SET",2),("SHADOWHEIGHT",1),("EDIT_FACE",2),
("MOVE_CAMERA",19),("PV_END",0),("SHADOWPOS",2),("NEAR_CLIP",2),("CLOTH_WET",1)]

def parse(data):
    w = struct.unpack(f'<{len(data)//4}i', data[:len(data)//4*4])
    i, t, out = 0, 0, []
    while i < len(w):
        op = w[i]
        if op < 0 or op >= len(OPS):
            out.append((t, f'?? {op} at word {i}', ())); i += 1; continue
        name, n = OPS[op]
        args = w[i+1:i+1+n]
        if name == 'TIME': t = args[0]
        out.append((t, name, args)); i += 1 + n
        if name == 'END': break
    return out

def write(cmds):
    names = {n: k for k, (n, _) in enumerate(OPS)}
    b = bytearray()
    for _, name, args in cmds:
        assert len(args) == OPS[names[name]][1], (name, args)
        b += struct.pack(f'<{1+len(args)}i', names[name], *args)
    return bytes(b)

def merge(cmds, extra):
    """insert timed commands [(time, name, args)] into a parsed script and rebuild the TIME commands"""
    body = [(t, n, a) for t, n, a in cmds if n not in ('TIME', 'END')]
    tail = [(t, n, a) for t, n, a in cmds if n == 'END']
    order = {id(c): i for i, c in enumerate(body)}
    allc = body + [(t, n, tuple(a)) for t, n, a in extra]
    allc.sort(key=lambda c: (c[0], 0 if c in body else -1))
    out, cur = [], None
    for t, n, a in allc:
        if t != cur:
            out.append((t, 'TIME', (t,))); cur = t
        out.append((t, n, a))
    return out + tail


if __name__ == '__main__':
    cmds = parse(open(sys.argv[1], 'rb').read())
    skip = set(sys.argv[2].split(',')) if len(sys.argv) > 2 else set()
    for t, name, args in cmds:
        if name in skip or name == 'TIME': continue
        print(f'{t/100000:9.3f}s  {name:14s} {" ".join(map(str, args))}')
