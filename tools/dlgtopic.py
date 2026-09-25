# -*- coding: utf-8 -*-
"""«대화 두 개가 통째로 뒤바뀐 것»을 주제어로 잡아낸다.

  python tools/dlgtopic.py              # 의심 대화
  python tools/dlgtopic.py --all        # 주제어를 못 찾은 대화까지 전부

## 왜 필요한가 (2026-09-11 사용자 신고 l4m3)

정렬 도구는 «화자 배열»로 대본 덩어리↔주제를 짝짓는다. `.mfk`(`mfkorder.py`)가 «대화 순서»를
알려 주지만, **`.mfk` 가 선언하지 않는 대화**(미션 중 `noboxconv`)는 오라클이 없다.
그래서 l4m3 에서 앞 세 줄 화자가 똑같은(`mrg·clt·mrg`) `baby`(제안)와 `ketchup`(미션 중)이
**통째로 뒤바뀌었다.** 게다가 `winter` 까지 물려 한 칸씩 밀렸다.

★ 그런데 대화 이름(주제)은 **그 대화 내용에서 따온 것**이다 —
```
baby     "…what happened to my baby boy"        pappy   "my granpappy done seen…"
winter   "…during the long winter"              dumpster "…in the dumpster's 'round here"
ketchup  "…they'll have ketchup"
```
⇒ **주제어가 «자기 대화»에 없고 «같은 미션의 다른 대화»에 있으면 바뀐 것이다.**

## ⛔ 함정 — «형제에 있다»만으로는 오탐이 쏟아진다

실측한 오탐 두 갈래 —
```
① 다음 장소·목표를 «알려 주는» 대화   l3m2 노이즈랜드 대화가 「Wall E. Weasel's 로 가 봐」로 끝난다
                                      → "weasel" 이 늘 «앞 대화»에 나온다 (l3m2 sign/store 도 같은 꼴)
② 목표 이름을 딴 대화                  l1m2 `mower` = 잔디깎이를 찾은 «직후» 나오는 줄
                                      → 줄 안에 "mower" 가 없는 게 정상이다
③ 번역이 아예 없는 «이름2» 중복        churro2·baby2·probe2 … 영문이 비어 있을 뿐 뒤바뀐 게 아니다
```
★ 그래서 판정은 **«바꿔 보면 양쪽 다 자기 주제어를 얻는가»** 로 한다.
   l4m3 은 baby↔ketchup 을 바꾸면 baby 가 "baby boy" 를, ketchup 이 "ketchup" 을 «둘 다» 얻는다.
   위 오탐들은 한쪽만 좋아진다. `--loose` 로 약한 신호까지 볼 수 있다.
"""
import argparse
import collections
import csv
import io
import re

GENERIC = {'success', 'fail', 'fail1', 'fail2', 'intro', 'count', 'complete',
           'done', 'convinit', 'start', 'win', 'lose'}


def stem(t):
    """`baby2`·`churro2` → `baby`·`churro` (번호 변형은 같은 낱말이다)"""
    return re.sub(r'\d+$', '', t.lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tsv', default='work/dialog_all.tsv')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--loose', action='store_true',
                    help='«형제에 있다»만으로도 보고 (오탐 많음)')
    a = ap.parse_args()

    rows = list(csv.reader(io.open(a.tsv, encoding='utf-8'), delimiter='\t'))
    H = {h: i for i, h in enumerate(rows[0])}
    mis = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows[1:]:
        if len(r) <= H['한국어']:
            continue
        mis[r[H['태그']].lower()][r[H['주제']].lower()].append(r)

    nsus = nnone = 0
    for tag in sorted(mis):
        text = {t: ' '.join(x[H['영문']] for x in rs).lower()
                for t, rs in mis[tag].items()}
        for t in sorted(text):
            s = stem(t)
            if len(s) < 4 or s in GENERIC:
                continue
            if s in text[t]:
                continue                                  # 자기 대화에 있다 → 정상
            others = [u for u in text if u != t and s in text[u]]
            # ★ 진짜 뒤바뀜이면 «바꿨을 때 양쪽 다» 자기 주제어를 얻는다.
            strong = [u for u in others
                      if text[u].strip() and stem(u) not in GENERIC
                      and len(stem(u)) >= 4 and stem(u) in text[t]]
            if not a.loose:
                others = strong
            if others:
                nsus += 1
                print('%s' % ('★ 양방향(강한 신호)' if strong else '· 한쪽만(약한 신호)'))
                print('⛔ %-8s «%s» 주제어가 자기 대화에 없고 → %s 에 있다'
                      % (tag, t, ', '.join('«%s»' % u for u in others)))
                for u in [t] + others:
                    rs = sorted(mis[tag][u], key=lambda x: int(x[H['순서']] or 0))
                    print('     %-12s %-18s %s' % (u,
                          '·'.join(x[H['화자']] for x in rs),
                          (rs[0][H['영문']][:70] or '(영문 없음)')))
                print()
            elif a.all:
                nnone += 1
                print('·  %-8s «%s» 주제어가 이 미션 어디에도 없다 (신호 없음)' % (tag, t))
    print('★ 뒤바뀜 의심 %d건%s' % (nsus, (' · 신호 없음 %d건' % nnone) if a.all else ''))


if __name__ == '__main__':
    main()
