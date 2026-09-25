# -*- coding: utf-8 -*-
"""SHAR 텍스트 바이블(srr2.p3d) 판독기.

  python tools/txtbible.py <srr2.p3d>            # 언어별 요약
  python tools/txtbible.py <srr2.p3d> E > out.tsv  # 그 언어 전량 (키<TAB>문자열)

포맷 (Pure3D 청크 0x0001800D 안에 0x0001800E 가 언어 수만큼)
    u8+이름   "exportart\frontend\scrooby\resource\txtbible\srr2<언어>"
    u8        언어 코드 ('E' 'F' 'G' 'I' 'S')
    u32 n     항목 수
    u32 ?     (마지막 키 근처 값)
    u32 blen  문자열 영역 바이트 수
    u32 key[n]     정렬된 키 해시
    u32 off[n]     문자열 영역 내 오프셋
    <blen 바이트>  **UTF-16LE, NUL 종단**
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p3d


def langs(d):
    out = []
    for depth, cid, off, dsz, csz in p3d.walk(d, 12):
        if cid != 0x0001800E:
            continue
        p = off + 12
        ln = d[p]
        name = d[p + 1:p + 1 + ln].rstrip(b'\0').decode('latin1')
        p += 1 + ln
        code = chr(d[p]); p += 1
        n, a, blen = struct.unpack_from('<III', d, p); p += 12
        keys = struct.unpack_from('<%dI' % n, d, p); p += 4 * n
        offs = struct.unpack_from('<%dI' % n, d, p); p += 4 * n
        blob = d[p:p + blen]
        out.append(dict(code=code, name=name, n=n, a=a, blen=blen,
                        keys=keys, offs=offs, blob=blob, chunk=off))
    return out


def text(L, i):
    o = L['offs'][i]
    e = L['blob'].find(b'\0\0', o)
    while e >= 0 and (e - o) % 2:
        e = L['blob'].find(b'\0\0', e + 1)
    if e < 0:
        e = len(L['blob'])
    return L['blob'][o:e].decode('utf-16-le', 'replace')


def main():
    d = open(sys.argv[1], 'rb').read()
    Ls = langs(d)
    if len(sys.argv) > 2:
        want = sys.argv[2]
        for L in Ls:
            if L['code'] == want:
                for i in range(L['n']):
                    s = text(L, i).replace('\t', '\t').replace('\n', '\n').replace('\r', '')
                    print('%08X\t%s' % (L['keys'][i], s))
                return
        raise SystemExit('그런 언어 없음: %s' % want)
    for L in Ls:
        nz = sum(1 for i in range(L['n']) if text(L, i))
        print('%s  항목 %5d (빈칸 아닌 것 %5d)  문자열영역 %7d B  청크 0x%06X  %s'
              % (L['code'], L['n'], nz, L['blen'], L['chunk'], L['name']))


if __name__ == '__main__':
    main()
