# -*- coding: utf-8 -*-
"""Pure3D(.p3d) 청크 리더.  청크 = u32 id, u32 dataSize(머리, 12 포함), u32 chunkSize(전체)"""
import struct
import sys


def walk(d, off=0, end=None, depth=0):
    if end is None:
        end = len(d)
    out = []
    while off + 12 <= end:
        cid, dsz, csz = struct.unpack_from('<III', d, off)
        if csz < 12 or off + csz > end:
            break
        out.append((depth, cid, off, dsz, csz))
        if csz > dsz:
            out += walk(d, off + dsz, off + csz, depth + 1)
        off += csz
    return out


if __name__ == '__main__':
    d = open(sys.argv[1], 'rb').read()
    assert d[:4] == b'P3D\xff'
    for depth, cid, off, dsz, csz in walk(d, 12):
        print('%s0x%08X  off=0x%06X  data=%-8d total=%-8d %s'
              % ('  ' * depth, cid, off, dsz, csz,
                 repr(d[off + 12:off + min(dsz, 12 + 48)])))
