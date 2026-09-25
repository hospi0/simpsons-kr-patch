# -*- coding: utf-8 -*-
"""레벨별 정렬 결과를 하나로 합치고 통계를 낸다.

  python tools/dlgall.py --out work/dialog_all.tsv

`work/dialog_lN.tsv` 들을 읽어 «번역용 한 장»으로 만든다.
`한국어` 칸은 비워 두니 거기에 번역을 채우면 된다.
"""
import argparse
import glob
import io
import os
import re
from collections import Counter


def cls_of(tag):
    if re.fullmatch(r'l\dt\d', tag):
        return '튜토리얼'
    if re.fullmatch(r'l\dr\d', tag):
        return '레이스'
    if re.fullmatch(r'l\db\d', tag):
        return '보너스'
    if re.fullmatch(r'l\d', tag):
        return '레벨도입'
    return '미션'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='work/dialog_all.tsv')
    a = ap.parse_args()

    rows = []
    for p in sorted(glob.glob('work/dialog_l?.tsv')):
        lv = int(re.search(r'l(\d)\.tsv$', p).group(1))
        for ln in io.open(p, encoding='utf-8'):
            c = ln.rstrip('\n').split('\t')
            if c[0] == '파일명' or len(c) < 8:
                continue
            rows.append([lv] + c)

    tot, miss = Counter(), Counter()
    for r in rows:
        k = cls_of(r[2])
        tot[k] += 1
        if not r[8]:
            miss[k] += 1

    print('레벨1~%d · 클립 %d개 · 원문 확보 %d개 (%.0f%%)'
          % (max(r[0] for r in rows), len(rows),
             len(rows) - sum(miss.values()),
             100.0 * (len(rows) - sum(miss.values())) / len(rows)))
    print('\n%-10s %6s %6s %6s' % ('구분', '전체', '확보', '미확보'))
    for k in ('미션', '레이스', '레벨도입', '보너스', '튜토리얼'):
        if tot[k]:
            print('%-10s %6d %6d %6d' % (k, tot[k], tot[k] - miss[k], miss[k]))

    with io.open(a.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write('파일명\t레벨\t구분\t태그\t주제\t순서\t화자\t미션\t방식\t영문\t한국어\n')
        for r in sorted(rows, key=lambda r: (r[0], r[2], r[3], int(r[4]))):
            # r = [레벨, 파일명, 태그, 주제, 순서, 화자, 미션, 방식, 영문]
            f.write('%s\t%d\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t\n'
                    % (r[1], r[0], cls_of(r[2]), r[2], r[3], r[4], r[5], r[6], r[7], r[8]))
    print('\n-> %s  (%d줄, 「한국어」 칸 비어 있음)' % (a.out, len(rows)))


if __name__ == '__main__':
    main()
