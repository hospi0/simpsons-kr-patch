# -*- coding: utf-8 -*-
"""대사 음성 받아쓰기(위스퍼 large-v3, utils/whisper-venv 의 파이썬으로 실행).

  C:/claude/utils/whisper-venv/Scripts/python.exe tools/asr.py <wav폴더> <출력.tsv> [--only 이름목록.txt]

- rsdwav.exe 로 푼 24 kHz 모노 WAV 를 16 kHz numpy 배열로 넘긴다(파일 경로 → av 오류, reference_whisper_venv).
- ⛔ vad_filter 끔 — 짧은 외침을 버린다(feedback_asr_vad_drops_short_shouts).
- 결과 TSV: 이름 · 길이(초) · 영문 · avg_logprob · no_speech_prob · 비고
  빈 결과·환각 의심도 «빼지 않고» 그대로 남긴다 → 사람이 들을 줄(feedback_asr_fail_not_nonverbal).
- 이어서 하기: 출력 TSV 에 이미 있는 이름은 건너뛴다.
"""
import argparse
import io
import os
import sys
import time
import wave

import numpy as np


def load16k(path):
    w = wave.open(path, 'rb')
    sr = w.getframerate()
    a = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').astype(np.float32) / 32768.0
    w.close()
    if sr != 16000 and len(a):
        n = int(round(len(a) * 16000 / sr))
        x = np.linspace(0, len(a) - 1, n)
        a = np.interp(x, np.arange(len(a)), a).astype(np.float32)
    return a, len(a) / 16000.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('wavdir')
    ap.add_argument('out')
    ap.add_argument('--only')
    ap.add_argument('--prompt', default="The Simpsons: Hit & Run. Homer, Marge, Bart, Lisa, Apu, Mr. Burns, Smithers, Springfield.")
    a = ap.parse_args()
    from faster_whisper import WhisperModel
    names = sorted(n[:-4] for n in os.listdir(a.wavdir) if n.endswith('.wav'))
    if a.only:
        keep = set(l.strip().lower() for l in io.open(a.only, encoding='utf-8') if l.strip())
        names = [n for n in names if n.lower() in keep]
    done = set()
    if os.path.exists(a.out):
        for l in io.open(a.out, encoding='utf-8'):
            done.add(l.split('\t', 1)[0])
    todo = [n for n in names if n not in done]
    print('대상 %d · 이미 %d · 남음 %d' % (len(names), len(done), len(todo)), flush=True)
    m = WhisperModel('large-v3', device='cuda', compute_type='float16')
    new = not os.path.exists(a.out)
    out = io.open(a.out, 'a', encoding='utf-8', newline='\n')
    if new:
        out.write('이름\t초\t영문\tlogprob\tno_speech\t비고\n')
    t0 = time.time()
    for k, n in enumerate(todo):
        arr, sec = load16k(os.path.join(a.wavdir, n + '.wav'))
        segs, info = m.transcribe(arr, language='en', beam_size=5, condition_on_previous_text=False,
                                  vad_filter=False, initial_prompt=(a.prompt or None))
        segs = list(segs)
        txt = ' '.join(s.text.strip() for s in segs).strip()
        lp = min((s.avg_logprob for s in segs), default=0.0)
        ns = max((s.no_speech_prob for s in segs), default=1.0)
        note = '빈 결과' if not txt else ('확인 필요' if lp < -0.8 or ns > 0.5 else '')
        out.write('%s\t%.2f\t%s\t%.2f\t%.2f\t%s\n' % (n, sec, txt.replace('\t', ' '), lp, ns, note))
        out.flush()
        if k % 50 == 0:
            el = time.time() - t0
            print('%d/%d  %.0f초 경과  %s: %s' % (k + 1, len(todo), el, n, txt[:60]), flush=True)
    out.close()
    print('끝 %.0f초' % (time.time() - t0))


if __name__ == '__main__':
    main()
