# -*- coding: utf-8 -*-
"""로딩 화면 신문에서 «글자 덩어리»만 골라 지운다.

  python tools/newsedit.py work/news/loading1.png out.png --blocks head,side
  python tools/newsedit.py ... --show          # 무엇을 지울지 표시만 (빨강)

## 왜 이렇게 하나 (2026-09-11)

전에는 「글자 자리를 네모로 덮고 다시 쓰기」를 했다가 **네모 자국**이 드러났다.
원인은 방법이 아니라 **바탕이 단색이 아니라서**다 — 실측:
```
신문 위쪽 종이   밝기 200~254 · 표준편차 15.9 · 가로 이웃 화소 차 평균 3.1
```
그래서 네모로 칠하면 그 자리만 평평해져 눈에 띈다.

★ 대신 **잉크 화소만** 지운다. 글자 사이 종이는 원본 그대로 남으므로 네모가 생길 수 없다.
  글자는 8-이웃 연결 덩어리로 찾는다 — 덩어리 단위라 **옆 칸 본문을 건드릴 위험이 없다**
  (띠(band)로 자르면 기운 신문 때문에 오른쪽 본문을 물어뜯는다).

## 신문은 기울어 있다 (실측 loading1)
```
가로줄 두 개     (77,36)→(250,47)   (27,42)→(247,58)      기울기 ≈ 0.068 (3.9°)
헤드라인 글자 중심 (35,56) (80,59.5) (206,68.5)             기울기 ≈ 0.075
```
⇒ 띠로 자르려면 기울기를 따라가야 하지만, 덩어리 방식은 그럴 필요가 없다.
"""
import argparse
from collections import deque

import numpy as np

from PIL import Image

INK = 150          # 이 밝기보다 어두우면 «잉크»
# ⛔ 번짐 문턱을 높게(238) 잡고 반경 2 로 훑었더니 «종이까지» 먹어 빨간 덩어리가 됐다.
#    이 신문은 종이 밝기가 200까지 내려간다 — 문턱이 종이보다 높으면 안 된다.
#    실측(헤드라인 잉크 둘레) : 거리 1 에 번짐이 몰려 있고, 거리 2 부터는 대부분 깨끗한 종이다.
#      거리1  140~220대 ≈ 1,400화소(번짐)  240대 1,302화소(종이)
#      거리2  추가분은 대부분 220~254 (종이)
HALO = 225         # 지우개 둘레에서 이 밝기보다 어두우면 «글자 번짐»으로 보고 같이 지운다
GROW = 1           # 번짐을 찾는 반경
NEAR = 3           # 작은 조각을 «고른 글자에 붙었다»고 볼 거리

# 블록 = (이름, y0, y1, x0, x1, 최소높이, 최소화소) — 덩어리의 «진짜 왼위 모서리»가 이 안에 들면 그 블록
#   ⛔ 신문마다 짜임새가 다르다. 1번은 헤드라인·소제목·오른쪽아래 토막기사,
#      2번은 헤드라인·가운데왼쪽 토막기사 — 그래서 번호별로 따로 둔다.
BLOCKS_BY_N = {
    1: {
        'head': (42, 65, 18, 250, 14, 30),    # LOCAL MAN RUINS HOT DOG / EATING CONTEST
        'sub':  (81, 84, 18, 155,  8, 40),    # DISQUALIFIED FOR VOMITING
        'side': (117, 141, 138, 240, 7, 30),  # STUDY: 90% OF VIDEO GAMES …
    },
    2: {
        'head': (41, 64, 18, 250, 13, 30),    # LOW LEVEL EMPLOYEE HARASSES / MILLIONAIRE …
        'side': (106, 121, 10, 160, 8, 20),   # BONESTORM 2 OUT TODAY - RECORD / TRUANCY …
    },
    3: {
        'head': (41, 64, 18, 250, 15, 30),    # BART SIMPSON DISAPPEARS / IN BRIGHT LIGHT
        'side': (133, 158, 132, 240, 8, 25),  # FAMILY PLEADS TO LIGHT: "GIVE BACK OUR BOY!"
    },
    4: {
        'head': (41, 46, 18, 250, 11, 40),    # MYSTERIOUS SHAPE FOUND IN FIELD  (한 줄)
        'sub':  (55, 70, 18, 105,  9, 100),   # CONFUSED YOKEL / SCRATCHES HEAD
        'side': (94, 110, 88, 240,  9, 60),   # MISSING BOY FOUND SAFE - MIND / ERASED …
    },
    5: {                                      # ⛔ 큰 제목 2줄과 작은 인용문 1줄이 y' 로 1px 차이다
        'head': (42, 66, 18, 250, 15, 50, 25),    # EXCITING NEW COLA GAINS / POPULARITY
        'quote': (58, 74, 120, 245, 8, 40, 14),   # "COLA IS GREAT!" SAYS COLA / INSTITUTE
        'side': (90, 104, 120, 245, 9, 100, 20),  # ANNOYING HOUSEWIFE / CLAIMS COLA "EVIL"
        'foot': (157, 163, 118, 240, 8, 100, 15),  # PHOTO SUPPLIED BY HUSBAND
    },
    6: {                                      # ⛔ 크러스티 사진(높이 89)은 높이 상한으로 걸러 낸다
        'head': (42, 64, 18, 250, 14, 50, 25),    # KRUSTY AT SQUIDPORT TODAY / FOR COLA-BRATION
        'sub':  (119, 144, 78, 160, 9, 50, 20),   # KRUSTY VOWS / TO FIGHT / PATERNITY SUIT
    },
    7: {                                      # ⛔ 외계인 사진(높이 77)은 높이 상한으로 걸러 낸다
        'head': (42, 64, 18, 250, 9, 50, 25),     # ALIENS INVADE SPRINGFIELD! / EVIL COLA …
        'sub':  (120, 158, 58, 135, 8, 100, 20),  # LOCAL BRAIN / WHOLESALER / REPORTS SURGE / IN …
    },
}
BLOCKS = BLOCKS_BY_N[1]                        # 옛 이름 (기본 1번)


def blocks(n):
    return BLOCKS_BY_N[n]


def lum(p):
    return 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]


def components(im, y0=0, y1=None, x0=0, x1=None):
    """⛔⛔ 창을 «블록 범위»로 잘라서 부르면 안 된다 — 위 경계를 가로지르는 덩어리
       (가로줄·OCTOBER 25 밑동)가 잘려 y0 가 경계값이 되고, 선택 조건을 그대로 통과한다.
       2026-09-11 실측으로 가로줄 41/43·OCTOBER 25 405/590 화소가 지워지고 있었다.
       ⇒ «그림 전체»에서 한 번 구해 «진짜 테두리»로 고른다."""
    px = im.load()
    if y1 is None:
        y1 = im.size[1]
    if x1 is None:
        x1 = im.size[0]
    ink = {(x, y) for y in range(y0, y1) for x in range(x0, x1) if lum(px[x, y]) < INK}
    seen, out = set(), []
    for p in sorted(ink):
        if p in seen:
            continue
        q = deque([p]); seen.add(p); cur = []
        while q:
            x, y = q.popleft(); cur.append((x, y))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    n = (x + dx, y + dy)
                    if n in ink and n not in seen:
                        seen.add(n); q.append(n)
        out.append(cur)
    return out


TIL = 0.075        # 신문 기울기 — 블록 경계는 «기울기 보정» y 로 잰다


def pick(comps, spec):
    """⛔ 생 y 로 블록을 가르면 안 된다 — 신문이 기울어 «헤드라인 오른쪽 끝»의 y 가
       «아래 기사 왼쪽 끝»의 y 와 겹친다(신문4 에서 둘 다 y0=60 이었다).
       ✅ y' = y − 0.075·x 로 보면 줄마다 깨끗이 갈린다."""
    by0, by1, bx0, bx1, minh, minn = spec[:6]
    maxh = spec[6] if len(spec) > 6 else 999      # 큰 제목과 작은 인용문이 y' 1px 차이일 때 쓴다
    got = []
    for c in comps:
        xs = [a for a, b in c]; ys = [b for a, b in c]
        h = max(ys) - min(ys) + 1
        if len(c) < minn or h < minh or h > maxh:
            continue
        k = min(b - TIL * a for a, b in c)
        if by0 <= k <= by1 and bx0 <= min(xs) and max(xs) <= bx1:
            got.append(c)
    if not got:
        return got
    # ★ 「90%」의 점처럼 «너무 작아» 기준에 안 걸리는 조각이 남는다.
    # ⛔ 처음엔 «고른 글자들의 테두리 안»이면 집게 했는데, 헤드라인은 테두리가 x22~247·y44~90 로
    #    넓어서 「50c」까지 삼켰다(실제로 지워졌다). ⇒ «고른 글자에 바짝 붙은 것»만 집는다.
    near = set()
    for c in got:
        for x, y in c:
            for dx in range(-NEAR, NEAR + 1):
                for dy in range(-NEAR, NEAR + 1):
                    near.add((x + dx, y + dy))
    have = {id(c) for c in got}
    for c in comps:
        if id(c) in have or len(c) > minn:
            continue
        if any(p in near for p in c):
            got.append(c)
    return got


def smart(im, sel, a, keep=frozenset()):
    """번짐 테두리까지 지우되, 어두운 종이를 잘못 먹지 않게 «문턱만» 그 자리에 맞춘다.

    ⛔ 실패한 두 가지 (2026-09-11) —
      ① 고정 문턱 238 + 반경 2 : 종이가 228~236 인 오른쪽까지 통째로 먹어 «빨간 덩어리»가 됐다.
      ② 지운 자리를 «둘레 종이 중앙값»으로 채우기 : 굵은 글자 속은 표본이 멀리서 잡혀
         오히려 더 어둡게 칠해졌다 — 글자가 더 선명해졌다.
    ✅ 되는 방법 : 채우는 «색»은 사용자가 찍어 준 종이색 하나로 두고,
       «지울지 말지»만 그 자리 종이 밝기(둘레 밝은 쪽 90% 지점)로 판단한다.
    ⛔ 그래도 반경 3 이면 위쪽 「OCTOBER 25」 밑동과 가로줄을 먹는다.
    ✅ 그래서 «안 고른 잉크 덩어리»(keep)는 통째로 보호한다 — 반경을 넉넉히 줘도 안전하다.
    """
    px = im.load()
    W, H = im.size
    G = a.grow
    region = set()
    for x, y in sel:
        for dx in range(-G, G + 1):
            for dy in range(-G, G + 1):
                q = (x + dx, y + dy)
                if 0 <= q[0] < W and 0 <= q[1] < H and q not in keep:
                    region.add(q)
    R = a.local or 10
    col = tuple(int(v) for v in a.color.split(','))
    out = set()
    for (x, y) in region:
        if (x, y) in sel:
            out.add((x, y)); continue                 # 잉크는 무조건
        near = []
        for dx in range(-R, R + 1):
            for dy in range(-R, R + 1):
                q = (x + dx, y + dy)
                if q in region or not (0 <= q[0] < W and 0 <= q[1] < H):
                    continue
                near.append(lum(px[q]))
        if not near:
            out.add((x, y)); continue
        near.sort()
        paper = near[int(len(near) * 0.9) - 1]        # 둘레의 «밝은 쪽» = 진짜 종이
        if lum(px[(x, y)]) < paper - a.margin:
            out.add((x, y))
    print('  구역 %d 화소 중 %d 화소를 지운다' % (len(region), len(out)))
    if a.show:
        for p in out:
            px[p] = (255, 0, 0)
        return set()
    if not a.diffuse:
        for p in out:
            px[p] = col
        return set()
    field = paper_field(im, out | region, keep)
    for (x, y) in out:
        px[(x, y)] = tuple(int(v) for v in field[y, x])
    return set()


def paper_field(im, holes, keep):
    """⛔⛔ 써 보니 «단색»보다 나빴다 (2026-09-11, 실제 크기에서 확인). 기본값 아님.
       남의 잉크(keep)까지 «미지»로 잡는 바람에 채움값이 주변 종이보다 밝아져
       글자가 오히려 또렷한 «밝은 유령»으로 떠올랐다.
       사용자가 찍어 준 종이색 하나로 칠하는 쪽이 눈에 덜 띈다.

    «종이 밝기 지도»를 만들어 구멍을 메운다.

    ⛔ 단색 (240,240,242) 로 채우면 종이가 228 인 오른쪽에서는 글자가 «더 밝게» 떠 보인다
       (신문 종이는 200~254 로 넓게 변한다).
    ⛔ 「둘레 종이의 중앙값」을 화소마다 따로 구하는 방법은 굵은 글자 속에서 표본이 멀리서
       잡혀 오히려 더 어둡게 칠해졌다 — 2026-09-11 실패.
    ✅ «정규화 합성곱»: 종이인 화소만 남기고 «값의 흐림 ÷ 가중치의 흐림»을 여러 번 반복하면
       구멍 안으로 주변 밝기가 매끄럽게 번져 들어온다. 국소 그라데이션이 그대로 이어진다.
    """
    a = np.asarray(im, dtype=np.float64)
    H, W, _ = a.shape
    unknown = np.zeros((H, W), dtype=bool)
    for x, y in holes:
        unknown[y, x] = True
    for x, y in keep:                      # 남의 잉크도 «종이가 아니다» — 번져 들어오면 안 된다
        if 0 <= x < W and 0 <= y < H:
            unknown[y, x] = True
    v = a.copy()
    v[unknown] = a[~unknown].mean(axis=0)  # 출발값 = 아는 종이의 평균 (수렴이 빠르다)
    # ⛔ 가중치를 회마다 갱신하는 «정규화 합성곱»으로 짰다가, 둘째 회부터 구멍이 다시
    #    «원본 화소»로 리셋돼 **아무것도 안 지워졌다**(2026-09-11).
    # ✅ 아는 화소는 고정하고 구멍만 흐림 값으로 갈아 끼우는 «확산»이면 그럴 일이 없다.
    for _ in range(300):
        b = blur(v)
        v[unknown] = b[unknown]
    return np.clip(v, 0, 255)


def blur(z):
    """[1,2,1]/4 를 가로·세로로 한 번씩 — PIL 은 float 그림을 못 흐린다."""
    def one(t, ax):
        lo = np.roll(t, 1, axis=ax); hi = np.roll(t, -1, axis=ax)
        if ax == 0:
            lo[0] = t[0]; hi[-1] = t[-1]
        else:
            lo[:, 0] = t[:, 0]; hi[:, -1] = t[:, -1]
        return (lo + 2.0 * t + hi) / 4.0
    return one(one(z, 0), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--blocks', default='head,side')
    ap.add_argument('--n', type=int, default=1, help='몇 번 신문인가')
    ap.add_argument('--color', default='240,240,242',
                    help='지울 색 (사용자가 신문에서 찍어 준 종이색)')
    ap.add_argument('--show', action='store_true', help='지우는 대신 빨강으로 표시')
    ap.add_argument('--halo', type=int, default=HALO)
    ap.add_argument('--grow', type=int, default=GROW)
    ap.add_argument('--smart', action='store_true',
                    help='문턱을 «그 자리 종이 밝기»로 잡는다 (권장)')
    ap.add_argument('--margin', type=int, default=5)
    ap.add_argument('--diffuse', action='store_true',
                    help='⛔ 권장하지 않음 — 확산으로 메운다. 실측상 «단색»보다 유령이 더 진하다')
    ap.add_argument('--local', type=int, default=0, metavar='R',
                    help='단색 대신 «반경 R 안의 깨끗한 종이 중앙값»으로 채운다 (유령 방지)')
    a = ap.parse_args()

    im = Image.open(a.src).convert('RGB')
    px = im.load()
    W, H = im.size
    col = tuple(int(v) for v in a.color.split(','))

    allc = components(im)                     # ★ 전체에서 한 번만
    mask = set()
    for name in a.blocks.split(','):
        spec = blocks(a.n)[name]
        got = pick(allc, spec)
        n = sum(len(c) for c in got)
        print('  %-5s 덩어리 %2d개 · 잉크 %d 화소' % (name, len(got), n))
        for c in got:
            mask |= set(c)

    # 글자 번짐(안티에일리어싱)까지 — 지운 자리 둘레에서 «어두운» 화소만 더 지운다
    halo = set()
    for x, y in mask:
        for dx in range(-a.grow, a.grow + 1):
            for dy in range(-a.grow, a.grow + 1):
                q = (x + dx, y + dy)
                if 0 <= q[0] < W and 0 <= q[1] < H and q not in mask and lum(px[q]) < a.halo:
                    halo.add(q)
    print('  잉크 %d + 번짐 %d = %d 화소' % (len(mask), len(halo), len(mask) + len(halo)))

    gone = mask | halo
    if a.smart:
        # ★ 안 고른 잉크 덩어리 = 지키는 것 (가로줄·DAILY·OCTOBER 25·50c·소제목·본문·만화)
        keep = set()
        for c in allc:
            if not (set(c) & mask):
                keep |= set(c)
        grown = set()
        for x, y in keep:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    grown.add((x + dx, y + dy))
        print('  지키는 잉크 %d 화소 (+둘레 1)' % len(keep))
        gone = smart(im, mask, a, frozenset(grown))
    if a.show:
        for p in gone:
            px[p] = (255, 0, 0)
    elif a.local:
        # ★ 단색으로 채우면 그 자리가 주변 종이와 밝기가 달라 «글자 유령»이 남는다.
        #   지운 화소마다 «반경 R 안의 안 지운 종이»의 중앙값을 쓰면 밝기가 이어져 유령이 없다.
        R = a.local
        src = {}
        for (x, y) in gone:
            near = []
            for dx in range(-R, R + 1):
                for dy in range(-R, R + 1):
                    q = (x + dx, y + dy)
                    if q in gone or not (0 <= q[0] < W and 0 <= q[1] < H):
                        continue
                    if lum(px[q]) >= a.halo:                 # 깨끗한 종이만
                        near.append(px[q])
            if near:
                near.sort(key=lum)
                src[(x, y)] = near[len(near) // 2]
        miss = [p for p in gone if p not in src]
        if miss:
            print('  ⚠️ 둘레에 깨끗한 종이가 없어 단색으로 채운 화소 %d' % len(miss))
        for p in gone:
            px[p] = src.get(p, col)
    else:
        for p in gone:
            px[p] = col
    im.save(a.dst)
    print('  ✅ %s' % a.dst)


if __name__ == '__main__':
    main()
