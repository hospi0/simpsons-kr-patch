# -*- coding: utf-8 -*-
"""동영상 자막 — 타이밍 «초안» 생성 · SRT 출력 · 미리보기 MP4 굽기.

  python tools/movsub.py time                 # 소리를 재서 시작/끝 초안을 채운다
  python tools/movsub.py srt                  # work/movies/subs/<이름>.srt
  python tools/movsub.py preview fmv3         # 자막+타임코드 박힌 미리보기 MP4

## 왜 «초안»인가

배경음악이 끊이지 않아서 「조용한 구간 = 대사 사이」가 성립하지 않는다.
그래서 무음 판정 대신 **줄 수를 아는 것**을 이용한다 —
대사가 N줄이면 경계는 N−1개뿐이니, 소리 골짜기가 깊은 곳 N−1군데를
«글자 수에 비례한 길이»를 지키면서 고르는 DP 로 뽑는다.
⇒ 사람이 듣고 고치는 것을 전제로 한, 「대충 맞는」 출발점이다.
"""
import argparse
import io
import os
import subprocess
import sys
import wave

import numpy as np

FF = r'C:\claude\utils\ffmpeg-9.0.1-essentials_build\bin\ffmpeg.exe'
FONT = r'C:\claude\utils\font\nanum-gothic\NanumGothicBold.ttf'
RAD = r'C:\Program Files (x86)\RADVideo\radvideo64.exe'
BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'work', 'movies')
SUBS = os.path.join(BASE, 'subs')
TSV = os.path.join(SUBS, 'movie_lines.tsv')
GRID = 0.05                     # DP 격자 50 ms
MOVIES = ['fmv1A', 'fmv2', 'fmv3', 'fmv4', 'fmv5', 'fmv6', 'fmv7']


def rows():
    r = [l.rstrip('\n').split('\t') for l in io.open(TSV, encoding='utf-8')]
    return r[0], r[1:]


def save(head, body):
    with io.open(TSV, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\t'.join(head) + '\n')
        for r in body:
            r = r + [''] * (len(head) - len(r))
            f.write('\t'.join(r[:len(head)]) + '\n')


def envelope(name):
    """대사 대역(200~3500 Hz) 에너지 포락선을 dB 로. 50 ms 격자."""
    wav = os.path.join(BASE, 'tmp_%s.wav' % name)
    subprocess.run([FF, '-hide_banner', '-loglevel', 'error', '-y',
                    '-i', os.path.join(BASE, 'src', name + '.rmv'), '-vn',
                    '-af', 'pan=mono|c0=0.5*c0+0.5*c1,highpass=f=200,lowpass=f=3500',
                    '-ar', '16000', '-c:a', 'pcm_s16le', wav], check=True)
    w = wave.open(wav)
    sr, n = w.getframerate(), w.getnframes()
    a = np.frombuffer(w.readframes(n), dtype='<i2').astype(np.float32) / 32768
    w.close()
    os.remove(wav)
    H = int(sr * GRID)
    m = len(a) // H
    e = np.sqrt((a[:m * H].reshape(m, H) ** 2).mean(1)) + 1e-9
    db = 20 * np.log10(e)
    # 150 ms 평활
    k = np.ones(3) / 3
    return np.convolve(db, k, 'same'), n / sr


def minlen(chars):
    """그 줄이 화면에 있어야 할 «최소» 시간(초). 읽는 속도 기준."""
    return max(0.8, 0.13 * chars)


def split_dp(db, dur, weights, t0, t1):
    """골짜기 깊이 + 「글자 수 비례」 를 함께 만족하는 경계 N-1 개를 고른다.

    ⛔ 최소 구간 길이를 강제하지 않으면 «경계가 한 점에 몰린다»
       (골짜기 점수가 깊은 한 곳으로 여러 개가 빨려 들어간다).
       그래서 k 번째 구간은 적어도 d[k] 격자만큼 길어야 한다는 제약을 건다 —
       제약이 «닫는 구간»에만 걸리므로 누적최대(prefix max)로 O(N·L) 에 푼다.
    """
    N = len(weights)
    i0, i1 = int(t0 / GRID), min(int(t1 / GRID), len(db) - 1)
    seg = db[i0:i1 + 1]
    L = len(seg)
    d = [max(1, int(minlen(w) / GRID)) for w in weights]
    if N == 1 or sum(d) >= L:
        cuts = [int(L * sum(weights[:k + 1]) / sum(weights)) for k in range(N - 1)]
        return [t0] + [(i0 + c) * GRID for c in cuts] + [t1]
    # 골짜기 점수 : ±0.6초 국소 최대 대비 얼마나 낮은가
    R = int(0.6 / GRID)
    hi = np.array([seg[max(0, i - R):i + R + 1].max() for i in range(L)])
    dip = hi - seg
    dip = (dip - dip.min()) / (dip.max() - dip.min() + 1e-9)
    w = np.array(weights, dtype=np.float64)
    ideal = (np.cumsum(w) / w.sum())[:-1] * L
    LAM = 6.0 / L
    NEG = -1e18
    idx = np.arange(L)
    best = np.full((N - 1, L), NEG)
    back = np.zeros((N - 1, L), dtype=np.int32)
    gain = [dip - LAM * np.abs(idx - ideal[k]) for k in range(N - 1)]
    ok = np.zeros(L, dtype=bool)
    ok[d[0]:L - sum(d[1:])] = True         # 첫 경계가 놓일 수 있는 범위
    best[0][ok] = gain[0][ok]
    for k in range(1, N - 1):
        pm = np.maximum.accumulate(best[k - 1])
        pa = np.zeros(L, dtype=np.int32)
        run, arg = NEG, 0
        for j in range(L):                  # 누적최대의 «위치»
            if best[k - 1, j] > run:
                run, arg = best[k - 1, j], j
            pa[j] = arg
        lo, hi2 = d[0] + sum(d[1:k + 1]), L - sum(d[k + 1:])
        for i in range(max(lo, d[k]), max(lo, min(hi2, L))):
            j = i - d[k]
            if j >= 0 and pm[j] > NEG:
                best[k, i] = pm[j] + gain[k][i]
                back[k, i] = pa[j]
    i = int(np.argmax(best[N - 2]))
    cuts = [i]
    for k in range(N - 2, 0, -1):
        i = back[k, i]
        cuts.append(i)
    cuts.reverse()
    return [t0] + [(i0 + c) * GRID for c in cuts] + [t1]


def speech_span(db, dur):
    """앞뒤의 «확실히 조용한» 부분을 잘라낸 대사 구간."""
    thr = db.max() - 30
    on = np.where(db > thr)[0]
    if len(on) == 0:
        return 0.5, dur - 0.5
    return max(0.0, on[0] * GRID - 0.2), min(dur, on[-1] * GRID + 0.4)


def cmd_time(a):
    head, body = rows()
    iF, iK, iS, iE = (head.index('파일'), head.index('한국어'),
                      head.index('시작'), head.index('끝'))
    for name in MOVIES:
        idx = [j for j, r in enumerate(body) if r[iF] == name]
        if not idx:
            continue
        db, dur = envelope(name)
        t0, t1 = speech_span(db, dur)
        wgt = [max(4, len(body[j][iK])) for j in idx]
        bnd = split_dp(db, dur, wgt, t0, t1)
        for k, j in enumerate(idx):
            while len(body[j]) <= iE:
                body[j].append('')
            # ★ 끝은 «다음 줄 직전»이 아니라 «읽는 데 걸리는 시간» 으로 —
            #   안 그러면 대사 사이가 긴 곳에서 자막이 30초씩 붙어 있는다.
            show = max(1.5, 0.22 * len(body[j][iK]))
            body[j][iS] = '%.2f' % bnd[k]
            body[j][iE] = '%.2f' % min(bnd[k] + show, max(bnd[k] + 1.0, bnd[k + 1] - 0.05))
        print('%-6s %.1f초 · %2d줄 · 대사구간 %.1f~%.1f'
              % (name, dur, len(idx), t0, t1))
    save(head, body)
    print('-> %s 의 시작/끝 칸을 채웠다' % TSV)


def cmd_redo(a):
    """한 편만 «대사 구간»을 손으로 지정해 초안을 다시 뽑는다.

      python tools/movsub.py redo fmv6 --from 8
    ⛔ 통째로 미는 것과 다르다 — 미는 방식은 마지막 줄이 영상 끝을 넘어간다.
    """
    head, body = rows()
    iF, iK, iS, iE = (head.index('파일'), head.index('한국어'),
                      head.index('시작'), head.index('끝'))
    idx = [j for j, r in enumerate(body) if r[iF] == a.name]
    if not idx:
        raise SystemExit('⛔ %s 를 못 찾았다' % a.name)
    db, dur = envelope(a.name)
    t0, t1 = speech_span(db, dur)
    if a.start is not None:
        t0 = a.start
    if a.end is not None:
        t1 = a.end
    if a.lines:                     # 일부 줄만 다시 나눈다 (앞줄은 그대로 둔다)
        lo, hi = (a.lines.split('-') + [a.lines])[:2]
        keep = [j for j in idx if int(body[j][head.index('번호')]) < int(lo)]
        idx = [j for j in idx
               if int(lo) <= int(body[j][head.index('번호')]) <= int(hi)]
        if keep:
            t0 = max(t0, float(body[keep[-1]][iE]) + 0.05)
    wgt = [max(4, len(body[j][iK])) for j in idx]
    bnd = split_dp(db, dur, wgt, t0, t1)
    for k, j in enumerate(idx):
        show = max(1.5, 0.22 * len(body[j][iK]))
        body[j][iS] = '%.2f' % bnd[k]
        body[j][iE] = '%.2f' % min(bnd[k] + show, max(bnd[k] + 1.0, bnd[k + 1] - 0.05))
        print('  %2s  %6.2f ~ %6.2f  %s'
              % (body[j][head.index('번호')], bnd[k], float(body[j][iE]),
                 body[j][iK][:40]))
    save(head, body)
    print('-> %s (%.1f초) 대사구간 %.1f~%.1f 로 재배치' % (a.name, dur, t0, t1))


def cmd_set(a):
    """사용자 교정 반영 — «시작»만 받고 «끝»은 다시 계산한다.

      python tools/movsub.py set fmv3 1=3.0 2=12.0 3=31.0
    """
    head, body = rows()
    iF, iN, iK, iS, iE = (head.index('파일'), head.index('번호'), head.index('한국어'),
                          head.index('시작'), head.index('끝'))
    want = dict(x.split('=') for x in a.pairs)
    idx = [j for j, r in enumerate(body) if r[iF] == a.name]
    if not idx:
        raise SystemExit('⛔ %s 를 못 찾았다' % a.name)
    for j in idx:
        n = body[j][iN]
        if n in want:
            body[j][iS] = '%.2f' % float(want[n])
    dur = None
    for k, j in enumerate(idx):
        s = float(body[j][iS])
        show = max(1.5, 0.22 * len(body[j][iK]))
        if k + 1 < len(idx):
            nxt = float(body[idx[k + 1]][iS])
        else:
            if dur is None:
                _, dur = envelope(a.name)
            nxt = dur
        body[j][iE] = '%.2f' % min(s + show, max(s + 1.0, nxt - 0.05))
        print('  %2s  %6.2f ~ %6.2f  %s'
              % (body[j][iN], s, float(body[j][iE]), body[j][iK][:38]))
    save(head, body)
    print('-> %s 갱신' % a.name)


def wrap(s, n=34):
    out, cur = [], ''
    for word in s.split(' '):
        if cur and len(cur) + 1 + len(word) > n:
            out.append(cur)
            cur = word
        else:
            cur = (cur + ' ' + word).strip()
    if cur:
        out.append(cur)
    return out[:2] if len(out) <= 2 else [' '.join(out[:len(out) // 2]),
                                          ' '.join(out[len(out) // 2:])]


def ts(t):
    h = int(t // 3600)
    m = int(t // 60) % 60
    s = t - int(t // 60) * 60
    return '%02d:%02d:%06.3f' % (h, m, s)


def cmd_srt(a):
    head, body = rows()
    iF, iN, iK, iS, iE = (head.index('파일'), head.index('번호'),
                          head.index('한국어'), head.index('시작'), head.index('끝'))
    for name in MOVIES:
        idx = [r for r in body if r[iF] == name and len(r) > iE and r[iS]]
        if not idx:
            continue
        # 두 벌을 쓴다 — «최종용»(깨끗함) 과 «교정용»(줄 번호가 앞에 붙음).
        for tag, num in (('', False), ('_num', True)):
            p = os.path.join(SUBS, name + tag + '.srt')
            with io.open(p, 'w', encoding='utf-8', newline='\n') as f:
                for k, r in enumerate(idx, 1):
                    txt = wrap(r[iK])
                    if num:
                        txt[0] = '%s. %s' % (r[iN], txt[0])
                    f.write('%d\n%s --> %s\n%s\n\n'
                            % (k, ts(float(r[iS])).replace('.', ','),
                               ts(float(r[iE])).replace('.', ','), '\n'.join(txt)))
        print('%-6s -> %s.srt / %s_num.srt (%d줄)' % (name, name, name, len(idx)))


def cmd_preview(a):
    """⛔ 필터 문자열에 «드라이브 문자의 콜론»이 들어가면 파싱이 깨진다.
       (`C\\:/...` 로 탈출시켜도 판마다 다르게 먹는다.)
       → 작업 폴더를 자막 폴더로 옮기고 «상대 이름»만 쓴다. 콜론이 아예 없어진다."""
    import shutil
    local_font = os.path.join(SUBS, os.path.basename(FONT))
    if not os.path.exists(local_font):
        shutil.copy(FONT, local_font)
    names = a.names or MOVIES
    for name in names:
        out = name + '_preview.mp4'
        style = ('FontName=NanumGothic,FontSize=17,PrimaryColour=&H00FFFFFF,'
                 'OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,'
                 'Alignment=2,MarginV=14')
        vf = ("subtitles=%s_num.srt:fontsdir=.:force_style='%s',"
              "drawtext=fontfile=%s:text='%%{pts\\:hms}':x=8:y=6:"
              "fontsize=18:fontcolor=yellow:box=1:boxcolor=black@0.6:boxborderw=4"
              % (name, style, os.path.basename(FONT)))
        cmd = [FF, '-hide_banner', '-loglevel', 'error', '-y',
               '-i', os.path.join(BASE, 'src', name + '.rmv'),
               '-vf', vf, '-c:v', 'libx264', '-crf', '20', '-preset', 'veryfast',
               '-c:a', 'aac', '-b:a', '160k', out]
        r = subprocess.run(cmd, cwd=SUBS)
        if r.returncode:
            print('⛔ %s 실패' % name)
        else:
            print('%-6s -> %s (%.1f MB)'
                  % (name, out, os.path.getsize(os.path.join(SUBS, out)) / 1e6))


def bink_info(path):
    """Bink 파일 머리를 읽어 (프레임수, 폭, 높이, fps, 오디오트랙수, 최대프레임) 로."""
    import struct
    d = open(path, 'rb').read(48)
    if d[:3] != b'BIK':
        raise SystemExit('⛔ %s 는 Bink 가 아니다 (%r)' % (path, d[:4]))
    fn, lf, _, w, h, num, den, _fl, ntr = struct.unpack_from('<IIIIIIIII', d, 8)
    return fn, w, h, num / den, ntr, lf


def cmd_burn(a):
    """최종 — 자막을 «구워» Bink 1 로 다시 만든다.

      python tools/movsub.py burn fmv3            # work/movies/out/fmv3.rmv 까지
      python tools/movsub.py burn fmv3 --iso <경로>   # ISO 교체까지

    ⛔ RAD 압축기 함정 (docs 참조)
       · Git Bash 에서는 /V100 같은 스위치가 «경로»로 바뀐다 → 반드시 이 도구로.
       · /M 은 «초당 바이트». 전체레이트보다 작은 값을 주면 말없이 사용법 창만 뜬다.
         → 배수(2.0)로 준다.
       · 끝나도 창이 안 닫힌다 → 출력 크기가 안 변하면 끝난 것으로 보고 죽인다.
    """
    import shutil
    import time
    out_dir = os.path.join(BASE, 'out')
    tmp_dir = os.path.join(BASE, 'tmp')
    for d in (out_dir, tmp_dir):
        if not os.path.exists(d):
            os.makedirs(d)
    local_font = os.path.join(SUBS, os.path.basename(FONT))
    if not os.path.exists(local_font):
        shutil.copy(FONT, local_font)

    for name in (a.names or MOVIES):
        src = os.path.join(BASE, 'src', name + '.rmv')
        fn, w, h, fps, ntr, lf = bink_info(src)
        rate = int(os.path.getsize(src) / (fn / fps))      # 원본과 같은 무게로
        avi = os.path.join(tmp_dir, name + '.avi')
        dst = os.path.join(out_dir, name + '.rmv')
        style = ('FontName=NanumGothic,FontSize=17,PrimaryColour=&H00FFFFFF,'
                 'OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,'
                 'Alignment=2,MarginV=14')
        vf = "subtitles=%s.srt:fontsdir=.:force_style='%s'" % (name, style)
        print('%-6s %dx%d %d프레임 %gfps · 목표 %d B/s' % (name, w, h, fn, fps, rate))
        # ⛔ -frames:v 를 안 박으면 편에 따라 «한 프레임 더» 나온다(fmv5 가 4205→4206).
        #    프레임 수가 다르면 원본과 길이가 어긋나므로 원본 값으로 못 박는다.
        subprocess.run([FF, '-hide_banner', '-loglevel', 'error', '-y', '-i', src,
                        '-vf', vf, '-c:v', 'rawvideo', '-pix_fmt', 'bgr24',
                        '-frames:v', str(fn),
                        '-c:a', 'pcm_s16le', '-ar', '48000', '-ac', '2', avi],
                       cwd=SUBS, check=True)
        print('   자막 구운 AVI %.1f GB' % (os.path.getsize(avi) / 1e9))
        # ⛔ 출력 확장자는 «.bik» 이어야 한다 — .rmv 로 주면 RAD 가 아무것도 안 만든다.
        bik = os.path.join(tmp_dir, name + '.bik')
        for q in (bik, dst):
            if os.path.exists(q):
                os.remove(q)
        p = subprocess.Popen([RAD, 'Binkc', avi, bik, '/V100', '/D%d' % rate,
                              '/M2.0', '/K30', '/T0', '/R48000', '/B16', '/C2', '/L4'])
        # ⛔ «생길 때까지» 먼저 기다린다. 곧장 크기 안정만 보면 0 == 0 이라 바로 끝나 버린다.
        for _ in range(120):
            if os.path.exists(bik) and os.path.getsize(bik) > 0:
                break
            time.sleep(1)
        else:
            p.kill()
            raise SystemExit('⛔ %s : 압축기가 출력을 안 만든다 (인수 거부?)' % name)
        last, still = -1, 0
        while still < 4:                       # 크기가 12초간 안 변하면 끝난 것
            time.sleep(3)
            cur = os.path.getsize(bik)
            still = still + 1 if cur == last else 0
            last = cur
        p.kill()
        time.sleep(1)
        shutil.move(bik, dst)
        os.remove(avi)
        f2, w2, h2, fps2, ntr2, lf2 = bink_info(dst)
        # ★ 프레임 수는 «±2 까지» 봐준다 — 압축기가 마지막 한 장을 두고 오락가락한다
        #   (fmv5 는 -frames:v 없이 4206, 박으면 4204 가 나왔다). 33 ms 차이라 무해하다.
        #   해상도와 오디오 트랙은 어긋나면 안 된다.
        ok = (abs(f2 - fn) <= 2 and (w2, h2) == (w, h) and ntr2 == ntr)
        print('   -> %s  %d B (%s) · %d프레임 %dx%d 트랙%d 최대프레임%d'
              % (os.path.basename(dst), os.path.getsize(dst),
                 '✅규격일치' if ok else '⛔규격다름', f2, w2, h2, ntr2, lf2))
        if f2 != fn and ok:
            print('   ⚠️ 프레임 %d → %d (%+d)' % (fn, f2, f2 - fn))
        if not ok:
            raise SystemExit('⛔ 규격이 원본과 다르다 — 넣지 않는다')
        if lf2 > lf * 1.5:
            print('   ⚠️ 최대 프레임이 원본(%d)보다 크다 — 읽기 버퍼 위험' % lf)
        if a.iso:
            # ⛔ isofile.py 는 ✅ 를 찍는다 — 자식 프로세스가 cp949 면 거기서 죽는다.
            env = dict(os.environ, PYTHONIOENCODING='utf-8')
            subprocess.run([sys.executable,
                            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         'isofile.py'),
                            a.iso, '--replace', '/movies/%s.rmv' % name, dst],
                           check=True, env=env)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('time')
    sub.add_parser('srt')
    p = sub.add_parser('preview')
    p.add_argument('names', nargs='*')
    q = sub.add_parser('set')
    q.add_argument('name')
    q.add_argument('pairs', nargs='+', metavar='번호=시작초')
    b = sub.add_parser('burn')
    b.add_argument('names', nargs='*')
    b.add_argument('--iso')
    d = sub.add_parser('redo')
    d.add_argument('name')
    d.add_argument('--from', dest='start', type=float)
    d.add_argument('--to', dest='end', type=float)
    d.add_argument('--lines', metavar='시작번호-끝번호')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    {'time': cmd_time, 'srt': cmd_srt, 'preview': cmd_preview,
     'set': cmd_set, 'redo': cmd_redo, 'burn': cmd_burn}[a.cmd](a)


if __name__ == '__main__':
    main()
