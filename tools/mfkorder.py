# -*- coding: utf-8 -*-
"""미션 스크립트(`.mfk`)에서 «대화가 나오는 순서»를 읽는다 — 자막 배정의 오라클.

  python tools/mfkorder.py <iso>                 # 미션마다 대화 순서
  python tools/mfkorder.py <iso> --check         # 지금 배정(dialog_all.tsv)과 대조

## 왜 필요한가

`dialog.rcf` 의 클립 이름은 «주제»만 알려 줄 뿐 **순서를 안 알려 준다.**
팬위키 대본은 «순서»만 알려 줄 뿐 **주제 이름을 안 알려 준다.**
그래서 정렬 도구가 «화자 배열»로 짝을 지었는데, 한 미션 안에 화자 배열이 같은 대화가 둘이면
구별이 안 된다(L2M5 의 `roadkill`·`slack` 이 둘 다 `Brt·Clt·Brt·Clt`).
그때는 「대본 순서 = 주제 순서」로 가정할 수밖에 없었고 — **그 가정이 틀릴 수 있다.**

★ `.mfk` 는 평문이고 **대화 순서를 명시**한다. 추측이 필요 없다.
```
/scripts/missions/levelNN/mMsdi.mfk   SetDialogueInfo(pc,npc,"주제",n)  ← 미션 «제안» 대화
/scripts/missions/levelNN/mMi.mfk     AddStage 블록 순서대로
                                         SetDialogueInfo(pc,npc,"주제",n)
                                         SetCompletionDialog("주제",npc)
```
실측(L2M5): `slack`(제안) → `stinkdog`(완료대사) → `roadkill`(마지막 보상 대화).
그런데 정렬 도구는 `roadkill` 을 첫 대화로 놓고 있었다 → 미션이 「크러스티 버거가 로드킬…」로 시작.

## 파일 이름 → 미션 태그
```
mN(sd)i.mfk → lLmN      srK(i).mfk → lLrK      bm1(i).mfk → lLb1
level(i).mfk, d1, gr1, demo → 레벨 전용(lL)
```
"""
import argparse
import io
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gcfst import read_fst

DLG = re.compile(r'SetDialogueInfo\s*\(\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"')
CMP = re.compile(r'SetCompletionDialog\s*\(\s*"([^"]*)"\s*(?:,\s*"([^"]*)")?')


def tag_of(path):
    """/scripts/missions/level02/m5sdi.mfk → ('l2m5', 0=제안 / 1=미션중)"""
    m = re.search(r'/level(\d+)/([a-z0-9]+)\.mfk$', path, re.I)
    if not m:
        return None, 0
    lv = int(m.group(1))
    base = m.group(2).lower()
    mm = re.match(r'^m(\d+)(sd)?(i|l)?$', base)
    if mm:
        return 'l%dm%s' % (lv, mm.group(1)), (0 if mm.group(2) else 1)
    mm = re.match(r'^sr(\d+)(i|l)?$', base)
    if mm:
        return 'l%dr%s' % (lv, mm.group(1)), 1
    mm = re.match(r'^bm(\d+)(i|l)?$', base)
    if mm:
        return 'l%db%s' % (lv, mm.group(1)), 1
    return 'l%d' % lv, 1


def scan(iso):
    """{태그: [주제, …]}  — 제안 대화 먼저, 그다음 미션 스크립트의 파일 순서."""
    f = open(iso, 'rb')
    h, ents = read_fst(f)
    out = {}
    for path, off, size, isdir in ents:
        if isdir or not path.lower().endswith('.mfk'):
            continue
        if '/scripts/missions/' not in path.lower():
            continue
        tag, phase = tag_of(path)
        if not tag:
            continue
        f.seek(off)
        txt = f.read(size).decode('latin1')
        # ⛔ 주석(//) 줄은 «게임이 안 부르는» 대화다 — L3M4 의 kaiser2 가 그렇다
        txt = chr(10).join(l.split('//')[0] for l in txt.splitlines())
        got = []
        for m in re.finditer(r'SetDialogueInfo\s*\([^)]*\)|SetCompletionDialog\s*\([^)]*\)', txt):
            s = m.group()
            d = DLG.search(s)
            if d:
                got.append((d.group(3), 'dialogue'))
                continue
            c = CMP.search(s)
            if c and c.group(1):
                got.append((c.group(1), 'completion'))
        if got:
            out.setdefault(tag, []).append((phase, os.path.basename(path), got))
    order = {}
    for tag, items in out.items():
        items.sort(key=lambda x: (x[0], x[1]))          # 제안(0) 먼저, 그다음 파일 이름순
        seq = []
        for phase, name, got in items:
            for topic, kind in got:
                if topic not in [t for t, k, n in seq]:
                    seq.append((topic, kind, name))
        order[tag] = seq
    return order


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('iso')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--missing', action='store_true',
                    help='.mfk 가 «실제로 부르는데» 번역이 빈 대화를 전부 고른다')
    ap.add_argument('--tsv', default='work/dialog_all.tsv')
    ap.add_argument('--script', default='my files/level script')
    a = ap.parse_args()

    order = scan(a.iso)

    if a.missing:
        import csv
        import collections
        import re as _re
        rows = list(csv.reader(io.open(a.tsv, encoding='utf-8'), delimiter='	'))
        Hh = {h: i for i, h in enumerate(rows[0])}
        g = collections.defaultdict(lambda: collections.defaultdict(list))
        for r in rows[1:]:
            if len(r) > Hh['한국어']:
                g[r[Hh['태그']].lower()][r[Hh['주제']].lower()].append(r)
        HAN = _re.compile(r'[가-힣]')
        nrow = ntop = 0
        for tag in sorted(order):
            for topic, kind, fname in order[tag]:
                lines = g.get(tag, {}).get(topic)
                if lines is None:
                    print('⚠️ %-8s %-14s (%s) — tsv 에 행이 아예 없다' % (tag, topic, fname))
                    ntop += 1
                    continue
                empty = [r for r in lines if not HAN.search(r[Hh['한국어']])]
                if empty:
                    ntop += 1
                    nrow += len(empty)
                    print('⛔ %-8s %-14s (%s)  %d/%d 줄 비어 있음' %
                          (tag, topic, fname, len(empty), len(lines)))
                    for r in sorted(empty, key=lambda x: int(x[Hh['순서']] or 0)):
                        en = r[Hh['영문']][:60] if len(r) > Hh['영문'] else ''
                        print('      %s %-4s %s' % (r[Hh['순서']], r[Hh['화자']], en or '(영문도 없음)'))
        print(chr(10) + '★ 게임이 «실제로 부르는» 대화 중 번역이 빈 것 : %d개 대화 · %d줄' % (ntop, nrow))
        return

    if not a.check:
        for tag in sorted(order):
            print('%-8s %s' % (tag, ' → '.join('%s(%s)' % (t, k[:4]) for t, k, n in order[tag])))
        print('\n미션 %d개' % len(order))
        return

    import csv
    import collections
    rows = list(csv.reader(io.open(a.tsv, encoding='utf-8'), delimiter='\t'))
    H = {h: i for i, h in enumerate(rows[0])}
    g = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows[1:]:
        if len(r) <= H['영문']:
            continue
        g[r[H['태그']].lower()][r[H['주제']].lower()].append(r)

    # 팬위키 대본 전문 (레벨별)
    script = {}
    for lv in range(1, 8):
        p = os.path.join(a.script, 'level%d.txt' % lv)
        if os.path.exists(p):
            script[lv] = io.open(p, encoding='utf-8', errors='replace').read()

    def pos_in_script(lv, text):
        """대본에서 그 영문이 처음 나오는 위치(문자 오프셋). 못 찾으면 None."""
        s = script.get(lv)
        if not s or not text:
            return None
        key = re.sub(r'\s+', ' ', text).strip()[:40]
        if not key:
            return None
        i = s.find(key)
        return i if i >= 0 else None

    bad = 0
    for tag in sorted(order):
        lv = int(tag[1])
        seq = [t for t, k, n in order[tag] if t in g.get(tag, {})]
        if len(seq) < 2:
            continue
        # 지금 배정에서 각 주제의 «대본 위치»
        pos = {}
        for t in seq:
            lines = sorted(g[tag][t], key=lambda r: int(r[H['순서']] or 0))
            for r in lines:
                p = pos_in_script(lv, r[H['영문']])
                if p is not None:
                    pos[t] = p
                    break
        have = [t for t in seq if t in pos]
        if len(have) < 2:
            continue
        ok = all(pos[have[i]] < pos[have[i + 1]] for i in range(len(have) - 1))
        if not ok:
            bad += 1
            print('⛔ %-8s .mfk 순서 %s' % (tag, ' → '.join(have)))
            print('        대본 위치 %s' % ' → '.join('%s@%d' % (t, pos[t]) for t in have))
            for t in have:
                r = sorted(g[tag][t], key=lambda x: int(x[H['순서']] or 0))[0]
                print('          [%s] %s' % (t, r[H['영문']][:64]))
    print('\n순서가 어긋난 미션 %d개' % bad)


if __name__ == '__main__':
    main()
