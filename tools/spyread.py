# -*- coding: utf-8 -*-
"""정찰 훅(`tools/dolhook.py --apply spy`)이 남긴 값을 돌핀에서 읽는다.

  python tools/spyread.py            # 계속 감시하며 새 대사마다 객체를 덤프
  python tools/spyread.py --once     # 지금 값 한 번만

관측 자리
  0x80004A00  고른 «대사 줄 객체» 포인터   (0x80132520 의 r4 = r20)
  0x80004A04  이벤트 ID                    (r30)
  0x80004A08  훅 호출 횟수
  0x80004A0C  r3  = [r31+0xC]  (확실한 유효 포인터 — 대조용)
  0x80004A10  r5  = r23 (3D 좌표 버퍼 또는 0)
  0x80004A14  r31 = 대사 매니저
"""
import argparse
import struct
import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dolmem import Dolphin

SPY = 0x80004A00
DUMP = 0x100


def h31(s):
    """엔진 자신의 해시 (0x801341E4: h = 31*h + (signed char)c)"""
    h = 0
    for ch in s.encode('latin1'):
        if ch >= 0x80:
            ch -= 0x100
        h = (h * 31 + ch) & 0xFFFFFFFF
    return h


def load_names(path):
    t = {}
    for ln in open(path, encoding='utf-8'):
        ln = ln.strip()
        if not ln or ln.startswith('=='):
            continue
        stem = ln[:-4] if ln.lower().endswith('.rsd') else ln
        for v in (stem, stem.lower(), stem.upper(), ln, ln.lower()):
            t.setdefault(h31(v), v)
    return t


def dump(d, va, n, names):
    b = d.read(va, n)
    for k in range(0, n, 16):
        ws = struct.unpack_from('>4I', b, k)
        tag = ''
        for j, w in enumerate(ws):
            if w in names:
                tag += '  +%02X=%s' % (k + j * 4, names[w])
        print('    +%03X  %08X %08X %08X %08X%s' % (k, ws[0], ws[1], ws[2], ws[3], tag))
    return b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--names', default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                    '..', 'work', 'dialog_names.txt'))
    a = ap.parse_args()
    names = load_names(a.names)
    print('이름 해시표 %d개 (h=31h+c)' % len(names))
    d = Dolphin()
    print('돌핀 부착 pid=%d' % d.pid)
    last = None
    t0 = time.time()
    while True:
        ptr, ev, cnt, r3, r5, r31 = struct.unpack('>6I', d.read(SPY, 24))
        if cnt != last:
            last = cnt
            print('\n[%6.2fs] #%d  이벤트ID=0x%X' % (time.time() - t0, cnt, ev))
            print('  r4(대사줄)=%08X  r3=%08X  r5=%08X  r31=%08X' % (ptr, r3, r5, r31))
            if 0x7E000000 <= ptr < 0x80000000:
                # 객체 +0xC 가 이벤트 ID 와 같은 매핑을 fake VMEM 으로 확정한다
                d.find_vmem(ptr, lambda b, e=ev: 0x80300000 <= struct.unpack_from('>I', b, 0)[0]
                            < 0x80400000 and struct.unpack_from('>I', b, 0xC)[0] == e)
            for nm, v in (('r4', ptr), ('r3', r3), ('r31', r31)):
                if 0x7E000000 <= v < 0x81800000:
                    print('  -- %s @ %08X  vtable=%08X' % (nm, v, d.u32(v)))
                    dump(d, v, DUMP if nm == 'r4' else 0x40, names)
                else:
                    print('  -- %s = %08X  (범위 밖)' % (nm, v))
            sys.stdout.flush()
        if a.once:
            break
        time.sleep(0.02)


if __name__ == '__main__':
    main()
