# -*- coding: utf-8 -*-
"""v0.8 이 «자막 칸»으로 고쳐 둔 레터박스 바 페이지(LetterBoxButtons.pag)를 원본으로 되돌린다.

  python tools/lbrestore.py <원본 ingame.p3d> <대상 ingame.p3d> [--write <출력>]

v0.8 이 바꾼 것 (원본과 바이트 비교, 2026-11-11):
  · 텍스트 요소 Skip·Cancel·Accept(0x00018007) 필드 (17,x,y,폭,18,[5]정렬,…) → x=60·폭=520·정렬4·y=22/45
  · Skip 텍스트 요소 뒤쪽 몇 바이트
  · 버튼 아이콘 3개(0x00018006) → x=900(화면 밖)·폭/높이 0  ← 아이콘이 안 보였다
  · 글꼴 참조(0x00018104) boulder_16 → boulderK16          ← 한글 버튼 글자에 필요, «유지»
⇒ 페이지 크기가 같으므로 «글꼴 참조 청크만 대상 그대로, 나머지 페이지 바이트는 전부 원본».
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p3d

KEEP = (0x00018104,)          # 대상 쪽을 그대로 둘 청크(글꼴 참조)


def page(d):
    i = d.find(b'LetterBoxButtons.pag')
    if i < 0:
        raise SystemExit('⛔ LetterBoxButtons.pag 를 못 찾았다')
    best = None
    for depth, cid, off, dsz, csz in p3d.walk(d, 12):
        if cid == 0x00018002 and off <= i < off + csz and (best is None or csz < best[1]):
            best = (off, csz)
    if not best:
        raise SystemExit('⛔ 페이지 청크를 못 찾았다')
    return best


def keep_ranges(d, off, size):
    out = []
    for depth, cid, o, dsz, csz in p3d.walk(d, 12):
        if off < o < off + size and cid in KEEP:
            out.append((o - off, o - off + csz))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('orig')
    ap.add_argument('target')
    ap.add_argument('--write')
    a = ap.parse_args()
    o = open(a.orig, 'rb').read()
    t = bytearray(open(a.target, 'rb').read())
    oo, os_ = page(o)
    to, ts = page(bytes(t))
    if os_ != ts:
        raise SystemExit('⛔ 페이지 크기가 다르다: 원본 %d · 대상 %d' % (os_, ts))
    po, pt = o[oo:oo + os_], bytes(t[to:to + ts])
    kr = keep_ranges(bytes(t), to, ts)
    kro = keep_ranges(o, oo, os_)
    if [k for k in kr] != [k for k in kro]:
        raise SystemExit('⛔ 글꼴 참조 청크 배치가 다르다: %s / %s' % (kro, kr))
    new = bytearray(po)
    for s, e in kr:
        new[s:e] = pt[s:e]
    diff = [i for i in range(ts) if new[i] != pt[i]]
    kept = sum(1 for s, e in kr for i in range(s, e) if po[i] != pt[i])
    print('  레터박스 페이지 0x%X (%d B): 원본으로 되돌릴 바이트 %d · 글꼴 참조로 남긴 차이 %d' % (to, ts, len(diff), kept))
    t[to:to + ts] = new
    if a.write:
        open(a.write, 'wb').write(bytes(t))
        print('✅ → %s (크기 %d B 그대로)' % (a.write, len(t)))


if __name__ == '__main__':
    main()
