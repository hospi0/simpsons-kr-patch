# -*- coding: utf-8 -*-
"""번역이 «대본 문단의 일부만» 담고 있는 줄을 전수로 골라낸다.

  python tools/dlgcover.py            # 안 덮인 구간이 긴 것부터
  python tools/dlgcover.py --min 20   # 문턱값(글자수)
  python tools/dlgcover.py --tag l4m1 # 한 미션만

## 왜 필요한가

`dialog_all.tsv` 의 `영문` 열은 정렬 도구가 «대본 문단을 토막 내» 배정한 결과다.
토막이 문단 전체를 덮지 못하면, 그 뒤 문장은 **번역에서 통째로 빠진다** —
그런데 음성 클립은 문단 전체를 말하므로 화면에는 «앞부분만» 자막이 뜬다.

실례(2026-09-11 사용자 신고) `c_nuts_2_convinit_mrg_l4m1.rsd` —
```
대본  Hmmmh, oh Bart, what's causing your ooga-booga talk?
      My special little guy's noodle has turned to google.        ← 빠짐
      The whole town's gone nuts! Security cameras, mysterious vans, crop circles?
      There's got to be a connection. Maybe the police know something.  ← 빠짐
tsv   oh Bart … crop circles?                                     ← 가운데 토막만
```
⛔ 「영문 열이 전문이겠거니」 하고 봐서는 절대 안 잡힌다 — **대본과 대조해야** 보인다.

## 판정

⛔ **문단 통째로 찾으면 안 잡힌다** — 위 실례처럼 tsv 가 «가운데 토막»만 담고 있으면
   그 문자열은 문단의 연속 부분열이 아니기 때문이다(가운데가 빠져 있다).
   그래서 **문장 단위**로 쪼개, 문단의 각 문장이 어느 tsv 줄에든 들어 있는지 본다.
한 문장도 못 찾은 문단은 «배정 자체가 안 된 것»이라 여기서는 다루지 않는다(`mfkorder --missing` 몫).
"""
import argparse
import collections
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvlscript

SCRIPT = 'my files/level script'
HAN = re.compile(r'[가-힣]')


def norm(s):
    """대소문자·공백·따옴표·군더더기 문장부호를 지운 «비교용» 문자열과, 원문 위치 대응표."""
    out, idx = [], []
    for i, c in enumerate(s):
        if c.isalnum():
            out.append(c.lower()); idx.append(i)
        elif c.isspace():
            if out and out[-1] != ' ':
                out.append(' '); idx.append(i)
    while out and out[-1] == ' ':
        out.pop(); idx.pop()
    return ''.join(out), idx


def contains(hay, needle):
    """needle 이 hay 에 «거의» 들어 있나 — 앞뒤로 최대 1/3 낱말까지 떼어 보고 찾는다."""
    if needle in hay:
        return True
    w = needle.split()
    drop = max(1, len(w) // 3)
    for i in range(drop + 1):
        for j in range(drop + 1):
            if i == 0 and j == 0:
                continue
            sub = ' '.join(w[i:len(w) - j])
            if len(sub) >= 10 and len(sub) >= len(needle) * 0.6 and sub in hay:
                return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tsv', default='work/dialog_all.tsv')
    ap.add_argument('--script', default=SCRIPT)
    ap.add_argument('--min', type=int, default=20, help='보고할 «안 덮인 구간» 최소 글자수')
    ap.add_argument('--tag')
    a = ap.parse_args()

    rows = list(csv_rows(a.tsv))
    H = rows[0]
    Hh = {h: i for i, h in enumerate(H)}
    bylvl = collections.defaultdict(list)
    for r in rows[1:]:
        if len(r) <= Hh['한국어']:
            continue
        en = r[Hh['영문']].strip()
        if not en or en.startswith('('):
            continue
        try:
            lv = int(r[Hh['레벨']])
        except ValueError:
            continue
        bylvl[lv].append(r)

    hits = []
    for lv in sorted(bylvl):
        p = os.path.join(a.script, 'level%d.txt' % lv)
        if not os.path.exists(p):
            continue
        # 그 레벨 번역들의 «영문»을 정규화해 둔다
        ens = [(r, norm(r[Hh['영문']])[0]) for r in bylvl[lv]]
        for m in lvlscript.parse(p):
            for code, who, txt in m['lines']:
                sents = [x.strip() for x in re.split(r'(?<=[.?!])\s+', txt) if x.strip()]
                if len(norm(txt)[0]) < 30:
                    continue
                got, miss, rows = 0, [], []
                for st in sents:
                    n = norm(st)[0]
                    if len(n) < 10:
                        got += 1                    # 너무 짧은 문장은 판정 보류
                        continue
                    # ⛔ 완전 일치만 보면 「Hmmmh, oh Bart…」처럼 «머리말 한 낱말» 차이로
                    #    멀쩡히 담긴 문장을 빠졌다고 오탐한다. 앞뒤 낱말을 조금씩 떼며 찾는다.
                    owner = [r for r, e in ens if contains(e, n)]
                    if owner:
                        got += 1
                        for r in owner:
                            if r not in rows:
                                rows.append(r)
                    else:
                        miss.append(st)
                # ⛔ «진짜로 맞은 줄»이 있어야 한다 — 짧은 문장 때문에 got 이 올라간 것만으로는
                #    배정 안 된 문단(=mfkorder --missing 몫)을 허수로 잡는다.
                if rows and miss:
                    big = [g for g in miss if len(norm(g)[0]) >= a.min]
                    if big and (not a.tag or any(r[Hh['태그']].lower() == a.tag.lower()
                                                 for r in rows)):
                        hits.append((sum(len(g) for g in big),
                                     dict(lv=lv, who=who, txt=txt, rows=rows), big))

    hits.sort(key=lambda x: -x[0])
    for total, pa, gaps in hits:
        tags = sorted({'%s/%s' % (r[Hh['태그']], r[Hh['주제']]) for r in pa['rows']})
        print('⛔ L%d %-6s %-22s  안 덮인 %d자' % (pa['lv'], pa['who'], ','.join(tags)[:22], total))
        print('   대본 %s' % pa['txt'][:150])
        for r in pa['rows']:
            print('   담긴것 %s' % r[Hh['영문']][:110])
            print('   번역   %s' % r[Hh['한국어']][:80])
        for g in gaps:
            print('   ⇢ 빠짐 %s' % g[:130])
        print()
    print('★ 문단 %d개에서 «번역에 안 담긴 구간»을 찾았다 (문턱 %d자)' % (len(hits), a.min))


def csv_rows(path):
    import csv
    return list(csv.reader(io.open(path, encoding='utf-8'), delimiter='\t'))


if __name__ == '__main__':
    main()
