# -*- coding: utf-8 -*-
"""대화 중 «줄마다 바뀌는 워드»를 찾는다 — 좁은 구조체 추적이 실패했을 때 쓰는 정공법.

  python tools/dlgdiff.py --secs 30 --ms 100

대사 노드가 사는 VMEM 힙과 재생기가 사는 MEM1 힙을 통째로 100ms마다 찍고,
끝난 뒤 «변화 횟수»로 후보를 거른다. 줄이 4개면 3~5회 바뀌는 워드가 범인이다.

전제: `dolhook.py --apply spy` 가 심겨 있을 것(대화 시작 시각을 알아야 한다).
"""
import argparse
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dolmem import Dolphin

SPY = 0x80004A00
REGIONS = [('vmem', 0x7E130000, 0x40000),      # 대사 노드 힙
           ('mem1', 0x80640000, 0x80000)]      # 재생기·매니저 힙 (0x806AE6B8 포함)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--secs', type=float, default=30)
    ap.add_argument('--ms', type=int, default=100)
    ap.add_argument('--min', type=int, default=2)
    ap.add_argument('--max', type=int, default=20)
    a = ap.parse_args()
    d = Dolphin()
    ptr, ev, cnt = struct.unpack('>3I', d.read(SPY, 12))
    if 0x7E000000 <= ptr < 0x80000000:
        d.find_vmem(ptr, lambda b, e=ev: 0x80300000 <= struct.unpack_from('>I', b, 0)[0]
                    < 0x80400000 and struct.unpack_from('>I', b, 0xC)[0] == e)
    print('돌핀 부착 pid=%d · 훅 호출 %d회' % (d.pid, cnt))
    print('%.0f초 · %dms 간격으로 찍는다 — 지금 말을 거세요' % (a.secs, a.ms))
    sys.stdout.flush()

    snaps = []
    t0 = time.time()
    while time.time() - t0 < a.secs:
        t = time.time() - t0
        row = [d.read(base, size) for _, base, size in REGIONS]
        c = struct.unpack('>I', d.read(SPY + 8, 4))[0]
        snaps.append((t, c, row))
        dt = a.ms / 1000.0 - (time.time() - t0 - t)
        if dt > 0:
            time.sleep(dt)
    print('스냅샷 %d장' % len(snaps))
    starts = [s[0] for i, s in enumerate(snaps) if i and s[1] != snaps[i-1][1]]
    print('대화 시작 시각: %s' % (['%.2fs' % x for x in starts] or '없음(대화가 없었다)'))

    for ri, (tag, base, size) in enumerate(REGIONS):
        import numpy as np
        n = size // 4
        arr = np.stack([np.frombuffer(row[ri], dtype='>u4') for _, _, row in snaps])
        cntarr = (arr[1:] != arr[:-1]).sum(axis=0)
        cand = np.nonzero((cntarr >= a.min) & (cntarr <= a.max))[0].tolist()
        print('\n== %s %08X  변화 %d~%d회인 워드 %d개' % (tag, base, a.min, a.max, len(cand)))
        for k in cand[:60]:
            va = base + k * 4
            tl = []
            pv = None
            for t, c, row in snaps:
                v = struct.unpack_from('>I', row[ri], k * 4)[0]
                if v != pv:
                    tl.append('%.1fs:%08X' % (t, v))
                    pv = v
            print('  %08X (%2d회)  %s' % (va, cntarr[k], ' '.join(tl[:14])))


if __name__ == '__main__':
    main()
