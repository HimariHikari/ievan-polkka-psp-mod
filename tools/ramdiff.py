"""Diff two PSP user-RAM dumps (0x08800000.., 24MB) and report changes that look like per-song flags for one PV.
usage: py -P ramdiff.py before.bin after.bin [pv=27]"""
import sys
import numpy as np

BASE = 0x08800000
a = np.fromfile(sys.argv[1], np.uint8)
b = np.fromfile(sys.argv[2], np.uint8)
pv = int(sys.argv[3]) if len(sys.argv) > 3 else 27
diff = np.nonzero(a != b)[0]
print(f'{len(diff)} bytes changed')
# group into runs
runs = []
for i in diff:
    if runs and i - runs[-1][1] <= 8:
        runs[-1][1] = i
    else:
        runs.append([i, i])
small = [(s, e) for s, e in runs if e - s < 64]
print(f'{len(runs)} changed regions, {len(small)} small ones (< 64 bytes):')
for s, e in small[:400]:
    addr = BASE + s
    before = a[s:e + 1].tolist(); after = b[s:e + 1].tolist()
    print(f'  {addr:#010x} (+{e - s + 1:2d})  {before} -> {after}')
