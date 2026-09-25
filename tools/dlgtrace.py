# -*- coding: utf-8 -*-
"""대화 한 판을 «볼 곳만» 추적한다 — 블라인드 diff 는 힙 할당기 잡음에 묻힌다.

  python tools/dlgtrace.py --secs 30

추적 대상
  훅 관측 자리 0x80004A00  (대화 시작·이벤트ID·매니저)
  매니저      0x806AE6B8 +0x80~+0x100
  재생기      [매니저+0x88] 0x44 B   ← 대화마다 새로 할당된다
  사운드 콜백 0x8044A7C0 ~ 0x8044A840  ← 소리 하나가 끝날 때마다 바뀌는 자리
  대화 노드   재생기 +0x14 가 가리키는 VMEM 노드 0x80 B + 줄 노드 사슬(+0x10)
"""
import argparse
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dolmem import Dolphin

SPY = 0x80004A00
SND = 0x8044A7C0
SND_LEN = 0x80


def words(b):
    return struct.unpack('>%dI' % (len(b) // 4), b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--secs', type=float, default=30)
    ap.add_argument('--ms', type=int, default=30)
    a = ap.parse_args()
    d = Dolphin()
    ptr, ev, cnt, mgr, r5, r31 = struct.unpack('>6I', d.read(SPY, 24))
    if 0x7E000000 <= ptr < 0x80000000:
        try:
            d.find_vmem(ptr, lambda b, e=ev: 0x80300000 <= words(b[:4])[0] < 0x80400000
                        and words(b[0xC:0x10])[0] == e)
        except SystemExit:
            pass
    print('pid=%d · 시작 시점 훅 호출 %d회 · 매니저 %08X' % (d.pid, cnt, mgr))
    sys.stdout.flush()
    t0 = time.time()
    prev = {}
    node_shown = set()

    def track(tag, addr, ln, skip=()):
        if not (0x7E000000 <= addr < 0x81800000):
            return
        try:
            b = d.read(addr, ln)
        except Exception:
            return
        if skip:                       # 잡음 필드(타이머 등)는 0 으로 눌러 무시한다
            b = bytearray(b)
            for o in skip:
                b[o:o+4] = bytes(4)
            b = bytes(b)
        k = tag
        if k not in prev:
            print('[%6.2fs] 초기 %-10s %08X  %s' % (time.time() - t0, tag, addr,
                  ' '.join('%08X' % w for w in words(b))))
        elif b != prev[k]:
            pw, cw = words(prev[k]), words(b)
            ch = '  '.join('+%02X %08X->%08X' % (i * 4, pw[i], cw[i])
                           for i in range(len(cw)) if pw[i] != cw[i])
            print('[%6.2fs] %-10s %s' % (time.time() - t0, tag, ch))
        prev[k] = b

    while time.time() - t0 < a.secs:
        ptr, ev, cnt2, mgr, r5, r31 = struct.unpack('>6I', d.read(SPY, 24))
        if prev.get('_cnt') != cnt2:
            print('[%6.2fs] ★훅 #%d  이벤트=0x%X  노드=%08X' % (time.time() - t0, cnt2, ev, ptr))
            prev['_cnt'] = cnt2
        track('사운드', SND, SND_LEN, skip=(0x5C,))
        if 0x80000000 <= mgr < 0x81800000:
            track('매니저', mgr + 0x80, 0x80)
            p = d.u32(mgr + 0x88)
            if 0x7E000000 <= p < 0x81800000:
                track('재생기', p, 0x44)
                # ★ 재생기가 «가리키는» 하위 객체들의 내용까지 본다 (포인터만 보면 안 바뀐다)
                for off in (0x34, 0x1C, 0x20):
                    sub = d.u32(p + off)
                    if 0x7E000000 <= sub < 0x81800000:
                        track('재생기+%02X' % off, sub, 0x80)
                node = d.u32(p + 0x14)
                if 0x7E000000 <= node < 0x80000000:
                    track('노드', node, 0x40)
                    first = d.u32(node + 0x18)          # 줄 노드 목록의 첫 항목
                    if 0x7E000000 <= first < 0x80000000:
                        track('줄노드', first, 0x40)
                        arr = d.u32(first + 0x14)       # 그 줄의 리소스 배열
                        if 0x7E000000 <= arr < 0x81800000:
                            track('리소스배열', arr, 0x80)
                    # 줄 사슬을 한 번만 펼쳐 둔다
                    if node not in node_shown:
                        node_shown.add(node)
                        cur, k = node, 0
                        while 0x7E000000 <= cur < 0x80000000 and k < 12:
                            w = words(d.read(cur, 0x20))
                            print('        묶음[%d] %08X vt=%08X ev=0x%X 다음=%08X 개수=%d 줄목록=%08X'
                                  % (k, cur, w[0], w[3], w[4], w[5], w[6]))
                            cur = w[4]
                            k += 1
        sys.stdout.flush()
        time.sleep(a.ms / 1000.0)


if __name__ == '__main__':
    main()
