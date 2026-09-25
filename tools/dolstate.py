# -*- coding: utf-8 -*-
"""돌핀 세이브스테이트(.s01 / lastState.sav)를 풀어 게스트 RAM·PPC 상태를 읽는다.

  python tools/dolstate.py <state 파일> --info
  python tools/dolstate.py <state 파일> --dump ram.bin
  python tools/dolstate.py <state 파일> --pc          # PC/LR 후보 찾기

돌핀은 상태를 **LZ4 블록**으로 압축한다(프레임 헤더도, zstd 매직도 없다).
블록 포맷은 단순해서 순수 파이썬으로 충분히 푼다.

머리 (실측, Dolphin 2606-315)
```
0x00  char  game_id[6]        "GHQE7D"
0x10  u8    md5/해시 12~16B
0x1C  u32   버전 문자열 길이
0x20  char  version[len]      "Dolphin 2606-315"
그 뒤   압축 방식 · 원본 크기(u64) · 압축 데이터
```
정확한 자리는 판마다 달라서 «원본 크기 u64 + LZ4 시작점»을 훑어 찾는다.
"""
import argparse
import struct
import sys


def lz4_block(src, want=None):
    """LZ4 블록 압축 해제 (순수 파이썬)."""
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while i < n:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        if i + lit > n:
            raise ValueError('리터럴이 잘림')
        out += src[i:i + lit]
        i += lit
        if want is not None and len(out) >= want:
            return bytes(out[:want])
        if i + 2 > n:
            break                                   # 마지막 블록은 리터럴로 끝난다
        off = src[i] | (src[i + 1] << 8)
        i += 2
        if off == 0 or off > len(out):
            raise ValueError('매치 오프셋 이상 %d' % off)
        ml = token & 0xF
        if ml == 15:
            while i < n:
                b = src[i]
                i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        p = len(out) - off
        for k in range(ml):                          # 겹침 복사라 한 바이트씩
            out.append(out[p + k])
        if want is not None and len(out) >= want:
            return bytes(out[:want])
    return bytes(out)


def unpack(path, limit=None):
    d = open(path, 'rb').read()
    gid = d[:6].decode('latin1', 'replace')
    vlen = struct.unpack_from('<I', d, 0x1C)[0]
    ver = d[0x20:0x20 + vlen].decode('latin1', 'replace')
    base = 0x20 + vlen
    best = None
    for start in range(base, base + 0x40):
        # 원본 크기로 그럴듯한 u64 를 찾고, 그 뒤부터 LZ4 로 풀어 본다
        if start + 8 > len(d):
            break
        size = struct.unpack_from('<Q', d, start)[0]
        if not (0x1000000 <= size <= 0x20000000):
            continue
        for off in (start + 8, start + 12, start + 16):
            try:
                out = lz4_block(d[off:], want=limit or size)
            except Exception:
                continue
            if len(out) >= min(0x100000, limit or size):
                best = (gid, ver, size, off, out)
                break
        if best:
            break
    if not best:
        raise SystemExit('⛔ 압축 데이터 시작점을 못 찾았다')
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('state')
    ap.add_argument('--info', action='store_true')
    ap.add_argument('--dump')
    ap.add_argument('--limit', type=lambda x: int(x, 0), default=0)
    a = ap.parse_args()
    gid, ver, size, off, out = unpack(a.state, a.limit or None)
    print('게임 %s · %s' % (gid, ver))
    print('원본 크기 %d B · 압축 시작 0x%X · 푼 길이 %d B' % (size, off, len(out)))
    print('앞 64 B: %s' % out[:64].hex(' '))
    if a.dump:
        open(a.dump, 'wb').write(out)
        print('-> %s' % a.dump)


if __name__ == '__main__':
    main()
