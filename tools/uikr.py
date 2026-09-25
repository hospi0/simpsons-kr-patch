# -*- coding: utf-8 -*-
"""UI 번역 조각(work/kr/ui/*.tsv)을 모아 «색인<TAB>한국어» 한 장으로 만든다.

  python tools/uikr.py            # 검사만
  python tools/uikr.py --write    # work/ui_kr_all.tsv 생성

조각 파일의 왼쪽 칸은 «키 이름»(MISSION_OBJECTIVE_00 …) 또는 «색인»(숫자) 둘 다 된다.
키→색인 변환은 work/bible_map.tsv 를 쓴다.

## 검사 항목
- 알 수 없는 키 / 같은 색인에 두 번 번역
- «글자 스프라이트»가 그리는 칸에 한글을 넣었는지 (넣으면 크래시)
  [[feedback_sprite_letter_table_is_ascii_only]]
- 버튼 아이콘 문자([ + ¡ ® ¿ µ § @ © ¥ $ # %d …)가 원문에서 사라졌는지
"""
import argparse
import glob
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP = os.path.join(ROOT, 'work', 'bible_map.tsv')
SRC = os.path.join(ROOT, 'work', 'kr', 'ui')
OUT = os.path.join(ROOT, 'work', 'ui_kr_all.tsv')

# 스프라이트 요소가 그리는 칸 — 한글 금지
SPRITE_IDX = set([11, 12, 59, 62, 114, 122, 306, 490, 663, 1585, 1628,
                  108, 611, 1026, 1136, 1541, 1166, 440, 377,
                  898, 922, 1450, 1016, 1017, 1018, 1019, 1020, 1021, 1158, 1160]
                 + list(range(1000, 1016)))
# 게임이 채우는 자리 / 버튼 그림 문자
TOKENS = ['%d', '%D', '\\', '$', '#', '¥', '[', '+', '¡', '®', '¿', 'µ', '§', '@', '©']
HANGUL = re.compile('[가-힣ㄱ-ㆎ]')


def load_map():
    key2idx, idx2en, idx2key = {}, {}, {}
    for n, line in enumerate(io.open(MAP, encoding='utf-8')):
        if n == 0:
            continue
        r = line.rstrip('\n').split('\t')
        i = int(r[0])
        idx2en[i] = r[5]
        idx2key[i] = r[1]
        if r[1] and not r[1].isdigit():
            key2idx.setdefault(r[1], i)
    return key2idx, idx2en, idx2key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', action='store_true')
    a = ap.parse_args()

    key2idx, idx2en, idx2key = load_map()
    tr, src_of, bad = {}, {}, []

    for path in sorted(glob.glob(os.path.join(SRC, '*.tsv'))):
        name = os.path.basename(path)
        for ln, line in enumerate(io.open(path, encoding='utf-8'), 1):
            line = line.rstrip('\n')
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            if '\t' not in line:
                bad.append('%s:%d 탭 없음: %s' % (name, ln, line[:40]))
                continue
            k, v = line.split('\t', 1)
            k = k.strip()
            if k.isdigit():
                i = int(k)
                if i not in idx2en:
                    bad.append('%s:%d 없는 색인 %s' % (name, ln, k))
                    continue
            elif k in key2idx:
                i = key2idx[k]
            else:
                bad.append('%s:%d 모르는 키 %s' % (name, ln, k))
                continue
            if i in tr:
                bad.append('%s:%d 색인 %d 중복 (앞: %s)' % (name, ln, i, src_of[i]))
                continue
            tr[i] = v
            src_of[i] = name

    # 검사
    crash = [i for i in tr if i in SPRITE_IDX and HANGUL.search(tr[i])]
    lost = []
    for i, v in tr.items():
        en = idx2en[i]
        for t in TOKENS:
            if en.count(t) > v.count(t):
                lost.append((i, t, idx2key.get(i, ''), en[:40], v[:40]))

    print('번역 %d행 (조각 %d개)' % (len(tr), len(glob.glob(os.path.join(SRC, '*.tsv')))))
    if bad:
        print('⛔ 문제 %d건' % len(bad))
        for b in bad[:40]:
            print('   ' + b)
    if crash:
        print('⛔⛔ 스프라이트 칸에 한글 %d행 — 크래시 난다: %s' % (len(crash), sorted(crash)))
    if lost:
        print('⚠️ 자리표시/아이콘 문자가 빠진 행 %d개' % len(lost))
        for i, t, k, en, v in lost[:20]:
            print('   %5d %-28s %r 없어짐 | %s -> %s' % (i, k, t, en, v))
    if not (bad or crash or lost):
        print('✅ 문제 없음')

    if a.write:
        if bad or crash:
            raise SystemExit('⛔ 문제가 있어 쓰지 않았다')
        with io.open(OUT, 'w', encoding='utf-8', newline='\n') as f:
            f.write('# 자동 생성 — tools/uikr.py, 원본은 work/kr/ui/*.tsv\n')
            for i in sorted(tr):
                f.write('%d\t%s\n' % (i, tr[i]))
        print('-> %s' % OUT)


if __name__ == '__main__':
    main()
