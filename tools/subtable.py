# -*- coding: utf-8 -*-
"""자막 문자열표를 만들어 텍스트 바이블의 «영어 문자열 영역 뒤»에 덧붙인다.

  python tools/subtable.py <src.p3d> <dst.p3d> [--tsv work/dialog_all.tsv] [--row 0x44]

## 왜 «영어 슬롯 뒤»인가

- DOL 에는 80 KB 자리가 없다. 새 데이터 섹션은 아레나(힙) 시작 주소까지 손봐야 한다.
- ⛔ 안 쓰는 «스페인어 슬롯»에 넣는 수를 먼저 썼다가 실패했다 — 로더 `0x8020BD48` 이
  **선택된 언어 하나만 적재**하고 나머지는 통째로 건너뛴다(객체조차 안 만든다).
  그래서 S 언어 객체는 영원히 NULL 이었다.
- 반면 문자열 영역은 `blen`(언어 레코드 +0x18)만큼 «동적 할당»된다
  (`0x8020BE10 lwz r0,0x18(r29) → alloc → stw r3,0x28(r29)`).
  ⇒ **blen 을 키우면 그만큼 RAM 이 더 잡힌다.** 파일 크기가 커지지만
  `tools/isofile.py --replace` 가 미사용 영역으로 옮겨 준다.

## 찾는 법 (케이브)

표는 문자열 영역 «맨 뒤»에 놓고, 블롭의 마지막 u32 에 «표 시작 오프셋»을 적어 둔다.
케이브는 언어 객체에서 blen 과 blob 을 읽어 `[blob+blen-4]` 한 번만 보면 된다.
박아 둔 주소가 없으므로 번역이 바뀌어도 안 깨진다.

## 로더의 «u16 스왑»을 미리 상쇄한다

로더는 문자열 영역을 u16 단위로 바이트 교환해 올린다(디스크 LE → RAM BE).
표를 «RAM 에 올라간 모습»(전부 빅엔디안)으로 만든 뒤 통째로 u16 스왑해 디스크에 쓴다.
[[feedback_loader_swaps_string_endianness]]

## RAM 배치 (전부 빅엔디안)

```
표시작 +0x00  u32 rowbase   행 영역 시작(표 시작 기준 오프셋)
       +0x04  u32 count     항목 수
       +0x08  항목 count개 : u32 주제해시 · u16 줄색인 · u16 행번호 · u16 미션 · u16 레벨
       rowbase + 행번호*ROW*4 : 윗줄 ROW · 아랫줄 ROW · 합친줄 ROW*2 (UTF-16BE)
블롭 맨 끝 u32 = 표 시작 오프셋
```
★ 항목 +8 의 u32 = «미션<<16 | 레벨» — 케이브가 묶음노드 +4·+8 을 같은 모양으로 합쳐 한 번에 비교한다.

## 열쇠 (주제, 줄색인, 미션, 레벨) 는 «게임과 같은 규칙»으로 대사 이름에서 뽑는다

줄 노드 생성자 `0x80132A8C` → `0x80132E38` 이 리소스 이름(`C_count_1_noboxconv_Mil_L1R1`)을
`_` 로 쪼개 필드1=주제(해시 → +0x18) · 필드5=태그를 `0x80133324` 로 푼다:
```
+8 = 'L' 뒤 숫자(레벨, 1 기준 그대로)
M : +4 = 숫자      R : +4 = 숫자+8      B : +4 = 8      T : +4 = 12      태그가 «L숫자» 뿐 : +4 = 0
```
⛔ 예전 `dialog_all.tsv` 의 `미션색인`(대본 순서로 추정)은 이 규칙과 어긋났다 —
   레이스 전부(l1r1 을 8 로), 보너스(11/12), L2~L7 스토리(한 칸 작게). 이제 안 쓴다.
★ 이름의 대소문자는 `.spt` 그대로 써야 한다(주제 해시가 대소문자를 탄다 — `C_Gil_…`).
"""
import argparse
import io
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p3d
import txtbible

BSLASH = chr(92)   # 바이블의 줄바꿈 문자
LINE = 33          # 한 행 최대 글자수 (한글 기준, docs/02)
SPLIT = 16         # 이보다 길면 두 줄로 갈라 균형을 맞춘다
LANGCHUNK = 0x0001800E
BIBLECHUNK = 0x0001800D


def h31(s):
    """게임이 쓰는 해시 h = 31*h + c (부호 있는 char). DOL 0x801341E4 에서 읽었다."""
    h = 0
    for c in s.encode('latin-1'):
        if c > 127:
            c -= 256
        h = (h * 31 + c) & 0xFFFFFFFF
    return h


def game_fields(name):
    """리소스 이름 → (주제, 미션, 레벨). DOL 0x80132E38 · 0x80133324 를 그대로 옮겼다."""
    f = name.split('_')
    if f[0] != 'C' or len(f) < 6:
        raise SystemExit('⛔ 대화(C_…) 이름 형식이 아니다: %s' % name)
    tag = f[5]
    lv = mi = 0                                  # 기반 생성자 0x80136E3C 의 기본값
    if len(tag) >= 2 and tag[0] == 'L' and '0' <= tag[1] <= '9':
        lv = ord(tag[1]) - 0x30
        if len(tag) >= 4:
            mi = ord(tag[3]) - 0x30
            if tag[2] == 'B':
                mi = 8
            elif tag[2] == 'R':
                mi += 8
            elif tag[2] == 'T':
                mi = 12
    return f[1], mi, lv


def wrap2(s):
    """두 행으로 «반드시» 나눈다.

    ⛔ 아랫줄을 빈 문자열로 두면 안 된다 — 짧은 한 줄일 때 «같은 글이 두 줄에 겹쳐»
      나온다(docs/06 §7 의 미해결 증상). 시제품이 멀쩡했던 건 두 행을 늘 채웠기 때문.
      나눌 자리가 없는 한 낱말짜리 대사는 아랫줄에 «공백 한 칸»을 넣어 비우지 않는다.
    """
    s = s.strip()
    if len(s) > LINE:
        cut = s.rfind(' ', 0, LINE + 1)
        if cut <= 0:
            cut = LINE
    elif len(s) > SPLIT:
        # 어중간한 길이는 «가운데에 가장 가까운 공백»에서 갈라 두 줄 균형을 맞춘다
        mid = len(s) // 2
        cuts = [i for i, c in enumerate(s) if c == ' ']
        cut = min(cuts, key=lambda i: abs(i - mid)) if cuts else 0
    else:
        cut = 0                     # 아주 짧으면 윗줄에 몰고 아랫줄은 공백 한 칸
    top, bot = (s[:cut].rstrip(), s[cut:].strip()) if cut else (s, '')
    if not bot:
        bot = ' '
    if len(top) > LINE or len(bot) > LINE:
        raise ValueError('두 행에 안 들어간다(%d자): %s' % (len(s), s))
    return top, bot


def swap16(b):
    """u16 단위 바이트 교환 — 로더가 적재하며 한 번 더 뒤집으므로 상쇄된다."""
    if len(b) % 2:
        b += b'\0'
    return b''.join(b[i + 1:i + 2] + b[i:i + 1] for i in range(0, len(b), 2))


def build(tsv, row, spt):
    names = {}
    for l in io.open(spt, encoding='utf-8'):
        if l.strip():
            names[l.strip().lower()] = l.strip()
    rows = [l.rstrip('\n').split('\t') for l in io.open(tsv, encoding='utf-8')]
    h = rows[0]
    iF, iT, iO, iKR = h.index('파일명'), h.index('주제'), h.index('순서'), h.index('한국어')
    # ★ 두 줄 칸(Accept·Cancel)에는 «압축 전 원문», 한 줄 칸(Skip)에는 «압축본»을 넣는다.
    #   레터박스는 대화 종류마다 다른 요소를 띄우는데 어느 쪽인지 미리 알 수 없어서,
    #   두 벌을 다 넣어 두고 게임이 고르게 한다.
    iOR = h.index('원문') if '원문' in h else iKR
    ents, blob, seen, skipped = [], b'', {}, []
    for r in rows[1:]:
        if len(r) <= iKR or not r[iKR].strip():
            continue
        # ★ 엔진의 줄 색인은 «0 기준» 이다(첫 줄=0). 파일 이름의 _N_ 은 1 기준이라 1 을 뺀다.
        #   이걸 안 맞추면 자막이 «한 줄씩 늦게» 나온다.
        # ★ 주제·미션·레벨은 게임이 푸는 «리소스 이름»(.spt, 대소문자 그대로)에서 뽑는다.
        #   ⛔ tsv 의 `미션색인` 은 대본 순서 추정이라 규칙과 어긋났다 — 쓰지 않는다.
        base = r[iF][:-4] if r[iF].lower().endswith('.rsd') else r[iF]
        name = names.get(base.lower())
        if name is None:
            raise SystemExit('⛔ .spt 에 없는 대사 이름: %s' % r[iF])
        topic, mi, lv = game_fields(name)
        if topic.lower() != r[iT].lower():
            raise SystemExit('⛔ 주제가 tsv 와 다르다: %s vs %s' % (name, r[iT]))
        key = (h31(topic), int(r[iO]) - 1, mi, lv)
        if key in seen:
            if seen[key] != r[iKR]:
                skipped.append((r[iT], r[iO], r[iKR]))
            continue
        seen[key] = r[iKR]
        full = (r[iOR] if len(r) > iOR and r[iOR].strip() else r[iKR])
        top, bot = wrap2(full)
        # ★ 미션 중 대화의 레터박스는 «요소가 하나»뿐이라 한 칸에 두 줄을 담아야 한다.
        #   바이블의 줄바꿈 문자는 역슬래시다(튜토리얼 상자·목표문에서 확인).
        # ★ 이 요소는 «폭에서 저절로 접힌다»(GenericPrompt.Message 와 같은 조판).
        #   역슬래시는 글자로 찍히므로 쓰지 않는다 — 원문을 그대로 넣고 맡긴다.
        both = r[iKR].strip()          # 한 줄 칸 — 630 px 이하로 압축된 것
        for t, cap in ((top, row), (bot, row), (both, row * 2)):
            # ★ 표는 «RAM 에 올라간 모습» 그대로 만든다(전부 빅엔디안).
            e = t.encode('utf-16-be') + b'\0\0'
            if len(e) > cap:
                raise SystemExit('⛔ 행이 %d B 로 %d 를 넘는다: %r' % (len(e), cap, t))
            blob += e + b'\0' * (cap - len(e))
        ents.append(key + (len(ents),))
    return ents, blob, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--tsv', default='work/dialog_all.tsv')
    ap.add_argument('--row', type=lambda x: int(x, 0), default=0x44)
    ap.add_argument('--lang', default='E')
    ap.add_argument('--spt', default='work/spt_names.txt')
    a = ap.parse_args()

    ents, rowblob, skipped = build(a.tsv, a.row, a.spt)
    rowbase = 8 + len(ents) * 12
    tbl = struct.pack('>II', rowbase, len(ents))
    for k, i, mi, lv, n in ents:
        tbl += struct.pack('>IHHHH', k, i, n, mi, lv)
    tbl += rowblob
    tbl += b'\0' * ((-len(tbl)) % 4)
    print('항목 %d개 · 행 %d개 · 표 %d B (rowbase 0x%X · ROW 0x%X)'
          % (len(ents), len(ents) * 2, len(tbl), rowbase, a.row))
    if skipped:
        # 열쇠가 게임 규칙 그대로라 «같은 대사 두 번»이 아니면 나올 수 없다
        print('⚠️ 같은 열쇠에 다른 번역이 있어 «첫 것만» 남긴 줄 %d개:' % len(skipped))
        for s in skipped:
            print('   ', s)

    d = bytearray(open(a.src, 'rb').read())
    L = [x for x in txtbible.langs(bytes(d)) if x['code'] == a.lang][0]
    coff = L['chunk']                       # 이 언어의 0x0001800E 청크 위치
    cid, cdsz, ccsz = struct.unpack_from('<III', d, coff)
    assert cid == LANGCHUNK and cdsz == ccsz, '언어 청크가 잎이 아니다'
    blob_end = coff + ccsz                  # 문자열 영역 끝 = 청크 끝
    # 검증: 문자열 영역의 마지막 64 B 가 실제로 청크 끝에 붙어 있나
    if bytes(d[blob_end - 64:blob_end]) != bytes(L['blob'][-64:]):
        raise SystemExit('⛔ 문자열 영역이 청크 끝이 아니다 — 배치 가정이 틀렸다')

    payload = swap16(tbl + struct.pack('>I', 0))     # 자리만 잡고
    # 표 시작 오프셋 = 새 blen - (표 길이 + 4)
    newblen = L['blen'] + len(tbl) + 4
    tstart = L['blen']
    payload = swap16(tbl + struct.pack('>I', tstart))
    delta = len(payload)

    d[blob_end:blob_end] = payload
    # 청크 크기 갱신 : 이 언어 청크 · 부모 0x0001800D · 파일 머리
    struct.pack_into('<II', d, coff + 4, cdsz + delta, ccsz + delta)
    for depth, ccid, off, dsz, csz in p3d.walk(bytes(d), 12):
        if ccid == BIBLECHUNK and off < coff < off + csz + delta:
            struct.pack_into('<I', d, off + 8, csz + delta)
            break
    struct.pack_into('<I', d, 8, struct.unpack_from('<I', bytes(d), 8)[0] + delta)
    # blen (언어 레코드 +0x18) 갱신 — 이름 길이가 가변이라 파서가 준 값으로 되짚는다
    p = coff + 12
    ln = d[p]; p += 1 + ln + 1                       # 이름 + 언어코드
    n_, a_, blen_ = struct.unpack_from('<III', d, p)
    assert (n_, blen_) == (L['n'], L['blen']), 'blen 자리를 잘못 짚었다'
    struct.pack_into('<I', d, p + 8, newblen)

    open(a.dst, 'wb').write(bytes(d))
    print('%s 슬롯 문자열영역 %d B -> %d B (+%d) · 파일 %d B -> %d B'
          % (a.lang, L['blen'], newblen, delta, len(open(a.src, 'rb').read()), len(d)))

    # ── 되읽어 «RAM 에 올라갈 모습»으로 확인
    L2 = [x for x in txtbible.langs(open(a.dst, 'rb').read()) if x['code'] == a.lang][0]
    if L2['blen'] != newblen or len(L2['blob']) != newblen:
        raise SystemExit('⛔ 되읽은 blen 이 안 맞는다: %d / %d' % (L2['blen'], len(L2['blob'])))
    ram = swap16(bytes(L2['blob']))
    ts = struct.unpack_from('>I', ram, newblen - 4)[0]
    rb, cnt = struct.unpack_from('>II', ram, ts)
    k0, i0, n0, m0, l0 = struct.unpack_from('>IHHHH', ram, ts + 8)
    raw = ram[ts + rb: ts + rb + a.row]
    n = 0
    while n + 2 <= len(raw) and raw[n:n + 2] != b'\0\0':
        n += 2
    print('✅ 되읽기 표시작 0x%X · rowbase 0x%X · 항목 %d · 첫 항목 %08X#%d(L%d 미션%d)→행%d'
          % (ts, rb, cnt, k0, i0, l0, m0, n0))
    print('   첫 자막 %r' % raw[:n].decode('utf-16-be'))
    print('   기존 문자열 온전: %r' % txtbible.text(L2, 691))


if __name__ == '__main__':
    main()
