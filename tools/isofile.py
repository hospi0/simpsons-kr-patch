# -*- coding: utf-8 -*-
"""GC ISO 안의 파일을 «미사용 영역»으로 옮기고 FST 항목만 고친다.

  python tools/isofile.py <iso> --list                      # FST 목록(오프셋·크기)
  python tools/isofile.py <iso> --free                      # 미사용 구멍 목록
  python tools/isofile.py <iso> --move <경로> <새오프셋>      # 파일을 옮기고 FST 갱신
  python tools/isofile.py <iso> --replace <경로> <파일>       # 새 내용으로 교체(커지면 구멍으로 이동)

## 원리

```
디스크 헤더 0x420 = DOL 오프셋 · 0x424 = FST 오프셋 · 0x428 = FST 크기 (u32 BE)
FST 항목 12 B = [0]종류(0=파일,1=디렉터리) · [1..3]이름오프셋 · [4..7]오프셋 · [8..11]크기 (BE)
```

★ ISO 전체를 재패킹할 필요가 없다. 파일을 미사용 영역에 놓고 **FST 항목만** 고치면 된다.
⚠️ 미사용 영역은 **0 이 아니라 «난수 패딩»** 일 수 있다(심슨 GC 가 그렇다).
   빈 공간 판정은 «0 인지»가 아니라 **FST 커버리지**로 해야 한다.
"""
import argparse
import struct
import sys

ALIGN = 0x8000          # 32 KB 정렬(디스크 읽기 안전)


def read_hdr(f):
    f.seek(0x420)
    dol, fsto, fsts = struct.unpack('>3I', f.read(12))
    return dol, fsto, fsts


def read_fst(f):
    dol, fsto, fsts = read_hdr(f)
    f.seek(fsto)
    fst = f.read(fsts)
    n = struct.unpack('>I', fst[8:12])[0]
    strt = 12 * n
    out = []
    stack = [(n, '')]
    for i in range(n):
        e = fst[i * 12:(i + 1) * 12]
        noff = struct.unpack('>I', b'\x00' + e[1:4])[0]
        j = fst.find(b'\x00', strt + noff)
        nm = fst[strt + noff:j].decode('latin1', 'replace')
        a, b = struct.unpack('>II', e[4:12])
        while len(stack) > 1 and i >= stack[-1][0]:
            stack.pop()
        path = stack[-1][1] + '/' + nm if i else ''
        if e[0]:
            stack.append((b, path))
            out.append((i, path, True, a, b))
        else:
            out.append((i, path, False, a, b))
    return fsto, fsts, fst, n, out


def dol_extent(f):
    """★★★ 옮긴 DOL 은 FST 에 «없다» — 구멍 계산에서 반드시 빼야 한다.
    (안 빼면 새 파일이 DOL 위에 얹혀 부팅불가가 된다. 실제로 한 번 밟았다.)"""
    f.seek(0x420)
    dol = struct.unpack('>I', f.read(4))[0]
    f.seek(dol)
    h = f.read(0x100)
    off = struct.unpack_from('>18I', h, 0x00)
    siz = struct.unpack_from('>18I', h, 0x90)
    end = max((off[i] + siz[i]) for i in range(18) if siz[i])
    return dol, dol + end


def free_holes(entries, disc, reserved=()):
    iv = sorted([(a, a + b) for _, _, d, a, b in entries if not d] + list(reserved))
    merged = []
    for a, b in iv:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append([a, b])
    holes, prev = [], 0x400000
    for a, b in merged:
        if a > prev:
            holes.append((prev, a - prev))
        prev = b
    if disc > prev:
        holes.append((prev, disc - prev))
    return sorted(holes, key=lambda h: -h[1])


def set_entry(f, fsto, idx, off, size):
    f.seek(fsto + idx * 12 + 4)
    f.write(struct.pack('>II', off, size))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('iso')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--free', action='store_true')
    ap.add_argument('--move', nargs=2, metavar=('경로', '새오프셋'))
    ap.add_argument('--replace', nargs=2, metavar=('경로', '내용파일'))
    a = ap.parse_args()
    import os
    disc = os.path.getsize(a.iso)
    mode = 'r+b' if (a.move or a.replace) else 'rb'
    f = open(a.iso, mode)
    fsto, fsts, fst, n, ents = read_fst(f)
    if a.list:
        for i, p, d, o, s in ents:
            print('%5d %-70s %s' % (i, p, 'DIR' if d else '0x%09X %10d' % (o, s)))
        return
    if a.free:
        for o, l in free_holes(ents, disc, [dol_extent(f)])[:12]:
            print('  0x%09X  %12d B (%.2f MB)' % (o, l, l / 1048576))
        return
    path = (a.move or a.replace)[0]
    hit = [e for e in ents if not e[2] and e[1].lower() == path.lower()]
    if len(hit) != 1:
        raise SystemExit('⛔ 경로를 %d개 찾았다: %s' % (len(hit), path))
    idx, p, _, off, size = hit[0]
    print('대상 [%d] %s  현재 0x%09X %d B' % (idx, p, off, size))
    if a.move:
        new = int(a.move[1], 0)
        if new % ALIGN:
            raise SystemExit('⛔ 새 오프셋은 0x%X 정렬이어야 한다' % ALIGN)
        f.seek(off); data = f.read(size)
        f.seek(new); f.write(data)
        set_entry(f, fsto, idx, new, size)
        print('  ✅ 0x%09X 로 옮기고 FST 갱신' % new)
    else:
        data = open(a.replace[1], 'rb').read()
        holes = free_holes(ents, disc, [dol_extent(f)])
        spot = None
        for o, l in holes:
            oo = (o + ALIGN - 1) & ~(ALIGN - 1)
            if l - (oo - o) >= len(data):
                spot = oo; break
        if spot is None:
            raise SystemExit('⛔ 들어갈 구멍이 없다 (%d B)' % len(data))
        f.seek(spot); f.write(data)
        set_entry(f, fsto, idx, spot, len(data))
        print('  ✅ 0x%09X 에 %d B 로 교체하고 FST 갱신' % (spot, len(data)))
    f.close()


if __name__ == '__main__':
    main()
