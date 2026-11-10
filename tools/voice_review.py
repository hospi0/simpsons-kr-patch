# -*- coding: utf-8 -*-
r"""자막 없던 대사 음성 검수 페이지 (v0.9, 2026-11-11).

  python tools/voice_review.py            → work/check/voice_<종류>.html (d·w·p·c·v)

- 음성은 HTML 에 넣지 않고 «../snd/wav/<이름>.wav» 상대 경로로 건다(3,282개 · 500 MB).
  ⇒ 페이지는 반드시 work/check/ 에서 열 것(work/snd/wav 와 같은 프로젝트 폴더 안).
- 줄마다: 재생 · 기계 받아쓰기(영문, work/snd/asr_all.tsv) · 번역(work/snd/voice_ko.tsv, 있으면) · 고칠 칸 ·
  «소리만(자막 안 넣음)».  빨간 줄 = 받아쓰기 빈 결과·확신 낮음 → 먼저 들어 볼 것.
  ⛔ 빈 결과를 «말 없음»으로 빼지 않는다(feedback_asr_fail_not_nonverbal) — 사람이 들을 줄로 남긴다.
- «결과 복사» = «이름\t고친 말» 줄들(고친 줄·소리만 체크한 줄만) → 대화창에 붙여 넣기.
"""
import csv
import html
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

KIND = {'d': '운전 중 대사', 'w': 'NPC 응답', 'p': '보행자 반응', 'c': '대화(미션 밖·튜토리얼)', 'v': '차량'}

CSS = """:root{--bg:#f6f5f2;--fg:#1d1d1b;--mut:#6b6a66;--card:#fff;--line:#dedbd4;--acc:#b4441c}
@media (prefers-color-scheme:dark){:root{--bg:#1b1a19;--fg:#ece9e3;--mut:#a29e96;--card:#262523;--line:#3a3835;--acc:#e0774f}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,"Malgun Gothic",sans-serif}
main{max-width:980px;margin:0 auto;padding:16px}h1{font-size:20px;margin:8px 0}p.note{color:var(--mut);margin:4px 0 16px}
.bar{position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:center;flex-wrap:wrap;z-index:2}
button{font:inherit;padding:6px 12px;border:1px solid var(--acc);background:var(--acc);color:#fff;border-radius:6px;cursor:pointer}
.row{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:10px 0}
.row.done{opacity:.55}.row.need{border-left:4px solid var(--acc)}
.hd{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.id{font-weight:600;font-family:ui-monospace,Consolas,monospace;font-size:13px}
.meta{color:var(--mut);font-size:13px}audio{height:32px;max-width:100%}
.g{display:grid;grid-template-columns:72px 1fr;gap:4px 8px;margin-top:6px;font-size:14px}.g>span{color:var(--mut)}
input.t{font:inherit;width:100%;box-sizing:border-box;padding:5px 8px;border:1px solid var(--line);border-radius:5px;background:var(--bg);color:var(--fg)}
label{font-size:13px;color:var(--mut)}textarea{width:100%;height:140px;box-sizing:border-box;font:12px ui-monospace,Consolas,monospace;background:var(--card);color:var(--fg);border:1px solid var(--line);margin-top:12px}
@media (max-width:600px){.g{grid-template-columns:1fr}}"""

JS = r"""function filt(){const o=document.getElementById('onlyneed').checked;document.querySelectorAll('.row').forEach(r=>{r.style.display=(o&&r.dataset.need==='0')?'none':''})}
function copyOut(){const L=[];document.querySelectorAll('.row').forEach(r=>{const t=r.querySelector('input.t').value.trim(),s=r.querySelector('input.s').checked;if(t||s)L.push(r.dataset.id+'\t'+(s?'(소리만)':t))});
const txt=L.join('\n');document.getElementById('out').value=txt;
navigator.clipboard.writeText(txt).then(()=>{document.getElementById('msg').textContent=L.length+'줄 복사됨'},()=>{document.getElementById('msg').textContent='아래 칸에서 복사해 주세요'})}
document.addEventListener('input',e=>{const r=e.target.closest('.row');if(r){const t=r.querySelector('input.t').value.trim(),s=r.querySelector('input.s').checked;r.classList.toggle('done',!!(t||s))}});"""


def load(path, key='이름'):
    if not os.path.exists(path):
        return {}
    return {r[key]: r for r in csv.DictReader(io.open(path, encoding='utf-8'), delimiter='\t')}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    asr = load(os.path.join(ROOT, 'work', 'snd', 'asr_all.tsv'))
    ko = load(os.path.join(ROOT, 'work', 'snd', 'voice_ko.tsv'))
    # 번역 때 고친 영문(work/snd/tr/en_*.tsv: 이름·초·영문·비고) · 힌트 없이 다시 받아쓴 영문(work/snd/reasr/noprompt.tsv)
    import glob
    fixed = {}
    for p in sorted(glob.glob(os.path.join(ROOT, 'work', 'snd', 'tr', 'en_*.tsv'))):
        for l in io.open(p, encoding='utf-8'):
            c = l.rstrip('\n').split('\t')
            if len(c) >= 3:
                fixed[c[0]] = c[2]
    re_asr = load(os.path.join(ROOT, 'work', 'snd', 'reasr', 'noprompt.tsv'))
    for n, r in re_asr.items():
        fixed[n] = r.get('영문') or fixed.get(n, '')
    groups = {}
    for n in sorted(asr):
        groups.setdefault(n.split('_')[0].lower(), []).append(n)
    outdir = os.path.join(ROOT, 'work', 'check')
    os.makedirs(outdir, exist_ok=True)
    for kd, names in sorted(groups.items()):
        body = []
        need_n = 0
        for n in names:
            r = asr[n]
            en = fixed.get(n, r.get('영문') or '')
            k = ko.get(n, {})
            kt = (k.get('한국어') or '').replace('|', '  ▶다음 쪽▶  ').replace('\\n', ' / ')
            note = k.get('비고') or ''
            need = (not kt) or ('확인' in note) or ('받아쓰기' in note)
            need_n += need
            body.append(
                '<div class="row %s" data-id="%s" data-need="%d"><div class="hd"><span class="id">%s</span>'
                '<span class="meta">%s초 %s</span><audio controls preload="none" src="../snd/wav/%s.wav"></audio></div>'
                '<div class="g"><span>받아쓰기</span><div class="meta">%s</div><span>번역</span><div>%s</div>'
                '<span>고칠 말</span><input class="t" placeholder="틀렸으면 들은 영어 또는 고친 한국어">'
                '<span></span><label><input class="s" type="checkbox"> 소리만(자막 안 넣음)</label></div></div>'
                % ('need' if need else '', html.escape(n), need, html.escape(n), r.get('초', ''),
                   ('· ' + html.escape(note)) if note else '', html.escape(n),
                   html.escape(en or '— (못 알아들음)'), html.escape(kt or '—')))
        title = '심슨 음성 검수 — %s' % KIND.get(kd, kd)
        page = ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>%s</title><style>%s</style></head><body><main><h1>%s (%d개)</h1>'
                '<p class="note">빨간 줄 = 번역이 비었거나 받아쓰기를 의심해 비고를 단 줄(%d개) — 먼저 들어 봐 주세요. '
                '틀린 줄만 «고칠 말»에 적으면 됩니다(영어로 들은 말 또는 고친 한국어). 숨소리·비명 같은 소리면 «소리만». '
                '다 하면 «결과 복사» → 대화창에 붙여 주세요.</p>'
                '<div class="bar"><button onclick="copyOut()">결과 복사</button><label><input type="checkbox" id="onlyneed" onchange="filt()"> 빨간 줄만 보기</label>'
                '<span id="msg" class="meta"></span></div>%s'
                '<textarea id="out" placeholder="결과 복사를 누르면 여기에도 나옵니다"></textarea></main><script>%s</script></body></html>'
                % (title, CSS, title, len(names), need_n, ''.join(body), JS))
        p = os.path.join(outdir, 'voice_%s.html' % kd)
        io.open(p, 'w', encoding='utf-8').write(page)
        print('%s %-18s %4d줄 · 빨간 줄 %4d → %s' % (kd, KIND.get(kd, kd), len(names), need_n, p))


if __name__ == '__main__':
    main()
