# -*- coding: utf-8 -*-
"""p3d 안의 폰트를 «새 아틀라스 + 새 글리프표»로 갈아 끼운다.

  python tools/p3dinject.py work/extract/ingame.p3d work/extract/ingame_kr.p3d \
      --font boulder_16 --png work/font/kr_boulder_16.png --glyphs work/font/kr_boulder_16.glyphs

## 청크 배치 (ingame.p3d 실측)

```
0x00022000 FONT            data=50   ← 최상위. 위로 갱신할 부모가 없다
  0x00019000 TEXTURE       data=69     이름 + u32 버전 + u32 폭 + u32 높이 + u32 bpp + …
    0x00019001 IMGHDR      data=41     빈 이름 + u32 버전 + u32 폭 + u32 높이 + u32 bpp + …
      0x00019002 IMGDATA   data=…      u32 길이 + PNG
  0x00022001 GLYPHS        data=…      u32 개수 + 개수 × 40B
```

청크 = `u32 id · u32 dataSize(머리 12 포함, = 첫 자식까지의 거리) · u32 chunkSize(자식 포함 전체)`.
폭·높이는 **TEXTURE 와 IMGHDR 양쪽**에 있으니 둘 다 고쳐야 한다.
"""
import argparse
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p3d import walk

FONT, GLYPHS, TEXTURE, IMGHDR, IMGDATA = 0x00022000, 0x00022001, 0x00019000, 0x00019001, 0x00019002


def chunk(cid, data, children=b''):
    dsz = 12 + len(data)
    return struct.pack('<III', cid, dsz, dsz + len(children)) + data + children


def fix_wh(data, w, h):
    """이름(pstr) + u32 버전 다음의 폭·높이를 고친다."""
    n = data[0]
    p = 1 + n + 4
    out = bytearray(data)
    struct.pack_into('<II', out, p, w, h)
    return bytes(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--font', default='boulder_16')
    ap.add_argument('--png', required=True, nargs='+', help='아틀라스 PNG (여러 장이면 다중 텍스처)')
    ap.add_argument('--glyphs', required=True)
    a = ap.parse_args()

    d = open(a.src, 'rb').read()
    assert d[:4] == b'P3D\xff'
    ch = walk(d, 12)

    fi = None
    for i, (depth, cid, off, dsz, csz) in enumerate(ch):
        if cid == FONT and a.font.encode() in d[off + 12:off + dsz]:
            fi = i
            break
    if fi is None:
        raise SystemExit('⛔ 폰트 %s 를 못 찾았다' % a.font)
    fdepth, _, foff, fdsz, fcsz = ch[fi]
    if fdepth != 0:
        raise SystemExit('⛔ FONT 가 최상위가 아니다(부모 갱신 필요) depth=%d' % fdepth)

    sub = {}
    for depth, cid, off, dsz, csz in ch[fi:]:
        if off >= foff + fcsz:
            break
        if cid in (TEXTURE, IMGHDR, IMGDATA, GLYPHS):
            sub[cid] = (off, dsz, csz)
    for k in (TEXTURE, IMGHDR, IMGDATA, GLYPHS):
        if k not in sub:
            raise SystemExit('⛔ 하위 청크 0x%08X 가 없다' % k)

    gb = open(a.glyphs, 'rb').read()
    ng = struct.unpack_from('<I', gb, 0)[0]

    toff, tdsz, _ = sub[TEXTURE]
    hoff, hdsz, _ = sub[IMGHDR]
    tex_data0 = d[toff + 12:toff + tdsz]
    hdr_data0 = d[hoff + 12:hoff + hdsz]
    tname0 = tex_data0[1:1 + tex_data0[0]].decode('latin1')

    textures = b''
    for i, path in enumerate(a.png):
        png = open(path, 'rb').read()
        w, h = struct.unpack_from('>II', png, 16)          # IHDR
        print('아틀라스[%d] %dx%d (%d B) · 디코드 %d KB' % (i, w, h, len(png), w * h // 2 // 1024))
        imgdata = chunk(IMGDATA, struct.pack('<I', len(png)) + png)
        imghdr = chunk(IMGHDR, fix_wh(hdr_data0, w, h), imgdata)
        # 텍스처 이름은 «장마다 달라야» 한다 — 끝의 _0 을 _i 로 바꾼다
        nm = (tname0.rsplit('_', 1)[0] + '_%d' % i).encode('latin1')
        td = bytes([len(nm)]) + nm + tex_data0[1 + len(tname0):]
        textures += chunk(TEXTURE, fix_wh(td, w, h), imghdr)

    new_glyphs = chunk(GLYPHS, gb)

    # 폰트 머리의 «텍스처 수»(마지막 u32)를 장수로 갱신
    fdata = bytearray(d[foff + 12:foff + fdsz])
    struct.pack_into('<I', fdata, len(fdata) - 4, len(a.png))
    print('글리프 %d개 · 텍스처 수 %d' % (ng, len(a.png)))

    new_font = chunk(FONT, bytes(fdata), textures + new_glyphs)

    out = d[:foff] + new_font + d[foff + fcsz:]
    open(a.dst, 'wb').write(out)
    print('FONT 청크 %d B -> %d B · 파일 %d B -> %d B (+%d)'
          % (fcsz, len(new_font), len(d), len(out), len(out) - len(d)))

    # 되읽어 검산
    import p3dfont
    for f in p3dfont.scan(a.dst):
        if f['font']['name'] == a.font:
            print('검산: %s · %s · 글리프 %d개 · 항목 %d B'
                  % (f['font']['name'], f['img'], len(f['glyphs']), f['per']))
            ks = [g for g in f['glyphs'] if 0xAC00 <= g['code'] <= 0xD7A3]
            print('       한글 %d자 · 코드 오름차순=%s'
                  % (len(ks), all(f['glyphs'][i]['code'] < f['glyphs'][i + 1]['code']
                                  for i in range(len(f['glyphs']) - 1))))


if __name__ == '__main__':
    main()
