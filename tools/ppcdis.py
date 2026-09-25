# -*- coding: utf-8 -*-
"""ISO 안 DOL 을 읽는 작은 PowerPC 디스어셈블러.

  python tools/ppcdis.py <iso> 0x802134D0 0x60          # 구간 디스어셈블
  python tools/ppcdis.py <iso> --xref 0x80213400        # 그 주소로 가는 bl/b 를 전부 찾기
  python tools/ppcdis.py <iso> --data 0x8033D620 0x80   # 바이트 덤프
  python tools/ppcdis.py <iso> --str "TutorialMessage"  # 문자열 위치 + 그 주소를 만드는 코드

★ 게임큐브 DOL 은 섹션마다 «파일↔메모리 델타»가 다르다 → 헤더로 매핑한다.
  [[feedback_dol_section_deltas_differ]]
"""
import argparse
import struct
import sys


class Dol(object):
    def __init__(self, iso):
        f = open(iso, 'rb')
        f.seek(0x420)
        base = struct.unpack('>I', f.read(4))[0]
        f.seek(base)
        h = f.read(0x100)
        self.seg = []
        for i in range(18):
            o = struct.unpack_from('>I', h, 0x00 + 4 * i)[0]
            a = struct.unpack_from('>I', h, 0x48 + 4 * i)[0]
            s = struct.unpack_from('>I', h, 0x90 + 4 * i)[0]
            if s:
                f.seek(base + o)
                self.seg.append((a, f.read(s), i))
        self.bss = struct.unpack_from('>I', h, 0xD8)[0]

    def read(self, va, n):
        for a, d, i in self.seg:
            if a <= va < a + len(d):
                return d[va - a:va - a + n]
        return None

    def word(self, va):
        b = self.read(va, 4)
        return struct.unpack('>I', b)[0] if b else None

    def find(self, pat):
        for a, d, i in self.seg:
            j = d.find(pat)
            while j >= 0:
                yield a + j
                j = d.find(pat, j + 1)


SPR = {444: 'or', 266: 'add', 40: 'subf', 23: 'lwzx', 151: 'stwx', 0: 'cmpw', 32: 'cmplw',
       87: 'lbzx', 215: 'stbx', 279: 'lhzx', 407: 'sthx', 339: 'mfspr', 467: 'mtspr',
       954: 'extsb', 922: 'extsh', 28: 'and', 60: 'andc', 124: 'nor', 316: 'xor',
       412: 'orc', 24: 'slw', 536: 'srw', 792: 'sraw', 824: 'srawi', 104: 'neg',
       235: 'mullw', 491: 'divw', 11: 'mulhwu', 75: 'mulhw', 86: 'dcbf', 1014: 'dcbz',
       598: 'sync', 854: 'eieio', 20: 'lwarx', 150: 'stwcx', 8: 'subfc', 10: 'addc',
       138: 'adde', 202: 'addze', 234: 'addme', 983: 'stfiwx', 535: 'lfsx', 663: 'stfsx'}
LD = {32: 'lwz', 33: 'lwzu', 34: 'lbz', 35: 'lbzu', 36: 'stw', 37: 'stwu', 38: 'stb',
      39: 'stbu', 40: 'lhz', 41: 'lhzu', 42: 'lha', 44: 'sth', 45: 'sthu',
      48: 'lfs', 49: 'lfsu', 50: 'lfd', 52: 'stfs', 53: 'stfsu', 54: 'stfd'}


def dis(w, va):
    if w is None:
        return '??'
    op = w >> 26
    rD, rA, rB = (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31
    si = w & 0xFFFF
    s = si - 0x10000 if si >= 0x8000 else si
    if op in LD:
        return '%-6s r%d,%d(r%d)' % (LD[op], rD, s, rA)
    if op == 14:
        return 'addi   r%d,r%d,%d' % (rD, rA, s) if rA else 'li     r%d,%d' % (rD, s)
    if op == 15:
        return 'addis  r%d,r%d,0x%04X' % (rD, rA, si) if rA else 'lis    r%d,0x%04X' % (rD, si)
    if op == 24: return 'ori    r%d,r%d,0x%04X' % (rA, rD, si)
    if op == 25: return 'oris   r%d,r%d,0x%04X' % (rA, rD, si)
    if op == 28: return 'andi.  r%d,r%d,0x%04X' % (rA, rD, si)
    if op == 11: return 'cmpwi  cr%d,r%d,%d' % (rD >> 2, rA, s)
    if op == 10: return 'cmplwi cr%d,r%d,0x%X' % (rD >> 2, rA, si)
    if op == 7:  return 'mulli  r%d,r%d,%d' % (rD, rA, s)
    if op == 20: return 'rlwimi r%d,r%d,%d,%d,%d' % (rA, rD, rB, (w >> 6) & 31, (w >> 1) & 31)
    if op == 21: return 'rlwinm r%d,r%d,%d,%d,%d' % (rA, rD, rB, (w >> 6) & 31, (w >> 1) & 31)
    if op == 18:
        li = w & 0x03FFFFFC
        if li >= 0x02000000:
            li -= 0x04000000
        t = li if (w & 2) else va + li
        return '%-6s 0x%08X' % ('bl' if w & 1 else 'b', t)
    if op == 16:
        bd = w & 0xFFFC
        if bd >= 0x8000:
            bd -= 0x10000
        bo, bi = (w >> 21) & 31, (w >> 16) & 31
        nm = {(12, 0): 'blt', (12, 1): 'bgt', (12, 2): 'beq', (4, 0): 'bge',
              (4, 1): 'ble', (4, 2): 'bne', (16, 0): 'bdnz'}.get((bo, bi), 'bc%d,%d' % (bo, bi))
        return '%-6s 0x%08X%s' % (nm, va + bd, '  (lk)' if w & 1 else '')
    if op == 19:
        x = (w >> 1) & 0x3FF
        if x == 16: return 'blr' if w == 0x4E800020 else 'bclr'
        if x == 528: return 'bctrl' if w & 1 else 'bctr'
        if x == 193: return 'crxor'
        return 'op19.%d' % x
    if op == 31:
        x = (w >> 1) & 0x3FF
        n = SPR.get(x)
        if n == 'mfspr':
            sp = ((w >> 11) & 0x3E0) | ((w >> 16) & 31)
            return 'mflr   r%d' % rD if sp == 8 else 'mfspr  r%d,%d' % (rD, sp)
        if n == 'mtspr':
            sp = ((w >> 11) & 0x3E0) | ((w >> 16) & 31)
            return ('mtlr   r%d' % rD) if sp == 8 else (('mtctr  r%d' % rD) if sp == 9
                                                        else 'mtspr  %d,r%d' % (sp, rD))
        if n == 'or' and rD == rB: return 'mr     r%d,r%d' % (rA, rD)
        if n in ('cmpw', 'cmplw'): return '%-6s r%d,r%d' % (n, rA, rB)
        if n: return '%-6s r%d,r%d,r%d' % (n, rA, rD, rB)
        return 'op31.%-3d r%d,r%d,r%d' % (x, rD, rA, rB)
    return '.long  0x%08X' % w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('iso')
    ap.add_argument('addr', nargs='?')
    ap.add_argument('size', nargs='?', default='0x40')
    ap.add_argument('--xref')
    ap.add_argument('--data', nargs=2)
    ap.add_argument('--str')
    a = ap.parse_args()
    d = Dol(a.iso)

    if a.str:
        pat = a.str.encode('latin1')
        for va in d.find(pat + b'\x00'):
            print('문자열 0x%08X %r' % (va, a.str))
            hi, lo = va >> 16, va & 0xFFFF
            if lo >= 0x8000:
                hi += 1
            hits = 0
            for sa, sd, si in d.seg:
                for k in range(0, len(sd) - 8, 4):
                    w = struct.unpack_from('>I', sd, k)[0]
                    if (w >> 26) == 15 and (w & 0xFFFF) == (hi & 0xFFFF) and not ((w >> 16) & 31):
                        rD = (w >> 21) & 31
                        w2 = struct.unpack_from('>I', sd, k + 4)[0]
                        if (w2 >> 26) == 14 and ((w2 >> 16) & 31) == rD and (w2 & 0xFFFF) == lo:
                            print('   만드는 코드 0x%08X' % (sa + k))
                            hits += 1
            if not hits:
                print('   (lis+addi 로 만드는 코드 없음 — 표 안의 포인터일 수 있다)')
                for sa, sd, si in d.seg:
                    j = sd.find(struct.pack('>I', va))
                    while j >= 0:
                        print('   포인터로 0x%08X' % (sa + j))
                        j = sd.find(struct.pack('>I', va), j + 1)
        return

    if a.xref:
        t = int(a.xref, 0)
        for sa, sd, si in d.seg:
            for k in range(0, len(sd) - 4, 4):
                w = struct.unpack_from('>I', sd, k)[0]
                if (w >> 26) == 18:
                    li = w & 0x03FFFFFC
                    if li >= 0x02000000:
                        li -= 0x04000000
                    va = sa + k
                    if (li if (w & 2) else va + li) == t:
                        print('  0x%08X  %s' % (va, dis(w, va)))
                elif (w >> 26) == 16:
                    bd = w & 0xFFFC
                    if bd >= 0x8000:
                        bd -= 0x10000
                    if sa + k + bd == t:
                        print('  0x%08X  %s' % (sa + k, dis(w, sa + k)))
        for sa, sd, si in d.seg:
            j = sd.find(struct.pack('>I', t))
            while j >= 0:
                print('  «표» 0x%08X 에 포인터' % (sa + j))
                j = sd.find(struct.pack('>I', t), j + 1)
        return

    if a.data:
        va, n = int(a.data[0], 0), int(a.data[1], 0)
        b = d.read(va, n)
        for i in range(0, n, 16):
            print('  %08X  %-48s %s' % (va + i, ' '.join('%02X' % x for x in b[i:i + 16]),
                                        ''.join(chr(x) if 32 <= x < 127 else '.' for x in b[i:i + 16])))
        return

    va, n = int(a.addr, 0), int(a.size, 0)
    for k in range(0, n, 4):
        w = d.word(va + k)
        print('  %08X  %08X  %s' % (va + k, w if w is not None else 0, dis(w, va + k)))


if __name__ == '__main__':
    main()
