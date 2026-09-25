# -*- coding: utf-8 -*-
"""로딩 화면 «신문»(288x224)의 구운 글자를 한글로 갈아 끼운다.

  python tools/newskr.py --preview 1        # 1번 신문 미리보기(4배 확대)
  python tools/newskr.py --write 1          # work/news/kr/loading1.png 저장

## 왜 이렇게 하나

신문 헤드라인은 «글자»가 아니라 **그림에 구워진 픽셀**이다(바이블 문자열이 아니다).
그래서 원문을 지우고 한글을 그려 넣어야 한다. 그런데 신문이 비스듬히 놓여 있어
글줄이 «오른쪽으로 내려가게» 기울어 있다 — 그냥 수평으로 쓰면 티가 난다.

## 하는 일

1. **지우기** — 글줄이 놓인 «기울어진 띠»를 종이색으로 덮는다.
   ★ 종이는 균일한 흰색이 아니라 음영이 있다. 그래서 «행마다 밝은 화소(종이)의 값을
     좌우로 1차 맞춤»해서 그 행의 종이색 기울기를 그대로 복원한다. 평평한 흰색으로 칠하면
     네모난 자국이 남는다.
2. **쓰기** — 한글을 4배 해상도로 그린 뒤 폭에 맞춰 눌러(condensed) 기울여 붙인다.
   원본이 저해상도라 LANCZOS 축소가 원본과 비슷한 부드러움을 준다.

## 좌표 규약
`x,y` = 글줄 왼쪽 «위» 모서리. `w,h` = 폭·높이(왼쪽 기준). `slope` = x 한 칸당 내려가는 y.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = 'C:/claude/utils/font/nanum-gothic/NanumGothicBold.ttf'
FONT_ALT = 'C:/claude/utils/font/nanum-gothic/NanumGothicBold.ttf'

# 신문마다 글줄 정의 — 원문 잉크 경계에서 잰 값
NEWS = {
 1: dict(blocks=[
      dict(t='동네 남자, 핫도그 먹기',  x=21,  y=48,  w=224, h=15, slope=0.054, italic=0.17),
      dict(t='대회를 망쳐 놓다',        x=19,  y=64,  w=171, h=15, slope=0.053, italic=0.17),
      dict(t='토하는 바람에 실격',      x=20,  y=84,  w=190, h=12, slope=0.053, italic=0.17),
      dict(t='연구: 게임의 90%는',      x=146, y=131, w=84,  h=11, slope=0.045, italic=0.17),
      dict(t='쉬운 튜토리얼',           x=146, y=143, w=82,  h=11, slope=0.045, italic=0.17),
      dict(t='단계로 시작한다',         x=146, y=155, w=86,  h=11, slope=0.045, italic=0.17)]),
}


def measure(img, b, seek=5, gap=4, clamp=4):
    """원문 잉크에서 그 글줄의 «실제» 좌우 끝과 상하 끝을 잰다.

    ★ 손으로 넣은 좌표를 믿으면 글자가 신문 밖으로 나가거나 옆 단을 침범한다.
      원문이 차지한 범위를 그대로 쓰면 그런 일이 구조적으로 안 생긴다.
    ★ 낱말 사이 빈 열은 gap 까지 이어진 것으로 본다.
    """
    arr = np.array(img.convert('L')).astype(float)
    al = np.array(img.convert('RGBA'))[..., 3]
    ink = (al > 200) & (arr < 118)
    H, W = arr.shape
    cols = {}
    for x in range(max(0, b['x'] - seek), min(W, b['x'] + b['w'] + seek)):
        i = x - b['x']
        top = int(round(b['y'] + b['slope'] * i))
        bot = top + b['h']
        lo, hi = max(0, top - 2), min(H - 1, bot + 2)
        rows = [y for y in range(lo, hi + 1) if ink[y, x]]
        if rows:
            cols[x] = (min(rows), max(rows))
    if not cols:
        return b
    xs = sorted(cols)
    # b['x'] 근처에서 시작해 gap 이하의 빈틈만 건너뛰며 좌우로 넓힌다
    start = min(xs, key=lambda x: abs(x - b['x']))
    L = R = start
    while True:
        nxt = [x for x in xs if L - gap <= x < L]
        if not nxt:
            break
        L = min(nxt)
    while True:
        nxt = [x for x in xs if R < x <= R + gap]
        if not nxt:
            break
        R = max(nxt)
    tops = [cols[x][0] for x in xs if L <= x <= R]
    bots = [cols[x][1] for x in xs if L <= x <= R]
    # ⛔ 신문 가장자리·사진 테두리를 물지 않게 «적어 둔 값 ±clamp» 로 묶는다
    # ⛔ 가로는 «적어 둔 값» 그대로 쓴다. 늘리면 지우는 띠가 옆 단(채움 기사)까지 먹는다.
    L, R = b['x'], b['x'] + b['w']
    o = dict(b)
    # 왼쪽 끝의 잉크 상단을 기준으로 y 를 맞춘다(기울기는 그대로)
    left = [cols[x][0] for x in xs if L <= x <= L + 6]
    o['y'] = min(left) if left else b['y']
    hh = int(round(np.percentile(np.array(bots) - np.array(tops), 90)))
    o['h'] = max(6, min(b['h'], hh + 1))
    return o


def paper_color(img, b, margin=14):
    """그 글줄 둘레의 «종이 화소» 중앙값 = 단색 배경색.

    ★ 이 신문의 종이는 사실상 단색이다(실측: 헤드라인 둘레 236, 측면 기사 226).
      그래서 행마다 음영을 맞추지 말고 «한 가지 색»으로 미는 게 깔끔하다 —
      그래야 글자 자리가 얼룩덜룩해지지 않는다.
    """
    arr = np.array(img.convert('L')).astype(int)
    rgb = np.array(img.convert('RGB')).astype(int)
    al = np.array(img.convert('RGBA'))[..., 3]
    H, W = arr.shape
    x0, x1 = max(0, b['x'] - margin), min(W, b['x'] + b['w'] + margin)
    y0 = max(0, int(b['y'] - margin))
    y1 = min(H, int(b['y'] + b['slope'] * b['w'] + b['h'] + margin))
    m = (al[y0:y1, x0:x1] > 200) & (arr[y0:y1, x0:x1] > 150)
    if m.sum() < 30:
        return (235, 235, 238)
    c = rgb[y0:y1, x0:x1][m]
    return tuple(int(np.median(c[:, k])) for k in range(3))


def erase(img, b, pad=2, look=5, grow=4):
    """글줄 자리를 신문 바탕색(단색)으로 깔끔하게 민다.

    ★ 좌표를 믿지 않는다 — 각 «열»에서 예상 띠 둘레(±look)의 **실제 잉크**를 찾아 덮는다.
      좌표가 조금 어긋나도 원문 획이 안 남는다.
    ⛔ 확장은 띠 밖 grow 화소까지만 — 안 묶으면 위 괘선과 50¢ 까지 먹는다.
    ⛔ 알파가 없는 곳(신문 바깥)은 건드리지 않는다.
    """
    arr = np.array(img.convert('L')).astype(float)
    rgba = np.array(img.convert('RGBA'))
    al = rgba[..., 3]
    H, W = arr.shape
    ink = (al > 200) & (arr < 118)
    col = paper_color(img, b)
    for i in range(-pad, b['w'] + pad + 1):
        x = b['x'] + i
        if not (0 <= x < W):
            continue
        top = int(round(b['y'] + b['slope'] * i))
        bot = top + b['h']
        lo, hi = max(0, top - look), min(H - 1, bot + look)
        rows = [y for y in range(lo, hi + 1) if ink[y, x]]
        if rows:
            lo2 = max(min(rows) - 1, top - grow)
            hi2 = min(max(rows) + 1, bot + grow)
        else:
            lo2, hi2 = top, bot
        for y in range(max(0, lo2), min(H, hi2 + 1)):
            if al[y, x] <= 200:
                continue
            rgba[y, x, :3] = col
    return Image.fromarray(rgba)


def render(b):
    """글줄을 «최종 크기»로 한 번에 그린다 — 두 번 줄이면 글자가 쪼그라든다.

    · 글자 높이 = 원문 잉크 높이 × fill  (한글은 라틴 대문자보다 글자상자를 꽉 채운다)
    · 폭은 자연 비율. 상자보다 넓으면 «가로로만» 눌러 담는다(신문 헤드라인의 condensed 느낌).
    · italic 은 원본 서체가 기울어져 있어서 준다.
    """
    path = FONT if os.path.exists(FONT) else FONT_ALT
    th = max(5, int(round(b['h'] * b.get('fill', 0.86))))
    # 그 높이가 나오는 글꼴 크기를 찾는다
    size = th * 2
    for _ in range(60):
        f = ImageFont.truetype(path, size)
        tmp = Image.new('L', (2400, size * 3), 0)
        ImageDraw.Draw(tmp).text((20, size // 2), b['t'], font=f, fill=255)
        bb = tmp.getbbox()
        if bb and (bb[3] - bb[1]) <= th:
            break
        size -= 1
        if size < 6:
            break
    glyph = tmp.crop(bb)
    if b.get('italic'):
        gw, gh = glyph.size
        sh = b['italic']
        glyph = glyph.transform((gw + int(gh * sh), gh), Image.AFFINE,
                                (1, sh, -sh * gh, 0, 1, 0), Image.BICUBIC)
    gw, gh = glyph.size
    if gw > b['w']:                      # 넘치면 가로로만 눌러 담는다
        glyph = glyph.resize((b['w'], gh), Image.LANCZOS)
    return glyph


def paste_slanted(img, b, glyph):
    """기울기를 주어 붙인다 — 열마다 세로로 밀어 넣는다(shear). 잉크는 검정."""
    rgba = np.array(img.convert('RGBA')).astype(float)
    al = np.array(img.convert('RGBA'))[..., 3]
    gl = np.array(glyph).astype(float) / 255.0
    gh, gw = gl.shape
    off = (b['h'] - gh) / 2.0
    H, W = rgba.shape[:2]
    for i in range(gw):
        x = b['x'] + i
        if not (0 <= x < W):
            continue
        top = b['y'] + b['slope'] * i + off
        for j in range(gh):
            m = gl[j, i]
            if m <= 0.02:
                continue
            y = top + j
            y0 = int(np.floor(y))
            fr = y - y0
            for yy, ww in ((y0, 1 - fr), (y0 + 1, fr)):
                if 0 <= yy < H and ww > 0 and al[yy, x] > 200:
                    rgba[yy, x, :3] = rgba[yy, x, :3] * (1 - m * ww)
    return Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8))


# ── 로딩 화면 «자막» — 신문 그림은 손대지 않고 아래 빈 자리에 한글을 굽는다
#    (바이블에 이미 번역돼 있는 헤드라인을 그대로 쓴다)
CAPTION = {
 1: '동네 남자, 핫도그 먹기 대회 망쳐',
 3: '바트 심슨, 밝은 빛 속으로 사라지다',
}


def caption(n, text=None, y0=200, h=17, margin=6, outline=2):
    """신문 아래 «완전히 빈 행»(실측 y199~223)에 한글 자막을 굽는다.

    ★ 신문 레이아웃을 전혀 안 건드린다 — 지우기도, 기울기 맞추기도 필요 없다.
    ★ 배경이 붉은 화면이라 «흰 글자 + 검은 테두리»로 쓴다.
    """
    img = Image.open('work/news/loading%d.png' % n).convert('RGBA')
    t = text or CAPTION.get(n)
    if not t:
        raise SystemExit('⛔ %d 번 자막 문구가 없다' % n)
    path = FONT if os.path.exists(FONT) else FONT_ALT
    W = img.width - margin * 2
    size = h * 3
    for _ in range(80):
        f = ImageFont.truetype(path, size)
        tmp = Image.new('L', (img.width * 4, size * 3), 0)
        ImageDraw.Draw(tmp).text((10, size // 2), t, font=f, fill=255)
        bb = tmp.getbbox()
        if bb and (bb[3] - bb[1]) <= h and (bb[2] - bb[0]) <= W * 3:
            break
        size -= 1
        if size < 8:
            break
    g = tmp.crop(bb)
    gw, gh = g.size
    tw = min(W, int(round(gw * (h / float(gh)))))
    g = g.resize((tw, h), Image.LANCZOS)
    x0 = (img.width - tw) // 2
    a = np.array(img).astype(float)
    m = np.array(g).astype(float) / 255.0
    # 검은 테두리 먼저
    for dy in range(-outline, outline + 1):
        for dx in range(-outline, outline + 1):
            if dx * dx + dy * dy > outline * outline:
                continue
            for j in range(h):
                yy = y0 + j + dy
                if not (0 <= yy < img.height):
                    continue
                for i in range(tw):
                    xx = x0 + i + dx
                    if 0 <= xx < img.width and m[j, i] > 0.25:
                        a[yy, xx] = (0, 0, 0, 255)
    # 흰 글자
    for j in range(h):
        yy = y0 + j
        for i in range(tw):
            xx = x0 + i
            k = m[j, i]
            if k > 0.02:
                a[yy, xx, :3] = a[yy, xx, :3] * (1 - k) + 255 * k
                a[yy, xx, 3] = max(a[yy, xx, 3], 255 * k)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def build(n, verbose=False):
    src = 'work/news/loading%d.png' % n
    img = Image.open(src).convert('RGBA')
    bs = [measure(img, b) for b in NEWS[n]['blocks']]       # ★ 원문 잉크에서 실측
    if verbose:
        for b0, b1 in zip(NEWS[n]['blocks'], bs):
            print('  %-18s x %3d w %3d y %3d h %2d   (적어 둔 값 x %3d w %3d y %3d h %2d)'
                  % (b1['t'], b1['x'], b1['w'], b1['y'], b1['h'],
                     b0['x'], b0['w'], b0['y'], b0['h']))
    for b in bs:
        img = erase(img, b)
    for b in bs:
        img = paste_slanted(img, b, render(b))
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--preview', type=int)
    ap.add_argument('--write', type=int)
    ap.add_argument('--zoom', type=int, default=4)
    ap.add_argument('--out', default='')
    ap.add_argument('--caption', type=int, help='신문 아래 빈 자리에 한글 자막을 굽는다')
    ap.add_argument('--text', default='')
    a = ap.parse_args()
    if a.caption:
        img = caption(a.caption, a.text or None)
        os.makedirs('work/news/kr', exist_ok=True)
        p = a.out or 'work/news/kr/loading%d.png' % a.caption
        img.save(p)
        img.convert('RGB').resize((img.width * 4, img.height * 4), Image.LANCZOS).save(
            p.replace('.png', '_4배.png'))
        print('-> %s (+ _4배 미리보기)' % p)
        return
    n = a.preview or a.write
    if not n:
        raise SystemExit('⛔ --preview N 또는 --write N')
    img = build(n, verbose=True)
    if a.write:
        os.makedirs('work/news/kr', exist_ok=True)
        p = a.out or 'work/news/kr/loading%d.png' % n
        img.save(p)
        print('-> %s' % p)
    else:
        p = a.out or ('C:/Users/kbwor/AppData/Local/Temp/claude/preview%d.png' % n)
        img.convert('RGB').resize((img.width * a.zoom, img.height * a.zoom),
                                  Image.LANCZOS).save(p)
        print('-> %s (%dx)' % (p, a.zoom))


if __name__ == '__main__':
    main()
