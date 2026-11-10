# -*- coding: utf-8 -*-
"""사운드 재생기 연결 리스트(머리 [0x80476BA0], 다음 +4)의 «모든» 객체를 훑어
대사 리소스(풀 순번 239~4123)를 가리키는 워드가 생기거나 바뀌면 기록한다(종류 무관, 오프셋 무관).
  python tools/sndwatch2.py [초]  → work/snd/watch2_<시각>.txt
객체마다 0x200 B 를 읽어 «대사 리소스 포인터가 들어 있는 오프셋»과 vtbl·+0x44 를 함께 적는다."""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dolmem import Dolphin
import ksub

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 120
names = ksub.dialog_names()
D = Dolphin()
u = D.u32
pool = u(0x80476BD8)
b0 = pool + 0x20
lo = b0 + 239 * 0x14
hi = lo + 3885 * 0x14
o = u(0x80476BA0)
objs = []
while 0x80000000 <= o < 0x81800000 and len(objs) < 400:
    objs.append(o)
    o = u(o + 4)
vt = {}
for o in objs:
    vt.setdefault(u(o), 0)
    vt[u(o)] += 1
log = ['players %d  vtbls %s' % (len(objs), ' '.join('%08X×%d' % kv for kv in vt.items()))]
prev = {}
t0 = time.time()
while time.time() - t0 < secs:
    for o in objs:
        b = D.read(o, 0x200)
        cur = []
        for k in range(0, 0x200, 4):
            w = int.from_bytes(b[k:k + 4], 'big')
            if lo <= w < hi and (w - lo) % 0x14 == 0:
                cur.append((k, names[(w - lo) // 0x14]))
        st = int.from_bytes(b[0x44:0x48], 'big')
        key = (tuple(cur), st)
        if prev.get(o) != key:
            if cur or (prev.get(o) and prev[o][0]):
                log.append('%6.2f %08X vt=%08X st=%d %s' % (time.time() - t0, o, int.from_bytes(b[:4], 'big'), st,
                                                          ' '.join('+%X:%s' % c for c in cur) or '-'))
            prev[o] = key
    time.sleep(0.02)
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'work', 'snd',
                   'watch2_%s.txt' % time.strftime('%H%M%S'))
open(out, 'w', encoding='utf-8').write('\n'.join(log))
print('\n'.join(log))
