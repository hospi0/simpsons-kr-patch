# -*- coding: utf-8 -*-
"""p3d 안의 «폰트 이름»을 바꾼다 (파일 크기 불변).

  python tools/p3drename.py <src> <dst> --from boulder_16 --to boulderK16

## 왜 필요한가

Scrooby 는 폰트를 «이름»으로 찾는다. 같은 이름(`boulder_16`)이 여러 p3d 에 있으면
그때 «올라와 있는» 것이 이긴다 — 부팅 파일이 아직 안 내려간 화면(타이틀·로딩·
게임 시작 프롬프트)에서는 `bootup.p3d` 의 영문 폰트가 우리 한글 폰트를 가린다.
⇒ 한글 폰트를 «다른 이름»으로 바꾸고 그 파일의 참조도 같이 바꾸면 충돌이 사라진다.
   (bootup.p3d 는 커지면 크래시해서 손댈 수 없다 — 그래서 이쪽을 피한다.)

## 어떻게 크기를 안 바꾸나

FONT 청크 본문 = `u32 버전 · u8 길이 · char 이름[길이]`. 길이칸은 «칸 크기»(12)라
실제 이름 뒤엔 NUL 패딩이 있다. 같은 길이 이하의 이름을 NUL 로 채워 넣으면 그만이다.
참조 쪽 치환은 `tools/p3dfontref.py --to` 가 같은 원리로 한다.
"""
import argparse
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p3d import walk

FONT = 0x00022000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--from', dest='old', required=True)
    ap.add_argument('--to', dest='new', required=True)
    a = ap.parse_args()

    d = bytearray(open(a.src, 'rb').read())
    hits = 0
    for depth, cid, off, dsz, csz in walk(bytes(d), 12):
        if cid != FONT:
            continue
        p = off + 12 + 4                      # u32 버전 뒤
        cap = d[p]
        cur = bytes(d[p + 1:p + 1 + cap]).rstrip(b'\0').decode('latin-1')
        if cur != a.old:
            continue
        nb = a.new.encode('latin-1')
        if len(nb) > cap:
            raise SystemExit('⛔ 새 이름이 칸(%d)보다 길다: %r' % (cap, a.new))
        d[p + 1:p + 1 + cap] = nb + b'\0' * (cap - len(nb))
        hits += 1
        print('  FONT @0x%06X  %r -> %r (칸 %d)' % (p, cur, a.new, cap))
    if not hits:
        raise SystemExit('⛔ %r 라는 폰트가 없다' % a.old)
    if len(d) != os.path.getsize(a.src):
        raise SystemExit('⛔ 크기가 변했다')
    open(a.dst, 'wb').write(bytes(d))
    print('%d개 이름 변경 · %d B (크기 불변)' % (hits, len(d)))


if __name__ == '__main__':
    main()
