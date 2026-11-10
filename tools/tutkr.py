# -*- coding: utf-8 -*-
"""튜토리얼 상자 한글 그림 (v0.9).

  python tools/tutkr.py preview      → work/tut/미리보기_튜토리얼.png  (원본 상자 글자 | 한글)

- 원본 상자는 글자를 스프라이트로 찍는다(Tutorial.pag/Hud.pag «TutorialMessage», 80칸).
  버튼 아이콘 10칸(but_dpad~but_hand)의 PNG 가 ingame.p3d 에 «원본 그대로» 있다 → 그대로 뽑아 한글 그림에 끼운다.
- 기호 → 아이콘: 문자표 0x8033D620(u8×128) 실측 «+»70 dpad «[»71 lths «]»72 rths «@»73 actn,
  나머지(74~79)는 문장 뜻으로: ¡ jump · © kick · ® run · ¿ gas · µ brak · § hand.
- 번역 = work/tut/tut_ko.tsv (키 · 한국어, «\\n» 줄바꿈, 버튼 기호는 원문 기호 그대로).
"""
import io
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

INGAME = os.path.join(ROOT, 'work/v09/ingame_orig.p3d')
TSV = os.path.join(ROOT, 'work/tut/tut_ko.tsv')
BIBLE_E = os.path.join(ROOT, 'work/v09/bible_E.tsv')
FONT = 'C:/claude/utils/font/nanum-gothic/NanumGothicBold.ttf'

ICON = {'+': 'but_dpad', '[': 'but_lths', ']': 'but_rths', '@': 'but_actn', '¡': 'but_jump', '©': 'but_kick',
        '®': 'but_run', '¿': 'but_gas', 'µ': 'but_brak', '§': 'but_hand'}
PUNCT = {' ': 'space', ':': 'colon', ',': 'comma', '-': 'hyphen', '!': 'exclamation', '$': 'money', '.': 'period',
         '#': 'pound', '?': 'question', '/': 'slash'}


def sprites():
    """ingame.p3d 이미지 → {이름(확장자 없음): RGBA}. 같은 이름 여러 장이면 첫 장(큰 밉)."""
    from PIL import Image
    from p3d import walk
    d = open(INGAME, 'rb').read()
    out = {}
    # 0x19005 = 그림 한 장(실제 w×h)을 2의 거듭제곱 조각(0x19001)들로 «행 우선» 나눠 담은 것
    #   머리: pstr 이름 · u32 640 · u32 480 · u32 w · u32 h · u32 조각 수 · u32 ?
    ch = list(walk(d, 12))
    for idx, (depth, cid, off, dsz, csz) in enumerate(ch):
        if cid != 0x00019005:
            continue
        n = d[off + 12]
        nm = d[off + 13:off + 13 + n].rstrip(b'\0').decode('latin1')
        nm = nm[:-4] if nm.endswith('.png') else nm
        if nm in out:
            continue
        w, h, npc = struct.unpack_from('<III', d, off + 13 + n + 9)   # 640·480 뒤 바이트 1개(?) 다음
        pcs = []
        for depth2, cid2, off2, dsz2, csz2 in ch[idx + 1:]:
            if off2 >= off + csz:
                break
            if cid2 != 0x00019001:
                continue
            blob = d[off2:off2 + csz2]
            i, j = blob.find(b'\x89PNG'), blob.find(b'DDS ')
            k = i if i >= 0 and (j < 0 or i < j) else j
            pcs.append(Image.open(io.BytesIO(blob[k:])).convert('RGBA'))
        if len(pcs) != npc:
            continue
        cols, sw = 0, 0
        while sw < w:
            sw += pcs[cols].size[0]
            cols += 1
        rows = npc // cols
        hs = [pcs[r * cols].size[1] for r in range(rows)]
        ws = [pcs[c].size[0] for c in range(cols)]
        im = Image.new('RGBA', (sum(ws), sum(hs)), (0, 0, 0, 0))
        y = 0
        for r in range(rows):
            x = 0
            for c in range(cols):
                im.paste(pcs[r * cols + c], (x, y))
                x += ws[c]
            y += hs[r]
        out[nm] = im.crop((0, 0, w, h))
    return out


def load_tsv():
    rows = []
    for l in io.open(TSV, encoding='utf-8'):
        l = l.rstrip('\n')
        if not l or l.startswith('#'):
            continue
        k, v = l.split('\t')[:2]
        rows.append((k, v))
    return rows


def ink(im):
    bb = im.getchannel('A').getbbox()
    return im.crop(bb) if bb else im


def render_en(spr, text, h=24):
    """원본 상자 글자 흉내(스프라이트 이어 찍기, 줄 가운데 맞춤) — 미리보기용."""
    from PIL import Image
    lines = text.split('\\')
    rows = []
    for ln in lines:
        parts = []
        for c in ln:
            if c in ICON:
                nm = ICON[c]
            elif c.isalpha():
                nm = 'letter' + c.upper()
            elif c.isdigit():
                nm = c
            else:
                nm = PUNCT.get(c, 'dot')
            if nm == 'space':
                parts.append(None)
                continue
            im = spr.get(nm)
            if im is None:
                parts.append(None)
                continue
            s = h / float(im.size[1]) * (1.4 if nm.startswith('but_') else 1.0)   # 칸 높이 기준(잉크 아님 — 마침표가 커진다)
            bb = im.getchannel('A').getbbox()
            if bb:
                im = im.crop((bb[0], 0, bb[2], im.size[1]))
            parts.append(im.resize((max(1, int(im.size[0] * s)), max(1, int(im.size[1] * s))), Image.LANCZOS))
        w = sum((p.size[0] + 1) if p else h // 2 for p in parts)
        row = Image.new('RGBA', (max(1, w), int(h * 1.4)), (0, 0, 0, 0))
        x = 0
        for p in parts:
            if p is None:
                x += h // 2
                continue
            row.alpha_composite(p, (x, (row.size[1] - p.size[1]) // 2))
            x += p.size[0] + 1
        rows.append(row)
    W = max(r.size[0] for r in rows)
    out = Image.new('RGBA', (W, sum(r.size[1] for r in rows)), (0, 0, 0, 0))
    y = 0
    for r in rows:
        out.alpha_composite(r, ((W - r.size[0]) // 2, y))
        y += r.size[1]
    return out


def layout_ko(spr, text, px=30, outline=3, icon_h=None):
    """한글 줄 + 아이콘 자리. 4배로 그려 줄인다(자막과 같은 방식). 반환 (글자 L, 테두리 L, 아이콘 자리)."""
    from PIL import Image, ImageDraw, ImageFont
    SS = 4
    f = ImageFont.truetype(FONT, px * SS)
    asc, desc = f.getmetrics()
    icon_h = icon_h or int(px * 1.25)
    lh = max(asc + desc, icon_h * SS) + 4 * SS
    lines = text.split('\\n')
    segs_all = []
    for ln in lines:
        segs, cur = [], ''
        for c in ln:
            if c in ICON:
                if cur:
                    segs.append(('t', cur))
                    cur = ''
                segs.append(('i', ICON[c]))
            else:
                cur += c
        if cur:
            segs.append(('t', cur))
        segs_all.append(segs)

    def seg_w(s):
        if s[0] == 't':
            return f.getlength(s[1])
        im = ink(spr[s[1]])
        return im.size[0] * icon_h * SS / im.size[1]
    pad = (outline + 2) * SS
    W = int(max(sum(seg_w(s) for s in segs) for segs in segs_all)) + 2 * pad
    H = lh * len(lines) + 2 * pad
    fill = Image.new('L', (W, H), 0)
    edge = Image.new('L', (W, H), 0)
    df, de = ImageDraw.Draw(fill), ImageDraw.Draw(edge)
    icons = []
    for li, segs in enumerate(segs_all):
        lw = sum(seg_w(s) for s in segs)
        x = (W - lw) / 2.0
        ymid = pad + li * lh + lh / 2.0
        for s in segs:
            if s[0] == 't':
                y = ymid - (asc + desc) / 2.0
                de.text((x, y), s[1], font=f, fill=255, stroke_width=outline * SS, stroke_fill=255)
                df.text((x, y), s[1], font=f, fill=255)
            else:
                icons.append((s[1], x, ymid))
            x += seg_w(s)
    fill = fill.resize((W // SS, H // SS), Image.LANCZOS)
    edge = edge.resize((W // SS, H // SS), Image.LANCZOS)
    pl = []                                     # (아이콘 이름, x, y, w, h) — 결과 그림 px
    for nm, x, ymid in icons:
        im = ink(spr[nm])
        w = max(1, int(round(im.size[0] * icon_h / im.size[1])))
        pl.append((nm, int(round(x / SS)), int(round(ymid / SS - icon_h / 2.0)), w, icon_h))
    return fill, edge, pl


def render_ko(spr, text, px=30, outline=3, icon_h=None):
    """미리보기용 RGBA(글자 흰색·테두리 검정 + 원본 아이콘)."""
    from PIL import Image
    fill, edge, pl = layout_ko(spr, text, px, outline, icon_h)
    out = Image.new('RGBA', fill.size, (0, 0, 0, 0))
    black = Image.new('RGBA', fill.size, (0, 0, 0, 255))
    white = Image.new('RGBA', fill.size, (255, 255, 255, 255))
    out = Image.composite(black, out, edge)
    out = Image.composite(white, out, fill)
    for nm, x, y, w, h in pl:
        out.alpha_composite(ink(spr[nm]).resize((w, h), Image.LANCZOS), (x, y))
    return out


# 아이콘 번호(게임 안 그림 32×32 RGB5A3 순서) — 같은 그림은 하나로(jump=gas=A, kick=hand=B, run=brak=X)
ICON_ID = {'but_dpad': 0, 'but_lths': 1, 'but_actn': 2, 'but_jump': 3, 'but_gas': 3,
           'but_kick': 4, 'but_hand': 4, 'but_run': 5, 'but_brak': 5, 'but_rths': 6}
ICON_IMG = ['but_dpad', 'but_lths', 'but_actn', 'but_jump', 'but_kick', 'but_run', 'but_rths']


def bible_hash(s):
    """게임 버퍼의 u16 문자열(NUL 앞까지) FNV-1a — ksub.c ksub_tut 와 같아야 한다."""
    h = 2166136261
    for c in s:
        h ^= ord(c)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def rgb5a3(im):
    """RGBA 32×32 → GX RGB5A3 (4×4 타일, 빅엔디안)."""
    w, h = im.size
    p = im.load()
    out = bytearray()
    for ty in range(0, h, 4):
        for tx in range(0, w, 4):
            for y in range(ty, ty + 4):
                for x in range(tx, tx + 4):
                    r, g, b, a = p[x, y]
                    if a >= 0xE0:
                        v = 0x8000 | (r >> 3) << 10 | (g >> 3) << 5 | (b >> 3)
                    else:
                        v = (a >> 5) << 12 | (r >> 4) << 8 | (g >> 4) << 4 | (b >> 4)
                    out += struct.pack('>H', v)
    return bytes(out)


def icon_images(spr):
    """아이콘 그림 묶음(번호 순, 2,048 B 씩)."""
    from PIL import Image
    return b''.join(rgb5a3(ink(spr[n]).resize((32, 32), Image.LANCZOS)) for n in ICON_IMG)


def build(px=30, outline=3):
    """튜토리얼 → [(해시, 키, w, h, I4 px, [(아이콘번호, x, y, w, h)])] · 아이콘 그림 묶음.
    w·h 는 8 배수(I4 타일). 글자 I4 값은 자막과 같은 규칙(8+7a 글자 / 4e 테두리)."""
    spr = sprites()
    en = dict(l.rstrip('\n').split('\t', 1) for l in io.open(BIBLE_E, encoding='utf-8') if '\t' in l)
    rows = load_tsv()
    out, seen = [], {}
    for k, ko in rows:
        if k not in en:
            raise SystemExit('⛔ 튜토리얼 키가 바이블에 없다: %s' % k)
        h = bible_hash(en[k])
        if h in seen:
            if seen[h] != ko:
                raise SystemExit('⛔ 같은 영문(%s·%s)에 번역이 다르다' % (seen[h], k))
            continue
        seen[h] = ko
        fill, edge, pl = layout_ko(spr, ko, px, outline, int(px * 1.5))
        w = (fill.size[0] + 7) // 8 * 8
        hh = (fill.size[1] + 7) // 8 * 8
        fp, ep = fill.load(), edge.load()
        px2 = [[0] * w for _ in range(hh)]
        for y in range(fill.size[1]):
            for x in range(fill.size[0]):
                a, e = fp[x, y] / 255.0, ep[x, y] / 255.0
                px2[y][x] = min(15, 8 + int(round(7 * a)) if a > 0.02 else int(round(4 * e)))
        out.append((h, k, w, hh, px2, [(ICON_ID[n], x, y, iw, ih) for n, x, y, iw, ih in pl]))
    out.sort()
    return out, icon_images(spr)


def preview():
    from PIL import Image, ImageDraw, ImageFont
    spr = sprites()
    miss = [v for v in ICON.values() if v not in spr]
    if miss:
        raise SystemExit('⛔ 아이콘 그림 없음: %s' % miss)
    en = dict(l.rstrip('\n').split('\t', 1) for l in io.open(BIBLE_E, encoding='utf-8') if '\t' in l)
    rows = load_tsv()
    lab = ImageFont.truetype(FONT, 14)
    tiles = []
    for k, ko in rows:
        a = render_en(spr, en[k])
        b = render_ko(spr, ko, icon_h=45)
        tiles.append((k, a, b))
    colw = max(max(a.size[0] for _, a, _ in tiles), max(b.size[0] for _, _, b in tiles)) + 24
    hs = [max(a.size[1], b.size[1]) + 30 for _, a, b in tiles]
    sheet = Image.new('RGBA', (colw * 2 + 20, sum(hs) + 30), (52, 70, 110, 255))
    dr = ImageDraw.Draw(sheet)
    dr.text((10, 6), '원본 상자 글자(스프라이트 이어 붙인 흉내)', font=lab, fill=(255, 255, 0, 255))
    dr.text((colw + 20, 6), '한글 + 원본 버튼 아이콘 (화면 크기 ×1.5 — 자막과 같은 비율)', font=lab, fill=(255, 255, 0, 255))
    y = 30
    for (k, a, b), h in zip(tiles, hs):
        dr.line((0, y - 2, sheet.size[0], y - 2), fill=(90, 110, 150, 255))
        dr.text((10, y), k, font=lab, fill=(200, 200, 200, 255))
        sheet.alpha_composite(a, (10 + (colw - a.size[0]) // 2, y + 18))
        sheet.alpha_composite(b, (colw + 20 + (colw - b.size[0]) // 2, y + 18))
        y += h
    p = os.path.join(ROOT, 'work/tut/미리보기_튜토리얼.png')
    sheet.convert('RGB').save(p)
    print('✅ %d개 → %s' % (len(tiles), p))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'preview':
        preview()
    else:
        print(__doc__)
