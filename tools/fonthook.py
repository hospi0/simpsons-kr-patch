# -*- coding: utf-8 -*-
"""부팅 폰트(`boulder_16`·`Tt2001m__14`)를 «런타임에» 한글 폰트로 돌린다.

  python tools/fonthook.py <iso> --show
  python tools/fonthook.py <iso> --apply
  python tools/fonthook.py <iso> --reset

## 왜 필요한가 — 실측으로 확정된 사실 (2026-09-11)

화면 요소가 실제로 어느 폰트에 묶이는지는 **정적 폰트 참조로 알 수 없다.**
`Sound.pag` 는 frontend.p3d 안에 있고 참조 청크에도 `boulderK16` 이라고 적혀 있는데,
실기에서는 **bootup.p3d 의 `boulder_16`** 으로 그려지고 있었다(그래서 한글이 전부 □).
RAM 실측: `boulder_16` 121곳 · `Tt2001m__14` 96곳 · 한글 `boulderK16` 61곳.

폰트 객체 꼬리 6워드만 한글 폰트 것으로 바꾸면 그 화면들이 즉시 한글이 된다(돌핀 실증).
**파일이 한 바이트도 안 커지므로** 예전에 막혔던 「bootup.p3d 를 키우면 크래시」를 안 만난다.

## ⛔ 그냥 바꾸면 «이중 해제»로 죽는다

폰트 소멸자 `0x8023D5C4` 가 배열을 직접 free 한다 —
```
8023D65C  lwz r3,0x30(r26)  → bl 0x8006AA50   free(텍스처 배열)
8023D668  lwz r3,0x3C(r26)  → bl 0x801A746C   글리프 배열 해제
8023D674  lwz r3,0x40(r26)  → bl 0x8006AA50   free(코드 배열)
```
두 객체가 같은 배열을 가리키면 두 번 해제돼 힙이 깨진다.
실측: 게임 진입 시 크래시(PC 0x802289D0 · LR 0x8023D598), 그때 한글 폰트 객체의
vtable 자리가 이미 프리리스트 포인터로 바뀌어 있었다.

⇒ **소멸자 진입을 가로채 «손댄 객체면 원래 꼬리로 되돌린 뒤» 통과시킨다.**
   되돌린 최악의 결과는 «그 순간 영문» 이라 안전하다.

## 훅 두 개

```
0x8023FA9C  or  r3,r31,r31    폰트 적재 «완료» — 에필로그 첫 명령, r31 = 폰트 객체
                               ⛔ 0x8023F740(코드배열 대입 직후)에 걸면 +0x34 가 아직 0 이다.
                                  +0x34 는 «못 찾은 글자에 쓸 대체 글리프(□)» 색인이고
                                  로더가 U+7F7F 를 만나는 0x8023FA98 에서야 채운다.
0x8023D5E4  lis r3,0x803A      폰트 소멸자 — LR 이 이미 0x24(r1) 에 저장된 뒤, r26 = 객체
                               (0x8023D5E0 의 널검사를 지난 자리)
```
⛔ 둘 다 «함수 첫 명령»이 아니다. 첫 명령을 가로채면 LR 이 저장되기 전이라 깨진다.

## 케이브 자리

```
코드 0x80003A88 ~ 0x80003D54  (716 B 연속 0 — DOL·실기 RAM 둘 다 확인)
자료 0x80004D88 ~ 0x80004E54  (204 B)
자막 케이브는 0x80004888~0x80004D1C — ⛔겹치지 않는다. dolhook.py --reset 도 여기까지 안 민다.
```
"""
import argparse
import struct

# ── 훅 자리
H1 = 0x8023FA9C            # or r3,r31,r31  (= mr r3,r31)
H1_ORIG = 0x7FE3FB78
H2 = 0x8023D5E4            # lis r3,0x803A
H2_ORIG = 0x3C60803A

# ── 케이브
CODE = 0x80003A88
CODE_MAX = 0x2CC           # 716 B
FD = 0x80004D88            # 자료
FD_MAX = 0xCC              # 204 B

KF = 0x4D88                # 살아 있는 한글 폰트 객체
N1 = 0x4D8C                # 훅1 횟수(진단)
N2 = 0x4D90                # 훅2 횟수(진단)
LRSV = 0x4D94
SLOT0 = 0x4D9C             # 슬롯 4개 · 보폭 0x20
NSLOT, STRIDE = 4, 0x20
#   슬롯: +0x00 객체 · +0x04 «패치됨» 표시 · +0x08..+0x1F 원래 꼬리 6워드

TAIL = 0x2C                # 꼬리 = 객체 +0x2C(텍스처수) +0x30(텍스처배열) +0x34 +0x38(글리프수)
NTAIL = 6                  #        +0x3C(글리프배열) +0x40(코드배열)

# ── 폰트 이름 해시 쌍 (객체 +0x08 / +0x0C) — 실기에서 읽은 값
HASH_KR = (0xA5C0BACC, 0xE4042E57)   # boulderK16  (한글 863자, frontend·ingame·minigame)
HASH_EN = [(0xA5C0BAC0, 0xDDFB6C43),  # boulder_16   16px  bootup
           (0x5F611EFD, 0xD229DA85)]  # Tt2001m__14  12px  bootup·frontend
# ⛔⛔ 여기에 «boulderB16»(0xA5C0BAD5, 0xE870B95A — backend.p3d, 로딩 화면 글자)을 «넣지 말 것».
#   2026-09-11 로딩 화면 한글화를 하려고 넣었다가 **미션 중 불러오기에서 게임이 멈춘다.**
#     · 첫 화면에서 불러오기 → 정상       · 미션 진행 중 불러오기 → 멈춤
#   backend.p3d 는 «레벨이 바뀌어도 안 내려가는» 상주 자원이라, 레벨 자원(한글 폰트)이
#   먼저 해제되면 이 슬롯이 «이미 풀린 배열»을 계속 가리킨다. 소멸자 훅은 한글 폰트가
#   내려갈 때 영문 폰트를 되돌려 주지 못한다 — 되돌릴 대상을 «영문 폰트 해제 시점»에만 찾기 때문.
#   ⇒ 로딩 화면 「로딩 중」은 backend.p3d 에 이미 구워진 한글 5자(데딩로모중)로 충분하다.


# ────────────────────────────────── 작은 어셈블러 (라벨 지원)
def _lis(d, i):      return 0x3C000000 | (d << 21) | (i & 0xFFFF)
def _ori(a, s, i):   return 0x60000000 | (s << 21) | (a << 16) | (i & 0xFFFF)
def _addi(d, a, x):  return 0x38000000 | (d << 21) | (a << 16) | (x & 0xFFFF)
def _li(d, x):       return _addi(d, 0, x)
def _or(a, s, b):    return 0x7C000378 | (s << 21) | (a << 16) | (b << 11)
def _mr(a, s):       return _or(a, s, s)
def _lwz(d, o, a):   return 0x80000000 | (d << 21) | (a << 16) | (o & 0xFFFF)
def _stw(s, o, a):   return 0x90000000 | (s << 21) | (a << 16) | (o & 0xFFFF)
def _lwzx(d, a, b):  return 0x7C00002E | (d << 21) | (a << 16) | (b << 11)
def _stwx(s, a, b):  return 0x7C00012E | (s << 21) | (a << 16) | (b << 11)
def _cmplw(a, b):    return 0x7C000040 | (a << 16) | (b << 11)
def _cmplwi(a, i):   return 0x28000000 | (a << 16) | (i & 0xFFFF)
def _mflr(d):        return 0x7C0802A6 | (d << 21)
def _mtlr(s):        return 0x7C0803A6 | (s << 21)
def _mtctr(s):       return 0x7C0903A6 | (s << 21)
def _blr():          return 0x4E800020


class Asm(object):
    """라벨을 쓰는 아주 작은 PPC 어셈블러. 분기 거리를 손으로 세지 않는다."""

    def __init__(self, base):
        self.base = base
        self.w = []          # 워드 또는 (kind, label)
        self.lab = {}

    def __call__(self, word):
        self.w.append(word)

    def label(self, name):
        if name in self.lab:
            raise SystemExit('⛔ 라벨 중복: %s' % name)
        self.lab[name] = len(self.w)

    def b(self, name):    self.w.append(('b', name))
    def bl(self, name):   self.w.append(('bl', name))
    def beq(self, name):  self.w.append(('bc', 12, 2, name))
    def bne(self, name):  self.w.append(('bc', 4, 2, name))
    def blt(self, name):  self.w.append(('bc', 12, 0, name))
    def bge(self, name):  self.w.append(('bc', 4, 0, name))
    def bdnz(self, name): self.w.append(('bc', 16, 0, name))

    def out(self):
        res = []
        for i, x in enumerate(self.w):
            if isinstance(x, int):
                res.append(x)
                continue
            if x[0] in ('b', 'bl'):
                tgt = self.lab[x[1]]
                d = (tgt - i) * 4
                if not -0x2000000 <= d < 0x2000000:
                    raise SystemExit('⛔ 분기 거리 초과')
                res.append(0x48000000 | (d & 0x03FFFFFC) | (1 if x[0] == 'bl' else 0))
            else:
                _, bo, bi, name = x
                d = (self.lab[name] - i) * 4
                if not -0x8000 <= d < 0x8000:
                    raise SystemExit('⛔ 조건분기 거리 초과')
                res.append(0x40000000 | (bo << 21) | (bi << 16) | (d & 0xFFFC))
        return res


def code_words():
    a = Asm(CODE)

    # ─────────── PATCH(r5=객체, r6=슬롯주소, r7=한글폰트)  — r0 r5 r6 r7 r8 ctr 만 쓴다
    a.label('PATCH')
    a(_cmplwi(5, 0));  a.beq('PRET')
    a(_cmplwi(7, 0));  a.beq('PRET')
    a(_lwz(0, 4, 6));  a(_cmplwi(0, 0));  a.bne('PRET')     # 이미 패치됨 → 건드리지 않는다
    a(_li(0, 1));      a(_stw(0, 4, 6))
    a(_addi(6, 6, 8 - TAIL))                                # 저장칸을 «+0x2C 기준»으로 옮긴다
    a(_li(0, NTAIL));  a(_mtctr(0));  a(_li(8, TAIL))
    a.label('PLP')
    a(_lwzx(0, 5, 8)); a(_stwx(0, 6, 8))                    # 원래 꼬리 저장
    a(_lwzx(0, 7, 8)); a(_stwx(0, 5, 8))                    # 한글 폰트 꼬리 복사
    a(_addi(8, 8, 4)); a.bdnz('PLP')
    a.label('PRET'); a(_blr())

    # ─────────── UNDO(r5=객체, r6=슬롯주소)
    a.label('UNDO')
    a(_cmplwi(5, 0));  a.beq('URET')
    a(_lwz(0, 4, 6));  a(_cmplwi(0, 0));  a.beq('URET')     # 패치 안 했으면 그냥 통과
    a(_li(0, 0));      a(_stw(0, 4, 6))
    a(_addi(6, 6, 8 - TAIL))
    a(_li(0, NTAIL));  a(_mtctr(0));  a(_li(8, TAIL))
    a.label('ULP')
    a(_lwzx(0, 6, 8)); a(_stwx(0, 5, 8))
    a(_addi(8, 8, 4)); a.bdnz('ULP')
    a.label('URET'); a(_blr())

    # ─────────── 훅1 : 폰트 적재 완료 (r31 = 객체)
    a.label('HOOK1')
    a(_lis(12, 0x8000))
    a(_mflr(11)); a(_stw(11, LRSV, 12))
    a(_lwz(11, N1, 12)); a(_addi(11, 11, 1)); a(_stw(11, N1, 12))
    a(_lwz(10, 0x08, 31)); a(_lwz(9, 0x0C, 31))             # 이름 해시 쌍
    # 한글 폰트인가?
    a(_lis(11, HASH_KR[0] >> 16)); a(_ori(11, 11, HASH_KR[0]))
    a(_cmplw(10, 11)); a.bne('H1_ENG')
    a(_lis(11, HASH_KR[1] >> 16)); a(_ori(11, 11, HASH_KR[1]))
    a(_cmplw(9, 11)); a.bne('H1_ENG')
    #   → 기록하고 «등록된 영문 폰트 전부» 패치
    a(_stw(31, KF, 12))
    a(_mr(7, 31))
    for i in range(NSLOT):
        a(_addi(6, 12, SLOT0 + i * STRIDE))
        a(_lwz(5, 0, 6))
        a.bl('PATCH')
    a.b('H1_OUT')
    # 영문 폰트 둘 중 하나인가?
    a.label('H1_ENG')
    a(_lis(11, HASH_EN[0][0] >> 16)); a(_ori(11, 11, HASH_EN[0][0]))
    a(_cmplw(10, 11)); a.bne('H1_TT')
    a(_lis(11, HASH_EN[0][1] >> 16)); a(_ori(11, 11, HASH_EN[0][1]))
    a(_cmplw(9, 11)); a.beq('H1_ADD')
    a.label('H1_TT')
    a(_lis(11, HASH_EN[1][0] >> 16)); a(_ori(11, 11, HASH_EN[1][0]))
    a(_cmplw(10, 11)); a.bne('H1_OUT')
    a(_lis(11, HASH_EN[1][1] >> 16)); a(_ori(11, 11, HASH_EN[1][1]))
    a(_cmplw(9, 11)); a.bne('H1_OUT')
    #   → 빈 슬롯에 등록하고, 한글 폰트가 이미 있으면 곧바로 패치
    a.label('H1_ADD')
    a(_addi(6, 12, SLOT0))
    a(_li(0, NSLOT)); a(_mtctr(0))
    a.label('H1_FIND')
    a(_lwz(10, 0, 6)); a(_cmplwi(10, 0)); a.beq('H1_GOT')
    a(_addi(6, 6, STRIDE)); a.bdnz('H1_FIND')
    a.b('H1_OUT')                                           # 슬롯이 없으면 그냥 포기(안전)
    a.label('H1_GOT')
    a(_stw(31, 0, 6))
    a(_mr(5, 31)); a(_lwz(7, KF, 12))
    a.bl('PATCH')
    a.label('H1_OUT')
    a(_lis(12, 0x8000)); a(_lwz(11, LRSV, 12)); a(_mtlr(11))
    a(H1_ORIG)                                              # 훔친 명령 or r3,r31,r31
    a(_blr())

    # ─────────── 훅2 : 폰트 소멸자 진입 (r26 = 객체)
    a.label('HOOK2')
    a(_lis(12, 0x8000))
    a(_mflr(11)); a(_stw(11, LRSV, 12))
    a(_lwz(11, N2, 12)); a(_addi(11, 11, 1)); a(_stw(11, N2, 12))
    a(_lwz(10, KF, 12)); a(_cmplw(26, 10)); a.bne('H2_ENG')
    #   한글 폰트가 죽는다 → 전 슬롯 원상복구 (이중 해제 차단)
    a(_li(0, 0)); a(_stw(0, KF, 12))
    for i in range(NSLOT):
        a(_addi(6, 12, SLOT0 + i * STRIDE))
        a(_lwz(5, 0, 6))
        a.bl('UNDO')
    a.b('H2_OUT')
    a.label('H2_ENG')
    #   패치해 둔 영문 폰트가 죽는가?
    a(_addi(9, 12, SLOT0))
    a(_li(0, NSLOT)); a(_mtctr(0))
    a.label('H2_FIND')
    a(_lwz(10, 0, 9)); a(_cmplw(26, 10)); a.beq('H2_HIT')
    a(_addi(9, 9, STRIDE)); a.bdnz('H2_FIND')
    a.b('H2_OUT')
    a.label('H2_HIT')
    a(_mr(5, 26)); a(_mr(6, 9))
    a.bl('UNDO')
    a(_li(0, 0)); a(_stw(0, 0, 9))                          # 슬롯 비우기
    a.label('H2_OUT')
    a(_lis(12, 0x8000)); a(_lwz(11, LRSV, 12)); a(_mtlr(11))
    a(H2_ORIG)                                              # 훔친 명령 lis r3,0x803A
    a(_blr())

    ws = a.out()
    if len(ws) * 4 > CODE_MAX:
        raise SystemExit('⛔ 케이브가 %d B 로 %d B 를 넘는다' % (len(ws) * 4, CODE_MAX))
    return ws, {k: CODE + v * 4 for k, v in a.lab.items()}


def b_form(frm, to, lk=0):
    d = (to - frm) & 0xFFFFFFFF
    if 0x02000000 <= d < 0xFE000000:
        raise SystemExit('⛔ 분기 거리 초과')
    return 0x48000000 | (d & 0x03FFFFFC) | lk


class Dol(object):
    def __init__(self, iso, mode='rb'):
        self.f = open(iso, mode)
        self.f.seek(0x420)
        self.base = struct.unpack('>I', self.f.read(4))[0]
        self.f.seek(self.base)
        h = self.f.read(0x100)
        self.seg = [(struct.unpack_from('>I', h, 0x00 + 4 * i)[0],
                     struct.unpack_from('>I', h, 0x48 + 4 * i)[0],
                     struct.unpack_from('>I', h, 0x90 + 4 * i)[0]) for i in range(18)]

    def iso(self, va):
        for o, a, s in self.seg:
            if s and a <= va < a + s:
                return self.base + o + (va - a)
        raise SystemExit('⛔ VA 0x%08X 가 어느 섹션에도 없다' % va)

    def rd(self, va):
        self.f.seek(self.iso(va))
        return struct.unpack('>I', self.f.read(4))[0]

    def wr(self, va, v):
        self.f.seek(self.iso(va))
        self.f.write(struct.pack('>I', v))


def plan():
    ws, labs = code_words()
    p = [(H1, H1_ORIG, b_form(H1, labs['HOOK1'], 1)),
         (H2, H2_ORIG, b_form(H2, labs['HOOK2'], 1))]
    for k, w in enumerate(ws):
        p.append((CODE + k * 4, 0x00000000, w))
    return p, labs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('iso')
    ap.add_argument('--show', action='store_true')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--reset', action='store_true')
    ap.add_argument('--asm', action='store_true', help='케이브를 워드로 찍어만 본다')
    a = ap.parse_args()

    ws, labs = code_words()
    if a.asm:
        print('케이브 %d 워드 (%d B / %d B)' % (len(ws), len(ws) * 4, CODE_MAX))
        for k, v in sorted(labs.items(), key=lambda x: x[1]):
            print('   %-8s 0x%08X' % (k, v))
        for k, w in enumerate(ws):
            print('   %08X  %08X' % (CODE + k * 4, w))
        return

    d = Dol(a.iso, 'r+b' if (a.apply or a.reset) else 'rb')
    print('DOL 위치 ISO 0x%08X · 케이브 %d 워드' % (d.base, len(ws)))
    items, _ = plan()

    if a.reset:
        for va, orig in ((H1, H1_ORIG), (H2, H2_ORIG)):
            cur = d.rd(va)
            if cur != orig:
                d.wr(va, orig); print('  ↩ 훅 VA %08X  %08X -> %08X' % (va, cur, orig))
        for k in range(CODE_MAX // 4):
            va = CODE + k * 4
            if d.rd(va):
                d.wr(va, 0); print('  ↩ 케이브 VA %08X 를 0 으로' % va)
        for k in range(FD_MAX // 4):
            va = FD + k * 4
            if d.rd(va):
                d.wr(va, 0); print('  ↩ 자료 VA %08X 를 0 으로' % va)
        d.f.close(); return

    if a.apply:
        # ★ 먼저 «전부» 검증한다 — 반만 깔리는 사고를 막는다
        for va, old, new in items:
            cur = d.rd(va)
            if cur not in (old, new):
                raise SystemExit('⛔ VA %08X 가 예상 밖이다 (현재 %08X · 원본 %08X). '
                                 '먼저 --reset 할 것' % (va, cur, old))
        for va, _, new in items:
            if d.rd(va) != new:
                d.wr(va, new)
        d.f.close()
        print('  ✅ 훅 2개 + 케이브 %d 워드 적용' % len(ws))
        return

    for va, old, new in items[:2]:
        cur = d.rd(va)
        st = '원본' if cur == old else ('적용됨' if cur == new else '⛔알수없음')
        print('  훅 VA %08X  현재 %08X  원본 %08X  패치 %08X  %s' % (va, cur, old, new, st))
    bad = [va for va, old, new in items[2:] if d.rd(va) != new]
    print('  케이브 %d 워드 중 다른 것 %d 개' % (len(ws), len(bad)))
    print('  자료 0x%08X~0x%08X : %s' % (FD, FD + FD_MAX,
          '전부 0' if not any(d.rd(FD + k * 4) for k in range(FD_MAX // 4)) else '값 있음(실행 흔적)'))


if __name__ == '__main__':
    main()
