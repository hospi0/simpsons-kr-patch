# -*- coding: utf-8 -*-
"""자막 칸 주소가 밀렸을 때, 실행 중인 게임의 케이브 상수를 «현재 주소»로 고쳐 넣는다.

  python tools/rebase.py            # 찾아서 고침
  python tools/rebase.py --dry      # 찾기만

원리
  텍스트 바이블 블롭은 힙에 올라가므로 **파일 크기를 바꾸면 시작 주소가 밀린다.**
  RAM 에서 UTF-16«BE» 기준 문자열을 찾아 블롭 시작을 역산한다.
  케이브의 `lis r9,hi / addi r9,r9,lo` 두 쌍(윗줄·아랫줄)을 새 주소로 다시 쓴다.

⚠️ 돌핀은 호스트가 쓴 코드 변경을 JIT 에 반영하지 않는다.
   **그 코드가 아직 한 번도 실행되지 않았을 때**(= 첫 대사 전) 고쳐야 한다.
⛔ 임시 수단이다. 배포판은 블롭 포인터를 런타임에 얻어야 한다.
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dolmem import Dolphin

# ★★★ RAM 의 텍스트 바이블은 UTF-16 «빅엔디안» 이다.
#     로더 0x8020BE60 이 문자열 영역을 read(dst, blen/2, 2) 로 «u16 단위 스왑»해 올린다
#     (키·오프셋 표는 size=4). 디스크의 p3d 는 LE 이고 «적재 시» 뒤집힌다.
#     ⛔ RAM 에 쓸 때는 반드시 'utf-16-be'. LE 로 쓰면 영문만 우연히 맞고
#        한글은 «앞 글자의 상위 바이트 | 이 글자의 하위 바이트» 로 읽혀 □ 가 된다.
#     ⛔ LE 패턴으로 RAM 을 검색하면 «한 바이트 늦은» 홀수 주소에 걸린다 → 반드시 -1.
L1_LIS, L1_ADDI = 0x80004984, 0x80004988
L2_LIS, L2_ADDI = 0x800049A8, 0x800049AC
# ★ 자막 칸의 «블롭 내 오프셋» (srr2.p3d 영어 블롭에서 실측)
OFF_L1, OFF_L2 = 0x06B4E, 0x02B80          # "Start Mission" / "Cancel"
# ⛔ 기준을 자막 칸으로 잡으면 안 된다 — 케이브가 덮어쓰고 나면 사라진다.
#    «절대 안 건드리는» 문자열을 기준으로 블롭 시작을 역산한다.
ANCHOR = 'Unable to load The Simpsons Hit & Run saved game.'
ANCHOR_OFF = 0x00598


def enc_lis(r, v):
    return 0x3C000000 | (r << 21) | ((((v >> 16) + (1 if v & 0x8000 else 0))) & 0xFFFF)


def enc_addi(r, v):
    return 0x38000000 | (r << 21) | (r << 16) | (v & 0xFFFF)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()
    d = Dolphin()
    mem = d.read(0x80000000, 0x1800000)
    # ★ RAM 은 UTF-16 BE 다(로더 0x8020BE60 이 u16 단위로 스왑해 올린다).
    #   BE 패턴으로 «직접» 찾는다 — 이 검색이 성공한다는 것 자체가 엔디안 확인이다.
    pat = ANCHOR.encode('utf-16-be')
    i = mem.find(pat)
    if i < 0:
        j = mem.find(ANCHOR.encode('utf-16-le'))
        if j >= 0:
            raise SystemExit('⛔ RAM 이 «리틀엔디안»으로 들어 있다 (0x%08X). '
                             '엔디안 가정이 틀렸으니 도구를 다시 볼 것.' % (0x80000000 + j))
        raise SystemExit('★기준 문자열을 못 찾았다 — 게임이 실행 중이어야 한다')
    if mem.find(pat, i + 1) >= 0:
        print('⚠ 기준 문자열이 여러 곳에 있다 — 첫 것을 쓴다')
    blob = 0x80000000 + i - ANCHOR_OFF
    if blob % 2:
        raise SystemExit('⛔ 블롭 시작이 홀수(%08X) — 엔디안·오프셋 가정을 다시 볼 것' % blob)
    l1, l2 = blob + OFF_L1, blob + OFF_L2
    print('블롭 시작 %08X · 자막칸 L1 %08X · L2 %08X' % (blob, l1, l2))
    print('  L1 현재: %r' % d.read(l1, 32).decode('utf-16-be', 'replace').split(chr(0))[0])
    print('  L2 현재: %r' % d.read(l2, 32).decode('utf-16-be', 'replace').split(chr(0))[0])
    cur = struct.unpack('>4I', d.read(L1_LIS, 4) + d.read(L1_ADDI, 4)
                        + d.read(L2_LIS, 4) + d.read(L2_ADDI, 4))
    want = (enc_lis(9, l1), enc_addi(9, l1), enc_lis(9, l2), enc_addi(9, l2))
    for (va, c, w) in zip((L1_LIS, L1_ADDI, L2_LIS, L2_ADDI), cur, want):
        print('  %08X  %08X -> %08X %s' % (va, c, w, '(그대로)' if c == w else ''))
    if a.dry:
        return
    for va, w in zip((L1_LIS, L1_ADDI, L2_LIS, L2_ADDI), want):
        d.write(va, struct.pack('>I', w))
    print('고쳐 넣었다. 이제 말을 거세요.')


if __name__ == '__main__':
    main()
