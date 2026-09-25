# -*- coding: utf-8 -*-
"""GC ISO 안의 DOL 을 «제자리»로 고친다 (크기 불변 → FST 손 안 댐).

  python tools/dolpatch.py <iso> --apply poc1 poc2
  python tools/dolpatch.py <iso> --revert poc1 poc2
  python tools/dolpatch.py <iso> --show

각 패치는 (ISO 오프셋, 원래 워드, 새 워드) 목록이다. 적용 전에 «원래 값»을 대조하고
다르면 거부한다. 되돌리기도 같은 방식으로 검사한다.

DOL 은 ISO 0x1EC00 부터. VA↔ISO 변환은 `doltables.py` 의 섹션표와 같다.
"""
import argparse
import struct
import sys

PATCHES = {
    # 화면 텍스트 «내용 취득» 함수 0x80214A10 안
    #   lwz r12,0x138(r12) / bctrl 로 얻은 문자열 포인터가 NULL 이면
    #   "No Valid Text" 를 쓰는 분기. 이를 «무조건» 으로 만들면 모든 텍스트가 대체된다.
    'poc1': [(0x0002303F4, 0x41820018, 0x48000018)],   # beq 0x80214A6C -> b
    # 대체 문자열 포인터를 'convinit'(VA 0x80379B90) 으로 돌린다.
    'poc2': [(0x00023040C, 0x3C808039, 0x3C808038),    # lis  r4,0x8039 -> 0x8038
             (0x000230414, 0x38846F14, 0x38849B90)],   # addi r4,r4,0x6F14 -> 0x9B90
}


def rd(f, off):
    f.seek(off)
    return struct.unpack('>I', f.read(4))[0]


def wr(f, off, val):
    f.seek(off)
    f.write(struct.pack('>I', val))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('iso')
    ap.add_argument('--apply', nargs='*', default=[])
    ap.add_argument('--revert', nargs='*', default=[])
    ap.add_argument('--show', action='store_true')
    a = ap.parse_args()
    mode = 'r+b' if (a.apply or a.revert) else 'rb'
    f = open(a.iso, mode)
    if a.show or not (a.apply or a.revert):
        for name, items in PATCHES.items():
            for off, old, new in items:
                cur = rd(f, off)
                st = '원본' if cur == old else ('적용됨' if cur == new else '⛔알수없음')
                print('  %-5s ISO 0x%09X  현재 %08X  (원본 %08X · 패치 %08X)  %s'
                      % (name, off, cur, old, new, st))
        return
    for name in a.apply:
        for off, old, new in PATCHES[name]:
            cur = rd(f, off)
            if cur == new:
                print('  %-5s ISO 0x%09X 이미 적용됨' % (name, off)); continue
            if cur != old:
                raise SystemExit('⛔ %s ISO 0x%09X 원본이 아니다: %08X (기대 %08X)' % (name, off, cur, old))
            wr(f, off, new)
            print('  ✅ %-5s ISO 0x%09X  %08X -> %08X' % (name, off, old, new))
    for name in a.revert:
        for off, old, new in PATCHES[name]:
            cur = rd(f, off)
            if cur == old:
                print('  %-5s ISO 0x%09X 이미 원본' % (name, off)); continue
            if cur != new:
                raise SystemExit('⛔ %s ISO 0x%09X 패치본이 아니다: %08X' % (name, off, cur))
            wr(f, off, old)
            print('  ↩ %-5s ISO 0x%09X  %08X -> %08X' % (name, off, new, old))
    f.close()


if __name__ == '__main__':
    main()
