# -*- coding: utf-8 -*-
"""UI 한글 폰트(boulderK16) 아틀라스를 «2배 해상도»로 바꾼다 — 글리프표·UV·폭·전진은 그대로 (v0.9).

  python tools/kfont2x.py preview                 → work/uifont/미리보기_2배.png (지금 | 2배, 실제 색)
  python tools/kfont2x.py apply <p3d> <원본v08 p3d> <출력 p3d>

- UV 가 0~1 정규화라 텍스처만 2배로 바꾸면 화면 크기는 그대로, 선명도만 오른다(엔진이 폭을 글리프 «w» 로 잡는다는 가정 —
  시험판으로 확인할 것).
- 한글 음절(U+AC00~D7A3)만 나눔고딕 Bold 로 다시 그린다 — v0.8 은 13px·기준선 11(역추정 오차 최소)이었으니 2배 = 26px·22.
  4배로 그려 줄인다. 라틴·기호(원본 boulder 그림, 「」…· 등)는 원본 칸을 2배 확대.
- RAM: 텍스처가 실행 중 4bpp 로 올라간다(스테이트 실측) → 512×512 128 KB → 1024×1024 512 KB.
- ⚠ 같은 한글 폰트가 4개 파일에 «다른 판»으로 있다: frontend·ingame(512×512, 1006자) · language(512×256) · minigame(512×192).
  원본은 work/uifont/v08/ (v0.8 그대로, ingame 은 레터박스 원복본) — 늘 여기서 다시 만든다(되풀어 2배 금지).
"""
import io
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import kfont          # load_atlas · save_atlas(4bpp 흰 팔레트 + tRNS, IDAT 하나)
import p3dfont
from p3d import walk

FONT_NAME = 'boulderK16'
TTF = 'C:/claude/utils/font/nanum-gothic/NanumGothicBold.ttf'
S1, B1 = 13, 11            # v0.8 1배 크기·기준선(역추정)
SCALE = 2
SS = 4
FONT, TEXTURE, IMGHDR, IMGDATA = 0x00022000, 0x00019000, 0x00019001, 0x00019002


def k16(p3d_bytes):
    import tempfile
    fd, p = tempfile.mkstemp(suffix='.p3d')
    os.write(fd, p3d_bytes)
    os.close(fd)
    try:
        fs = [f for f in p3dfont.scan(p) if f['font']['name'] == FONT_NAME]
    finally:
        os.remove(p)
    if len(fs) != 1:
        raise SystemExit('⛔ %s 가 %d개' % (FONT_NAME, len(fs)))
    return fs[0]


def build_atlas(src_bytes):
    """v0.8 p3d → 2배 아틀라스 PNG 바이트, (W, H), 다시 그린 한글 수, 칸 밖으로 넘친 글자."""
    from PIL import Image, ImageDraw, ImageFont
    f = k16(src_bytes)
    old = kfont.load_atlas(io.BytesIO(f['png']))
    W, H = old.size
    new = old.resize((W * SCALE, H * SCALE), Image.LANCZOS)        # 라틴·기호: 원본 확대
    ttf = ImageFont.truetype(TTF, S1 * SCALE * SS)
    n, over = 0, []
    for g in f['glyphs']:
        if not (0xAC00 <= g['code'] <= 0xD7A3):
            continue
        x0 = round(g['u0'] * W)
        y0 = H - round(g['v1'] * H)                                 # v 는 아래에서 잰다
        w = round((g['u1'] - g['u0']) * W)
        h = round((g['v1'] - g['v0']) * H)
        cw, chh = w * SCALE, h * SCALE
        big = Image.new('L', (cw * SS, chh * SS), 0)
        ImageDraw.Draw(big).text((0, B1 * SCALE * SS), chr(g['code']), font=ttf, fill=255, anchor='ls')
        bb = ttf.getbbox(chr(g['code']), anchor='ls')
        if bb[2] > cw * SS + SS:                                    # 칸보다 1px 넘게 넓으면 기록
            over.append(chr(g['code']))
        cellimg = big.resize((cw, chh), Image.LANCZOS)
        new.paste(cellimg, (x0 * SCALE, y0 * SCALE))
        n += 1
    buf = io.BytesIO()
    tmp = os.path.join(ROOT, 'work/uifont/_tmp_atlas.png')
    kfont.save_atlas(new, tmp)
    png = open(tmp, 'rb').read()
    os.remove(tmp)
    return png, new.size, n, over, old, new, f


def ancestors_fix(d, path_offs, delta):
    """조상 청크들의 chunkSize(+8)를 delta 만큼 고친다."""
    for off in path_offs:
        cs = struct.unpack_from('<I', d, off + 8)[0]
        struct.pack_into('<I', d, off + 8, cs + delta)


def apply(dst_bytes, png, wh):
    """p3d 의 boulderK16 FONT 안 TEXTURE·IMGHDR 폭·높이와 IMGDATA(PNG)를 바꾼다. 글리프표는 손대지 않는다."""
    d = bytearray(dst_bytes)
    ch = walk(bytes(d), 12)
    fi = None
    for i, (depth, cid, off, dsz, csz) in enumerate(ch):
        if cid == FONT and FONT_NAME.encode() in d[off + 12:off + dsz]:
            fi = i
            break
    if fi is None:
        raise SystemExit('⛔ FONT %s 없음' % FONT_NAME)
    fdepth, _, foff, fdsz, fcsz = ch[fi]
    # FONT 의 조상
    anc = []
    want = fdepth - 1
    for depth, cid, off, dsz, csz in reversed(ch[:fi]):
        if depth == want and off < foff < off + csz:
            anc.append(off)
            want -= 1
            if want < 0:
                break
    sub = {}
    for depth, cid, off, dsz, csz in ch[fi:]:
        if off >= foff + fcsz:
            break
        if cid in (TEXTURE, IMGHDR, IMGDATA) and cid not in sub:
            sub[cid] = (off, dsz, csz)
    w, h = wh
    for cid in (TEXTURE, IMGHDR):
        off, dsz, csz = sub[cid]
        n = d[off + 12]
        p = off + 12 + 1 + n + 4
        struct.pack_into('<II', d, p, w, h)
    ioff, idsz, icsz = sub[IMGDATA]
    old_len = struct.unpack_from('<I', d, ioff + 12)[0]
    if idsz != 16 + old_len or icsz != idsz:
        raise SystemExit('⛔ IMGDATA 모양이 예상과 다르다')
    newchunk = struct.pack('<III', IMGDATA, 16 + len(png), 16 + len(png)) + struct.pack('<I', len(png)) + png
    delta = len(newchunk) - icsz
    out = d[:ioff] + newchunk + d[ioff + icsz:]
    # IMGDATA 의 조상: IMGHDR · TEXTURE · FONT · FONT 조상
    for off in [sub[IMGHDR][0], sub[TEXTURE][0], foff] + anc:
        cs = struct.unpack_from('<I', out, off + 8)[0]
        struct.pack_into('<I', out, off + 8, cs + delta)
    # 되읽기 검산
    f2 = k16(bytes(out))
    f1 = k16(dst_bytes)
    if [tuple(sorted(g.items())) for g in f2['glyphs']] != [tuple(sorted(g.items())) for g in f1['glyphs']]:
        raise SystemExit('⛔ 글리프표가 바뀌었다')
    if f2['png'] != png:
        raise SystemExit('⛔ PNG 되읽기 불일치')
    return bytes(out)



# ───────── 여러 장(512×512) — 1024 한 장은 게임이 멈춘다(docs/02 §9(3), 시험 12 재확인) ─────────
PAGE = 512
GLYPHS = 0x00022001


def font_chunks(d):
    """boulderK16 FONT 의 (fi, ch, foff, fdsz, fcsz, 조상 오프셋 목록, GLYPHS (off, dsz, csz), TEXTURE 목록)."""
    ch = walk(bytes(d), 12)
    fi = None
    for i, (depth, cid, off, dsz, csz) in enumerate(ch):
        if cid == FONT and FONT_NAME.encode() in d[off + 12:off + dsz]:
            fi = i
            break
    if fi is None:
        raise SystemExit('⛔ FONT %s 없음' % FONT_NAME)
    fdepth, _, foff, fdsz, fcsz = ch[fi]
    anc, want = [], fdepth - 1
    for depth, cid, off, dsz, csz in reversed(ch[:fi]):
        if want < 0:
            break
        if depth == want and off < foff < off + csz:
            anc.append(off)
            want -= 1
    gl, tex = None, []
    for depth, cid, off, dsz, csz in ch[fi + 1:]:
        if off >= foff + fcsz:
            break
        if depth != fdepth + 1:
            continue
        if cid == GLYPHS:
            gl = (off, dsz, csz)
        elif cid == TEXTURE:
            tex.append((off, dsz, csz))
    return foff, fdsz, fcsz, anc, gl, tex


def ui_syllables():
    """UI(바이블) 번역이 실제 쓰는 한글 음절 — v0.8 폰트엔 옛 자막용 음절(284)도 있었다(이제 자막은 ksub 가 그림)."""
    out = set()
    for path in ('work/ui_kr_boot_en6.tsv', 'work/v09/ui_override.tsv'):
        for c in io.open(os.path.join(ROOT, path), encoding='utf-8').read():
            if 0xAC00 <= ord(c) <= 0xD7A3:
                out.add(c)
    return out


def build_pages(src_bytes, scale=SCALE, keep=None, single=False):
    """v0.8 p3d → scale 배 글리프를 다시 배치. keep(음절 집합)이 있으면 그 밖의 한글 글리프는 뺀다.
    single = 폭 512 한 장(높이는 필요한 만큼, 8 배수) · 아니면 512×512 여러 장.
    반환 (PNG 목록, 새 GLYPHS 데이터, 한글 수, 장 그림 목록)."""
    from PIL import Image, ImageDraw, ImageFont
    f = k16(src_bytes)
    old = kfont.load_atlas(io.BytesIO(f['png']))
    W, H = old.size
    foff, fdsz, fcsz, anc, gl, tex = font_chunks(src_bytes)
    goff, gdsz, gcsz = gl
    graw = bytearray(src_bytes[goff + 12:goff + gdsz])
    n = struct.unpack_from('<I', graw, 0)[0]
    if n != len(f['glyphs']):
        raise SystemExit('⛔ 글리프 수 불일치')
    ttf = ImageFont.truetype(TTF, int(round(S1 * scale * SS)))
    cells = []
    for i, g in enumerate(f['glyphs']):
        if keep is not None and 0xAC00 <= g['code'] <= 0xD7A3 and chr(g['code']) not in keep:
            continue
        x0 = round(g['u0'] * W)
        y0 = H - round(g['v1'] * H)
        w = round((g['u1'] - g['u0']) * W)
        h = round((g['v1'] - g['v0']) * H)
        cw, chh = int(round(w * scale)), int(round(h * scale))
        if 0xAC00 <= g['code'] <= 0xD7A3 and w:
            big = Image.new('L', (cw * SS, chh * SS), 0)
            ImageDraw.Draw(big).text((0, B1 * scale * SS), chr(g['code']), font=ttf, fill=255, anchor='ls')
            img = big.resize((cw, chh), Image.LANCZOS)
        elif w and h:
            img = old.crop((x0, y0, x0 + w, y0 + h)).resize((cw, chh), Image.LANCZOS)
        else:
            img = None
        cells.append((i, cw, chh, img))
    # 높이별로 묶어 줄 단위 배치(위에서부터 — v 는 아래에서 잰 값으로 적는다)
    pad = 2
    PH = 2048 if single else PAGE
    pages = [Image.new('L', (PAGE, PH), 0)]
    x = y = pad
    rowh = None
    place = {}
    for i, cw, chh, img in sorted(cells, key=lambda c: (c[2], f['glyphs'][c[0]]['code'])):
        if rowh is None:
            rowh = chh
        if x + cw + pad > PAGE or chh != rowh:
            x = pad
            y += rowh + pad
            rowh = chh
        if y + chh + pad > PH:
            pages.append(Image.new('L', (PAGE, PH), 0))
            x = y = pad
            rowh = chh
        if img is not None:
            pages[-1].paste(img, (x, y))
        place[i] = (len(pages) - 1, x, y, cw, chh)
        x += cw + pad
    if single:
        used_h = (y + (rowh or 0) + pad + 7) // 8 * 8
        pages = [pages[0].crop((0, 0, PAGE, used_h))]
    PHs = [pg.size[1] for pg in pages]
    # 새 글리프표 — 뺀 글리프는 빼고(코드 오름차순 유지), 남은 것은 장·UV 만 고친다
    out_g = bytearray(struct.pack('<I', len(place)))
    for i in sorted(place):
        p, x, y, cw, chh = place[i]
        e = bytearray(graw[4 + 40 * i:4 + 40 * i + 40])
        ph = PHs[p]
        struct.pack_into('<I', e, 0, p)
        struct.pack_into('<4f', e, 4, x / PAGE, (ph - y - chh) / ph, (x + cw) / PAGE, (ph - y) / ph)
        out_g += e
    graw = out_g
    pngs = []
    tmp = os.path.join(ROOT, 'work/uifont/_tmp_page.png')
    for pg in pages:
        kfont.save_atlas(pg, tmp)
        pngs.append(open(tmp, 'rb').read())
    os.remove(tmp)
    nh = sum(1 for i in place if 0xAC00 <= f['glyphs'][i]['code'] <= 0xD7A3)
    return pngs, bytes(graw), nh, pages


def chunk(cid, data, children=b''):
    dsz = 12 + len(data)
    return struct.pack('<III', cid, dsz, dsz + len(children)) + data + children


def apply_pages(dst_bytes, pngs, graw):
    """FONT 안 TEXTURE 들을 새 장들로, GLYPHS 를 새 표로 바꾸고 «텍스처 수»를 갱신. 조상 크기 고침."""
    d = bytes(dst_bytes)
    foff, fdsz, fcsz, anc, gl, tex = font_chunks(d)
    if len(tex) < 1:
        raise SystemExit('⛔ TEXTURE 없음')
    toff, tdsz, tcsz = tex[0]
    tex_data0 = d[toff + 12:toff + tdsz]
    tname0 = tex_data0[1:1 + tex_data0[0]].rstrip(b'\0').decode('latin1')
    # IMGHDR 머리(첫 TEXTURE 의 자식)
    sub = walk(d, toff + tdsz, toff + tcsz)
    hdr = [c for c in sub if c[1] == IMGHDR][0]
    hdr_data0 = d[hdr[2] + 12:hdr[2] + hdr[3]]

    def fix_wh(data, w, h):
        out = bytearray(data)
        nn = out[0]
        struct.pack_into('<II', out, 1 + nn + 4, w, h)
        return bytes(out)
    textures = b''
    for i, png in enumerate(pngs):
        w, h = struct.unpack_from('>II', png, 16)
        imgdata = chunk(IMGDATA, struct.pack('<I', len(png)) + png)
        imghdr = chunk(IMGHDR, fix_wh(hdr_data0, w, h), imgdata)
        nm = (tname0.rsplit('_', 1)[0] + '_%d' % i).encode('latin1')
        pad = (len(nm) + 4) & ~3
        td = bytes([pad]) + nm + bytes(pad - len(nm)) + tex_data0[1 + tex_data0[0]:]
        textures += chunk(TEXTURE, fix_wh(td, w, h), imghdr)
    # FONT 의 자식들: TEXTURE 들 · GLYPHS (그 밖의 자식이 있으면 멈춤)
    kids = []
    for c in walk(d, foff + fdsz, foff + fcsz):
        if c[0] == 0:
            kids.append(c)
    if any(c[1] not in (TEXTURE, GLYPHS) for c in kids):
        raise SystemExit('⛔ FONT 에 예상 밖 자식')
    fdata = bytearray(d[foff + 12:foff + fdsz])
    struct.pack_into('<I', fdata, len(fdata) - 4, len(pngs))
    new_font = chunk(FONT, bytes(fdata), textures + chunk(GLYPHS, graw))
    delta = len(new_font) - fcsz
    out = bytearray(d[:foff] + new_font + d[foff + fcsz:])
    for off in anc:
        cs = struct.unpack_from('<I', out, off + 8)[0]
        struct.pack_into('<I', out, off + 8, cs + delta)
    # 검산: 글리프 폭·전진·코드·베어링은 원래대로, 텍스처 수 = 장 수
    f1, f2 = k16(d), k16(bytes(out))
    keys = ('w', 'adv', 'b0', 'b1', 'code')
    m1 = {g['code']: tuple(g[k] for k in keys) for g in f1['glyphs']}
    if any(m1.get(g['code']) != tuple(g[k] for k in keys) for g in f2['glyphs']):
        raise SystemExit('⛔ 글리프 폭·전진이 바뀌었다')
    cs = [g['code'] for g in f2['glyphs']]
    if cs != sorted(cs) or 0x7F7F not in cs:
        raise SystemExit('⛔ 코드 정렬·대체 글리프(0x7F7F) 이상')
    if f2['font']['ntex'] != len(pngs):
        raise SystemExit('⛔ 텍스처 수 %d ≠ %d' % (f2['font']['ntex'], len(pngs)))
    return bytes(out)


def preview():
    from PIL import Image, ImageDraw
    src = open(os.path.join(ROOT, 'work/uifont/v08/ingame.p3d'), 'rb').read()
    png, wh, n, over, old, new, f = build_atlas(src)
    G = {g['code']: g for g in f['glyphs']}
    W, H = old.size
    lines = ['튜토리얼 끄기', '게임 계속하기 · 수락 · 취소', '미션 완료! 동전 획득', '카메라 반전 · 진동 · 음량']
    Z = 4                       # 1배 기준 화면 확대(돌핀 고해상도 흉내)

    def draw(atlas, scale, text):
        x = 2
        img = Image.new('RGBA', (len(text) * 16 * Z + 8, 19 * Z + 8), (40, 56, 96, 255))
        for c in text:
            g = G.get(ord(c))
            if not g:
                x += 5
                continue
            x0 = round(g['u0'] * W) * scale
            y0 = (H - round(g['v1'] * H)) * scale
            w = round((g['u1'] - g['u0']) * W) * scale
            hh = round((g['v1'] - g['v0']) * H) * scale
            if not w or not g['w']:
                x += g['adv']
                continue
            cell = atlas.crop((x0, y0, x0 + w, y0 + hh))
            cell = cell.resize((int(g['w'] * Z), int(hh / scale * Z)), Image.BILINEAR)   # GPU 쌍선형 확대 흉내
            white = Image.new('RGBA', cell.size, (255, 255, 255, 255))
            white.putalpha(cell)
            img.alpha_composite(white, (int((x + g['b0']) * Z), 4 + int((19 - hh / scale) * Z / 2)))
            x += g['adv']
        return img.crop((0, 0, int(x * Z) + 8, img.size[1]))
    rows = []
    for t in lines:
        a, b = draw(old, 1, t), draw(new, SCALE, t)
        rows.append((a, b))
    cw = max(max(a.size[0], b.size[0]) for a, b in rows) + 20
    sheet = Image.new('RGBA', (cw * 2, sum(max(a.size[1], b.size[1]) + 10 for a, b in rows) + 30), (30, 30, 30, 255))
    dr = ImageDraw.Draw(sheet)
    dr.text((10, 8), 'v0.8 now (512x512)', fill=(255, 255, 0, 255))
    dr.text((cw + 10, 8), '2x (1024x1024)', fill=(255, 255, 0, 255))
    y = 30
    for a, b in rows:
        sheet.alpha_composite(a, (10, y))
        sheet.alpha_composite(b, (cw + 10, y))
        y += max(a.size[1], b.size[1]) + 10
    p = os.path.join(ROOT, 'work/uifont/미리보기_2배.png')
    sheet.convert('RGB').save(p)
    print('✅ 한글 %d자 다시 그림 · 칸 넘침 %d (%s) · 아틀라스 %dx%d PNG %d B → %s'
          % (n, len(over), ''.join(over[:30]), wh[0], wh[1], len(png), p))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'preview':
        preview()
    elif len(sys.argv) == 5 and sys.argv[1] == 'apply':
        src = open(sys.argv[3], 'rb').read()
        png, wh, n, over, *_ = build_atlas(src)
        out = apply(open(sys.argv[2], 'rb').read(), png, wh)
        open(sys.argv[4], 'wb').write(out)
        print('✅ %s → %s · 아틀라스 %dx%d · 한글 %d자 · 칸 넘침 %d' % (sys.argv[2], sys.argv[4], wh[0], wh[1], n, len(over)))
    else:
        print(__doc__)
