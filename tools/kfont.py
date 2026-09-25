# -*- coding: utf-8 -*-
"""심슨 GC 폰트에 «한글 글리프»를 굽는다.

  python tools/kfont.py work/extract/ingame.p3d --font boulder_16 --out work/font/kr
  ... --ttf "C:/claude/utils/font/nanum-gothic/NanumGothicBold.ttf" --size 15
  ... --atlas 1024 --preview

## 원본 아틀라스 규약 (실측)

- PNG **P 모드 4bpp**, 팔레트 16칸이 «전부 흰색», 투명도는 `tRNS` 의 16단계 램프
  (0x00,0x11,…,0xFF). 즉 실질적으로 **알파 전용** 폰트다. 색인 = 알파 단계.
- 글리프는 **높이가 전부 같은 고정 박스**(boulder_16 은 19px), 폭만 가변.
  UV 폭 × 텍스처 폭 = 글리프 픽셀 폭.
- 항등식 `전진 = 좌베어링 + 폭 + 우베어링`.
- 아틀라스는 아래에서 위로 채워져 있었으나, 새로 구울 땐 위에서부터 채워도
  UV 만 맞으면 된다(고정 격자가 아니라 UV 참조 방식).

## 하는 일

1. 기존 글리프 136개를 원본 아틀라스에서 «픽셀 그대로» 오려 온다 (영문이 안 변하도록).
2. 한글 음절을 TTF 로 같은 높이 박스에 렌더한다 (베이스라인 정렬).
3. 새 아틀라스에 다시 채우고 UV·폭·전진을 새로 계산한다.
4. 새 PNG(원본과 같은 규약) + 새 글리프표(.bin) + 눈으로 볼 미리보기를 낸다.
"""
import argparse
import io
import os
import struct
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p3dfont


def ksx1001():
    """KS X 1001 완성형 2,350자 (선행 0xB0~0xC8 · 후행 0xA1~0xFE)."""
    out = []
    for lead in range(0xB0, 0xC9):
        for trail in range(0xA1, 0xFF):
            try:
                out.append(bytes([lead, trail]).decode('euc-kr'))
            except UnicodeDecodeError:
                pass
    return out


def load_atlas(png_path):
    im = Image.open(png_path)
    tr = im.info.get('transparency')
    if im.mode != 'P' or not tr:
        raise SystemExit('⛔ 예상과 다른 아틀라스: %s %s' % (im.mode, type(tr)))
    lut = list(tr) + [0] * (256 - len(tr))
    a = Image.new('L', im.size)
    a.putdata([lut[v] for v in im.getdata()])
    return a                       # 알파 채널만 있는 회색 이미지


def save_atlas(alpha, path):
    """원본과 같은 규약으로 되돌린다 — 흰색 팔레트 + tRNS 16단계."""
    q = alpha.point(lambda v: min(15, (v * 16) // 256))
    im = Image.new('P', alpha.size)
    im.putdata(list(q.getdata()))
    im.putpalette([255, 255, 255] * 16 + [0] * (3 * (256 - 16)))
    im.info['transparency'] = bytes([min(255, i * 17) for i in range(16)])
    buf = io.BytesIO()
    im.save(buf, format='PNG', transparency=im.info['transparency'], bits=4, optimize=True)
    open(path, 'wb').write(single_idat(buf.getvalue()))
    return im


def single_idat(png):
    """★ IDAT 를 «한 덩어리»로 합친다.

    PIL 은 64KB 마다 IDAT 를 쪼갠다. 원본 아틀라스는 IDAT 가 하나뿐이고,
    게임의 PNG 디코더가 여러 IDAT 를 못 받을 수 있다(실제로 크래시했다).
    PNG 규격상 여러 IDAT 는 합법이지만 «원본과 같은 모양»으로 맞춰 두는 게 안전하다.
    """
    import zlib as _z
    out = png[:8]
    p = 8
    idat = b''
    tail = b''
    while p < len(png):
        ln = struct.unpack_from('>I', png, p)[0]
        typ = png[p + 4:p + 8]
        body = png[p + 8:p + 8 + ln]
        if typ == b'IDAT':
            idat += body
        elif typ == b'IEND':
            tail = b''
        else:
            out += png[p:p + 12 + ln]
        p += 12 + ln

    def ch(t, b):
        return struct.pack('>I', len(b)) + t + b + struct.pack('>I', _z.crc32(t + b) & 0xFFFFFFFF)

    return out + ch(b'IDAT', idat) + ch(b'IEND', b'') + tail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('p3d')
    ap.add_argument('--font', default='boulder_16')
    ap.add_argument('--ttf', default=r'C:/claude/utils/font/nanum-gothic/NanumGothicBold.ttf')
    ap.add_argument('--size', type=int, default=0, help='0 이면 박스 높이에서 자동')
    ap.add_argument('--atlas', type=int, default=1024, help='아틀라스 «폭»')
    ap.add_argument('--atlash', type=int, default=0, help='아틀라스 «높이»(0이면 폭과 같게)')
    ap.add_argument('--pages', type=int, default=1, help='아틀라스 장수(다중 텍스처)')
    ap.add_argument('--kshift', type=int, default=0,
                    help='한글을 이 픽셀만큼 «위로» 올려 그린다(셀 축소와 짝)')
    ap.add_argument('--kbox', type=int, default=0,
                    help='한글 «셀 높이»(0이면 라틴과 같은 박스 높이). 한글은 베이스라인 아래가 비므로 아래를 잘라 세로 여백을 회수한다')
    ap.add_argument('--pad', type=int, default=1)
    ap.add_argument('--out', default='work/font/kr')
    ap.add_argument('--limit', type=int, default=0, help='시험용: 음절 수 제한')
    ap.add_argument('--only', default='', help='시험용: 이 문자열에 나오는 음절만 굽는다')
    ap.add_argument('--extra', default='',
                    help='KS X 1001 한글 밖의 문자도 굽는다(「」«»—… 등). 이미 있는 코드는 건너뛴다')
    ap.add_argument('--swap-latin', action='store_true',
                    help='시험용: 글리프를 «추가»하지 않고 라틴 확장 칸의 문자코드를 한글로 바꿔치기한다 '
                         '(개수·아틀라스 크기를 원본 그대로 두고 「136개 초과」 변수를 제거)')
    ap.add_argument('--preview', action='store_true')
    a = ap.parse_args()

    fonts = p3dfont.scan(a.p3d)
    hit = [f for f in fonts if f['font']['name'] == a.font]
    if not hit:
        raise SystemExit('⛔ 폰트 %s 가 없다: %s' % (a.font, [f['font']['name'] for f in fonts]))
    f = hit[0]
    old = load_atlas(io.BytesIO(f['png']))
    W, H = old.size
    glyphs = f['glyphs']
    boxH = None
    for g in glyphs:
        h = round((g['v1'] - g['v0']) * H)
        boxH = h if boxH is None else boxH
        if h != boxH:
            raise SystemExit('⛔ 글리프 높이가 일정하지 않다: %d vs %d' % (h, boxH))
    print('폰트 %s · 아틀라스 %dx%d · 박스 높이 %d · 기존 글리프 %d개'
          % (a.font, W, H, boxH, len(glyphs)))

    # 1. 기존 글리프 픽셀 오려두기
    # ★★★ v 는 «아래에서» 잰다(OpenGL 방식). 위에서부터로 읽으면 빈 영역을 오려 온다.
    #     실측: 첫 글리프 v0=0.8438·v1=0.9922, H=128 → 이미지 행 1~20 에 잉크가 있다.
    cells = []
    for g in glyphs:
        x0 = round(g['u0'] * W)
        y0 = H - round(g['v1'] * H)
        w = round((g['u1'] - g['u0']) * W)
        img = old.crop((x0, y0, x0 + w, y0 + boxH)) if w else None
        cells.append(dict(code=g['code'], w=w, lb=g['b0'], rb=g['b1'], adv=g['adv'], img=img))

    # 2. 한글 렌더
    size = a.size or (boxH - 4)
    ttf = ImageFont.truetype(a.ttf, size)
    base = int(round(f['font']['base']))
    syls = ksx1001()
    if a.only:
        want = set(a.only)
        syls = [c for c in syls if c in want]
    if a.limit:
        syls = syls[:a.limit]
    if a.extra:
        # ★ 한글 블록 밖 문자(따옴표·대시·말줄임표 등). 순서를 지키려 중복만 걸러 붙인다.
        seen = set(syls)
        for ch in a.extra:
            if ch not in seen:
                seen.add(ch)
                syls.append(ch)
    have = set(c['code'] for c in cells)
    added = 0

    KBOX = a.kbox or boxH
    if KBOX > boxH:
        raise SystemExit('⛔ --kbox 는 박스 높이 %d 이하여야 한다' % boxH)

    def render(ch):
        bb = ttf.getbbox(ch)
        w = max(1, bb[2])
        img = Image.new('L', (w, boxH), 0)
        ImageDraw.Draw(img).text((0, base - a.kshift), ch, font=ttf, fill=255, anchor='ls')
        if KBOX < boxH:
            # ★ 위쪽을 남기고 «아래»를 자른다 — 한글엔 디센더가 없다.
            #   잘리는 곳에 잉크가 있으면 조판이 어긋나므로 반드시 확인한다.
            tail = img.crop((0, KBOX, w, boxH))
            if tail.getbbox() is not None:
                raise SystemExit('⛔ %r 의 잉크가 셀 높이 %d 아래로 내려간다 — --kbox 를 키울 것'
                                 % (ch, KBOX))
            img = img.crop((0, 0, w, KBOX))
        return w, img

    if a.swap_latin:
        # 라틴 확장 칸(0x7F 초과, 대체글리프 0x7F7F 제외)을 한글로 «덮어쓴다» — 개수 불변
        slots = [c for c in cells if 0x7F < c['code'] < 0x7F7F]
        if len(syls) > len(slots):
            raise SystemExit('⛔ 바꿔칠 칸이 %d개뿐인데 한글 %d자가 필요하다' % (len(slots), len(syls)))
        for slot, ch in zip(slots, syls):
            w, img = render(ch)
            slot.update(code=ord(ch), w=w, lb=0.0, rb=1.0, adv=float(w + 1),
                        img=img, bh=KBOX)
            added += 1
        print('★ 바꿔치기 모드 — 글리프 개수 %d 불변, 라틴 확장 %d칸을 한글로' % (len(cells), added))
    else:
        for ch in syls:
            cp = ord(ch)
            if cp in have:
                continue
            w, img = render(ch)
            cells.append(dict(code=cp, w=w, lb=0.0, rb=1.0, adv=float(w + 1),
                              img=img, bh=KBOX))
            added += 1
    print('한글 %d자 추가 → 총 %d 글리프 (렌더 크기 %d, 베이스라인 %d)'
          % (added, len(cells), size, base))

    # 3. 새 아틀라스에 채우기
    cells.sort(key=lambda c: c['code'])
    NW, NH = a.atlas, (a.atlash or a.atlas)
    x = y = a.pad
    rowh = None                                   # 지금 줄의 높이(셀마다 다를 수 있다)
    pages = [Image.new('L', (NW, NH), 0)]
    # ★ 배치는 «셀 높이»로 묶어서 한다 — 글리프표는 코드순이어야 하지만(이진 탐색),
    #   아틀라스 배치 순서는 자유다. 높이가 섞이면 줄이 바뀔 때마다 세로를 버린다
    #   (라틴 19px 사이에 낀 «·» 15px 하나가 줄 두 개를 날렸다).
    for c in sorted(cells, key=lambda c: (c.get('bh', boxH), c['code'])):
        w = c['w']
        bh = c.get('bh', boxH)
        if rowh is None:
            rowh = bh
        # 줄이 꽉 찼거나, 셀 높이가 바뀌는 지점이면 새 줄
        if x + w + a.pad > NW or bh != rowh:
            x = a.pad
            y += rowh + a.pad
            rowh = bh
        if y + bh + a.pad > NH:                   # 다음 장으로
            if len(pages) >= a.pages:
                raise SystemExit('⛔ %dx%d × %d장 으로는 부족하다 (%d 글리프에서 넘침)'
                                 % (NW, NH, a.pages, len(cells)))
            pages.append(Image.new('L', (NW, NH), 0))
            x = y = a.pad
            rowh = bh
        if c['img'] is not None and w:
            pages[-1].paste(c['img'], (x, y))
        c['x'], c['y'], c['tex'] = x, y, len(pages) - 1
        x += w + a.pad
    used = y + (rowh or boxH) + a.pad
    print('배치 완료 — %dx%d × %d장 (마지막 장 세로 %d px) · 장당 디코드 %d KB · 셀높이 라틴%d/한글%d(위로%d)'
          % (NW, NH, len(pages), used, NW * NH // 2 // 1024, boxH, KBOX, a.kshift))

    # 4. 산출
    os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
    pngs = []
    for i, pg in enumerate(pages):
        png = a.out + '_%s_p%d.png' % (a.font, i)
        save_atlas(pg, png)
        pngs.append(png)
    tab = b''
    for c in cells:
        cbh = c.get('bh', boxH)
        tab += struct.pack('<I4f4fI', c.get('tex', 0),
                           c['x'] / NW, (NH - (c['y'] + cbh)) / NH,
                           (c['x'] + c['w']) / NW, (NH - c['y']) / NH,
                           c['lb'], c['rb'], float(c['w']), c['adv'], c['code'])
    open(a.out + '_%s.glyphs' % a.font, 'wb').write(struct.pack('<I', len(cells)) + tab)
    for png in pngs:
        print('-> %s' % png)
    print('-> %s_%s.glyphs  (%d 글리프 · %d B)' % (a.out, a.font, len(cells), 4 + len(tab)))

    if a.preview:
        for i, pg in enumerate(pages):
            hh = used if i == len(pages) - 1 else NH
            pv = Image.new('RGB', (NW, hh), (24, 24, 32))
            white = Image.new('RGB', (NW, hh), (255, 255, 255))
            pv.paste(white, (0, 0), pg.crop((0, 0, NW, hh)))
            pv.save(a.out + '_%s_p%d_preview.png' % (a.font, i))
            print('-> %s_%s_p%d_preview.png' % (a.out, a.font, i))


if __name__ == '__main__':
    main()
