# -*- coding: utf-8 -*-
"""줄 단위 훅(`dolhook.py --apply line`)이 남긴 값을 읽어 «대사 한 줄»마다 보고한다.

  python tools/linewatch.py --secs 60

관측 자리
  0x80004A20  줄 훅 호출 횟수
  0x80004A24  재생기
  0x80004A28  줄 색인 (0,1,2,…)
  0x80004A2C  대화 묶음 노드
"""
import argparse
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dolmem import Dolphin

SPY = 0x80004A00
LINE = 0x80004A20


def h31(s):
    h = 0
    for c in s.encode('latin1'):
        if c >= 0x80:
            c -= 0x100
        h = (h * 31 + c) & 0xFFFFFFFF
    return h


def load_names(*paths):
    t = {}
    for p in paths:
        if not os.path.exists(p):
            continue
        for ln in open(p, encoding='utf-8'):
            ln = ln.strip()
            if not ln or ln.startswith('=='):
                continue
            stem = ln.rsplit('.', 1)[0] if '.' in ln[-5:] else ln
            for v in (ln, stem, ln.lower(), stem.lower(), ln.upper(), stem.upper()):
                t.setdefault(h31(v), v)
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--secs', type=float, default=60)
    a = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    names = load_names(os.path.join(here, '..', 'work', 'dialog_names.txt'),
                       os.path.join(here, '..', 'work', 'spt_names.txt'))
    d = Dolphin()
    ptr, ev, cnt = struct.unpack('>3I', d.read(SPY, 12))
    if 0x7E000000 <= ptr < 0x80000000:
        try:
            d.find_vmem(ptr, lambda b, e=ev: 0x80300000 <=
                        struct.unpack_from('>I', b, 0)[0] < 0x80400000 and
                        struct.unpack_from('>I', b, 0xC)[0] == e)
        except SystemExit:
            print('⚠ VMEM 미확정 — 대화가 한 번은 시작돼야 한다')
    print('pid=%d · 이름해시 %d개' % (d.pid, len(names)))
    t0 = time.time()
    last = None
    while time.time() - t0 < a.secs:
        c, player, idx, node = struct.unpack('>4I', d.read(LINE, 16))
        if c != last:
            last = c
            print('\n[%6.2fs] ▶ 줄 #%d  색인=%d  재생기=%08X  묶음=%08X'
                  % (time.time() - t0, c, idx, player, node))
            if 0x7E000000 <= node < 0x80000000:
                try:
                    w = struct.unpack('>8I', d.read(node, 0x20))
                    print('    묶음: 이벤트=0x%X 개수=%d 줄목록=%08X' % (w[3], w[5], w[6]))
                    cur = w[6]
                    for k in range(w[5] if 0 < w[5] < 32 else 1):
                        if not (0x7E000000 <= cur < 0x80000000):
                            break
                        lw = struct.unpack('>8I', d.read(cur, 0x20))
                        mark = '←지금' if k == idx else '     '
                        topic = names.get(lw[6], '?')
                        print('      줄[%d]%s %08X ev=0x%X 주제=%08X(%s) 배열=%08X 플래그=%08X'
                              % (k, mark, cur, lw[3], lw[6], topic, lw[5], lw[7]))
                        if 0x7E000000 <= lw[5] < 0x81800000:
                            ab = d.read(lw[5], 0x14 * 6)
                            hs = []
                            for j in range(6):
                                e = struct.unpack_from('>5I', ab, j * 0x14)
                                if e[0] != 0x8037F4A4:
                                    break
                                hv = d.u32(e[2])
                                hs.append('%08X(%s)' % (hv, names.get(hv, '?')))
                            print('         리소스: %s' % ' '.join(hs))
                        cur = lw[4]
                except Exception as e:
                    print('    읽기 실패: %s' % e)
            sys.stdout.flush()
        time.sleep(0.02)


if __name__ == '__main__':
    main()
