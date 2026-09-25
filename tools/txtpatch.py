# -*- coding: utf-8 -*-
"""텍스트 바이블(srr2.p3d)의 UTF-16 문자열을 ISO 안에서 «제자리» 교체한다.

  python tools/txtpatch.py <iso> --set "원래 문자열" "새 문자열"
  python tools/txtpatch.py <iso> --find "문자열"

★ 같은 «문자 수» 일 때만 바꾼다. 길이가 달라지면 오프셋 표(off[n])와 blen·청크 크기를
  다시 써야 하므로 이 도구는 거부한다(그건 본 빌드 도구의 몫).
⚠️ 언어 슬롯 5개(EFGIS)에 각각 사본이 있다. 영문 원문이 다른 언어에도 그대로 들어
  있을 수 있으니 «몇 곳에서 찾았는지» 반드시 확인할 것.
"""
import argparse
import sys

SRR2_ISO = 0x02360DCEC     # /art/frontend/scrooby/resource/txtbible/srr2.p3d
SRR2_SIZE = 646016


def find(d, s):
    pat = s.encode('utf-16-le')
    out, i = [], 0
    while True:
        i = d.find(pat, i)
        if i < 0:
            break
        out.append(i)
        i += 2
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('iso')
    ap.add_argument('--find')
    ap.add_argument('--set', nargs=2, metavar=('OLD', 'NEW'))
    a = ap.parse_args()
    f = open(a.iso, 'r+b' if a.set else 'rb')
    f.seek(SRR2_ISO)
    d = f.read(SRR2_SIZE)
    if a.find:
        for h in find(d, a.find):
            print('  p3d+0x%06X  ISO 0x%09X' % (h, SRR2_ISO + h))
        return
    old, new = a.set
    if len(old) != len(new):
        raise SystemExit('⛔ 길이가 다르다: %d vs %d (이 도구는 같은 길이만)' % (len(old), len(new)))
    hits = find(d, old)
    if len(hits) != 1:
        raise SystemExit('⛔ %d곳에서 찾았다(1곳이어야 안전): %s' % (len(hits), hits))
    off = SRR2_ISO + hits[0]
    f.seek(off)
    f.write(new.encode('utf-16-le'))
    f.close()
    print('  ✅ ISO 0x%09X  %r -> %r  (%d자)' % (off, old, new, len(new)))


if __name__ == '__main__':
    main()
