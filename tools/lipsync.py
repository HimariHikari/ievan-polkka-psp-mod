"""Lip sync for the PSP PV: Unity clip mouth blendshapes -> DSC MOUTH_ANIM events.

PSP mouth ids (from the game's own scripts): 6 = closed/rest, 0/1/2/5 = open vowel shapes; second arg 100.
Mapping: Ah -> 0, Ch (i) -> 1, U -> 2, Oh -> 5, nothing open -> 6.
usage: py -P lipsync.py <unity .anim> <work dir>   -> <work>/mouth_events.json  [[time_s, mouth_id], ...]
"""
import sys, os, re, json
import numpy as np

SHAPES = {'blendShape.Ah': 0, 'blendShape.Ch': 1, 'blendShape.U': 2, 'blendShape.Oh': 5}
CLOSED, OPEN_AT, FPS, MIN_HOLD = 6, 22.0, 30, 2       # weights are 0..100 in Unity


def read_curves(path, names):
    curves, keys, t = {}, [], None
    with open(path, encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s.startswith('- curve:'):
                keys = []
            elif s.startswith('time:'):
                t = float(s.split(':')[1])
            elif s.startswith('value:') and t is not None:
                try: keys.append((t, float(s.split(':')[1])))
                except ValueError: pass
                t = None
            elif s.startswith('attribute:'):
                name = s.split(':', 1)[1].strip().strip('"')
                if name in names and keys:
                    curves[name] = np.array(keys)
    return curves


def events(anim_path, duration=152.6):
    c = read_curves(anim_path, set(SHAPES))
    n = int(duration * FPS) + 1; grid = np.arange(n) / FPS
    w = np.stack([np.interp(grid, c[k][:, 0], c[k][:, 1]) if k in c else np.zeros(n) for k in SHAPES], 1)
    ids = np.array(list(SHAPES.values()))
    state = np.where(w.max(1) >= OPEN_AT, ids[w.argmax(1)], CLOSED)
    ev, last, held = [], None, 0
    for f, s in enumerate(state):
        if s != last and (held >= MIN_HOLD or last is None):
            ev.append((round(f / FPS, 4), int(s))); last = s; held = 0
        held += 1
    return ev, {k: (k in c) for k in SHAPES}


if __name__ == '__main__':
    ev, found = events(sys.argv[1])
    json.dump(ev, open(os.path.join(sys.argv[2], 'mouth_events.json'), 'w'))
    from collections import Counter
    print('curves found:', found)
    print(f'{len(ev)} mouth changes;', Counter(s for _, s in ev), 'first:', ev[:12])
