# -*- coding: utf-8 -*-
"""GC ISO 안의 DOL 에 «코드 케이브 + 훅»을 심는다 (크기 불변 → FST 손 안 댐).

  python tools/dolhook.py <iso> --show
  python tools/dolhook.py <iso> --apply spy
  python tools/dolhook.py <iso> --revert spy
  python tools/dolhook.py <iso> --read           # 정찰 결과 자리를 ISO 에서 읽기(무의미, 참고용)

★ DOL 위치는 디스크 헤더 0x420 에서 읽는다 — 옮긴 DOL(0x600000) 에도 그대로 쓸 수 있다.

## spy — 「어느 대사에 어떤 값이 오는가」 정찰 훅

```
0x80132520  bl 0x80135308  ->  bl CAVE      (대사 재생 직전. r4=고른 대사 줄 객체, r30=이벤트ID)

CAVE = 0x80004888  (text0 의 0 구간 1,228 B — 예외벡터 템플릿 슬롯 꼬리 패딩)
    lis   r12, 0x8000
    stw   r4,  0x4A00(r12)     ; 대사 줄 객체 포인터
    stw   r30, 0x4A04(r12)     ; 이벤트 ID
    lwz   r11, 0x4A08(r12)
    addi  r11, r11, 1
    stw   r11, 0x4A08(r12)     ; 호출 횟수
                               ; ⛔ r0 을 쓰면 안 된다 — addi 의 rA=0 은 «상수 0» 이라
                               ;    addi r0,r0,1 이 li r0,1 로 인코딩된다
    b     0x80135308           ; LR 을 안 건드리므로 원래 자리로 복귀
```
r0·r11·r12 는 호출 규약상 «죽는» 레지스터라 안전하다.
관측 자리 SPY = 0x80004A00 (ptr) / 0x80004A04 (eventID) / 0x80004A08 (count)
"""
import argparse
import struct

CAVE = 0x80004888
SPY = 0x80004A00
CAVE_MAX = 0x4CC          # --reset 이 미는 범위 = 0 구간 전체(0x80004888~0x80004D54)
#   ⚠ 예전 0x480 은 0x80004D04 까지만 밀어 케이브4 끝(0x80004D08 blr)을 못 지웠다
CAVE2 = 0x800048C0        # 두 번째 케이브 (같은 0 구간 안)
CAVE3 = 0x80004900        # 세 번째 케이브 — 대화 «첫 줄»(색인 0) 잡기
CAVE4 = 0x80004B80        # 네 번째 케이브 — «자막 판정·조회·복사» 본체
#   ⚠ 예전 문자열 표 자리다. 표가 바이블로 옮겨가 비었고, 여기가 0 구간에서
#     가장 넓다(0x4B80~0x4D54 = 468 B). 케이브2·3 은 주소를 안 바꿨다(도구 호환).
TIMER = 0x8044A81C        # 단조 증가(게임큐브 타임베이스, 약 40.5MHz) — 겹친 호출 판정용
ST_LAST = 0x80004A44      # 마지막으로 자막을 바꾼 시각
ST_LTOPIC = 0x80004A3C    # 그때의 «주제 해시» — 겹침 판정은 «같은 주제»일 때만 (아래 cave4_words)
ST_N = 0x80004A48         # 바꾼 횟수(진단용)
ST_IDX = 0x80004A28       # 훅이 남긴 «줄 색인» — 자막 선택은 이걸로 (전역 카운터는 오염된다)
ROW = 0x44                # 한 행 68B = UTF-16 33자 + NUL (한글 한 줄 33자)
ST_NODE = 0x80004A2C      # 훅이 남긴 «대화 묶음 노드»
ST_TOPIC = 0x80004A30     # (진단용) 마지막으로 조회한 주제 해시
ST_MIS = 0x80004A38       # 윗 u16 = 묶음노드 +0x04 «미션» · 아랫 u16 = +0x08 «레벨»
#   둘 다 대사 이름 태그를 0x80133324 가 푼 값 (L1R1 → 미션 9·레벨 1, L2M3 → 3·2, L3 → 0·3)
LANG_S = 0x80004A34       # (미사용) 로더가 «선택된 언어 하나»만 올린다 — 0x8020BD48
LANG_BLEN = 0x18          # 언어 객체 +0x18 = 문자열영역 길이
HEAPLO = 0x7E000000       # 힙(MMU) 하한 — 포인터 검증용
# ── 자막 칸 주소를 «런타임에» 얻는다 (박아 두면 번역이 바뀔 때마다 깨진다)
LANG = 0x80004A4C         # 바이블 «영어 언어 객체» 포인터 보관함
CAVE5 = 0x80004A50        # 바이블 로더 훅 (언어 객체를 잡아 둔다)
BIBHOOK = 0x8020BE1C      # stw r3,0x28(r29)  — 문자열영역(blob) 대입 직후
BIBHOOK_ORIG = 0x907D0028
LANG_CODE = 0x45          # 'E'
#   언어 객체 : +0x10 언어코드 · +0x1c 항목수 · +0x20 키배열 · +0x24 오프셋표 · +0x28 문자열영역
LANG_OFFS, LANG_BLOB, LANG_CODEOFF = 0x24, 0x28, 0x10
IDX_L1 = 394              # ACCEPT_MISSION "Start Mission"  (자막 윗줄)
IDX_L2 = 136              # CANCEL         "Cancel"         (자막 아랫줄)
IDX_L3 = 405              # SKIP           "SKIP"
#   ⚠ 레터박스 바는 대화 종류마다 «다른 요소»를 띄운다.
#     미션 제안 대화 = ACCEPT_MISSION + CANCEL (두 줄)
#     미션 중 대화   = SKIP (한 줄)  ← 여기 안 쓰면 자막이 아예 안 보인다
# ⚠️ 텍스트 바이블 블롭의 RAM 시작 주소. **파일 크기를 바꾸면 힙 배치가 밀려 이 값이 변한다.**
#    (p3d 5개를 고쳤더니 0x808BC919 → 0x808C1001 로 +0x46E8 이동했다.)
#    확인법: RAM 에서 UTF-16 "Start Mission" 을 찾아 그 주소 - 0x9EAE.
#    ⛔ 배포판에서는 이렇게 박아 두면 안 된다 — 블롭 포인터를 런타임에 얻어야 한다.
# ★★★ RAM 의 텍스트 바이블은 UTF-16 «빅엔디안» 이다.
#     로더 0x8020BE60 이 문자열 영역을 read(dst, blen/2, 2) 로 «u16 단위 스왑»해 올린다
#     (키·오프셋 표는 size=4). 디스크의 p3d 는 LE 이고 «적재 시» 뒤집힌다.
#     ⛔ 그래서 RAM 에 쓸 때는 반드시 'utf-16-be' 다. LE 로 쓰면 영문만 우연히 맞고
#        (상위 바이트가 00 이라 한 칸 밀린 LE 와 제자리 BE 의 바이트열이 같다)
#        한글은 «앞 글자의 상위 바이트 | 이 글자의 하위 바이트» 로 읽혀 □ 가 된다.
#     ⛔ LE 패턴으로 RAM 을 검색하면 «한 바이트 늦은» 홀수 주소에 걸린다 → 반드시 -1.
BIBLE = 0x808C0918        # ← tools/rebase.py 로 실측한 값 (실행 중 게임에서)
#   ⚠ «짝수» 여야 한다. rebase.py 가 LE 패턴으로 찾으면 +1 된 홀수가 나오므로 1 을 뺀 값이다.
L1 = BIBLE + 0x9EAE       # 자막 윗줄 칸 (ACCEPT_MISSION "Start Mission")
L2 = BIBLE + 0x5EE0       # 자막 아랫줄 칸 (CANCEL "Cancel")
GAP = 0x00A00000          # 약 0.259초 — 이 안에 겹쳐 오는 훅은 «예약»으로 보고 무시
FIRSTHOOK = 0x801361FC    # 0x801361C4「대화 시작」 안, node->vfn2C(색인) 직전
FIRSTHOOK_ORIG = 0x809E002C  # lwz r4,0x2c(r30)   — LR 은 이미 0x14(r1) 에 있다
LINEHOOK = 0x8013643C     # 「줄 #색인 재생 시작」 0x80136430 의 4번째 명령
LINEHOOK_ORIG = 0x93E1003C   # stw r31,0x3c(r1)  — 여기서 LR 은 이미 스택에 저장돼 있다
HOOK = 0x80132520            # bl 0x80135308
PLAY = 0x80135308


def b_form(frm, to, lk=0):
    d = (to - frm) & 0xFFFFFFFF
    if d >= 0x02000000 and d < 0xFE000000:
        raise SystemExit('⛔ 분기 거리 초과')
    return 0x48000000 | (d & 0x03FFFFFC) | lk


def cave_words():
    a = CAVE
    w = []
    w.append(0x3C000000 | (12 << 21) | 0x8000)            # lis  r12,0x8000
    w.append(0x90000000 | (4 << 21) | (12 << 16) | 0x4A00)   # stw  r4,0x4A00(r12)
    w.append(0x90000000 | (30 << 21) | (12 << 16) | 0x4A04)  # stw  r30,0x4A04(r12)
    w.append(0x80000000 | (11 << 21) | (12 << 16) | 0x4A08)  # lwz  r11,0x4A08(r12)
    w.append(0x38000000 | (11 << 21) | (11 << 16) | 1)       # addi r11,r11,1
    w.append(0x90000000 | (11 << 21) | (12 << 16) | 0x4A08)  # stw  r11,0x4A08(r12)
    w.append(0x90000000 | (3 << 21) | (12 << 16) | 0x4A0C)   # stw  r3,0x4A0C(r12)
    w.append(0x90000000 | (5 << 21) | (12 << 16) | 0x4A10)   # stw  r5,0x4A10(r12)
    w.append(0x90000000 | (31 << 21) | (12 << 16) | 0x4A14)  # stw  r31,0x4A14(r12)
    w.append(b_form(a + len(w) * 4, PLAY))                   # b    0x80135308
    return w


class Dol(object):
    def __init__(self, iso, mode='rb'):
        self.f = open(iso, mode)
        self.f.seek(0x420)
        self.base = struct.unpack('>I', self.f.read(4))[0]
        self.f.seek(self.base)
        h = self.f.read(0x100)
        off = struct.unpack_from('>18I', h, 0x00)
        adr = struct.unpack_from('>18I', h, 0x48)
        siz = struct.unpack_from('>18I', h, 0x90)
        self.sec = [(off[i], adr[i], siz[i]) for i in range(18) if siz[i]]

    def iso(self, va):
        for o, a, s in self.sec:
            if a <= va < a + s:
                return self.base + o + (va - a)
        raise SystemExit('⛔ VA 0x%08X 는 어느 섹션에도 없다' % va)

    def rd(self, va):
        self.f.seek(self.iso(va))
        return struct.unpack('>I', self.f.read(4))[0]

    def wr(self, va, v):
        self.f.seek(self.iso(va))
        self.f.write(struct.pack('>I', v))


def cave2_words():
    """줄 단위 훅 — 0x80136430(r3=재생기, r4=줄 색인) 이 «줄마다 한 번» 불린다.

    관측 자리
      0x80004A20  이 훅의 호출 횟수
      0x80004A24  재생기
      0x80004A28  줄 색인          ← 0,1,2,… 로 늘어난다
      0x80004A2C  대화 묶음 노드   ([재생기+0x14])
    """
    return [
        LINEHOOK_ORIG,                                          # 밀어낸 명령
        0x3C000000 | (12 << 21) | 0x8000,                        # lis  r12,0x8000
        0x80000000 | (11 << 21) | (12 << 16) | 0x4A20,           # lwz  r11,0x4A20(r12)
        0x38000000 | (11 << 21) | (11 << 16) | 1,                # addi r11,r11,1
        0x90000000 | (11 << 21) | (12 << 16) | 0x4A20,           # stw  r11,0x4A20(r12)
        0x90000000 | (3 << 21) | (12 << 16) | 0x4A24,            # stw  r3,0x4A24(r12)
        0x90000000 | (4 << 21) | (12 << 16) | 0x4A28,            # stw  r4,0x4A28(r12)
        0x80000000 | (0 << 21) | (3 << 16) | 0x14,               # lwz  r0,0x14(r3)
        0x90000000 | (0 << 21) | (12 << 16) | 0x4A2C,            # stw  r0,0x4A2C(r12)
        # ── 고리 버퍼: 0x80004B00 부터 16칸 × 8B (색인, 묶음노드)
        #    호스트 폴링이 «같은 순간의 두 호출»을 흘리는 걸 원천 차단한다
        0x55601E78,                                              # rlwinm r0,r11,3,25,28  = (r11&0xF)<<3
        0x7D8C0214,                                              # add    r12,r12,r0
        0x90000000 | (4 << 21) | (12 << 16) | 0x4B00,            # stw    r4,0x4B00(r12)
        0x80000000 | (0 << 21) | (3 << 16) | 0x14,               # lwz    r0,0x14(r3)
        0x90000000 | (0 << 21) | (12 << 16) | 0x4B04,            # stw    r0,0x4B04(r12)
        0x4E800020,                                              # blr
    ]


def cave3_words():
    """대화 «첫 줄» 훅 — 첫 줄은 0x80136430 을 안 거치고 0x801361C4 에서 바로 재생된다.
    줄 훅과 «같은» 관측 자리·고리를 쓰므로 호스트는 구분 없이 순서대로 읽으면 된다."""
    return [
        FIRSTHOOK_ORIG,                                          # 밀어낸 lwz r4,0x2c(r30)
        0x3C000000 | (12 << 21) | 0x8000,                        # lis  r12,0x8000
        0x80000000 | (11 << 21) | (12 << 16) | 0x4A20,           # lwz  r11,0x4A20(r12)
        0x38000000 | (11 << 21) | (11 << 16) | 1,                # addi r11,r11,1
        0x90000000 | (11 << 21) | (12 << 16) | 0x4A20,           # stw  r11,0x4A20(r12)
        0x90000000 | (30 << 21) | (12 << 16) | 0x4A24,           # stw  r30,0x4A24(r12)
        0x90000000 | (4 << 21) | (12 << 16) | 0x4A28,            # stw  r4,0x4A28(r12)
        0x80000000 | (0 << 21) | (30 << 16) | 0x14,              # lwz  r0,0x14(r30)
        0x90000000 | (0 << 21) | (12 << 16) | 0x4A2C,            # stw  r0,0x4A2C(r12)
        0x55601E78,                                              # rlwinm r0,r11,3,25,28
        0x7D8C0214,                                              # add    r12,r12,r0
        0x90000000 | (4 << 21) | (12 << 16) | 0x4B00,            # stw    r4,0x4B00(r12)
        0x80000000 | (0 << 21) | (30 << 16) | 0x14,              # lwz    r0,0x14(r30)
        0x90000000 | (0 << 21) | (12 << 16) | 0x4B04,            # stw    r0,0x4B04(r12)
        0x4E800020,                                              # blr
    ]


# ── PPC 인코더 (최소한만)
def _lis(d, i):      return 0x3C000000 | (d << 21) | (i & 0xFFFF)
def _addi(d, a, x):  return 0x38000000 | (d << 21) | (a << 16) | (x & 0xFFFF)
def _lwz(d, o, a):   return 0x80000000 | (d << 21) | (a << 16) | (o & 0xFFFF)
def _stw(x, o, a):   return 0x90000000 | (x << 21) | (a << 16) | (o & 0xFFFF)
def _lbz(d, o, a):   return 0x88000000 | (d << 21) | (a << 16) | (o & 0xFFFF)
def _stb(x, o, a):   return 0x98000000 | (x << 21) | (a << 16) | (o & 0xFFFF)
def _subf(d, a, b):  return 0x7C000050 | (d << 21) | (a << 16) | (b << 11)
def _cmplw(a, b):    return 0x7C000040 | (a << 16) | (b << 11)
def _mulli(d, a, x): return 0x1C000000 | (d << 21) | (a << 16) | (x & 0xFFFF)
def _add(d, a, b):   return 0x7C000214 | (d << 21) | (a << 16) | (b << 11)
def _rlwinm(d, x, sh, mb, me): return 0x54000000 | (x << 21) | (d << 16) | (sh << 11) | (mb << 6) | (me << 1)
def _cmplwi(a, i):   return 0x28000000 | (a << 16) | (i & 0xFFFF)
def _lbzx(d, a, b):  return 0x7C0000AE | (d << 21) | (a << 16) | (b << 11)
def _lhz(d, o, a):   return 0xA0000000 | (d << 21) | (a << 16) | (o & 0xFFFF)
def _sth(x, o, a):   return 0xB0000000 | (x << 21) | (a << 16) | (o & 0xFFFF)
def _mtctr(x):       return 0x7C0903A6 | (x << 21)
def _bc(bo, bi, off): return 0x40000000 | (bo << 21) | (bi << 16) | (off & 0xFFFC)
def _ha(v):          return (v >> 16) + (1 if (v & 0x8000) else 0)   # addi 로 이어붙일 상위


def cave5_words():
    """바이블 로더 훅 — «영어» 언어 객체 포인터를 잡아 둔다.

    0x8020BE1C 는 `stw r3,0x28(r29)` (문자열영역 대입). 그 자리에서 r29 가 언어 객체다.
    ⛔ 「다섯 언어가 차례로 올라온다」는 틀렸다 — 로더 0x8020BD48 이 «선택된 언어
       하나»만 만들고 나머지는 객체조차 안 만든다. 그래서 코드 검사는 사실상 형식이다.
    ⛔ r12·r0 만 쓴다(그 직후 코드가 곧바로 덮어쓰는 레지스터라 안전).
    """
    return [
        BIBHOOK_ORIG,                                   # stw r3,0x28(r29)  (원래 명령)
        _lis(12, 0x8000),
        _lbz(0, LANG_CODEOFF, 29),                      # lbz r0,0x10(r29)
        _cmplwi(0, 0x45),                               # 'E'
        _bc(4, 2, 8),                                   # bne +8
        _stw(29, LANG & 0xFFFF, 12),
        b_form(CAVE5 + 6 * 4, BIBHOOK + 4),             # 원래 자리로 복귀
    ]


def cave4_words():
    """자막 본체 — 「겹친 호출이면 무시 · (주제·줄색인·미션·레벨)로 표를 찾아 복사」.

    ★ 키에 «미션»과 «레벨»이 들어간다. 경주 진행자(밀하우스·넬슨·랄프)는 주제·줄색인이
      모두 같고, 레벨이 다른 같은 순번 레이스는 미션까지 같다. 묶음노드 +0x04·+0x08 이
      그 둘이다(대사 이름 태그에서 게임이 직접 푼 값이라 표도 같은 규칙으로 만든다).
    ⛔ r3·r4 는 안 건드린다(두 훅 자리 모두 인수가 살아 있다).
       쓰는 것은 r0·r8·r9·r10·r11·r12 + CTR·CR0.
    ⚠️ 여섯뿐이라 훑는 동안 표 주소를 못 들고 있는다 → 찾은 뒤 다시 계산한다.
    표 배치(RAM, BE) : +0 rowbase · +4 count · +8 [u32 주제 · u16 색인 · u16 행 · u16 미션 · u16 레벨]
    """
    w = []

    def here():
        return CAVE4 + len(w) * 4

    def patch(at, ins):
        w[at] = ins

    def table(dst, tmp):
        """dst = 표 시작 주소 (언어 객체 → 블롭 → 블롭 맨 끝 u32 = 표 오프셋)

        ⛔ 주소 레지스터로 r0 을 쓰면 안 된다 — rA=0 은 «상수 0» 으로 인코딩된다.
           그래서 끝 주소를 tmp 에 담아 거기서 읽는다.
        """
        return [_lwz(dst, LANG & 0xFFFF, 12),
                _lwz(tmp, LANG_BLEN, dst),
                _lwz(dst, LANG_BLOB, dst),
                _add(tmp, dst, tmp),      # tmp = 블롭 끝
                _lwz(tmp, 0xFFFC, tmp),   # 표 오프셋
                _add(dst, dst, tmp)]

    w.append(_lis(12, 0x8000))
    w.append(_lwz(11, LANG & 0xFFFF, 12))
    w.append(_cmplwi(11, 0))
    beq_e = len(w); w.append(0)

    # ── 묶음 노드에서 «미션·레벨»과 «주제 해시» (겹침 판정에 주제가 필요해 먼저 읽는다)
    w.append(_lis(8, HEAPLO >> 16))
    w.append(_lwz(10, ST_NODE & 0xFFFF, 12))
    w.append(_cmplw(10, 8))
    blt_n1 = len(w); w.append(0)
    w.append(_lwz(0, 4, 10))                        # +0x04 = 미션
    w.append(_sth(0, ST_MIS & 0xFFFF, 12))          #   → ST_MIS 윗 u16
    w.append(_lwz(0, 8, 10))                        # +0x08 = 레벨
    w.append(_sth(0, (ST_MIS + 2) & 0xFFFF, 12))    #   → ST_MIS 아랫 u16
    w.append(_lwz(10, 0x18, 10))                    # 첫 줄 노드
    w.append(_cmplw(10, 8))
    blt_n2 = len(w); w.append(0)
    w.append(_lwz(10, 0x18, 10))                    # r10 = 주제 해시
    w.append(_stw(10, ST_TOPIC & 0xFFFF, 12))

    # ── 겹침 판정 : «0.26초 안» 이고 «같은 주제»일 때만 예약 호출로 보고 버린다
    #   경계마다 훅이 두 번 오는데(docs/06 §8) 뒤의 것은 «같은 대화»의 다음 줄 예약이다.
    #   ⛔ 예전엔 주제를 안 봐서, 다른 대화가 0.26초 안에 이어지면 그 첫 줄을 버렸다
    #      (L1M7 완료대사 `there` 직후의 `accuse` 첫 줄 — 직전 자막이 레이스 내내 남아 보였다).
    #   ★ 노드 주소가 아니라 주제로 가른다 — 해제된 노드 자리에 새 노드가 같은 주소로 올 수 있다.
    w.append(_lis(9, _ha(TIMER)))
    w.append(_lwz(9, TIMER & 0xFFFF, 9))
    w.append(_lwz(0, ST_LAST & 0xFFFF, 12))
    w.append(_subf(0, 0, 9))
    w.append(_lis(11, GAP >> 16))
    w.append(_cmplw(0, 11))
    bge_gap = len(w); w.append(0)
    w.append(_lwz(0, ST_LTOPIC & 0xFFFF, 12))
    w.append(_cmplw(0, 10))
    beq_same = len(w); w.append(0)
    passed = here()
    w.append(_stw(9, ST_LAST & 0xFFFF, 12))
    w.append(_stw(10, ST_LTOPIC & 0xFFFF, 12))
    w.append(_lwz(8, ST_N & 0xFFFF, 12))
    w.append(_addi(8, 8, 1))
    w.append(_stw(8, ST_N & 0xFFFF, 12))

    # ── 표 훑기 : r8 항목 · r9 미션<<16|레벨 · r10 주제 · r11 줄색인
    w += table(9, 8)
    w.append(_lwz(0, 4, 9))
    w.append(_cmplwi(0, 0))
    beq_cnt = len(w); w.append(0)
    w.append(_mtctr(0))
    w.append(_addi(8, 9, 8))
    w.append(_lwz(11, ST_IDX & 0xFFFF, 12))
    w.append(_lwz(9, ST_MIS & 0xFFFF, 12))          # 표 주소는 버린다(뒤에서 재계산)
    loop = here()
    w.append(_lwz(0, 0, 8))
    w.append(_cmplw(0, 10))
    bne_k = len(w); w.append(0)
    w.append(_lhz(0, 4, 8))
    w.append(_cmplw(0, 11))
    bne_i = len(w); w.append(0)
    # ★ 미션·레벨은 항목 +8 의 u32 하나로 한 번에 비교한다.
    #   (예전 «0xFFFF 와일드카드»는 없앴다 — 표를 게임과 같은 태그 규칙으로 만들므로
    #    미션을 «모르는» 줄이 더는 없다. 556줄 열쇠 충돌 0.)
    w.append(_lwz(0, 8, 8))
    w.append(_cmplw(0, 9))
    beq_hit = len(w); w.append(0)
    nxt = here()
    w.append(_addi(8, 8, 12))
    w.append(_bc(16, 0, loop - here()))
    b_clear = len(w); w.append(0)

    # ── 찾음
    hit = here()
    w.append(_lhz(11, 6, 8))                        # r11 = 행 번호
    w += table(9, 8)                                # r9 = 표 주소 (재계산)
    w.append(_mulli(11, 11, ROW * 4))
    w.append(_lwz(0, 0, 9))                         # rowbase
    w.append(_add(11, 11, 0))
    w.append(_add(10, 9, 11))                       # r10 = 원본
    w.append(_lwz(11, LANG & 0xFFFF, 12))
    w.append(_lwz(8, LANG_OFFS, 11))
    w.append(_lwz(11, LANG_BLOB, 11))
    for idx, ln in ((IDX_L1, ROW), (IDX_L2, ROW), (IDX_L3, ROW * 2)):
        w.append(_lwz(0, idx * 4, 8))
        w.append(_rlwinm(0, 0, 0, 0, 30))
        w.append(_add(9, 11, 0))
        w.append(_addi(0, 0, ln))
        w.append(_mtctr(0))
        top = here()
        w.append(_lbz(0, 0, 10))
        w.append(_stb(0, 0, 9))
        w.append(_addi(10, 10, 1))
        w.append(_addi(9, 9, 1))
        w.append(_bc(16, 0, top - here()))
    b_end = len(w); w.append(0)

    clear = here()
    skip = here()
    w.append(0x4E800020)                            # blr

    def rel(at, to):
        return to - (CAVE4 + at * 4)
    patch(bge_gap, _bc(4, 0, rel(bge_gap, passed)))     # bge — 0.26초 밖이면 통과
    patch(beq_same, _bc(12, 2, rel(beq_same, skip)))    # 같은 주제의 겹침만 버림
    patch(beq_e, _bc(12, 2, rel(beq_e, skip)))
    patch(blt_n1, _bc(12, 0, rel(blt_n1, clear)))
    patch(blt_n2, _bc(12, 0, rel(blt_n2, clear)))
    patch(beq_cnt, _bc(12, 2, rel(beq_cnt, clear)))
    patch(bne_k, _bc(4, 2, rel(bne_k, nxt)))
    patch(bne_i, _bc(4, 2, rel(bne_i, nxt)))
    patch(beq_hit, _bc(12, 2, rel(beq_hit, hit)))
    patch(b_clear, b_form(CAVE4 + b_clear * 4, clear))
    patch(b_end, b_form(CAVE4 + b_end * 4, skip))
    return w


# 시제품 문구 — 「음성 시작 하나 = 자막 한 장」 규칙에 맞춰 압축했다(docs/06 §8)
SUBS = [
    ("마지: 디저트를 다 먹었어.",
     "아이스크림 사 와."),
    ("호머: 애들 중 하나겠지.",
     "밀하우스일 거야."),
]


def table_words():
    b = b''
    for top, bot in SUBS:
        for row in (top, bot):
            e = row.encode('utf-16-be') + bytes(2)   # ★BE — 파일 머리 설명 참조
            if len(e) > ROW:
                raise SystemExit('⛔ 행이 %d B 로 %d B 를 넘는다: %r' % (len(e), ROW, row))
            b += e + bytes(ROW - len(e))
    return [struct.unpack_from('>I', b, i)[0] for i in range(0, len(b), 4)]


def plan(names=('spy', 'line', 'first', 'sub')):
    """[(VA, 원본워드, 새워드), ...]"""
    p = []
    if 'spy' in names:
        p.append((HOOK, b_form(HOOK, PLAY, 1), b_form(HOOK, CAVE, 1)))
        for k, w in enumerate(cave_words()):
            p.append((CAVE + k * 4, 0x00000000, w))
    if 'line' in names:
        p.append((LINEHOOK, LINEHOOK_ORIG, b_form(LINEHOOK, CAVE2, 1)))
        for k, w in enumerate(cave2_words()):
            p.append((CAVE2 + k * 4, 0x00000000, w))
    if 'first' in names:
        p.append((FIRSTHOOK, FIRSTHOOK_ORIG, b_form(FIRSTHOOK, CAVE3, 1)))
        for k, w in enumerate(cave3_words()):
            p.append((CAVE3 + k * 4, 0x00000000, w))
    if 'sub' in names:
        # ★ 자막 칸 주소를 런타임에 얻기 위한 바이블 로더 훅 (없으면 케이브가 아무것도 안 쓴다)
        p.append((BIBHOOK, BIBHOOK_ORIG, b_form(BIBHOOK, CAVE5)))
        for k, w in enumerate(cave5_words()):
            p.append((CAVE5 + k * 4, 0x00000000, w))
        # 두 케이브의 마지막 blr 을 «자막 본체로 이어달기»로 바꾼다
        for base, ws in ((CAVE2, cave2_words()), (CAVE3, cave3_words())):
            va = base + (len(ws) - 1) * 4
            p.append((va, 0x4E800020, b_form(va, CAVE4)))
        for k, w in enumerate(cave4_words()):
            p.append((CAVE4 + k * 4, 0x00000000, w))
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('iso')
    ap.add_argument('--show', action='store_true')
    ap.add_argument('--apply', nargs='*', default=[])
    ap.add_argument('--revert', nargs='*', default=[])
    ap.add_argument('--reset', action='store_true',
                    help='케이브를 «내용에 상관없이» 0 으로 밀고 훅을 원본으로 되돌린다 '
                         '(케이브 정의를 바꿔 재적용할 때. 무엇을 덮었는지 전부 출력한다)')
    a = ap.parse_args()
    rw = bool(a.apply or a.revert or a.reset)
    d = Dol(a.iso, 'r+b' if rw else 'rb')
    print('DOL 위치 ISO 0x%08X' % d.base)
    items = plan(tuple(a.apply) or tuple(a.revert) or ('spy', 'line', 'first', 'sub'))
    if not rw:
        for va, old, new in items:
            cur = d.rd(va)
            st = '원본' if cur == old else ('적용됨' if cur == new else '⛔알수없음')
            print('  VA %08X (ISO 0x%09X)  현재 %08X  원본 %08X  패치 %08X  %s'
                  % (va, d.iso(va), cur, old, new, st))
        return
    if a.reset:
        cur = d.rd(HOOK)
        if cur != b_form(HOOK, PLAY, 1):
            d.wr(HOOK, b_form(HOOK, PLAY, 1))
            print('  ↩ 훅 VA %08X  %08X -> %08X' % (HOOK, cur, b_form(HOOK, PLAY, 1)))
        for nm, va, orig in (('줄훅', LINEHOOK, LINEHOOK_ORIG), ('첫줄훅', FIRSTHOOK, FIRSTHOOK_ORIG),
                             ('바이블훅', BIBHOOK, BIBHOOK_ORIG)):
            cur = d.rd(va)
            if cur != orig:
                d.wr(va, orig)
                print('  ↩ %s VA %08X  %08X -> %08X' % (nm, va, cur, orig))
        for k in range(CAVE_MAX // 4):
            va = CAVE + k * 4
            cur = d.rd(va)
            if cur:
                d.wr(va, 0)
                print('  ↩ 케이브 VA %08X  %08X -> 00000000' % (va, cur))
        d.f.close()
        return
    if a.apply:
        for va, old, new in items:
            cur = d.rd(va)
            if cur == new:
                print('  이미 적용됨 VA %08X' % va); continue
            if cur != old:
                raise SystemExit('⛔ VA %08X 원본이 아니다: %08X (기대 %08X)' % (va, cur, old))
        for va, old, new in items:
            d.wr(va, new)
            print('  ✅ VA %08X  %08X -> %08X' % (va, old, new))
    if a.revert:
        for va, old, new in items:
            cur = d.rd(va)
            if cur == old:
                continue
            if cur != new:
                raise SystemExit('⛔ VA %08X 패치본이 아니다: %08X' % (va, cur))
            d.wr(va, old)
            print('  ↩ VA %08X  %08X -> %08X' % (va, new, old))
    d.f.close()


if __name__ == '__main__':
    main()
