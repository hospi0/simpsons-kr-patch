# -*- coding: utf-8 -*-
"""게임큐브 ISO 의 FST(파일 목록)를 읽는다.

  python tools/gcfst.py <iso>              # 목록
  python tools/gcfst.py <iso> --get <경로> <출력>
"""
import os
import struct
import sys


def header(f):
    f.seek(0)
    d = f.read(0x440)
    return dict(code=d[0:6].decode('latin1'), name=d[0x20:0x60].split(b'\0')[0].decode('latin1'),
                dol=struct.unpack_from('>I', d, 0x420)[0],
                fst=struct.unpack_from('>I', d, 0x424)[0],
                fstsize=struct.unpack_from('>I', d, 0x428)[0])


def read_fst(f):
    h = header(f)
    f.seek(h['fst'])
    fst = f.read(h['fstsize'])
    nent = struct.unpack_from('>I', fst, 8)[0]
    strbase = nent * 12
    out = []
    stack = [(nent, '')]
    i = 1
    while i < nent:
        e = fst[i * 12:(i + 1) * 12]
        isdir = e[0]
        noff = struct.unpack('>I', b'\0' + e[1:4])[0]
        a = struct.unpack_from('>I', e, 4)[0]
        b = struct.unpack_from('>I', e, 8)[0]
        end = fst.index(b'\0', strbase + noff)
        name = fst[strbase + noff:end].decode('latin1')
        while stack and i >= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1] if stack else ''
        path = parent + '/' + name
        if isdir:
            out.append((path, None, None, True))
            stack.append((b, path))
        else:
            out.append((path, a, b, False))
        i += 1
    return h, out


def main():
    p = sys.argv[1]
    f = open(p, 'rb')
    h, ents = read_fst(f)
    if '--get' in sys.argv:
        want = sys.argv[sys.argv.index('--get') + 1]
        outp = sys.argv[sys.argv.index('--get') + 2]
        for path, off, size, isdir in ents:
            if not isdir and path.lower() == want.lower():
                f.seek(off)
                open(outp, 'wb').write(f.read(size))
                print('%s  %d B -> %s' % (path, size, outp))
                return
        raise SystemExit('없음: %s' % want)
    print('%s %r  dol=0x%X fst=0x%X(%d B)' % (h['code'], h['name'], h['dol'], h['fst'], h['fstsize']))
    print('항목 %d' % len(ents))
    for path, off, size, isdir in ents:
        print('  %-60s %-4s %s' % (path, 'DIR' if isdir else '', '' if isdir else '0x%09X %10d B' % (off, size)))


if __name__ == '__main__':
    main()
