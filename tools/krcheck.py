# -*- coding: utf-8 -*-
"""번역 파일 검사·병합.

  python tools/krcheck.py                      # work/kr/*.tsv 검사
  python tools/krcheck.py --merge              # dialog_all.tsv 의 「한국어」 칸 채우기

## 자막 조판 상한 (실측)
한 줄 33자 · 자막 한 장 2줄 = **66자**. 넘으면 화면 밖으로 나간다.
→ [[feedback_line_width_limit_is_per_script]]
"""
import argparse
import glob
import io
import os
import re
import sys

CAP = 66
LINE = 33


def load():
    kr = {}
    for p in sorted(glob.glob('work/kr/dialog_kr_l*.tsv')):
        for ln in io.open(p, encoding='utf-8'):
            ln = ln.rstrip('\n')
            if not ln.strip() or ln.lstrip().startswith('#') or '\t' not in ln:
                continue
            name, txt = ln.split('\t', 1)
            kr['c_' + name + '.rsd'] = txt.strip()
    return kr


def wrap(t, w=LINE):
    """공백에서 두 줄로 접어 본다 — 두 줄 안에 들어가는지 확인용."""
    if len(t) <= w:
        return [t]
    cut = t.rfind(' ', 0, w + 1)
    if cut <= 0:
        cut = w
    return [t[:cut], t[cut:].strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--merge', action='store_true')
    ap.add_argument('--all', default='work/dialog_all.tsv')
    a = ap.parse_args()
    kr = load()
    print('번역 %d행' % len(kr))

    over = [(k, v) for k, v in kr.items() if len(v) > CAP]
    long2 = [(k, v) for k, v in kr.items()
             if len(v) <= CAP and any(len(x) > LINE for x in wrap(v))]
    print('  %d자 초과 : %d행' % (CAP, len(over)))
    for k, v in sorted(over, key=lambda x: -len(x[1]))[:12]:
        print('     %3d자  %-38s %s' % (len(v), k[2:-4][:38], v[:52]))
    if long2:
        print('  두 줄로 안 접히는 것 : %d행' % len(long2))
        for k, v in long2[:6]:
            print('     %3d자  %-38s %s' % (len(v), k[2:-4][:38], v[:52]))

    rows = [l.rstrip('\n').split('\t') for l in io.open(a.all, encoding='utf-8')]
    hdr, body = rows[0], [r for r in rows[1:] if len(r) >= 10]
    have = sum(1 for r in body if kr.get(r[0]))
    need = sum(1 for r in body if r[9])
    print('\n대상 %d행 중 번역 %d행 (%.0f%%)' % (need, have, 100.0 * have / max(1, need)))
    missing = [r[0] for r in body if r[9] and not kr.get(r[0])]
    if missing:
        from collections import Counter
        lv = Counter(re.search(r'_l(\d)', m).group(1) for m in missing
                     if re.search(r'_l(\d)', m))
        print('   아직 안 된 것 %d행 · 레벨별 %s' % (len(missing), dict(sorted(lv.items()))))

    if a.merge:
        with io.open(a.all, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\t'.join(hdr) + '\n')
            for r in body:
                r = r[:10] + [kr.get(r[0], '')]
                f.write('\t'.join(r) + '\n')
        print('-> %s 갱신' % a.all)


if __name__ == '__main__':
    main()
