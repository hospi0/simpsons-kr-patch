# -*- coding: utf-8 -*-
"""레벨 대본과 대사 클립을 «화자»로 잇는다.

  python tools/dlgmatch.py 3 --tsv work/dialog_l3.tsv --verbose

## 세 단계 (뒤로 갈수록 느슨하게)

1. **구간 배정** — 클립 태그(`l3m5`)마다 «화자 다중집합»을 만들어 대본 꼭지와 겹침을 재고
   가장 잘 맞는 짝을 정한다(꼭지는 한 번씩만).
   ⛔ 이걸 안 하면 레이스처럼 짧고 비슷한 대화들이 서로 남의 자리에 붙는다(레벨3 실측).

2. **정확 정렬** — 대화(topic)의 화자 열이 «줄 단위로 그대로» 맞는 연속 구간을 찾는다.
   배정된 꼭지 안에서 먼저, 못 찾으면 대본 전체에서.
   후보가 여럿이면 주제어가 나오는 쪽(`bladder`↔"gall bladder").

3. **쪼갬·합침** — 게임이 한 대사를 여러 클립으로 쪼개거나 반대로 합친다.
   남은 대화는 «같은 화자가 연속된 덩어리» 단위로 맞추고, 개수가 다르면
   나눠 주거나 이어 붙인다(`방식` 칸에 `쪼갬2:1`·`합침1:3` 으로 표시).

⛔ 3단계를 «앞으로 끌어올리면 안 된다». 덩어리 경계에 맞추라고 강제하면
   줄 중간에서 시작하는 대화를 못 놓아 오히려 정확 정렬까지 깨진다(실측 83→59).

## ⛔ 그 밖의 함정

- 대본의 「Mission N」 번호는 못 믿고, 어긋나는 방식도 레벨마다 다르다
  (레벨1은 첫 미션이 «레벨 태그»(`l1`)라 한 칸 밀리고, 레벨2·3은 `m1` 부터 맞다).
- 미매칭을 「대본에 없다」고 단정하지 말 것. 실측하니 그런 건 1% 뿐이었다.
"""
import argparse
import io
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lvlscript

ISO = r'C:/claude/roms/gc/Simpsons, The - Hit & Run (USA).iso'
SPKSET = set(lvlscript.NAME2CODE.values())


def clips(level):
    out = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), 'rcfnames.py'),
                          ISO, 'dialog'], capture_output=True, text=True,
                         encoding='utf-8', errors='replace').stdout
    rows = []
    for n in sorted({l.strip() for l in out.splitlines() if l.strip().endswith('.rsd')}):
        if not n.startswith('c_'):
            continue
        p = n[2:-4].split('_')
        tag = ''
        i = len(p) - 1
        if p[i] not in SPKSET:
            tag = p[i]
            i -= 1
        if i < 2 or p[i] not in SPKSET or not p[i - 2].isdigit():
            continue
        if not re.match(r'l%d($|[mrbt]\d)$' % level, tag):
            continue
        rows.append(dict(topic='_'.join(p[:i - 2]), num=int(p[i - 2]),
                         kind=p[i - 1], spk=p[i], tag=tag, name=n))
    return rows


def overlap(a, b):
    """화자 다중집합 겹침 × 크기 비슷함.

    ⛔ 겹침만 보면 «클립 10개»가 «대본 2줄» 꼭지에 붙는다(레벨5에서 l5m1/l5m3 이 뒤바뀜).
       크기가 비슷할수록 높은 점수를 주어야 한다.
    """
    sa, sb = sum(a.values()), sum(b.values())
    common = sum((a & b).values())
    ratio = common / max(1, min(sa, sb))
    size = min(sa, sb) / max(1, max(sa, sb))
    return ratio * (0.4 + 0.6 * size)


def runs(seq):
    """[a,a,b] -> [('a',[0,1]), ('b',[2])]  (색인은 seq 안 위치)"""
    out = []
    for i, x in enumerate(seq):
        if out and out[-1][0] == x:
            out[-1][1].append(i)
        else:
            out.append((x, [i]))
    return out


def word_score(topic, texts):
    tw = [q for q in re.split(r'[_\d]', topic) if len(q) >= 4]
    if not tw:
        return 0
    blob = ' '.join(t.lower() for t in texts)
    flat = blob.replace(' ', '').replace('-', '')
    return sum(1 for q in tw if q in blob or q in flat)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('level', type=int)
    ap.add_argument('--script')
    ap.add_argument('--tsv')
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args()
    path = a.script or ('my files/level script/level%d.txt' % a.level)
    ms = lvlscript.parse(path)
    cl = clips(a.level)
    print('대본 %d꼭지 %d줄 · 레벨%d 클립 %d개'
          % (len(ms), sum(len(m['lines']) for m in ms), a.level, len(cl)))

    conv, bytag = defaultdict(list), defaultdict(list)
    for r in cl:
        conv[(r['tag'], r['topic'])].append(r)
        bytag[r['tag']].append(r)
    for k in conv:
        conv[k].sort(key=lambda r: r['num'])

    flat = []                       # [미션색인, 줄색인, 화자, 이름, 영문, 사용됨]
    for mi, m in enumerate(ms):
        for li, (code, who, t) in enumerate(m['lines']):
            flat.append([mi, li, code, who, t, False])

    # ── 1단계 : 구간 배정
    tagset = {t: Counter(r['spk'] for r in v) for t, v in bytag.items()}
    misset = {i: Counter(c for c, _, _ in m['lines']) for i, m in enumerate(ms) if m['lines']}
    # ★ 순서를 지키는 배정 — 태그도 꼭지도 «게임 진행 순서»다.
    #   탐욕적으로 점수만 보면 뒤 미션이 앞 꼭지를 가져간다
    #   (실측 l1m5 가 첫 미션의 크러스티 광고를 받아 갔다).
    def tag_order(t):
        m = re.match(r'l\d(?:([mbrt])(\d))?$', t)
        if not m or not m.group(1):
            return (0, 0)                     # 레벨 태그(`l1`) = 맨 앞
        return ({'m': 1, 'b': 2, 't': 3, 'r': 4}[m.group(1)], int(m.group(2)))

    T = sorted(tagset, key=tag_order)
    M = sorted(misset)
    sc = [[overlap(tagset[t], misset[i]) for i in M] for t in T]
    NEG = -1.0
    nT, nM = len(T), len(M)
    dp = [[NEG] * (nM + 1) for _ in range(nT + 1)]
    bk = [[None] * (nM + 1) for _ in range(nT + 1)]
    dp[0][0] = 0.0
    for x in range(nT + 1):
        for y in range(nM + 1):
            if dp[x][y] == NEG:
                continue
            if x < nT and dp[x + 1][y] < dp[x][y]:            # 이 태그는 배정 안 함
                dp[x + 1][y] = dp[x][y]
                bk[x + 1][y] = (x, y, None)
            if y < nM and dp[x][y + 1] < dp[x][y]:            # 이 꼭지는 건너뜀
                dp[x][y + 1] = dp[x][y]
                bk[x][y + 1] = (x, y, None)
            if x < nT and y < nM and sc[x][y] >= 0.5 and dp[x + 1][y + 1] < dp[x][y] + sc[x][y]:
                dp[x + 1][y + 1] = dp[x][y] + sc[x][y]
                bk[x + 1][y + 1] = (x, y, (T[x], M[y]))
    assign = {}
    x, y = nT, nM
    while bk[x][y]:
        px, py, act = bk[x][y]
        if act:
            assign[act[0]] = act[1]
        x, y = px, py
    if a.verbose:
        print('\n[구간 배정]')
        for t in sorted(tagset):
            print('   %-7s -> %s' % (t, ms[assign[t]]['title'] if t in assign else '(없음)'))

    res, how = {}, {}

    # ── 2단계 : 정확 정렬
    def windows(seq, mis):
        out = []
        for st in range(len(flat) - len(seq) + 1):
            win = flat[st:st + len(seq)]
            if any(w[5] for w in win):
                continue
            if mis is not None and any(w[0] != mis for w in win):
                continue
            if all(w[2] == c for w, c in zip(win, seq)):
                out.append(win)
        return out

    order = sorted(conv.items(), key=lambda kv: -len(kv[1]))

    # ★ 2단계 : 배정된 꼭지 안에서 먼저, 그다음 대본 전체에서 «정확 일치» 구간을 찾는다.
    #   ⛔ 여기에 «동시 배치(DP)»를 넣어 봤지만 전체 성적이 떨어졌다(84/99/100 → 78/95/96).
    #      DP 가 자기 꼭지 안 coverage 만 최대화하느라, 여러 꼭지에 걸치는 태그(`l1`)의
    #      대화가 쓸 줄을 먼저 집어삼켰다. 탐욕 + 주제어가 실측상 더 낫다.
    for scope in ('배정', '전체'):
        for (tag, topic), rows in order:
            if rows[0]['name'] in res:
                continue
            mis = assign.get(tag) if scope == '배정' else None
            if scope == '배정' and mis is None:
                continue
            seq = [r['spk'] for r in rows]
            hits = windows(seq, mis)
            pick = None
            if len(hits) == 1:
                pick = hits[0]
            elif len(hits) > 1:
                # ★ 주제어 점수로 먼저 거르고, 동점이면 «한 수 앞»을 본다 —
                #   같은 태그의 «아직 못 놓은» 대화들이 여전히 자리를 잡을 수 있는 쪽.
                #   ⛔ 이게 없으면 긴 대화가 남의 자리를 먹는다
                #      (실측 l3m7 : destroy 가 0~2 를 침범해 catch 를 밀어냈다).
                scored = [(word_score(topic, [w[4] for w in win]), win) for win in hits]
                top = max(sc for sc, _ in scored)
                cands = [win for sc, win in scored if sc == top]
                if top > 0:
                    others = [(tp, rw) for (tg, tp), rw in order
                              if tg == tag and rw[0]['name'] not in res and tp != topic]
                    best = None
                    for win in cands:
                        for w in win:
                            w[5] = True
                        ok = sum(1 for tp, rw in others
                                 if windows([x['spk'] for x in rw], mis))
                        for w in win:
                            w[5] = False
                        if best is None or ok > best[0]:
                            best = (ok, win)
                    if best:
                        pick = best[1]
            if pick:
                for w, r in zip(pick, rows):
                    w[5] = True
                    res[r['name']] = (ms[w[0]]['title'], w[4])
                    how[r['name']] = scope

    # ── 3단계 : 쪼갬·합침 (배정된 꼭지의 «남은 줄»만 대상)
    for (tag, topic), rows in order:
        if rows[0]['name'] in res or tag not in assign:
            continue
        mi = assign[tag]
        # ⛔ 남은 줄을 그냥 이어 붙이면 «0,5,6» 처럼 떨어진 줄이 한 대화로 묶인다.
        #   원래 순서에서 «연속»인 덩어리만 후보로 쓴다.
        sect = [w for w in flat if w[0] == mi]
        blocks, cur = [], []
        for w in sect:
            if w[5]:
                if cur:
                    blocks.append(cur)
                cur = []
            else:
                cur.append(w)
        if cur:
            blocks.append(cur)
        free = max(blocks, key=len) if blocks else []
        if not free:
            continue
        S = runs([w[2] for w in free])
        cr = runs([r['spk'] for r in rows])
        k = len(cr)
        cands = []
        for st in range(len(S) - k + 1):
            if any(S[st + j][0] != cr[j][0] for j in range(k)):
                continue
            blk = [free[i] for j in range(k) for i in S[st + j][1]]
            cands.append((word_score(topic, [w[4] for w in blk]), st))
        if not cands:
            continue
        cands.sort(key=lambda x: -x[0])
        if len(cands) > 1 and cands[0][0] == cands[1][0]:
            continue                      # 구별할 근거가 없으면 손대지 않는다
        st = cands[0][1]
        for j, (spk, cidx) in enumerate(cr):
            sw = [free[i] for i in S[st + j][1]]
            texts = [w[4] for w in sw]
            x, y = len(cidx), len(texts)
            for w in sw:
                w[5] = True
            if x == y:
                for p, ci in enumerate(cidx):
                    res[rows[ci]['name']] = (ms[mi]['title'], texts[p])
                    how[rows[ci]['name']] = '덩어리1:1'
            elif x > y:                                   # 대본 한 줄 → 클립 여럿
                for p, ci in enumerate(cidx):
                    res[rows[ci]['name']] = (ms[mi]['title'], texts[min(p, y - 1)])
                    how[rows[ci]['name']] = '쪼갬%d:%d' % (x, y)
            else:                                         # 대본 여럿 → 클립 하나
                per = [[] for _ in range(x)]
                for p, t in enumerate(texts):
                    per[min(p * x // y, x - 1)].append(t)
                for p, ci in enumerate(cidx):
                    res[rows[ci]['name']] = (ms[mi]['title'], ' '.join(per[p]))
                    how[rows[ci]['name']] = '합침%d:%d' % (x, y)

    n = len(cl)
    c = Counter(how.values())
    print('\n[정렬] %s' % ' · '.join('%s %d' % kv for kv in c.most_common(8)))
    print('   합계 %d/%d (%.0f%%)' % (len(res), n, 100.0 * len(res) / n))
    miss = [r for r in cl if r['name'] not in res]
    if miss:
        print('   미매칭 %d개 : %s' % (len(miss), dict(Counter(r['tag'] for r in miss))))
    print('   대본에서 안 쓰인 줄 %d개' % sum(1 for w in flat if not w[5]))

    if a.tsv:
        with io.open(a.tsv, 'w', encoding='utf-8', newline='\n') as f:
            f.write('파일명\t태그\t주제\t순서\t화자\t미션\t방식\t영문\n')
            for r in sorted(cl, key=lambda r: (r['tag'], r['topic'], r['num'])):
                t, txt = res.get(r['name'], ('', ''))
                f.write('%s\t%s\t%s\t%d\t%s\t%s\t%s\t%s\n'
                        % (r['name'], r['tag'], r['topic'], r['num'], r['spk'], t,
                           how.get(r['name'], ''), txt.replace('\t', ' ')))
        print('-> %s' % a.tsv)


if __name__ == '__main__':
    main()
