# -*- coding: utf-8 -*-
"""텍스트 바이블(srr2.p3d)의 한 언어 슬롯을 «통째로 다시 짠다».

  python tools/biblebuild.py <src.p3d> <dst.p3d> <번역.tsv> [--lang E] [--big 394=200 ...]

`biblewrite.py` 는 «원문보다 길면 안 된다»는 제약이 있다(문자열이 빽빽이 붙어 있어서).
이 도구는 오프셋 표 `off[n]` 을 다시 계산하므로 그 제약이 없다.

## 안전 규칙
- 항목 수 `n`·키 표 `key[n]`·문자열영역 크기 `blen` 은 «그대로» 둔다.
  ⇒ 청크 크기도 파일 크기도 안 변한다 (FST·ISO 배치에 영향 없음).
- 새 문자열 영역이 `blen` 을 넘으면 «거부»한다. 남는 자리는 0 으로 채운다.
- 디스크는 **UTF-16LE**. 로더가 u16 단위로 뒤집어 RAM 에서 BE 가 된다.
  ⛔ 여기서 BE 로 쓰면 안 된다 → [[feedback_loader_swaps_string_endianness]]
- `--big 색인=글자수` : 그 칸을 «넉넉히» 잡아 둔다(자막 케이브가 덮어쓸 칸 등).
  런타임에 긴 문자열을 memcpy 하려면 뒤쪽에 여유가 있어야 이웃 문자열을 안 깬다.
"""
import argparse
import io
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import txtbible


def load_tsv(path):
    tr = {}
    for ln, line in enumerate(io.open(path, encoding='utf-8'), 1):
        line = line.rstrip('\n')
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        k, v = line.split('\t', 1)
        tr[int(k)] = v
    return tr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('tsv')
    ap.add_argument('--lang', default='E')
    ap.add_argument('--big', action='append', default=[],
                    help='색인=글자수 — 그 칸을 그만큼 넉넉히 잡는다')
    a = ap.parse_args()

    big = {}
    for s in a.big:
        i, n = s.split('=')
        big[int(i)] = int(n)

    d = bytearray(open(a.src, 'rb').read())
    Ls = txtbible.langs(bytes(d))
    L = [x for x in Ls if x['code'] == a.lang][0]
    n, blen = L['n'], L['blen']

    # 파일 안에서 off[] 표와 문자열 영역의 실제 위치를 되짚는다
    blob_off = bytes(d).find(bytes(L['blob'][:64]), L['chunk'])
    if blob_off < 0:
        raise SystemExit('⛔ 문자열 영역을 파일에서 못 찾았다')
    offs_off = blob_off - 4 * n
    keys_off = offs_off - 4 * n
    if struct.unpack_from('<%dI' % n, d, offs_off) != tuple(L['offs']):
        raise SystemExit('⛔ 오프셋 표 위치가 안 맞는다')
    if struct.unpack_from('<%dI' % n, d, keys_off) != tuple(L['keys']):
        raise SystemExit('⛔ 키 표 위치가 안 맞는다')

    tr = load_tsv(a.tsv)
    unknown = [i for i in tr if not 0 <= i < n]
    if unknown:
        raise SystemExit('⛔ 범위 밖 색인: %s' % unknown[:10])

    out = bytearray()
    new_offs = [0] * n
    changed = 0
    for i in range(n):
        s = tr.get(i)
        if s is None:
            s = txtbible.text(L, i)
        else:
            changed += 1
        new_offs[i] = len(out)
        b = s.encode('utf-16-le') + b'\0\0'
        pad = big.get(i, 0)
        if pad:
            b += b'\0' * max(0, (pad + 1) * 2 - len(b))
        out += b

    print('%s 슬롯 : 항목 %d · 바꾼 것 %d' % (a.lang, n, changed))
    print('문자열 영역 %d B -> %d B  (한도 %d B, 남는 자리 %d B)'
          % (blen, len(out), blen, blen - len(out)))
    if len(out) > blen:
        raise SystemExit('⛔ %d B 넘쳤다 — 줄이거나 --big 을 줄여라' % (len(out) - blen))
    out += b'\0' * (blen - len(out))

    struct.pack_into('<%dI' % n, d, offs_off, *new_offs)
    d[blob_off:blob_off + blen] = out

    open(a.dst, 'wb').write(bytes(d))
    print('-> %s  (%d B, 원본과 같은 크기: %s)'
          % (a.dst, len(d), 'O' if len(d) == os.path.getsize(a.src) else 'X'))

    # 되읽어 확인
    L2 = [x for x in txtbible.langs(open(a.dst, 'rb').read()) if x['code'] == a.lang][0]
    bad = [i for i in sorted(tr) if txtbible.text(L2, i) != tr[i]]
    if bad:
        raise SystemExit('⛔ 되읽기 불일치 %d행: %s' % (len(bad), bad[:10]))
    print('✅ 되읽기 %d행 전부 일치' % len(tr))


if __name__ == '__main__':
    main()
