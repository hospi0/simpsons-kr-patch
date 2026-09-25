# -*- coding: utf-8 -*-
"""텍스트 바이블(srr2.p3d)의 항목을 «색인»으로 지정해 새 문자열로 바꾼다.

  python tools/biblewrite.py <src.p3d> <dst.p3d> <번역.tsv> [--lang E]

번역 TSV : `색인<TAB>한국어`  (# 로 시작하는 줄은 주석)

## 규칙

- 디스크의 바이블은 **UTF-16LE** 다. 게임 로더가 적재하며 u16 단위로 뒤집어
  RAM 에서는 BE 가 된다 → [[feedback_loader_swaps_string_endianness]]
  ⛔ 여기서 BE 로 쓰면 안 된다. 고칠 것은 «RAM 에 쓰는 쪽»뿐이다.
- 새 문자열은 원문보다 «길면 안 된다». 문자열 영역은 NUL 종단으로 빽빽이 붙어 있어
  길어지면 다음 항목을 침범한다. 짧은 건 괜찮다(NUL 로 끝내면 나머지는 안 읽힌다).
- 버튼 아이콘 문자(`[ + ¡ ® ¿ µ § @ …`)는 그림 자리이므로 그대로 옮겨야 한다.
- `\\` 는 «줄바꿈»이다(튜토리얼 상자·목표문에서 확인). 자막 요소에서는 아니다.
"""
import argparse
import io
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import txtbible


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('tsv')
    ap.add_argument('--lang', default='E')
    a = ap.parse_args()

    d = bytearray(open(a.src, 'rb').read())
    Ls = txtbible.langs(bytes(d))
    L = [x for x in Ls if x['code'] == a.lang][0]
    # 문자열 영역의 «파일 안» 시작 위치를 되짚는다
    blob_off = bytes(d).find(L['blob'][:64], L['chunk'])
    if blob_off < 0:
        raise SystemExit('⛔ 문자열 영역 위치를 못 찾았다')

    rows = []
    for ln in io.open(a.tsv, encoding='utf-8'):
        ln = ln.rstrip('\n')
        if not ln.strip() or ln.lstrip().startswith('#'):
            continue
        idx, txt = ln.split('\t', 1)
        rows.append((int(idx), txt.replace('\\n', '\n')))

    ok = 0
    for idx, new in rows:
        old = txtbible.text(L, idx)
        if len(new) > len(old):
            raise SystemExit('⛔ [%d] 새 문자열이 더 길다 (%d > %d)\n    원문 %r\n    번역 %r'
                             % (idx, len(new), len(old), old, new))
        p = blob_off + L['offs'][idx]
        enc = new.encode('utf-16-le') + b'\x00\x00'
        d[p:p + len(enc)] = enc
        ok += 1
        print('  [%4d] %2d자 -> %2d자  %s' % (idx, len(old), len(new),
                                             new.replace('\n', '\\n')[:46]))

    open(a.dst, 'wb').write(bytes(d))
    print('%d항목 기록 · %d B -> %d B (%s)'
          % (ok, len(open(a.src, 'rb').read()), os.path.getsize(a.dst),
             '크기 불변 OK' if os.path.getsize(a.src) == os.path.getsize(a.dst) else '⛔크기 변함'))

    # 되읽어 검산
    d2 = open(a.dst, 'rb').read()
    L2 = [x for x in txtbible.langs(d2) if x['code'] == a.lang][0]
    bad = [i for i, t in rows if txtbible.text(L2, i) != t]
    print('되읽기 불일치 %d개%s' % (len(bad), (' -> %s' % bad[:5]) if bad else ' (전부 일치)'))


if __name__ == '__main__':
    main()
