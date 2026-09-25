# -*- coding: utf-8 -*-
"""대화 «재생기» 객체를 추적해 «줄이 넘어갈 때 바뀌는 필드»를 찾는다.

  python tools/playerwatch.py [--secs 90]

전제: `tools/dolhook.py --apply spy` 가 심겨 있고 대화가 한 번이라도 시작됐어야 한다
(그래야 매니저 주소 r31 이 관측 자리에 남는다).

  매니저 = 관측 자리 0x80004A0C (r3 = [r31+0xC], 사운드/대기열 매니저)
  재생기 = [매니저+0x88]        ← 0x80135308 이 0x44 B 로 새로 할당한다
"""
import argparse
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dolmem import Dolphin

SPY = 0x80004A00
PLAYER_OFF = 0x88
PLAYER_LEN = 0x44


def hexrow(b):
    return ' '.join('%08X' % w for w in struct.unpack('>%dI' % (len(b) // 4), b))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--secs', type=float, default=90)
    a = ap.parse_args()
    d = Dolphin()
    print('돌핀 부착 pid=%d' % d.pid)
    t0 = time.time()
    lastcnt = lastplayer = None
    prev = None
    vmem_done = False
    while time.time() - t0 < a.secs:
        ptr, ev, cnt, mgr, r5, r31 = struct.unpack('>6I', d.read(SPY, 24))  # mgr = r3 = [r31+0xC]
        if not vmem_done and 0x7E000000 <= ptr < 0x80000000:
            try:
                d.find_vmem(ptr, lambda b, e=ev: 0x80300000 <= struct.unpack_from('>I', b, 0)[0]
                            < 0x80400000 and struct.unpack_from('>I', b, 0xC)[0] == e)
                vmem_done = True
            except SystemExit:
                pass
        if cnt != lastcnt:
            lastcnt = cnt
            print('\n[%6.2fs] ★대화 시작 #%d  이벤트=0x%X  매니저=%08X' % (time.time() - t0, cnt, ev, mgr))
        if not (0x80000000 <= mgr < 0x81800000):
            time.sleep(0.05); continue
        p = d.u32(mgr + PLAYER_OFF)
        if p != lastplayer:
            lastplayer = p
            prev = None if p == 0 else (prev or None)
            print('[%6.2fs] 재생기 = %08X' % (time.time() - t0, p))
        # 두 곳을 같이 본다: 매니저 상태창(+0x80~+0xC0)과 재생기 객체
        regions = [('매니저+80', mgr + 0x80, 0x40)]
        if 0x7E000000 <= p < 0x81800000:
            regions.append(('재생기  ', p, PLAYER_LEN))
        if prev is None:
            prev = {}
        for tag, addr, ln in regions:
            try:
                b = d.read(addr, ln)
            except Exception:
                continue
            key = tag
            if key not in prev:
                print('[%6.2fs]   초기 %s %08X  %s' % (time.time() - t0, tag, addr, hexrow(b)))
            elif b != prev[key]:
                diff = [i for i in range(0, ln, 4) if b[i:i+4] != prev[key][i:i+4]]
                print('[%6.2fs]   %s %s' % (time.time() - t0, tag,
                      '  '.join('+%02X %08X->%08X' % (i,
                                struct.unpack_from('>I', prev[key], i)[0],
                                struct.unpack_from('>I', b, i)[0]) for i in diff)))
            prev[key] = b
        sys.stdout.flush()
        time.sleep(0.02)


if __name__ == '__main__':
    main()
