# -*- coding: utf-8 -*-
"""Scrooby 페이지의 «폰트 참조»를 조회하고 다른 폰트로 돌린다.

  python tools/p3dfontref.py <p3d> --list
  python tools/p3dfontref.py <src> <dst> --to boulder_16 --pages Hud.pag Message.pag
  python tools/p3dfontref.py <src> <dst> --to boulder_16 --all

## 왜 필요한가

폰트마다 아틀라스(텍스처)가 따로 붙는데, 이 게임은 «텍스처 총 디코드 바이트»에 한계가 있다
(128 KB 안전 / 192 KB 불안정 / 256 KB 크래시 — [[feedback_texture_budget_is_total_decoded_bytes]]).
한 파일에 폰트가 4~5벌이라 전부 한글화하면 예산을 몇 배로 넘긴다.
그래서 «필요한 페이지의 참조를 한 폰트로 몰아» 그 한 벌만 한글화한다.

## 어떻게 크기를 안 바꾸고 고치는가

폰트참조 청크 `0x00018104` 의 꼬리에 «실물 폰트 이름»이 pstr(길이 프리픽스 + NUL 패딩)로 있다.
읽는 쪽이 NUL 을 떼고 쓰므로, 길이 바이트는 그대로 두고 «짧은 이름 + NUL 채움»을 넣으면
바이트 수가 안 변한다 → 청크 크기 갱신도, FST 손질도 필요 없다.

  길이 11 "Tt2001m__14"  →  길이 11 "boulder_16\0"

⛔ 새 이름이 원래 이름보다 길면 거부한다.
"""
import argparse
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p3d import walk

PAGE, FONTREF, TEXTEL = 0x00018002, 0x00018104, 0x00018007


def pstr(d, p):
    n = d[p]
    return d[p + 1:p + 1 + n].rstrip(b'\0').decode('latin1'), p + 1 + n


def real_name_span(d, off, dsz):
    """참조 청크 꼬리의 «실물 폰트 이름» pstr 위치를 (길이바이트오프셋, 선언길이, 이름) 으로."""
    end = off + dsz
    p = end - 1
    while p > off + 12 and d[p] == 0:            # 꼬리 NUL 패딩 건너뛰기
        p -= 1
    q = p
    while q > off + 12 and 32 <= d[q - 1] < 127:  # 인쇄 가능한 문자 구간
        q -= 1
    lenpos = q - 1
    declared = d[lenpos]
    if declared < (p - q + 1) or lenpos + 1 + declared > end:
        raise SystemExit('⛔ 참조 청크 0x%X 의 이름 자리를 못 읽었다' % off)
    return lenpos, declared, d[q:p + 1].decode('latin1')


def collect(d):
    ch = list(walk(d, 12))
    out = []
    for dep, cid, off, dsz, csz in ch:
        if cid != PAGE:
            continue
        pname, _ = pstr(d, off + 12)
        refs, nel = [], 0
        for dep2, cid2, o2, d2, c2 in ch:
            if not (off < o2 < off + csz):
                continue
            if cid2 == FONTREF:
                refs.append((o2, d2) + real_name_span(d, o2, d2))
            elif cid2 == TEXTEL:
                nel += 1
        if refs:
            out.append((pname, nel, refs))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst', nargs='?')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--to')
    ap.add_argument('--pages', nargs='*', default=[])
    ap.add_argument('--all', action='store_true')
    a = ap.parse_args()

    d = bytearray(open(a.src, 'rb').read())
    pages = collect(d)

    if a.list or not a.to:
        for pname, nel, refs in pages:
            names = sorted(set(r[4] for r in refs))
            print('%-34s 텍스트요소 %3d  폰트 %s' % (pname, nel, names))
        print('\n페이지 %d개 · 참조 %d개' % (len(pages), sum(len(p[2]) for p in pages)))
        return

    if not a.dst:
        raise SystemExit('⛔ 출력 파일이 필요하다')
    want = set(a.pages)
    if not a.all and not want:
        raise SystemExit('⛔ --pages 또는 --all 이 필요하다')
    new = a.to.encode('latin1')

    changed = 0
    for pname, nel, refs in pages:
        if not a.all and pname not in want:
            continue
        for o2, d2, lenpos, declared, old in refs:
            if old == a.to:
                continue
            if len(new) > declared:
                raise SystemExit('⛔ %s: %r(선언길이 %d) 자리에 %r(%d) 는 안 들어간다'
                                 % (pname, old, declared, a.to, len(new)))
            d[lenpos + 1:lenpos + 1 + declared] = new + bytes(declared - len(new))
            print('  %-30s %-13s -> %s' % (pname, old, a.to))
            changed += 1
        want.discard(pname)
    if want:
        raise SystemExit('⛔ 그런 페이지가 없다: %s' % sorted(want))

    open(a.dst, 'wb').write(bytes(d))
    print('참조 %d곳 변경 · %d B -> %d B (크기 불변 %s)'
          % (changed, os.path.getsize(a.src), os.path.getsize(a.dst),
             'OK' if os.path.getsize(a.src) == os.path.getsize(a.dst) else '⛔'))

    # 되읽어 검산
    for pname, nel, refs in collect(bytearray(open(a.dst, 'rb').read())):
        if a.all or pname in set(a.pages):
            bad = [r[4] for r in refs if r[4] != a.to]
            if bad:
                print('  ⛔ %s 에 아직 %s 가 남아 있다' % (pname, bad))


if __name__ == '__main__':
    main()
