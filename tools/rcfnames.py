# -*- coding: utf-8 -*-
"""`.rcf`(RADCORE CEMENT LIBRARY) 안의 항목 «이름» 을 뽑는다.

  python tools/rcfnames.py <iso> <아카이브명…>        # 이름 목록
  python tools/rcfnames.py <iso> dialog --dialogue    # 대사 이름을 «구조 분해»해 TSV

## RCF 머리 (실측)
```
0x00  "RADCORE CEMENT LIBRARY" + NUL 패딩
0x1C  u32 BE  버전 0x01020101
0x20  u32 BE  0x800   (디렉터리 오프셋)
0x800 u32 BE  파일 수
```
항목 구조는 아직 미확정이지만 **이름이 평문으로 한 덩어리에 모여 있어** 정규식으로 뽑힌다.

## 대사 이름 구조 (심슨 GC 실측)
```
c_ project _1_ convinit _ mrg _ l1m1 .rsd
   └주제    └순서 └대화형식  └화자  └미션
```
접두 `c_`=컷신·미션 대화 / `d_`=운전 중 / `w_`=NPC 응답 / `p_`=보행자 반응 / `v_`=차량
★ 주제는 미션 스크립트 `.mfk` 의 `SetDialogueInfo("화자","상대","주제",0)` 셋째 인수와 같다.
"""
import re
import struct
import sys

ARCHIVES = {           # FST 에서 읽은 ISO 오프셋·크기 (Simpsons GC USA)
    'ambience': (0x027AD4B9C, 32155648),
    'carsound': (0x02997F39C, 20633600),
    'dialog':   (0x02AD2CB9C, 159209472),
    'music':    (0x03450239C, 285341696),
    'nis':      (0x045521B9C, 22294528),
    'scripts':  (0x046A64B9C, 993280),
    'soundfx':  (0x046B5739C, 57708544),
}
NAME = re.compile(rb'[A-Za-z0-9_\-]{3,}\.[A-Za-z0-9]{2,4}')
DLG = re.compile(r'^([cdwpv])_(.+?)_(\d+)_(convinit|noboxconv)_([a-z]{3})_(l\d[mr]\d)\.rsd$')


def read(iso, name, cap=8 << 20):
    off, size = ARCHIVES[name]
    f = open(iso, 'rb')
    f.seek(off)
    d = f.read(min(size, cap))
    cnt = struct.unpack_from('>I', d, 0x800)[0]
    names = [m.group().decode('latin1') for m in NAME.finditer(d)]
    # 잡음 제거: 알려진 확장자만
    names = [n for n in names if n.rsplit('.', 1)[1].lower() in ('rsd', 'spt', 'p3d')]
    return cnt, names


def main():
    iso = sys.argv[1]
    args = [a for a in sys.argv[2:] if not a.startswith('--')]
    dialogue = '--dialogue' in sys.argv
    for a in args or sorted(ARCHIVES):
        cnt, names = read(iso, a)
        if not dialogue:
            print('== %s.rcf  항목 %d개 · 이름 %d개' % (a, cnt, len(names)))
            for n in names:
                print('   ', n)
            continue
        print('접두\t주제\t순서\t대화형식\t화자\t미션\t파일명')
        n_ok = 0
        for n in names:
            m = DLG.match(n)
            if m:
                n_ok += 1
                print('\t'.join(list(m.groups()) + [n]))
        sys.stderr.write('%s.rcf: 이름 %d개 중 «미션 대사» 구조 %d개\n' % (a, len(names), n_ok))


if __name__ == '__main__':
    main()
