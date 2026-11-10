# -*- coding: utf-8 -*-
"""돌핀 Sys/totaldb.dsy(SDK 함수 서명) 로 DOL 함수 이름 찾기.
  python tools/sigmatch.py <iso> [--lo 0x802E0000 --hi 0x80337000] > work/sdk_syms.txt
체크섬 = 돌핀 HashSignatureDB::ComputeCodeChecksum(주소·즉치 가림 + 17비트 회전 XOR).
함수 시작 후보 = 모든 bl 대상. 각 시작점에서 길이를 늘려 가며 (길이,체크섬) 이 DB 와 맞으면 이름."""
import sys, struct, argparse
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ppcdis import Dol

def mask(op_):
    op = op_ & 0xFC000000; aux = op >> 26; op2 = op3 = 0
    if aux == 4:
        op2 = op_ & 0x3F
        if op2 in (0, 8, 16, 21, 22): op3 = op_ & 0x7C0
    elif aux in (7, 8, 10, 11, 12, 13, 14, 15): op2 = op_ & 0x03FF0000
    elif aux in (19, 31, 63): op2 = op_ & 0x7FF
    elif aux == 59:
        op2 = op_ & 0x3F
        if op2 < 16: op3 = op_ & 0x7C0
    elif 32 <= aux < 56: op2 = op_ & 0x03FF0000
    return op | op2 | op3

ap = argparse.ArgumentParser(); ap.add_argument('iso'); ap.add_argument('--db', default='D:/hospi/Dolphin-x64/Sys/totaldb.dsy')
ap.add_argument('--lo', default='0x80005880'); ap.add_argument('--hi', default='0x80337660'); a = ap.parse_args()
db = open(a.db, 'rb').read(); n = struct.unpack_from('<I', db, 0)[0]
sig = {}
for k in range(n):
    cs, sz = struct.unpack_from('<II', db, 4 + k * 136)
    nm = db[4 + k * 136 + 8:4 + k * 136 + 136].split(b'\0')[0].decode('latin1')
    sig.setdefault(sz, {})[cs] = nm
maxsz = max(sig)
d = Dol(a.iso); lo, hi = int(a.lo, 16), int(a.hi, 16)
starts = set()
for base, data, i in d.seg:
    if base >= 0x80337660: continue
    for o in range(0, len(data), 4):
        w = struct.unpack_from('>I', data, o)[0]
        if w >> 26 == 18 and w & 1:
            off = w & 0x3FFFFFC
            if off & 0x2000000: off -= 0x4000000
            t = base + o + off
            if lo <= t < hi: starts.add(t)
out = []
for s in sorted(starts):
    sm = 0; L = 0; best = None
    while L < maxsz:
        w = d.word(s + L)
        if w is None: break
        sm = (((sm << 17) & 0xFFFE0000) | ((sm >> 15) & 0x1FFFF)) ^ mask(w)
        L += 4
        t = sig.get(L)
        if t and sm in t: best = (L, t[sm])
        if w == 0x4E800020 and best: break
    if best: out.append((s, best[0], best[1]))
for s, L, nm in out: print('%08X %5d %s' % (s, L, nm))
print('# %d/%d' % (len(out), len(starts)), file=sys.stderr)
