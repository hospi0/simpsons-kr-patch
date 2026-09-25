# -*- coding: utf-8 -*-
"""텍스트 바이블 항목에 «키 이름»과 «쓰이는 요소·페이지»를 붙인다.

  python tools/biblekeys.py                    # 요약
  python tools/biblekeys.py --out work/bible_map.tsv

## ★★★ 해시 (DOL 0x802087C8 에서 읽음)

```
802087D0  lbz   r6,0(r4)     ; c = *p   (extsb — 부호 있는 바이트)
802087D4  slwi  r0,r5,6      ; h*64
802087D8  lwz   r5,0x14(r3)  ; M = 언어객체 +0x14  (바이블 헤더의 세 번째 u32)
802087E4  add   r6,r6,r0
802087E8  divwu/mullw/subf   ; % M
   ⇒ h = (h*64 + c) mod M          M = 2,990,119 (심슨 GC)
```
조회 `0x8020877C` 는 키 배열(+0x20)을 **선형 탐색**해 오프셋표(+0x24)·문자열영역(+0x28)로 간다.

## 요소 종류 — 한글 가능 여부가 여기서 갈린다

```
0x00018007 폰트 텍스트  → 한글 OK
0x00018006 스프라이트   → ASCII 전용 (한글 넣으면 크래시)
   → [[feedback_sprite_letter_table_is_ascii_only]]
```
"""
import argparse
import glob
import io
import os
import struct
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p3d import walk
import txtbible

PAGE, TEXTEL, SPRITEEL, CANDS = 0x00018002, 0x00018007, 0x00018006, 0x0001800B


def bible_hash(name, mod):
    h = 0
    for ch in name.encode('latin1'):
        h = (h * 64 + (ch - 256 if ch > 127 else ch)) % mod
    return h


def pstrs(b):
    out, q = [], 0
    while q < len(b):
        n = b[q]
        if n == 0 or q + 1 + n > len(b):
            break
        out.append(b[q + 1:q + 1 + n].rstrip(b'\0').decode('latin1'))
        q += 1 + n
    return out


def scan_pages(path):
    """[(페이지, 요소, 요소종류, [키이름…])]"""
    d = open(path, 'rb').read()
    if d[:4] != b'P3D\xff':
        return []
    ch = list(walk(d, 12))

    def nm(off):
        n = d[off + 12]
        return d[off + 13:off + 13 + n].rstrip(b'\0').decode('latin1')

    pages = [(o, s, nm(o)) for dep, c, o, ds, s in ch if c == PAGE]
    out = []
    for dep, c, o, ds, s in ch:
        if c not in (TEXTEL, SPRITEEL):
            continue
        pg = [p for p in pages if p[0] < o < p[0] + p[1]]
        keys = []
        for dep2, c2, o2, ds2, s2 in ch:
            if c2 == CANDS and o < o2 < o + s:
                p2 = pstrs(d[o2 + 12:o2 + ds2])
                if len(p2) >= 2:
                    keys.append(p2[-1])
        if keys:
            out.append((pg[-1][2] if pg else '?', nm(o), c, keys))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bible', default='work/extract/srr2.p3d')
    ap.add_argument('--p3d', default='work/extract/*.p3d')
    ap.add_argument('--lang', default='E')
    ap.add_argument('--out')
    a = ap.parse_args()

    d = open(a.bible, 'rb').read()
    L = [x for x in txtbible.langs(d) if x['code'] == a.lang][0]
    M = L['a']
    idx_of = {k: i for i, k in enumerate(L['keys'])}
    print('바이블 %s : 항목 %d · 해시 M = %d' % (a.lang, L['n'], M))

    use = defaultdict(list)          # 바이블색인 -> [(페이지, 요소, 종류)]
    name_of = {}
    files = [p for p in sorted(glob.glob(a.p3d)) if 'srr2' not in p]
    for p in files:
        for pg, el, cid, keys in scan_pages(p):
            for k in keys:
                h = bible_hash(k, M)
                i = idx_of.get(h)
                if i is None:
                    continue
                name_of[i] = k
                use[i].append((os.path.basename(p), pg, el, cid))

    known = len(name_of)
    spr = {i for i, v in use.items() if any(c == SPRITEEL for *_, c in v)}
    fnt = {i for i, v in use.items() if any(c == TEXTEL for *_, c in v)}
    print('키 이름을 알아낸 항목 %d / %d (%.0f%%)' % (known, L['n'], 100.0 * known / L['n']))
    print('  폰트 요소가 쓰는 항목      %d  (한글 OK)' % len(fnt - spr))
    print('  ⛔스프라이트 요소가 쓰는 항목 %d  (ASCII 전용)' % len(spr))
    print('  둘 다                      %d' % len(spr & fnt))
    print('  어느 요소에도 안 붙은 항목  %d' % (L['n'] - len(use)))

    if spr:
        print('\n[스프라이트 요소가 쓰는 항목 — 한글 금지]')
        for i in sorted(spr):
            where = ', '.join('%s/%s' % (v[1], v[2]) for v in use[i][:3])
            print('  [%4d] %-24s %-40s %r'
                  % (i, name_of.get(i, '?'), where, txtbible.text(L, i)[:40]))

    if a.out:
        with io.open(a.out, 'w', encoding='utf-8', newline='\n') as f:
            f.write('색인\t키이름\t종류\t페이지\t요소\t영문\n')
            for i in range(L['n']):
                t = txtbible.text(L, i).replace('\t', ' ').replace('\n', '\\n')
                if i in use:
                    kind = '스프라이트' if i in spr else '폰트'
                    fp, pg, el, _ = use[i][0]
                    f.write('%d\t%s\t%s\t%s\t%s\t%s\n'
                            % (i, name_of.get(i, ''), kind, pg, el, t))
                else:
                    f.write('%d\t%s\t\t\t\t%s\n' % (i, name_of.get(i, ''), t))
        print('\n-> %s' % a.out)


if __name__ == '__main__':
    main()
