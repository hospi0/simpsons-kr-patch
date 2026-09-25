# -*- coding: utf-8 -*-
"""지운 신문에 한글을 «획만» 얹는다 (네모 배경 없이).

  python tools/newsdraw.py work/news/erased/loading1.png out.png --n 1
  python tools/newsdraw.py ... --box      # 맞춘 상자를 빨강으로 표시(진단)

## ① 획만 굽기

글자를 RGBA 레이어에 그려 `alpha_composite` 한다. 글리프가 덮은 화소만 바뀌고 가장자리는
반투명이라 밑의 신문 바탕과 섞인다 — **네모 테두리가 생길 여지가 없다.**
(전에 보이던 네모는 «쓸 때»가 아니라 «지울 때» 생긴 것이다 — `newsedit.py` 참고)

## ② 기울기는 «두 가지»다 (실측 loading1)
```
RUINS 의 「I」 세로획  위→아래로 2.5px 왼쪽  기울기 0.167  ← 눈에 보이는 총 기울기
신문 자체 회전         헤드라인 글자 중심들   기울기 0.075 (4.3°)
⇒ 글꼴 고유 이탤릭 = 0.167 − 0.075 = 0.092 (5.3°)
```
⛔ 총 기울기를 그냥 이탤릭으로 주면 신문이 기운 만큼 또 기울어 두 배가 된다.
   ①이탤릭 0.092 로 밀고 → ②줄 전체를 4.3° 돌린다.

## ③ 자리·크기는 «원본 영문이 차지하던 상자»로 정한다

⛔ 손으로 좌표를 찍었더니 헤드라인이 「OCTOBER 25」와 소제목을 덮어 버렸다.
✅ 원본의 잉크 덩어리를 «줄»로 묶어 그 줄의 상자를 재고, 한글을 그 안에 꽉 맞춘다.
   상자에는 기울기가 이미 반영돼 있고, 한글 레이어도 기울인 뒤 재므로 서로 맞는다.
"""
import argparse
import math
import statistics

import numpy as np

from PIL import Image, ImageDraw, ImageFont

import newsedit

TTF = r'C:/claude/utils/font/nanum-gothic/NanumGothicBold.ttf'
# 작은 글자(토막기사·사진 설명)는 «픽셀 글꼴»을 쓴다.
#   ⛔ 9px 에서 NanumGothicBold 는 획 사이 틈이 1px 도 안 남아 무조건 뭉갠다.
#      알파 감마를 올리면 더 뭉개지고, 낮추면 회색으로 흐려진다 — 굵기 문제라 감마로는 못 푼다.
#   ✅ Galmuri9 는 9px 용으로 만들어진 글꼴이라 그 크기에서 획이 또렷하다. (사용자 선택)
SMALL_TTF = r'C:/claude/utils/font/Galmuri-v2.40.3/Galmuri9.ttf'
SMALL_H = 12               # 줄 높이가 이 이하면 작은 글자로 본다
REG_TTF = r'C:/claude/utils/font/nanum-gothic/NanumGothic.ttf'
# 픽셀 글꼴은 «제 크기(9px)»를 벗어나면 거칠어진다. 그런 자리는 매끈한 Regular 로 바꾼다.
SMOOTH = {
    2: {'side'},
    5: {'head'},
    6: {'sub'},
    7: {'head', 'sub'},
}
BOLD_TTF = TTF
BIG = 160                   # 이 크기로 그려서 줄인다 (계단 방지)
ITALIC = 0.092
TILT = math.degrees(math.atan(0.075))
INK = (0, 0, 0)
LINEGAP = 5                 # 덩어리 윗변이 이보다 더 벌어지면 «다른 줄»

# 줄마다 «손으로» 미세 조정하는 세로 이동 (양수 = 아래로). 자리를 다시 재는 것보다 이게 빠르다.
NUDGE = {
    1: {'side': [0, 2, 0]},
}

# 블록을 «줄 폭 안에서 가운데»로 놓는다 (기본은 왼쪽 맞춤)
CENTER = {
    4: {'head', 'sub'},
}

# 줄마다 «따로» 크기를 잡는 블록 — 큰 제목 한 줄 + 작은 소제목 한 줄처럼 성격이 다를 때.
#   (기본은 블록 안에서 한 크기로 통일한다 — 토막기사가 줄마다 들쭉날쭉하면 안 되니까)
PER_LINE = {
    5: {'head'},
    7: {'head'},
}

# 블록의 «글자 높이»를 손으로 정한다 (없으면 원본 영문 줄 높이에 맞춘다)
FORCE_H = {
    1: {'side': 12},
    2: {'side': 12},
    3: {'side': 12},
}

TEXT = {
    1: {'head': ['동네 사람, 핫도그 먹기', '대회를 망쳐놓다'],
        'sub':  ['토하는 바람에 실격'],
        'side': ['연구: 비디오 게임', '90%는 쉬운', '튜토리얼로 시작한다']},
    2: {'head': ['말단 직원이 백만장자를', '괴롭히자 사냥개 풀려나'],
        'side': ['본스톰 2 오늘 발매', '사상 최대 무단결석 예상']},
    3: {'head': ['바트 심슨, 밝은 빛', '속으로 사라지다'],
        'side': ['가족, 빛에 호소', '우리 아들을 돌려', '달라!']},
    4: {'head': ['밭에서 발견된 수수께끼 문양'],
        'sub':  ['멍한 촌뜨기', '머리만 긁적'],
        'side': ['실종 소년 무사 발견', '기억 지워지고 바지 축축']},
    7: {'head': ['외계인 스프링필드 침공!', '사악한 콜라가 죽은 자를 무덤에서 깨우다'],
        'sub':  ['동네 뇌', '도매상,', '매출 급증', '보고']},
    6: {'head': ['크러스티, 오늘 스퀴드포트에서', '콜라 축하 행사'],
        'sub':  ['크러스티', '친자', '소송 맞서겠다']},
    5: {'head': ['짜릿한 새 콜라 인기몰이', '「콜라는 훌륭하다」 콜라 연구소 발표'],
        'quote': ['「콜라는 훌륭하다」 콜라', '연구소 발표'],
        'side': ['성가신 주부, 콜라가', '「사악하다」 주장'],
        'foot': ['사진 제공: 남편']},
}


def lines_of(im, block, n=1):
    """원본에서 그 블록의 잉크를 «줄»로 묶어 각 줄의 상자를 돌려준다."""
    # ⛔ 창을 블록 범위로 자르면 남의 글자가 «잘린 채» 섞여 든다 — newsedit.components 참고
    comps = newsedit.pick(newsedit.components(im), newsedit.blocks(n)[block])
    # ⛔ 줄 묶기는 두 번 실패했다 —
    #   ①«윗변 간격» : 「90%」의 점 같은 작은 조각이 두 줄 사이를 이어 3줄이 2줄로 붙었다
    #   ②«세로 범위 겹침» : 신문이 기울어 헤드라인 1줄(y44~77)과 2줄(y66~90)이 겹쳐 1줄이 됐다
    # ✅ 기울기를 «먼저 보정»한 y 로 묶는다.  y' = y − 0.075·x
    #      LOCAL(26,46)→44.1  DOG(206,60)→44.6   EATING(22,66)→64.4  TEST(149,75)→63.8
    TIL = 0.075
    def key(c):
        return min(b - TIL * a for a, b in c)
    comps.sort(key=key)
    rows, cur, last = [], [], None
    for c in comps:
        k = key(c)
        if last is not None and k - last > LINEGAP:
            rows.append(cur); cur = []
        cur.append(c); last = k
    if cur:
        rows.append(cur)
    # ⛔ 잔조각(마침표·점) 하나가 «따로 한 줄»로 잡혀 줄 수가 안 맞는 일이 있다(신문2 에서 실제로).
    #    작은 줄은 y' 가 가장 가까운 줄에 붙인다.
    def size(r):
        return sum(len(c) for c in r)

    def yy(r):
        return min(key(c) for c in r)

    while len(rows) > 1:
        small = min(rows, key=size)
        if size(small) >= 30:
            break
        rest = [r for r in rows if r is not small]
        near = min(rest, key=lambda r: abs(yy(r) - yy(small)))
        near.extend(small)
        rows = rest
    rows.sort(key=yy)
    return [metrics(r) for r in rows]


TIL = 0.075                 # 신문 기울기 (세로 전단으로 준다)


def metrics(row):
    """한 줄의 «기울기 보정» 치수 : (왼쪽x, 그 자리의 윗변y, 글자높이, 쓸 수 있는 폭)"""
    pts = [(a, b) for c in row for a, b in c]
    yy = [b - TIL * a for a, b in pts]
    x0, x1 = min(a for a, b in pts), max(a for a, b in pts)
    h = round(max(yy) - min(yy)) + 1
    return x0, round(min(yy) + TIL * x0), h, x1 - x0 + 1


def shape(text):
    """이탤릭까지 마친 «자른» 레이어 (크기 조정 전)."""
    f = ImageFont.truetype(TTF, BIG)
    bx0, by0, bx1, by1 = f.getbbox(text)
    pad = int(BIG * (1 + ITALIC)) + 8
    lay = Image.new('RGBA', (bx1 - bx0 + pad * 2, by1 - by0 + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(lay).text((pad - bx0, pad - by0), text, font=f, fill=INK + (255,))
    H = lay.size[1]
    lay = lay.transform(lay.size, Image.AFFINE,
                        (1, ITALIC, -ITALIC * H, 0, 1, 0), resample=Image.BICUBIC)
    return lay.crop(lay.getbbox())


def block_scale(texts, rows, force=None):
    """블록의 «글자 크기 하나»를 정한다.

    ⛔ 줄마다 «그 줄 영문의 잉크 높이»에 맞추면 크기가 들쭉날쭉해진다 —
       토막기사가 9·13·10 이 돼 가운데 줄만 커 보였다(「90%」의 % 때문).
    ✅ 기준 글자 「가」의 높이로 한 배율을 정하고, 폭이 넘치는 줄이 있으면 그만큼만 줄인다.
       모든 줄을 같은 BIG 로 그리므로 «같은 배율 = 같은 글자 크기»다.
    """
    # ⛔ 기준 글자 「가」 높이로만 배율을 잡았더니 «실제 글줄»이 원본 줄 높이를 넘어
    #    신문3 사진 설명 세 줄이 서로 겹쳤다(글줄에 「빛」·「!」 처럼 더 높은 글자가 섞인다).
    # ✅ 줄마다 «그 줄이 자기 원본 높이·폭에 들어가는 배율»을 구해 그중 가장 작은 것을 쓴다.
    #    모든 줄을 같은 BIG 로 그리므로 같은 배율 = 같은 글자 크기다.
    # ⛔ 원본 줄 높이만 보면 «다음 줄까지의 간격»보다 커질 수 있다 —
    #    신문3 사진 설명은 간격이 8~10px 인데 글줄이 10px 이라 빽빽하게 붙었다.
    # ✅ 높이 한도 = min(그 줄 원본 높이, 다음 줄까지 간격 − 1)
    tops = [ytop - TIL * x0 for x0, ytop, h, wmax in rows]
    ss = []
    for i, (t, (x0, ytop, h, wmax)) in enumerate(zip(texts, rows)):
        lim = force if force else h
        if not force and i + 1 < len(tops):
            lim = min(lim, tops[i + 1] - tops[i] - 1)
        g = shape(t)
        ss.append(min(lim / g.size[1], wmax / g.size[0]))
    return min(ss)


def sharpen(lay, gamma):
    """작은 글자는 크게 그려 줄이면서 획이 «반투명»으로 흩어져 흐려 보인다.
       알파를 감마로 밀어 올려(0<γ<1) 획을 진하게 만든다. 모양은 그대로다."""
    a = np.asarray(lay, dtype=np.float64).copy()
    al = a[:, :, 3] / 255.0
    a[:, :, 3] = np.clip(al ** gamma, 0, 1) * 255.0
    return Image.fromarray(a.astype(np.uint8), 'RGBA')


def render(text, scale):
    """이탤릭 → 크기 맞춤 → 세로 전단. 왼위 모서리가 그대로 앵커가 된다.

    ⛔ 회전(rotate)으로 기울이면 확장된 상자의 «어느 모서리»가 원래 왼위였는지 알기 어려워
       자리를 잡을 수 없다 — 실제로 두 줄이 서로 파고들었다.
    ✅ 4.3° 는 작아서 «세로 전단»(y += 0.075x)과 눈으로 구별되지 않고,
       x=0 에서 y 가 안 움직이므로 왼쪽 끝이 앵커로 그대로 남는다.
    """
    lay = shape(text)
    w2 = max(1, round(lay.size[0] * scale)); h2 = max(1, round(lay.size[1] * scale))
    lay = lay.resize((w2, h2), Image.LANCZOS)
    nh = h2 + int(TIL * w2) + 2
    out = lay.transform((w2, nh), Image.AFFINE, (1, 0, 0, -TIL, 1, 0),
                        resample=Image.BICUBIC)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('dst')
    ap.add_argument('--orig', default='work/news/loading1.png',
                    help='상자를 재는 «원본»(영문이 살아 있는 그림)')
    ap.add_argument('--n', type=int, default=1)
    ap.add_argument('--blocks', default='head,side')
    ap.add_argument('--box', action='store_true')
    ap.add_argument('--size', type=int, default=0, help='글자 높이를 직접 지정(px)')
    ap.add_argument('--ttf', default='')
    ap.add_argument('--gamma', type=float, default=0.0,
                    help='알파 감마 (작을수록 진하다). 0 = 글자 크기 보고 자동')
    a = ap.parse_args()

    orig = Image.open(a.orig).convert('RGB')
    im = Image.open(a.src).convert('RGBA')
    for block in a.blocks.split(','):
        boxes = lines_of(orig, block, a.n)
        texts = TEXT[a.n][block]
        if len(boxes) != len(texts):
            raise SystemExit('⛔ %s : 원본 %d줄인데 한글은 %d줄' % (block, len(boxes), len(texts)))
        force = a.size or FORCE_H.get(a.n, {}).get(block)
        per = block in PER_LINE.get(a.n, ())
        if not per:
            gh = force or min(h for x0, ytop, h, wmax in boxes)
            small_ttf = REG_TTF if block in SMOOTH.get(a.n, ()) else SMALL_TTF
            globals()['TTF'] = a.ttf or (small_ttf if gh <= SMALL_H else BOLD_TTF)
            sc = block_scale(texts, boxes, force)
            print('  [%s] %s' % (block, TTF.rsplit('/', 1)[-1]))
        ux0 = min(x0 for x0, ytop, h, wmax in boxes)
        ux1 = max(x0 + wmax for x0, ytop, h, wmax in boxes)
        nud = NUDGE.get(a.n, {}).get(block, [0] * len(texts))
        for row, t, dy in zip(boxes, texts, nud):
            x0, ytop, h, wmax = row
            if per:
                # 줄 하나만 두고 크기·글꼴을 따로 정한다
                globals()['TTF'] = a.ttf or BOLD_TTF
                sc = block_scale([t], [row], force)
                gh = round(shape(t).size[1] * sc)
                if gh <= SMALL_H:
                    small_ttf = REG_TTF if block in SMOOTH.get(a.n, ()) else SMALL_TTF
                    globals()['TTF'] = a.ttf or small_ttf
                    sc = block_scale([t], [row], force)
                print('  [%s] %s' % (block, TTF.rsplit('/', 1)[-1]))
            g = render(t, sc)
            # 글줄이 원본 줄 높이보다 작으면 «줄 안에서 세로 가운데»에 놓는다
            gh = g.size[1] - int(TIL * g.size[0]) - 2
            ox, oy = x0, ytop + dy + max(0, (h - gh) // 2)
            if block in CENTER.get(a.n, ()):
                # ★ «줄마다» 가운데를 잡으면 줄 폭이 다를 때 중심이 어긋나 계단처럼 보인다
                #   (신문4 소제목은 원본 영문이 x21 과 x43 으로 어긋나 있었다).
                #   블록 전체가 차지한 가로 범위의 «한 중심»에 맞춘다.
                ox = ux0 + (ux1 - ux0 - g.size[0]) // 2
                oy += round(TIL * (ox - x0))          # 옮긴 만큼 기울기를 따라 내린다
            im.alpha_composite(g, (ox, oy))
            print('  %-5s 왼위(%3d,%3d)%s 폭한도%3d ← %-20s %dx%d'
                  % (block, ox, oy, (' %+d' % dy) if dy else '    ',
                     wmax, t, g.size[0], g.size[1]))
            if a.box:
                ImageDraw.Draw(im).rectangle(
                    [x0, ytop, x0 + wmax, ytop + h + int(TIL * wmax)], outline=(255, 0, 0, 255))
    im.convert('RGB').save(a.dst)
    print('  ✅ %s' % a.dst)


if __name__ == '__main__':
    main()
