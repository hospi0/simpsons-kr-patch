# -*- coding: utf-8 -*-
"""⛔⛔ 이 기능은 2026-09-11 «보류»됐다 — 케이브는 맞는데 «폰트»가 걸린다.
   로딩 화면 폰트 boulderB16 을 fonthook 에 등록해야 한글이 나오는데, 그러면
   **미션 중 불러오기에서 게임이 멈춘다**(backend 는 상주 자원인데 한글 폰트는 레벨 자원이라
   먼저 해제돼, 이미 풀린 배열을 계속 가리킨다). 자세한 것은 docs/07 §8.
   아래 훅 자리·색인 배치·--widen 은 다시 볼 때 그대로 쓸 수 있다.

   로딩 화면의 «로딩 중» 자리에 그 레벨의 «신문 헤드라인»을 띄운다.

  python tools/newshook.py <iso> --show / --apply / --reset / --asm

## 왜 이렇게 되나

로딩 화면 신문(`/art/frontend/dynaload/images/loadingN.p3d`)의 헤드라인은 **그림에 구운 픽셀**이라
고치려면 이미지를 손봐야 한다. 그런데 그 헤드라인의 **번역문이 이미 바이블에 있다.**
```
색인 = 812 + 레벨×4      812 핫도그 · 816 백만장자 · 820 밝은 빛 · 824 수수께끼 문양
                          828 새 콜라 · 832 크러스티 · 836 외계인 침공
```
그리고 로딩 화면은 이미 한글로 «로딩 중»을 띄우고 있다. 그 문자열 칸을 헤드라인으로 바꿔 쓰면
그림을 전혀 안 건드리고 한글 헤드라인이 나온다.

## 레벨 번호는 어디에 있나 (실측)
```
800B8C00  로딩 화면 여는 함수
800B8C18  bl 0x800744CC
800B8C1C  lwz r31,956(r3)     ★ r31 = 레벨 색인 0~6
800B8C20  cmpwi r31,7 ; 7 이상이면 −7
800B8C34  addi r4,r4,-30008   "loading%d.png"
800B8C38  addi r5,r31,1       ★ 여기를 가로챈다 (신문 번호 = 레벨+1)
800B8C40  bl sprintf
```
⛔ r3·r4 는 sprintf 인수라 건드리면 안 된다. 앞선 `bl`(0x800B8C18) 덕에 r5~r12 는 죽어 있다.

## ⛔ 왜 «폰트를 구워 넣는» 길로 안 갔나
`backend.p3d`(로딩 화면 폰트)를 69,212 → 76,334 B 로 키웠더니 **부팅이 안 넘어갔다**
(PC=0x8030F510 유휴 루프, 폰트 객체 2개 — backend 가 안 올라옴). bootup 과 같은 제약이다.
→ 대신 `fonthook.py` 가 `boulderB16` 을 «이미 떠 있는» 한글 폰트로 돌린다. 파일 증가 0.
"""
import argparse
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fonthook import Dol, b_form, Asm, _lis, _ori, _addi, _li, _lwz, _stw, _lwzx, \
    _cmplw, _cmplwi, _mflr, _mtlr, _mtctr, _blr, _mr

HOOK = 0x800B8C38
HOOK_ORIG = 0x38BF0001          # addi r5,r31,1

CODE = 0x80004E88               # 204 B (fonthook 의 코드·자료와 겹치지 않는다)
CODE_MAX = 0xCC
DATA = 0x80004F88               # 204 B
DATA_MAX = 0xCC

LANG = 0x4A4C                   # dolhook 의 CAVE5 가 넣어 두는 «영어 언어 객체»
NLR = 0x4F88                    # LR 보관
NCNT = 0x4F8C                   # 훅 횟수(진단)
NLVL = 0x4F90                   # 마지막 레벨(진단)
NDST = 0x4F94                   # 대상 색인 표 (u32, 0 으로 끝)

BASE = 812                      # 레벨 0 의 헤드라인 색인
STEP = 4
DSTS = [606, 607, 608, 609, 939]   # LOADING_0~3 · LOADING
MAXCH = 48                      # 복사 상한(바이블에서 50자 예약해 둔다)


def _lhzx(d, a, b):  return 0x7C00022E | (d << 21) | (a << 16) | (b << 11)
def _sthx(s, a, b):  return 0x7C00032E | (s << 21) | (a << 16) | (b << 11)
def _slwi(a, s, n):  return 0x54000000 | (s << 21) | (a << 16) | (n << 11) | (0 << 6) | ((31 - n) << 1)
def _clrbit0(a, s):  return 0x54000000 | (s << 21) | (a << 16) | (0 << 11) | (0 << 6) | (30 << 1)
def _add(d, a, b):   return 0x7C000214 | (d << 21) | (a << 16) | (b << 11)


def code_words():
    a = Asm(CODE)
    a(_lis(12, 0x8000))
    a(_mflr(11)); a(_stw(11, NLR, 12))
    a(_lwz(11, NCNT, 12)); a(_addi(11, 11, 1)); a(_stw(11, NCNT, 12))
    a(_stw(31, NLVL, 12))
    # ⛔ r31 은 «0~6 일 것»이지 보장이 아니다(0x800B8C20 은 7 이상일 때 −7 만 한다).
    #    범위를 벗어나면 남의 칸을 읽게 되므로 그냥 손대지 않는다.
    a(_cmplwi(31, 7)); a.bge('OUT')
    a(_lwz(11, LANG, 12))
    a(_cmplwi(11, 0)); a.beq('OUT')                 # 언어 객체가 없으면 아무것도 안 한다
    a(_lwz(10, 0x24, 11))                           # 오프셋 표
    a(_lwz(9, 0x28, 11))                            # 문자열 영역
    # src = blob + (offs[BASE + lvl*STEP] & ~1)
    a(_slwi(8, 31, 4))                              # lvl*16  (= (lvl*STEP) 항목 × 4바이트)
    a(_addi(8, 8, BASE * 4))
    a(_lwzx(8, 10, 8))
    a(_clrbit0(8, 8))
    a(_add(8, 9, 8))
    a(_addi(7, 12, NDST))
    a.label('LOOP')
    a(_lwz(6, 0, 7))
    a(_cmplwi(6, 0)); a.beq('OUT')
    a(_slwi(6, 6, 2))
    a(_lwzx(6, 10, 6))
    a(_clrbit0(6, 6))
    a(_add(6, 9, 6))                                # dst
    a(_li(0, MAXCH)); a(_mtctr(0))
    a(_li(5, 0))
    a.label('CP')
    a(_lhzx(0, 8, 5))
    a(_sthx(0, 6, 5))
    a(_cmplwi(0, 0)); a.beq('CPEND')
    a(_addi(5, 5, 2))
    a.bdnz('CP')
    a(_li(0, 0)); a(_sthx(0, 6, 5))                 # MAXCH 를 다 썼으면 «강제 종단»
    a.label('CPEND')
    a(_addi(7, 7, 4))
    a.b('LOOP')
    a.label('OUT')
    a(_lis(12, 0x8000)); a(_lwz(11, NLR, 12)); a(_mtlr(11))
    a(HOOK_ORIG)                                    # 훔친 명령 addi r5,r31,1
    a(_blr())
    ws = a.out()
    if len(ws) * 4 > CODE_MAX:
        raise SystemExit('⛔ 케이브 %d B > %d B' % (len(ws) * 4, CODE_MAX))
    return ws, {k: CODE + v * 4 for k, v in a.lab.items()}


def data_words():
    """DATA 구역: +0 LR · +4 횟수 · +8 레벨 · +0xC 부터 대상 색인 표(0 으로 끝)"""
    w = [0, 0, 0] + DSTS + [0]
    if len(w) * 4 > DATA_MAX:
        raise SystemExit('⛔ 자료 초과')
    return w


def plan():
    ws, labs = code_words()
    p = [(HOOK, HOOK_ORIG, b_form(HOOK, CODE, 1))]
    for k, w in enumerate(ws):
        p.append((CODE + k * 4, 0x00000000, w))
    for k, w in enumerate(data_words()):
        p.append((DATA + k * 4, 0x00000000, w))
    return p


# ── 헤드라인이 들어갈 «칸 넓히기» (backend.p3d 를 «제자리»에서, 파일 크기 변화 0) ──────────
#   원본 : Loading.pag/Loading    17 220  75 200 18 4 …   ← 정렬 4 = 가운데(중심 320)
#          LoadingFE.pag/Loading  17  90 380 200 18 0 …   ← 정렬 0 = 왼쪽(왼끝 90)
#   헤드라인은 최대 35자(≈550px)라 200px 칸으로는 모자란다.
#   Loading.pag 는 중심을 320 에 그대로 두고 폭만 640 으로, LoadingFE 는 왼끝을 90 에 두고 폭만 540 으로.
WIDEN = {('Loading.pag', 'Loading'): (0, None, 640),        # (x, y, 폭) · None = 그대로
         ('LoadingFE.pag', 'Loading'): (None, None, 540)}


def widen(path, dst=None, dry=True):
    from p3delem import tree, pstr_read, owner_page, TXT
    d = bytearray(open(path, 'rb').read())
    ch = tree(bytes(d))
    n = 0
    for dep, cid, o, ds, cs in ch:
        if cid != TXT:
            continue
        nm, p = pstr_read(bytes(d), o + 12)
        key = (owner_page(bytes(d), ch, o), nm)
        if key not in WIDEN:
            continue
        cur = [struct.unpack_from('<I', d, p + 4 * i)[0] for i in range(10)]
        new = list(cur)
        for fi, v in zip((1, 2, 3), WIDEN[key]):
            if v is not None:
                new[fi] = v
        print('   %-16s %-10s x,y,폭  %d,%d,%d → %d,%d,%d'
              % (key[0], key[1], cur[1], cur[2], cur[3], new[1], new[2], new[3]))
        if not dry:
            for i, v in enumerate(new):
                struct.pack_into('<I', d, p + 4 * i, v)
        n += 1
    if n != len(WIDEN):
        raise SystemExit('⛔ 요소를 %d개만 찾았다 (%d개여야)' % (n, len(WIDEN)))
    if not dry:
        assert len(d) == os.path.getsize(path), '⛔ 크기가 바뀌었다'
        open(dst or path, 'wb').write(bytes(d))
        print('   ✅ %s  %d B (크기 변화 0)' % (dst or path, len(d)))
    return bytes(d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('iso')
    ap.add_argument('--show', action='store_true')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--reset', action='store_true')
    ap.add_argument('--asm', action='store_true')
    ap.add_argument('--widen', metavar='backend.p3d',
                    help='로딩 화면 글자칸을 «제자리»에서 넓힌다 (dst 를 주면 그리로 쓴다)')
    ap.add_argument('--out')
    a = ap.parse_args()

    if a.widen:
        widen(a.widen, a.out, dry=not a.out)
        return

    ws, labs = code_words()
    if a.asm:
        print('케이브 %d 워드 (%d B / %d B)' % (len(ws), len(ws) * 4, CODE_MAX))
        for k, v in sorted(labs.items(), key=lambda x: x[1]):
            print('   %-6s 0x%08X' % (k, v))
        for k, w in enumerate(ws):
            print('   %08X  %08X' % (CODE + k * 4, w))
        return

    d = Dol(a.iso, 'r+b' if (a.apply or a.reset) else 'rb')
    items = plan()
    if a.reset:
        cur = d.rd(HOOK)
        if cur != HOOK_ORIG:
            d.wr(HOOK, HOOK_ORIG); print('  ↩ 훅 %08X -> %08X' % (cur, HOOK_ORIG))
        for base, n in ((CODE, CODE_MAX), (DATA, DATA_MAX)):
            for k in range(n // 4):
                va = base + k * 4
                if d.rd(va):
                    d.wr(va, 0)
        print('  ↩ 케이브·자료 비움')
        d.f.close(); return
    if a.apply:
        for va, old, new in items:
            cur = d.rd(va)
            if cur not in (old, new):
                raise SystemExit('⛔ VA %08X 예상 밖 (현재 %08X 원본 %08X) — 먼저 --reset' % (va, cur, old))
        for va, _, new in items:
            if d.rd(va) != new:
                d.wr(va, new)
        d.f.close()
        print('  ✅ 훅 1개 + 케이브 %d 워드 + 자료 %d 워드 적용' % (len(ws), len(data_words())))
        return
    cur = d.rd(HOOK)
    st = '원본' if cur == HOOK_ORIG else ('적용됨' if cur == b_form(HOOK, CODE, 1) else '⛔알수없음')
    print('  훅 VA %08X  현재 %08X  %s' % (HOOK, cur, st))
    bad = [va for va, old, new in items[1:] if d.rd(va) != new]
    print('  케이브+자료 %d 워드 중 다른 것 %d' % (len(items) - 1, len(bad)))


if __name__ == '__main__':
    main()
