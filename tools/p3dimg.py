# -*- coding: utf-8 -*-
"""Pure3D(.p3d) 안의 이미지를 목록으로 보거나 뽑아낸다.

  python tools/p3dimg.py <p3d…>                 # 목록
  python tools/p3dimg.py <p3d…> --out <디렉터리>  # 전부 뽑기
  python tools/p3dimg.py <iso> --iso --grep news  # ISO 안 p3d 를 훑어 이미지 찾기

★ 이 게임의 UI 이미지는 **원본 파일 그대로** 들어 있다 —
  `0x00019000 TEXTURE` → `0x00019001 IMGHDR` → `0x00019002 IMGDATA` 안에
  PNG(`\\x89PNG`) 또는 DDS(`DDS `) 가 헤더째 박혀 있다. 디코드가 필요 없다.
  (폰트 아틀라스도 같은 구조 — `tools/p3dfont.py` 는 폰트만 본다.)

⚠️ DDS 는 DXT 압축이라 그림판으로 안 열린다. `--png` 를 주면 PIL 로 PNG 로 바꿔 준다.
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p3d import walk

TEXTURE, IMGHDR, IMGDATA = 0x00019000, 0x00019001, 0x00019002


def pstr(d, p):
    n = d[p]
    return d[p + 1:p + 1 + n].rstrip(b'\0').decode('latin1'), p + 1 + n


def info(b):
    i = b.find(b'\x89PNG')
    if i >= 0:
        w, h = struct.unpack_from('>II', b, i + 16)
        return 'PNG', w, h, b[i + 24], i
    j = b.find(b'DDS ')
    if j >= 0:
        h, w = struct.unpack_from('<II', b, j + 12)
        fourcc = b[j + 84:j + 88].decode('latin1').strip()
        return 'DDS(%s)' % (fourcc or 'raw'), w, h, 0, j
    return '?', 0, 0, 0, -1


def scan(path):
    """[(텍스처이름, 종류, 폭, 높이, 원본바이트)…]"""
    d = open(path, 'rb').read()
    if d[:4] != b'P3D\xff':
        return []
    out, name = [], None
    for dep, cid, off, dsz, csz in walk(d, 12):
        if cid == TEXTURE:
            name = pstr(d, off + 12)[0]
        elif cid == IMGDATA:
            b = d[off + 12:off + dsz]
            kind, w, h, bpp, i = info(b)
            if i >= 0:
                out.append((name or '?', kind, w, h, b[i:]))
            name = None
    return out


def save(items, outdir, src, topng=False):
    os.makedirs(outdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(src))[0]
    n = 0
    for k, (name, kind, w, h, raw) in enumerate(items):
        ext = 'png' if kind == 'PNG' else 'dds'
        safe = ''.join(c if c.isalnum() or c in '_-.' else '_' for c in name)
        p = os.path.join(outdir, '%s__%02d_%s.%s' % (base, k, safe, ext))
        open(p, 'wb').write(raw)
        n += 1
        if topng and ext == 'dds':
            try:
                from PIL import Image
                import io as _io
                im = Image.open(_io.BytesIO(raw))
                im.convert('RGBA').save(p[:-4] + '.png')
            except Exception as e:
                print('    (DDS→PNG 실패 %s: %s)' % (safe, e))
    return n


def stitch(items, dst):
    """조각난 텍스처를 한 장으로 되돌린다.

    ★ 이 게임의 로딩 화면 신문(`/art/frontend/dynaload/images/loadingN.p3d`)은
      288x224 한 장을 «2의 거듭제곱 조각»으로 쪼개 저장한다 —
      256x128 + 32x128 + 256x64 + 32x64 + 256x32 + 32x32.
      가로 위치는 «폭이 큰 것이 왼쪽», 세로는 «높이가 큰 것이 위». 그 규칙으로 되붙인다.
    """
    from PIL import Image
    import io as _io
    ims = []
    for name, kind, w, h, raw in items:
        try:
            ims.append(Image.open(_io.BytesIO(raw)).convert('RGBA'))
        except Exception as e:
            print('  (열기 실패 %s: %s)' % (name, e))
    if not ims:
        raise SystemExit('⛔ 붙일 조각이 없다')
    ws = sorted({im.width for im in ims}, reverse=True)
    hs = sorted({im.height for im in ims}, reverse=True)
    xs, x = {}, 0
    for w in ws:
        xs[w] = x
        x += w
    ys, y = {}, 0
    for h in hs:
        ys[h] = y
        y += h
    canvas = Image.new('RGBA', (x, y), (0, 0, 0, 0))
    put = set()
    for im in ims:
        p = (xs[im.width], ys[im.height])
        if p in put:
            continue
        canvas.alpha_composite(im, p)
        put.add(p)
    canvas.save(dst)
    print('%s  %dx%d · 조각 %d개' % (dst, canvas.width, canvas.height, len(put)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('paths', nargs='+')
    ap.add_argument('--out')
    ap.add_argument('--png', action='store_true', help='DDS 도 PNG 로 같이 저장(PIL 필요)')
    ap.add_argument('--iso', action='store_true', help='첫 인수를 ISO 로 보고 안의 p3d 를 전부 훑는다')
    ap.add_argument('--grep', default='', help='--iso 일 때 파일 경로 걸러내기')
    ap.add_argument('--min', type=int, default=0, help='이 픽셀 폭 이상만')
    ap.add_argument('--stitch', help='조각들을 한 장으로 이어 붙여 이 PNG 로 저장')
    a = ap.parse_args()

    if a.iso:
        from gcfst import read_fst
        import tempfile
        f = open(a.paths[0], 'rb')
        h, ents = read_fst(f)
        tot = 0
        for path, off, size, isdir in ents:
            if isdir or not path.lower().endswith('.p3d'):
                continue
            if a.grep and a.grep.lower() not in path.lower():
                continue
            f.seek(off)
            blob = f.read(size)
            tmp = os.path.join(tempfile.gettempdir(), '_p3dimg.p3d')
            open(tmp, 'wb').write(blob)
            items = [x for x in scan(tmp) if x[2] >= a.min]
            if not items:
                continue
            print('%s' % path)
            for name, kind, w, hh, raw in items:
                print('    %-28s %-10s %4dx%-4d %8d B' % (name, kind, w, hh, len(raw)))
            if a.out:
                tot += save(items, a.out, path.replace('/', '_'), a.png)
        if a.out:
            print('\n→ %s 에 %d개 저장' % (a.out, tot))
        return

    if a.stitch:
        items = []
        for p in a.paths:
            items += scan(p)
        stitch(items, a.stitch)
        return

    tot = 0
    for p in a.paths:
        items = [x for x in scan(p) if x[2] >= a.min]
        print('########## %s  (이미지 %d개)' % (p, len(items)))
        for name, kind, w, h, raw in items:
            print('    %-28s %-10s %4dx%-4d %8d B' % (name, kind, w, h, len(raw)))
        if a.out:
            tot += save(items, a.out, p, a.png)
    if a.out:
        print('\n→ %s 에 %d개 저장' % (a.out, tot))


if __name__ == '__main__':
    main()
