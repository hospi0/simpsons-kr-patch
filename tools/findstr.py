# -*- coding: utf-8 -*-
"""ISO 전체에서 문자열을 찾고 «어느 FST 파일 안인지» 알려준다.

  python tools/findstr.py <iso> <문자열> [문자열…]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gcfst


def locate(ents, off):
    best = None
    for path, o, s, isdir in ents:
        if isdir:
            continue
        if o <= off < o + s:
            return path, off - o
        if o <= off:
            best = (path, off - o)
    return best if best else ('?', off)


def main():
    iso = sys.argv[1]
    words = [w.encode('latin1') for w in sys.argv[2:]]
    f = open(iso, 'rb')
    h, ents = gcfst.read_fst(f)
    ents = [e for e in ents if not e[3]]
    ents.sort(key=lambda e: e[1])
    hits = {w: [] for w in words}
    CH = 1 << 24
    off = 0
    size = os.path.getsize(iso)
    tailmax = max(len(w) for w in words)
    prev = b''
    while off < size:
        f.seek(off)
        b = f.read(CH)
        if not b:
            break
        blob = prev + b
        base = off - len(prev)
        for w in words:
            i = 0
            while True:
                i = blob.find(w, i)
                if i < 0:
                    break
                a = base + i
                if len(hits[w]) < 40:
                    hits[w].append(a)
                i += 1
        prev = b[-tailmax:]
        off += CH
    for w in words:
        print('== %r  %d곳' % (w.decode('latin1'), len(hits[w])))
        for a in hits[w][:12]:
            p, rel = locate(ents, a)
            print('   0x%09X  %s + 0x%X' % (a, p, rel))


if __name__ == '__main__':
    main()
