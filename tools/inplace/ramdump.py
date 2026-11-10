"""Dump PSP user RAM (0x08800000-0x0A000000, 24 MB) from a running PPSSPP through its remote debugger.
Reading memory doesn't pause or disturb the game.

usage: py -P ramdump.py <port> <out.bin>
"""
import base64, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'repo', 'tools'))
from ppsspp_dbg import PPSSPP

BASE, END, CHUNK = 0x08800000, 0x0A000000, 0x100000

if __name__ == '__main__':
    p = PPSSPP(int(sys.argv[1]))
    with open(sys.argv[2], 'wb') as f:
        for a in range(BASE, END, CHUNK):
            r = p.call('memory.read', address=a, size=CHUNK, timeout=30)
            data = base64.b64decode(r['base64'])
            assert len(data) == CHUNK, (hex(a), len(data), r)
            f.write(data)
    print('dumped', hex(BASE), '-', hex(END), '->', sys.argv[2])
