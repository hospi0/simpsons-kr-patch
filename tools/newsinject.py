# -*- coding: utf-8 -*-
"""한글로 고친 신문 그림을 `loadingN.p3d` 에 되넣는다.

  python tools/newsinject.py <원본.p3d> <한글.png> <출력.p3d>

## 담긴 방식 (실측 loading1.p3d)

```
0x00019005                                     묶음
  0x00019001 IMGHDR   pstr(이름) + u32×9
       14000 · 폭 · 높이 · bpp · 팔레트여부 · 알파 · 형식(1=PNG 6=DXT) · 102402 · ★IMGDATA 크기
    0x00019002 IMGDATA  u32(PNG 바이트수) + PNG 파일 그대로
```
288x224 한 장을 «2의 거듭제곱» 여섯 조각으로 나눠 담는다 —
`256x128 · 32x128 · 256x64 · 32x64 · 256x32`(PNG) + `32x32`(DXT1).
가로는 «폭 큰 것이 왼쪽», 세로는 «높이 큰 것이 위» (p3dimg.stitch 와 같은 규칙).

## ⛔ 지켜야 하는 것

- PNG 조각은 **256색 팔레트 + tRNS**다. 팔레트를 새로 만들지 말고 **원본 것을 그대로 쓴다** —
  IHDR·PLTE·tRNS 를 바이트째 물려받고 **IDAT 만** 갈아 끼운다. 형식이 바뀔 여지가 없다.
- 바뀐 화소만 다시 색인화한다. 안 건드린 곳은 원본 색인 그대로 남아 완전히 동일하다.
- IDAT 은 **한 덩어리**로 쓴다(폰트 주입 때 얻은 교훈).
- 오른쪽아래 32x32 는 DXT1 인데 신문 바깥 여백이라 **손대지 않는다**
  (한글본과 원본이 그 자리에서 RGB 차이 0 임을 확인했다).
- 크기가 바뀌면 ①IMGDATA 의 u32 길이 ②IMGDATA 청크 크기 ③IMGHDR 의 마지막 u32
  ④IMGHDR 청크 크기 ⑤묶음 청크 크기 를 «전부» 고쳐야 한다.
"""
import argparse
import io
import os
import struct
import sys
import zlib

import numpy as np
from PIL import Image

IMGHDR, IMGDATA = 0x00019001, 0x00019002


def chunks(png):
    """PNG 를 (종류, 알맹이) 목록으로."""
    out, i = [], 8
    while i < len(png):
        ln = struct.unpack_from('>I', png, i)[0]
        typ = png[i + 4:i + 8]
        out.append((typ, png[i + 8:i + 8 + ln]))
        i += 12 + ln
        if typ == b'IEND':
            break
    return out


IDAT_MAX = 8192      # ⛔⛔ 원본이 «정확히» 8192 로 끊겨 있다 — 디코더가 그 크기로 읽는다.
#   한 덩어리(20,984 B)로 넣었더니 **로딩 화면에서 크래시**했다 (2026-09-11 실기).
#   폰트 주입 때의 「IDAT 한 덩어리」 교훈은 «폰트 아틀라스» 얘기였고 여기엔 반대로 적용된다.
ZLEVEL = 6           # 원본 zlib 머리가 78 9c (수준 6). 9 로 하면 78 da 가 된다


def build_png(orig, idx, w, h):
    """원본의 IHDR·PLTE·tRNS 를 그대로 쓰고 IDAT 만 새로 만든다 (원본과 같은 8192 단위)."""
    keep = [(t, b) for t, b in chunks(orig) if t in (b'IHDR', b'PLTE', b'tRNS')]
    raw = b''.join(b'\0' + idx[y].tobytes() for y in range(h))
    z = zlib.compress(raw, ZLEVEL)
    for i in range(0, len(z), IDAT_MAX):
        keep.append((b'IDAT', z[i:i + IDAT_MAX]))
    keep.append((b'IEND', b''))
    out = [b'\x89PNG\r\n\x1a\n']
    for t, b in keep:
        out.append(struct.pack('>I', len(b)) + t + b +
                   struct.pack('>I', zlib.crc32(t + b) & 0xFFFFFFFF))
    return b''.join(out)


def reindex(orig_png, tile):
    """바뀐 화소만 원본 팔레트에서 가장 가까운 색으로 다시 색인화한다."""
    im = Image.open(io.BytesIO(orig_png))
    idx = np.asarray(im, dtype=np.uint8).copy()
    pal = np.asarray(im.getpalette(), dtype=np.int16).reshape(-1, 3)
    tr = im.info.get('transparency')
    alpha = (np.frombuffer(tr, dtype=np.uint8).astype(np.int16)
             if isinstance(tr, bytes) else np.full(len(pal), 255, np.int16))
    if len(alpha) < len(pal):
        alpha = np.concatenate([alpha, np.full(len(pal) - len(alpha), 255, np.int16)])
    old = np.asarray(im.convert('RGBA'), dtype=np.int16)
    new = np.asarray(tile.convert('RGBA'), dtype=np.int16)
    # ⛔⛔ 알파까지 비교하면 안 된다 — 우리 한글 PNG 는 알파가 없어(전부 불투명) 신문 «바깥»
    #     투명 영역까지 «바뀐 것»으로 잡히고, 그 자리가 불투명으로 칠해져 검은 테두리가 생겼다.
    # ⛔⛔ 그렇다고 «알파 255» 만 고르면 안 된다 — 이 팔레트는 알파가 이진이 아니다.
    #     실측(loading1 첫 조각) : 알파 255 칸 208개(밝기 0~254) · 254 칸 18개(밝기 1~71, 검은 글자)
    #     원본 영문 「DOG」 자리가 알파 249~254 라 «255 만» 고르자 통째로 안 지워졌다.
    # ✅ 편집 대상 = «거의 불투명»(≥200) 이면서 RGB 가 다른 곳. 색은 알파 250 이상 칸에서 고른다
    #    (지운 자리는 종이색 = 불투명, 새 글자도 불투명이면 된다).
    ch = np.any(old[:, :, :3] != new[:, :, :3], axis=2) & (old[:, :, 3] >= 200)
    n = int(ch.sum())
    if n:
        opaque = np.nonzero(alpha >= 250)[0]
        want = new[ch][:, :3].astype(np.int32)
        ref = pal[opaque].astype(np.int32)
        d = ((want[:, None, :] - ref[None, :, :]) ** 2).sum(axis=2)
        idx[ch] = opaque[d.argmin(axis=1)].astype(np.uint8)
    return idx, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('png'); ap.add_argument('dst')
    a = ap.parse_args()

    d = bytearray(open(a.src, 'rb').read())
    assert d[:4] == b'P3D\xff', a.src
    big = Image.open(a.png).convert('RGBA')

    # 조각 위치 = stitch 규칙 (폭 큰 것이 왼쪽, 높이 큰 것이 위)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from p3d import walk
    metas = []
    for dep, cid, o, ds, cs in walk(bytes(d), 12):
        if cid == IMGHDR:
            n = d[o + 12]
            p = o + 13 + n
            v = list(struct.unpack_from('<9I', d, p))
            metas.append(dict(hdr=o, hds=ds, hcs=cs, fld=p, v=v))
        elif cid == IMGDATA:
            metas[-1].update(dat=o, dds=ds, dcs=cs)
    ws = sorted({m['v'][1] for m in metas}, reverse=True)
    hs = sorted({m['v'][2] for m in metas}, reverse=True)
    xs, x = {}, 0
    for w in ws:
        xs[w] = x; x += w
    ys, y = {}, 0
    for hh in hs:
        ys[hh] = y; y += hh
    print('  캔버스 %dx%d · 조각 %d개' % (x, y, len(metas)))
    if (x, y) != big.size:
        raise SystemExit('⛔ 그림이 %dx%d 인데 조각 합은 %dx%d' % (big.size + (x, y)))

    # 뒤에서부터 바꿔야 앞쪽 오프셋이 안 밀린다
    delta_by = {}
    for m in metas:
        w, hh, fmt = m['v'][1], m['v'][2], m['v'][6]
        if fmt != 1:
            print('  %3dx%-3d DXT1 — 손대지 않음' % (w, hh))
            continue
        ln = struct.unpack_from('<I', d, m['dat'] + 12)[0]
        png = bytes(d[m['dat'] + 16:m['dat'] + 16 + ln])
        tile = big.crop((xs[w], ys[hh], xs[w] + w, ys[hh] + hh))
        idx, n = reindex(png, tile)
        if n == 0:
            print('  %3dx%-3d 바뀐 화소 0 — 원본 그대로' % (w, hh))
            continue                                   # 건드리지 않는다 (바이트째 보존)
        new = build_png(png, idx, w, hh)
        delta_by[m['dat']] = (m, new, n, ln)
        print('  %3dx%-3d 바뀐 화소 %5d · PNG %d → %d B' % (w, hh, n, ln, len(new)))

    for off in sorted(delta_by, reverse=True):
        m, new, n, ln = delta_by[off]
        body = struct.pack('<I', len(new)) + new
        old_dds = m['dds']
        d[m['dat'] + 12:m['dat'] + m['dds']] = body
        nds = 12 + len(body)
        struct.pack_into('<II', d, m['dat'] + 4, nds, nds)          # IMGDATA data·chunk
        diff = nds - old_dds
        struct.pack_into('<I', d, m['fld'] + 32, nds)               # IMGHDR 마지막 u32
        struct.pack_into('<I', d, m['hdr'] + 8, m['hcs'] + diff)    # IMGHDR chunkSize
        root = struct.unpack_from('<I', d, 12 + 8)[0]
        struct.pack_into('<I', d, 12 + 8, root + diff)              # 묶음 chunkSize

    # ⛔⛔ 파일 «맨 앞 12바이트»도 청크다 — `P3D\xff` + dataSize(12) + chunkSize(=파일 전체 크기).
    #    이걸 안 고치면 엔진이 파일 끝을 넘어 읽어 **로딩 화면에서 크래시**한다 (2026-09-11 실기).
    #    p3d.walk 는 오프셋 12 부터 보므로 이 머리는 검사에 안 걸린다.
    struct.pack_into('<I', d, 8, len(d))
    open(a.dst, 'wb').write(bytes(d))
    print('  ✅ %s  %d B → %d B' % (a.dst, len(open(a.src, 'rb').read()), len(d)))

    # 되읽어 검산
    from p3dimg import scan
    got = scan(a.dst)
    print('  되읽기 : %s' % ' · '.join('%s %dx%d' % (k, w, h) for _, k, w, h, _ in got))


if __name__ == '__main__':
    main()
