# -*- coding: utf-8 -*-
"""돌핀 RAM 을 읽어 daSoundClipStreamPlayer(vtbl 0x8037F998) 의 상태(+0x44)·리소스(+0x5C) 변화를 기록한다.
  python tools/sndwatch.py [초]        → work/snd/watch_<시각>.txt
리소스 풀 = [0x80476BD8]+0x20+i*0x14, dialog.spt 3,885개 = 순번 239~4123 (docs/08)."""
import sys, re, time, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
from dolmem import Dolphin
here = os.path.join(os.path.dirname(__file__), '..')
d = open(os.path.join(here, 'work/snd/scripts.rcf'), 'rb').read()
for m in re.finditer(rb'[^\x00]{20,}', d):
    es = re.findall(rb'create daSoundResourceData named (\S+)\s*\{', m.group())
    if len(es) == 3885:
        names = [e.decode() for e in es]
secs = float(sys.argv[1]) if len(sys.argv) > 1 else 60
D = Dolphin(); base = D.u32(0x80476BD8); b0 = base + 0x20
m = np.frombuffer(D.dump(), dtype='>u4')
objs = [0x80000000 + i * 4 for i in np.nonzero(m == 0x8037F998)[0].tolist()]
def nm(v):
    i = (v - b0) // 0x14
    if 239 <= i < 4124 and (v - b0) % 0x14 == 0: return names[i - 239]
    return '%08X' % v if v else '-'
prev = {}; t0 = time.time(); log = ['players %d' % len(objs)]
lo, hi = min(objs), max(objs) + 0x80
while time.time() - t0 < secs:
    blk = D.read(lo, hi - lo)
    for o in objs:
        b = blk[o - lo:o - lo + 0x80]
        st = int.from_bytes(b[0x44:0x48], 'big'); res = int.from_bytes(b[0x5C:0x60], 'big')
        if prev.get(o) != (st, res):
            if res or prev.get(o, (0, 0))[1]:
                log.append('%6.2f %08X st=%d %s' % (time.time() - t0, o, st, nm(res)))
            prev[o] = (st, res)
    time.sleep(0.01)
out = os.path.join(here, 'work/snd/watch_%s.txt' % time.strftime('%H%M%S'))
open(out, 'w', encoding='utf-8').write('\n'.join(log))
print('\n'.join(log))
