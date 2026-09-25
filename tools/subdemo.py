# -*- coding: utf-8 -*-
"""줄 단위 훅에 «자막»을 물린 실증 — 훅이 부를 때마다 다음 대사를 자막 칸에 써 넣는다.

  python tools/subdemo.py --secs 60

⚠ 아직 한글 글리프가 폰트에 없다. 지금은 «동기»만 보는 단계라 영문으로 띄운다.

  훅 카운터 0x80004A20  (dolhook.py --apply line)
  자막 칸   BASE+0x9EAE (윗줄) · BASE+0x5EE0 (아랫줄)   BASE = 0x808BC918 (짝수·BE)
"""
import argparse
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dolmem import Dolphin

LINE = 0x80004A20
RING = 0x80004B00      # 16칸 × 8B (색인, 묶음노드) — 케이브가 직접 남긴다
# ★★★ RAM 의 텍스트 바이블은 UTF-16 «빅엔디안» 이다.
#     로더 0x8020BE60 이 문자열 영역을 read(dst, blen/2, 2) 로 «u16 단위 스왑»해 올린다
#     (키·오프셋 표는 size=4). 디스크의 p3d 는 LE 이고 «적재 시» 뒤집힌다.
#     ⛔ RAM 에 쓸 때는 반드시 'utf-16-be'. LE 로 쓰면 영문만 우연히 맞고
#        한글은 «앞 글자의 상위 바이트 | 이 글자의 하위 바이트» 로 읽혀 □ 가 된다.
#     ⛔ LE 패턴으로 RAM 을 검색하면 «한 바이트 늦은» 홀수 주소에 걸린다 → 반드시 -1.
BASE = 0x808BC918          # ★짝수 (LE 검색으로 얻은 홀수 주소 - 1)
L1 = BASE + 0x9EAE
L2 = BASE + 0x5EE0
WRAP = 55

# 미션1 도입 대화.
# ★ 마지의 두 문장은 클립 둘(색인 0·1)이지만 «붙여서» 재생돼 그 사이 전환이 훅에 안 잡힌다.
#   실제로 들리는 시작은 «마지»와 «호머» 둘뿐이라, 자막도 둘로 짜고 마지 대사는 압축한다.
LINES = [
    "Marge: Homie, somebody ate every dessert in the house. Get me that ice cream with the little pies.",
    "Homer: Uh, must have been one of our kids, probably Milhouse.",
]
COALESCE = 0.25      # 이 시간 안에 겹쳐 오는 훅은 «예약»으로 보고 첫 것만 쓴다


def split2(s, w=WRAP):
    if len(s) <= w:
        return s, ''
    cut = s.rfind(' ', 0, w)
    if cut < 0:
        cut = w
    return s[:cut], s[cut + 1:][:w]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--secs', type=float, default=60)
    a = ap.parse_args()
    d = Dolphin()

    def w(addr, s):
        d.write(addr, s.encode('utf-16-be') + b'\x00\x00')

    w(L1, '(waiting for dialogue)')
    w(L2, '')
    print('pid=%d · 훅 카운터 감시 시작 (%.0f초)' % (d.pid, a.secs))
    c0 = struct.unpack('>I', d.read(LINE, 4))[0]
    last = c0
    n = 0
    missed = 0
    lastshow = 0.0
    t0 = time.time()
    while time.time() - t0 < a.secs:
        c = struct.unpack('>I', d.read(LINE, 4))[0]
        if c != last:
            ring = d.read(RING, 16 * 8)
            for k in range(last + 1, c + 1):        # ★ 고리에서 «놓친 호출까지» 전부 되짚는다
                if c - k >= 16:
                    missed += 1
                    continue
                idx, node = struct.unpack_from('>2I', ring, (k % 16) * 8)
                now = time.time()
                # ★ 경계마다 훅이 «끝난 색인 + 시작할 색인» 둘을 연달아 부른다.
                #   같은 순간에 겹쳐 오는 건 첫 것만 쓴다.
                if now - lastshow < COALESCE:
                    print('  %5.2fs  훅#%d 색인=%d — 같은 순간, 무시' % (now - t0, k, idx))
                    continue
                lastshow = now
                n += 1
                if n > len(LINES):
                    print('  %5.2fs  훅#%d 색인=%d — 대본 밖' % (now - t0, k, idx))
                    continue
                text = LINES[n - 1]
                top, bot = split2('[%d] %s' % (n, text))
                w(L1, top)
                w(L2, bot if bot else ' ')
                print('  %5.2fs  훅#%d 색인=%d 묶음=%08X → 자막 %d: %s'
                      % (time.time() - t0, k, idx, node, n, text[:46]))
            last = c
            sys.stdout.flush()
        time.sleep(0.005)
    print('총 %d줄 표시 · 고리를 넘겨 잃은 호출 %d회' % (n, missed))


if __name__ == '__main__':
    main()
