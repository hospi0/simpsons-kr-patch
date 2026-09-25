# -*- coding: utf-8 -*-
"""`my files/level script/levelN.txt` (팬위키 대본)을 파싱해 대사 줄을 뽑는다.

  python tools/lvlscript.py "my files/level script/level1.txt"
  python tools/lvlscript.py ... --tsv work/script_l1.tsv

## 형식 (실측)

```
<미션 제목>
Objectives | Mission Objectives | Steps: | What to do:
1. …                      ← 목표 목록
Transcript                ← 여기부터 대사
Marge: …                  ← 「이름: 내용」
(무대 지시)                 ← 괄호는 버린다
Starting the race / Winning the race / Cutscene / In-game   ← 소제목
```
⚠️ 미션에 따라 대사가 **줄바꿈 없이 한 줄에 이어져** 있다
   (`Marge: …Homer: …Apu: …`). 화자 이름으로 잘라야 한다.
"""
import argparse
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# DOL 캐릭터 표(3글자 코드)에서 온 이름 ↔ 코드
NAME2CODE = {
    'homer': 'hom', "homer's brain": 'hom', 'homer simpson': 'hom',
    'marge': 'mrg', 'bart': 'brt', 'lisa': 'lis', 'apu': 'apu',
    'agnes': 'agn', 'barney': 'brn', 'carl': 'crl', 'comic book guy': 'cbg',
    'cletus': 'clt', 'dolph': 'dol', 'dr. nick': 'nic', 'nick': 'nic',
    'professor frink': 'frk', 'frink': 'frk', 'ned': 'fla', 'ned flanders': 'fla',
    'flanders': 'fla', 'gil': 'gil', 'kang': 'kan', 'kodos': 'kod',
    'grandpa': 'grp', 'abe': 'grp', 'hans moleman': 'mol', 'moleman': 'mol',
    'jasper': 'jas', 'jimbo': 'jim', 'kearney': 'kea',
    'krusty': 'kru', 'krusty the clown': 'kru',
    'lenny': 'len', 'lou': 'loe', 'louie': 'lou', 'milhouse': 'mil', 'moe': 'moe',
    'nelson': 'nel', 'otto': 'oto', 'patty': 'pat', 'mayor quimby': 'qim',
    'quimby': 'qim', 'ralph': 'ral', 'sea captain': 'sea', 'captain': 'sea',
    'selma': 'sel', 'principal skinner': 'skn', 'skinner': 'skn',
    'smithers': 'smi', 'snake': 'snk', 'squeaky voiced teen': 'svt',
    'squeaky-voiced teen': 'svt', 'teen': 'svt', 'chief wiggum': 'wig',
    'wiggum': 'wig', 'groundskeeper willie': 'wil', 'willie': 'wil',
    'zombie': 'zom', 'dr. hibbert': 'hib', 'hibbert': 'hib', 'mr. burns': 'bur',
    'burns': 'bur', 'rod': 'rod', 'todd': 'rod',
}

TITLES = ('mr.', 'mrs.', 'ms.', 'dr.', 'principal', 'chief', 'professor',
          'groundskeeper', 'mayor', 'the', 'reverend', 'sideshow', 'comic')


def code_of(name):
    """「Marge Simpson」·「Mr. Smithers」·「Lenny Leonard」 같은 변형까지 받아 준다."""
    n = name.strip().lower().rstrip(':').strip()
    if n in NAME2CODE:
        return NAME2CODE[n]
    toks = n.replace("'s", '').split()
    while toks and toks[0] in TITLES:
        toks = toks[1:]
    if not toks:
        return None
    for cand in (' '.join(toks), toks[0], toks[-1]):
        if cand in NAME2CODE:
            return NAME2CODE[cand]
    return None


# ⚠️ 목표 머리말이 파일마다 다르다 — Objectives / Tasks / Steps: / What to do: …
HEAD = re.compile(r'^(Mission Objectives|Objectives?|Tasks?|Goals?|Steps:?|What to do:?|'
                  r'Transcript|Music|Cutscene|In-?game|Walkthrough|Notes?|'
                  r'Starting the race|Winning the race|Losing the race)\s*:?\s*$', re.I)
SPK = re.compile(r'([A-Z][A-Za-z.\'\- ]{1,24}?)\s*:\s*')
BULLET = re.compile(r'^\s*[•*\d]+[.)]?\s')


def split_speech(text):
    """한 줄에 이어 붙은 「이름: 내용」들을 잘라낸다."""
    out = []
    marks = [(m.start(), m.end(), m.group(1).strip()) for m in SPK.finditer(text)
             if code_of(m.group(1))]
    for k, (s, e, who) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(text)
        out.append((who, text[e:end].strip()))
    return out


def clean(t):
    t = re.sub(r'\([^)]*\)', ' ', t)          # 무대 지시
    t = re.sub(r'\s+', ' ', t).strip()
    return t.strip(' -')


def parse(path):
    lines = io.open(path, encoding='utf-8', errors='replace').read().splitlines()
    missions, cur, sect = [], None, ''
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        h = HEAD.match(s)
        if h:
            sect = h.group(1).lower()
            # ★ 한 미션 안에 `Transcript` 가 두 번 이상 나오면 «다른 대화»다
            #   (미션 대사 + 컷신). 안 나누면 한 꼭지가 비대해져 배정이 어긋난다
            #   (레벨5 `Curious Curator` 가 31줄로 부풀어 Kang·Kodos 컷신을 삼켰다).
            if sect == 'transcript' and cur and cur['lines']:
                cur = dict(title=cur['title'] + ' (2)', goals=[], lines=[])
                missions.append(cur)
            continue
        # ★ 번호·글머리 줄은 «언제나» 목표다. 머리말이 없는 파일에서 제목으로 오인하면
        #   미션 경계가 깨져 정렬이 통째로 어긋난다(레벨2 에서 실제로 밟았다).
        if BULLET.match(s) and not split_speech(s):
            if cur:
                cur['goals'].append(re.sub(r'^\s*[•*\d]+[.)]?\s*', '', s))
            continue
        got = split_speech(s)
        if got and sect:
            for who, txt in got:
                t = clean(txt)
                if t:
                    cur['lines'].append((code_of(who), who, t))
            continue
        # 화자도 목표도 아닌 짧은 줄 = 새 미션 제목
        if len(s) < 60 and not s.startswith(('(', '•', '*')):
            cur = dict(title=s, goals=[], lines=[])
            missions.append(cur)
            sect = ''
    return [m for m in missions if m['lines'] or m['goals']]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path')
    ap.add_argument('--tsv')
    a = ap.parse_args()
    ms = parse(a.path)
    tot = sum(len(m['lines']) for m in ms)
    print('%s : 미션/레이스 %d개 · 대사 %d줄' % (os.path.basename(a.path), len(ms), tot))
    for m in ms:
        print('  %-26s 목표 %2d · 대사 %2d  %s'
              % (m['title'], len(m['goals']), len(m['lines']),
                 ' · '.join(c for c, _, _ in m['lines'][:10])))
    if a.tsv:
        with io.open(a.tsv, 'w', encoding='utf-8', newline='\n') as f:
            f.write('미션\t순서\t화자코드\t화자\t영문\n')
            for m in ms:
                for i, (code, who, t) in enumerate(m['lines'], 1):
                    f.write('%s\t%d\t%s\t%s\t%s\n' % (m['title'], i, code, who, t))
        print('-> %s' % a.tsv)


if __name__ == '__main__':
    main()
