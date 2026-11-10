# -*- coding: utf-8 -*-
"""v0.9 자막(소리 재생 상태 → 직접 그리기) 빌더.  docs/08_v0.9_소리재생훅.md

  python tools/ksub.py code                                  # ksub/ksub.c+hooks.s → ksub/ksub.bin·low.bin (+검사)
  python tools/ksub.py data <자막.tsv> <출력폴더>             # 줄 그림 묶음 disc.bin + RAM 블록 block.bin + 미리보기
  python tools/ksub.py install <iso> <출력폴더>              # 시험 ISO 에 설치(제자리 수정)

자막 TSV = «클립이름<TAB>한국어» (dialog.spt 이름, 대소문자 무관, .rsd 있어도 됨). «\\n» = 강제 줄바꿈.
자동 줄바꿈은 «4:3 안전 폭»(화면 560px) 기준 최대 2줄 — 넘치면 빌드 실패.

## 표시 방식 (시험 7~)
줄마다 «미리 그린 I4 그림»(1.5배 해상도, 나눔고딕 Bold, 안티에일리어싱 테두리)을 디스크 빈 영역에 두고,
대사 재생기가 준비(상태 1~3)되면 DVDReadAbsAsyncPrio 로 버퍼(2개)에 미리 읽어 상태 4 에서 그린다.
RAM 에는 키 표 + 버퍼 2개 + 본체 코드만 — 글꼴이 RAM 에 없다.
I4 값: 0~4 = 바깥 테두리 가장자리(알파 = I×4 포화, 색 검정) · 8~15 = 글자(색 = (I−0.5)×2, 알파 1).

## 설치 (순서 고정)
1. 옛 자막 계통 제거: dolhook --reset
2. 레터박스 페이지 원복(tools/lbrestore.py — 글꼴 참조만 v0.8 유지) → isofile --replace
3. 줄 그림 묶음 → 가장 큰 빈 구멍의 «끝»(isofile 이 구멍 «앞»부터 쓰므로 안 겹친다) · disc_base 기록
4. 바이블 한국어 슬롯 뒤에 블록(옛 v0.8 자막 표는 잘라 냄) → isofile --replace
5. 적재기 → DOL text0 0 구간 0x80004888 · 훅 2곳
6. 최종 검사: 줄 그림 묶음이 FST 파일·DOL 과 안 겹치는지
"""
import argparse
import io
import os
import re
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
sys.path.insert(0, HERE)

ZIG = 'C:/claude/utils/zig-x86_64-windows-0.17.0/zig.exe'
OBJCOPY = 'C:/claude/utils/llvm19/x/bin/llvm-objcopy.exe'
NM = 'C:/claude/utils/llvm19/x/bin/llvm-nm.exe'
FONT = 'C:/claude/utils/font/nanum-gothic/NanumGothicBold.ttf'
ORIG_ISO = 'D:/hospi/My Documents/한글패치/GC/gc/Simpsons, The - Hit & Run (USA).iso'   # 읽기만

T2_VA = 0x8048AC00
T2_MAX = 0x8048CB00 - T2_VA            # 아레나 0x8048CB40 앞에서 멈춘다
LOW_VA, LOW_MAX = 0x80004888, 0x4CC    # v0.8 자막 케이브 자리(dolhook --reset 으로 0)
BIB_HOOK, BIB_ORIG = 0x8020BE1C, 0x907D0028
FRAME_HOOK = 0x80276D20
GXDRAWDONE = 0x8032AF68
BIBLE = '/art/frontend/scrooby/resource/txtbible/srr2.p3d'
INGAME = '/art/frontend/scrooby/ingame.p3d'
UI_TSV = os.path.join(ROOT, 'work/ui_kr_boot_en6.tsv')        # v0.8 바이블을 바이트 그대로 재현하는 UI 번역(367 만 고침)
UI_OVERRIDE = os.path.join(ROOT, 'work/v09/ui_override.tsv')  # v0.9 에서 바꾼 UI 줄

# 자막 모양 — 화면(640×480) 기준 값 × 1.5 = 텍스처
SCALE_NUM, SCALE_DEN = 2, 3            # 화면 = 텍스처 × 2/3
FONT_PX = 30                           # 텍스처 px (화면 20px — 하스피 «한 단계 줄여»)
OUTLINE = 3.0                          # 텍스처 px (화면 2px)
LINE_H = FONT_PX + 2 * 4 + 4           # 한 줄 칸 높이(텍스처)
LINEGAP = 3
MAXW = 840                             # 텍스처 px = 화면 560px «4:3 안전 폭» (하스피 «4:3 폭 기준으로 접어»)
MAXLINES = 2
BOTTOM = 72                            # 화면 px — 레터박스 바(윗변 ≈409) 바로 위 (하스피 «한 칸 올려야지»)
HDR = 0x3C                             # KHead 크기(ksub.c 와 같아야 함), 마지막 u32 = disc_base
TUT_DY = 11                            # 화면 px — 상자 요소 윗변 → 한글 그림 윗변(스샷 실측: 첫 줄 가운데 ≈ y206)
BOTTOM_TUT = 90                        # 튜토리얼 떠 있을 때 자막 아랫변(«튜토리얼 끄기» y≈395~420 을 피해 위로)
TUT_HOOK, TUT_ORIG_TO = 0x80213110, 0x802133C8   # HUD «bl 스프라이트 글자 그리기»
KLINE = 16                             # KLine 크기 — key·doff·w·h·t·pg (ksub.c 와 같아야 함)
UI_FONT_SCALE = 1.5                    # 시험 14: 1.5배 · 한 장(폭 512) · UI 가 쓰는 음절만(옛 자막 전용 284자 뺌)
UI_FONT_2X = True                      # UI 한글 폰트(boulderK16) 아틀라스 2배(하스피 «2배 시험부터») — 크래시면 False


def bform(frm, to, lk):
    return 0x48000000 | ((to - frm) & 0x03FFFFFC) | lk


def env():
    return dict(os.environ, MSYS_NO_PATHCONV='1', PYTHONIOENCODING='utf-8')


def syms_of(elf):
    out = {}
    for l in subprocess.run([NM, elf], capture_output=True, text=True).stdout.splitlines():
        p = l.split()
        if len(p) == 3:
            out[p[2]] = int(p[0], 16)
    return out


# ───────────────────────── code ─────────────────────────
def build_code():
    kd = os.path.join(ROOT, 'ksub')
    elf = os.path.join(kd, 'ksub.elf')
    cmd = [ZIG, 'cc', '-target', 'powerpc-freestanding-eabihf', '-mcpu=750', '-Os', '-g',
           '-fno-pic', '-fno-pie', '-fno-builtin', '-nostdlib', '-fno-stack-protector', '-Wall',
           '-Wl,-T,ksub.ld', '-Wl,--no-gc-sections', '-Wl,-e,ksub_frame', '-o', 'ksub.elf',
           'ksub.c', 'hooks.s']
    r = subprocess.run(cmd, cwd=kd, capture_output=True, text=True)
    msg = '\n'.join(l for l in (r.stdout + r.stderr).splitlines() if 'unused during' not in l)
    if r.returncode:
        raise SystemExit('⛔ 컴파일 실패\n' + msg)
    if msg.strip():
        print(msg)
    syms = syms_of(elf)

    def sect(names, out):
        subprocess.run([OBJCOPY, '-O', 'binary'] + ['--only-section=' + n for n in names] + [elf, out], check=True)
        return open(out, 'rb').read()
    low = sect(['.lowtext', '.lowdata'], os.path.join(kd, 'low.bin'))
    raw = sect(['.text', '.rodata', '.data'], os.path.join(kd, 'high.raw'))
    if syms['low_end'] - LOW_VA > LOW_MAX or len(low) != syms['low_end'] - LOW_VA:
        raise SystemExit('⛔ 적재기 크기 이상: %d B (한도 %d)' % (len(low), LOW_MAX))
    end = syms['ksub_end']
    size = end - T2_VA
    if size > T2_MAX:
        raise SystemExit('⛔ 본체가 8KB 구간을 넘는다: 0x%X' % size)
    img = raw + b'\0' * (size - len(raw))      # .bss 는 0 으로 실어 보낸다
    low_code_end = min(v for k, v in syms.items() if k in ('g_lang', 'g_ready', 'g_lowdbg'))
    high_code_end = syms['high_text_end']                 # .text 끝(뒤 .rodata 의 0.0f 상수는 코드 아님)
    check_code(low, LOW_VA, low_code_end, 'LOW')
    check_code(img, T2_VA, high_code_end, 'HIGH')
    open(os.path.join(kd, 'ksub.bin'), 'wb').write(img)
    print('✅ 적재기 0x%08X~0x%08X (%d B, 한도 %d) · ksub_entry %08X · hook_bib %08X · g_lang %08X · g_ready %08X'
          % (LOW_VA, syms['low_end'], len(low), LOW_MAX, syms['ksub_entry'], syms['hook_bib'], syms['g_lang'], syms['g_ready']))
    print('   hook_tut %08X' % syms['hook_tut'])
    print('✅ 본체 0x%08X~0x%08X (%d B, 한도 %d) · ksub_frame %08X · g_dbg %08X'
          % (T2_VA, end, size, T2_MAX, syms['ksub_frame'], syms['g_dbg']))


def check_code(img, base, code_end, tag):
    """기계어 전체 검사 — 게임 r2/r13 사용 금지 · 상대 분기는 LOW/HIGH 구역 안 또는 bib_ret 만."""
    from ppcdis import dis

    def ok(t):
        return LOW_VA <= t < LOW_VA + LOW_MAX or T2_VA <= t < T2_VA + T2_MAX or t == 0x8020BE20
    bad = []
    for i in range(0, code_end - base, 4):
        w = struct.unpack_from('>I', img, i)[0]
        va = base + i
        op, ra = w >> 26, (w >> 16) & 31
        if op in (14, 15) + tuple(range(32, 56)) and ra in (2, 13):
            bad.append('%08X r2/r13 %s' % (va, dis(w, va)))
        if op == 18:
            off = w & 0x3FFFFFC
            if off & 0x2000000:
                off -= 0x4000000
            t = (off if w & 2 else va + off) & 0xFFFFFFFF
            if not ok(t):
                bad.append('%08X 분기 밖 %08X' % (va, t))
        if op == 16:
            off = w & 0xFFFC
            if off & 0x8000:
                off -= 0x10000
            if not (base <= va + off < code_end):
                bad.append('%08X 조건분기 밖' % va)
        if w == 0:
            bad.append('%08X 0 워드(코드 안)' % va)
    if bad:
        raise SystemExit('⛔ 기계어 검사 실패(%s)\n  ' % tag + '\n  '.join(bad))
    print('✅ 기계어 검사 %s %d 명령 — r2/r13 0 · 바깥 상대분기 0' % (tag, (code_end - base) // 4))


# ───────────────────────── data ─────────────────────────
def dialog_names():
    d = open(os.path.join(ROOT, 'work/snd/scripts.rcf'), 'rb').read()
    for m in re.finditer(rb'[^\x00]{20,}', d):
        es = re.findall(rb'create daSoundResourceData named (\S+)\s*\{', m.group())
        if len(es) == 3885:
            return [e.decode() for e in es]
    raise SystemExit('⛔ dialog.spt(3,885) 를 scripts.rcf 에서 못 찾았다')


def dialog_keys(iso=ORIG_ISO):
    """dialog.rcf 목차 → {클립이름(소문자, 확장자 없음): 파일 키}.
    목차 0x810~ = (해시, 오프셋, 크기) «해시 순» · 이름 목록(머리 +4 오프셋) = «오프셋 순».
    ⇒ 목차를 오프셋 순으로 정렬해 이름과 짝짓는다. 리소스 [[res+8]] = 이 해시(docs/08, 아이스크림 9.44초로 검증)."""
    import gcfst
    f = open(iso, 'rb')
    o = [e[1] for e in gcfst.read_fst(f)[1] if e[0].endswith('/dialog.rcf')]
    if len(o) != 1:
        raise SystemExit('⛔ dialog.rcf 를 FST 에서 못 찾았다')
    f.seek(o[0])
    h = f.read(0x60000)
    cnt, noff = struct.unpack_from('>II', h, 0x800)
    ents = [struct.unpack_from('>III', h, 0x810 + 12 * i) for i in range(cnt)]
    assert all(ents[i][0] < ents[i + 1][0] for i in range(cnt - 1)), '목차가 해시 순이 아니다'
    byoff = sorted(ents, key=lambda e: e[1])
    q = noff + 8
    out = {}
    for k in range(cnt):
        ln = struct.unpack_from('<I', h, q)[0]
        nm = h[q + 4:q + 4 + ln].rstrip(b'\0').decode('latin1')
        q += 4 + ln + 4
        base = nm.replace(chr(92), '/').split('/')[-1].lower()
        if base.endswith('.rsd'):
            base = base[:-4]
        if base in out:
            raise SystemExit('⛔ dialog.rcf 이름 중복: %s' % base)
        out[base] = byoff[k][0]
    if len(set(out.values())) != cnt:
        raise SystemExit('⛔ 키 중복')
    return out


def load_tsv(tsvs):
    """TSV 여러 개(«,» 로 이어 줌). 열 = 이름 · 한국어 · (비고…). 머리줄 «이름» 과 빈 번역은 건너뛴다."""
    names = dialog_names()
    idx = {n.lower(): n for n in names}
    keys = dialog_keys()
    subs = []
    empty = []
    for tsv in tsvs.split(','):
      for ln, line in enumerate(io.open(tsv, encoding='utf-8'), 1):
        line = line.rstrip('\n')
        if not line.strip() or line.startswith('#'):
            continue
        c = line.split('\t')
        k, v = c[0], (c[1] if len(c) > 1 else '')
        if k == '이름':
            continue
        if not v.strip():
            empty.append(k)
            continue
        k = k.strip().lower()
        if k.endswith('.rsd'):
            k = k[:-4]
        if k not in idx or k not in keys:
            raise SystemExit('⛔ %s %d행 클립 이름이 dialog.spt/dialog.rcf 에 없다: %r' % (tsv, ln, k))
        subs.append((keys[k], idx[k], v))
    if len(set(s[0] for s in subs)) != len(subs):
        raise SystemExit('⛔ 같은 클립이 두 번 나온다')
    if empty:
        print('  ⚠ 빈 번역 %d줄 건너뜀: %s' % (len(empty), ' '.join(empty)))
    return subs


WAVDIR = os.path.join(ROOT, 'work/snd/wav')


def clip_sec(name):
    """클립 길이(초) — rsdwav 로 푼 WAV 머리에서."""
    import wave
    p = os.path.join(WAVDIR, name.lower() + '.wav')
    if not os.path.exists(p):
        p = os.path.join(WAVDIR, name + '.wav')
    w = wave.open(p, 'rb')
    try:
        return w.getnframes() / float(w.getframerate())
    finally:
        w.close()


def page_starts(pages, sec):
    """쪽마다 나오는 시각(1/100 초) — 글자 수(공백 뺌) 비례."""
    n = [max(1, len(p.replace(' ', '').replace('\\n', ''))) for p in pages]
    tot = float(sum(n))
    out, acc = [], 0
    for k in n:
        out.append(int(round(sec * 100 * acc / tot)))
        acc += k
    return out


def font():
    from PIL import ImageFont
    return ImageFont.truetype(FONT, FONT_PX)


def text_w(f, s):
    return f.getlength(s) + 2 * OUTLINE


def wrap(f, text):
    """4:3 안전 폭 기준 최대 MAXLINES 줄. 강제 줄바꿈 «\\n» 존중. 공백에서 끊고 두 줄은 폭을 고르게."""
    parts = text.replace('\\n', '\n').split('\n')
    lines = []
    for p in parts:
        words = []
        for wd in p.split(' '):                 # «A 버튼» 같은 «영문 한 글자 + 다음 낱말»은 안 끊는다(하스피 스샷: A / 버튼은)
            if words and re.fullmatch(r'[A-Za-z]', words[-1]):
                words[-1] += ' ' + wd
            else:
                words.append(wd)
        cur = ''
        for wd in words:
            cand = (cur + ' ' + wd) if cur else wd
            if text_w(f, cand) <= MAXW:
                cur = cand
                continue
            if cur:
                lines.append(cur)
            cur = wd
            while text_w(f, cur) > MAXW:
                k = len(cur)
                while text_w(f, cur[:k]) > MAXW:
                    k -= 1
                lines.append(cur[:k])
                cur = cur[k:]
        lines.append(cur)
    lines = [l for l in lines if l] or ['']
    if len(parts) == 1 and len(lines) == 2:       # 자동 두 줄 → 고르게
        full = lines[0] + ' ' + lines[1]
        best = None
        for i, c in enumerate(full):
            if c != ' ':
                continue
            if i >= 1 and full[i - 1].isascii() and full[i - 1].isalpha() and (i < 2 or full[i - 2] == ' '):
                continue                          # «A 버튼» 안 끊기
            a, b = full[:i], full[i + 1:]
            if text_w(f, a) <= MAXW and text_w(f, b) <= MAXW:
                sc = abs(text_w(f, a) - text_w(f, b))
                if best is None or sc < best[0]:
                    best = (sc, [a, b])
        if best:
            lines = best[1]
    return lines


def render_line(f, lines):
    """줄들 → (w, h, I4 값 2차원 배열). w·h 는 8의 배수."""
    from PIL import Image, ImageDraw
    asc, desc = f.getmetrics()
    ws = [text_w(f, l) for l in lines]
    w = int(max(ws) + 0.999) + 2 * int(OUTLINE + 0.999) + 8   # 글자 그림이 진행 폭보다 튀어나온 만큼(«?» 잘림) 여유
    w = (w + 7) // 8 * 8
    h = len(lines) * LINE_H + (len(lines) - 1) * LINEGAP
    h = (h + 7) // 8 * 8
    SS = 4                                        # 4배로 그려 줄여 부드럽게
    from PIL import ImageFont
    fb = ImageFont.truetype(FONT, FONT_PX * SS)
    fill = Image.new('L', (w * SS, h * SS), 0)
    edge = Image.new('L', (w * SS, h * SS), 0)
    df, de = ImageDraw.Draw(fill), ImageDraw.Draw(edge)
    for i, l in enumerate(lines):
        lw = f.getlength(l)
        x = (w - lw) / 2.0
        y = i * (LINE_H + LINEGAP) + (LINE_H - (asc + desc)) / 2.0
        de.text((x * SS, y * SS), l, font=fb, fill=255, stroke_width=int(OUTLINE * SS), stroke_fill=255)
        df.text((x * SS, y * SS), l, font=fb, fill=255)
    fill = fill.resize((w, h), Image.LANCZOS)
    edge = edge.resize((w, h), Image.LANCZOS)
    fp, ep = fill.load(), edge.load()
    out = [[0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            a, e = fp[x, y] / 255.0, ep[x, y] / 255.0
            if a > 0.02:
                v = 8 + int(round(7 * a))
            else:
                v = int(round(4 * e))
            out[y][x] = min(15, v)
    return w, h, out


def to_i4(w, h, px):
    b = bytearray(w * h // 2)
    for y in range(h):
        for x in range(w):
            tile = (y >> 3) * (w >> 3) + (x >> 3)
            p = tile * 32 + (y & 7) * 4 + ((x & 7) >> 1)
            if x & 1:
                b[p] |= px[y][x]
            else:
                b[p] |= px[y][x] << 4
    return bytes(b)


def preview(items, path):
    """게임과 같은 계산(TEV)으로 화면 미리보기 — 화면 640×480 을 3배 확대해서."""
    from PIL import Image
    S = 3
    rows = []
    for name, w, h, px in items:
        im = Image.new('RGB', (640 * S, 180 * S), (88, 120, 70))
        # 4:3 안전 폭 표시
        for x in (40 * S, 600 * S - 1):
            for y in range(0, 180 * S, 6):
                im.putpixel((x, y), (255, 255, 0))
        # 레터박스 바(윗변 409 → 이 그림에서 409-360=49)
        for y in range(109 * S, 180 * S):
            for x in range(640 * S):
                im.putpixel((x, y), (0, 0, 0))
        tex = Image.new('RGBA', (w, h))
        tp = tex.load()
        for y in range(h):
            for x in range(w):
                I = px[y][x] / 15.0
                c = min(1, max(0, (I - 0.5) * 2))
                a = min(1, I * 4)
                tp[x, y] = (int(255 * c),) * 3 + (int(255 * a),)
        sw, sh = w * SCALE_NUM * S // SCALE_DEN, h * SCALE_NUM * S // SCALE_DEN
        t2 = tex.resize((sw, sh), Image.BILINEAR)
        x0 = (640 * S - sw) // 2
        y1 = (480 - BOTTOM - 300) * S
        im.paste(t2, (x0, y1 - sh), t2)
        rows.append(im)
    sheet = Image.new('RGB', (640 * S, 180 * S * len(rows)))
    for k, r in enumerate(rows):
        sheet.paste(r, (0, 180 * S * k))
    sheet.save(path)


def build_data(tsv, outdir, tut=True):
    os.makedirs(outdir, exist_ok=True)
    subs = load_tsv(tsv)
    f = font()
    # 글꼴에 없는 글자 = 빌드 실패 (PIL 은 조용히 □/빈칸을 그린다)
    from fontTools.ttLib import TTFont
    cmap = TTFont(FONT).getBestCmap()
    miss = sorted(set(c for _, _, t in subs for c in t.replace('\\n', '').replace('|', '') if c != ' ' and ord(c) not in cmap))
    if miss:
        raise SystemExit('⛔ 글꼴에 없는 글자: %s' % ' '.join('%s(U+%04X)' % (c, ord(c)) for c in miss))
    code = open(os.path.join(ROOT, 'ksub/ksub.bin'), 'rb').read()
    disc = bytearray()
    table = []
    pv = []
    maxsz = 0
    bad = []
    npg = 0
    for key, name, text in subs:
        pages = [p.strip() for p in text.split('|')]
        if any(not p for p in pages):
            raise SystemExit('⛔ 빈 쪽: %s' % name)
        ts = page_starts(pages, clip_sec(name)) if len(pages) > 1 else [0]
        if len(pages) > 1:
            npg += 1
        for pg, (ptxt, t) in enumerate(zip(pages, ts)):
            lines = wrap(f, ptxt)
            if len(lines) > MAXLINES:
                bad.append('%s 쪽%d (%d줄): %s' % (name, pg + 1, len(lines), ' / '.join(lines)))
                continue
            w, h, px = render_line(f, lines)
            if w > 1024:
                raise SystemExit('⛔ 텍스처 폭 1024 초과: %s' % name)
            img = to_i4(w, h, px)
            sz = (len(img) + 31) & ~31
            table.append((key, pg, len(disc), w, h, t))
            disc += img + b'\0' * (sz - len(img))
            maxsz = max(maxsz, sz)
            if len(pv) < 12:
                pv.append((name, w, h, px))
    if bad:
        raise SystemExit('⛔ %d줄 넘침(최대 %d줄):\n  ' % (len(bad), MAXLINES) + '\n  '.join(bad))
    table.sort()
    # 튜토리얼 상자(tools/tutkr.py · work/tut/tut_ko.tsv) — 글자 I4 는 디스크, 아이콘 자리·아이콘 그림은 RAM
    ttab, ticons, iconimg = [], [], b''
    if tut:
        import tutkr
        trows, iconimg = tutkr.build()
        for hsh, k, w, h, px, ic in trows:
            img = to_i4(w, h, px)
            sz = (len(img) + 31) & ~31
            ttab.append((hsh, len(disc), w, h, len(ic), len(ticons)))
            disc += img + b'\0' * (sz - len(img))
            maxsz = max(maxsz, sz)
            ticons += ic
        print('  튜토리얼 %d문장 · 아이콘 자리 %d · 아이콘 그림 %d B · 가장 큰 그림 %d B'
              % (len(ttab), len(ticons), len(iconimg), max(((w * h // 2 + 31) & ~31) for _, _, w, h, _, _ in ttab)))
    off_lines = HDR
    off_tut = off_lines + KLINE * len(table)
    off_ticon = off_tut + KLINE * len(ttab)
    off_iconimg = (off_ticon + 8 * len(ticons) + 31) & ~31
    off_buf = off_iconimg + len(iconimg) + 32       # +32 = 런타임 32 정렬로 옮길 여유(ksub.c icons())
    bufsize = maxsz
    off_code = off_buf + 32 + 2 * bufsize
    off_code += (-off_code) % 4
    hdr = struct.pack('>IIIII HHHH II IIII HH I', 0x4B535542, len(table), off_lines, off_buf, bufsize,
                      BOTTOM, SCALE_NUM, SCALE_DEN, 0, off_code, len(code),
                      off_tut, len(ttab), off_ticon, off_iconimg, TUT_DY, BOTTOM_TUT, 0)
    assert len(hdr) == HDR, len(hdr)
    blk = hdr + b''.join(struct.pack('>IIHHHH', k, d, w, h, t, pg) for k, pg, d, w, h, t in table)
    blk += b''.join(struct.pack('>IIHHHH', *t) for t in ttab)
    blk += b''.join(struct.pack('>BBhhBB', i, 0, x, y, w, h) for i, x, y, w, h in ticons)
    blk += b'\0' * (off_iconimg - len(blk)) + iconimg
    blk += b'\0' * (off_code - len(blk)) + code
    open(os.path.join(outdir, 'block.bin'), 'wb').write(blk)
    open(os.path.join(outdir, 'disc.bin'), 'wb').write(bytes(disc))
    pvp = os.path.join(outdir, '미리보기_자막.png')
    preview(pv, pvp)
    print('✅ 자막 %d줄(그림 %d장 · 여러 쪽 대사 %d) · 줄 그림 묶음 %d B(디스크) · RAM 블록 %d B (버퍼 2×%d B · 코드 %d B)'
          % (len(subs), len(table), npg, len(disc), len(blk), bufsize, len(code)))
    for key, name, text in subs[:12]:
        print('   %08X %s → %s' % (key, name, ' / '.join(wrap(f, text))))
    print('   미리보기 %s' % os.path.abspath(pvp))


# ───────────────────────── install ─────────────────────────
def swap16(b):
    b = bytearray(b + (b'\0' if len(b) % 2 else b''))
    b[0::2], b[1::2] = b[1::2], b[0::2]
    return bytes(b)


def append_block(src, blk):
    """바이블 E 슬롯 문자열 영역 끝에 블록을 붙인다(옛 v0.8 자막 표는 잘라 냄). 반환: 새 p3d."""
    import p3d
    import txtbible
    d = bytearray(src)
    L = [x for x in txtbible.langs(bytes(d)) if x['code'] == 'E'][0]
    coff = L['chunk']
    cid, cdsz, ccsz = struct.unpack_from('<III', d, coff)
    assert cid == 0x0001800E and cdsz == ccsz, '언어 청크가 잎이 아니다'
    blob_end = coff + ccsz
    if bytes(d[blob_end - 64:blob_end]) != bytes(L['blob'][-64:]):
        raise SystemExit('⛔ 문자열 영역이 청크 끝이 아니다')
    keep = L['blen']
    ram0 = swap16(bytes(L['blob']))
    st0 = struct.unpack_from('>I', ram0, L['blen'] - 4)[0]
    maxoff = max(o & ~1 for o in L['offs'])
    if maxoff < st0 < L['blen'] - 8:
        rb, cnt = struct.unpack_from('>II', ram0, st0)
        if rb == 8 + cnt * 12 and 0 < cnt < 10000:
            keep = st0
            print('  ✂ 옛 자막 표 잘라 냄: 블롭 %d → %d B (−%d, 항목 %d)' % (L['blen'], keep, L['blen'] - keep, cnt))
        else:
            raise SystemExit('⛔ 블롭 꼬리가 옛 자막 표 모양이 아니다(rowbase %X count %d)' % (rb, cnt))
    cut = L['blen'] - keep
    pad = (-keep) % 32
    start = keep + pad
    body = b'\0' * pad + blk
    body += b'\0' * ((-len(body)) % 4)
    payload = swap16(body + struct.pack('>I', start))
    delta = len(payload) - cut
    newblen = L['blen'] + delta
    parent = [(off, csz) for depth, ccid, off, dsz, csz in p3d.walk(bytes(d), 12)
              if ccid == 0x0001800D and off < coff < off + csz]
    assert len(parent) == 1, parent
    d[blob_end - cut:blob_end] = payload
    struct.pack_into('<II', d, coff + 4, cdsz + delta, ccsz + delta)
    struct.pack_into('<I', d, parent[0][0] + 8, parent[0][1] + delta)
    struct.pack_into('<I', d, 8, struct.unpack_from('<I', bytes(d), 8)[0] + delta)
    p = coff + 12
    ln = d[p]
    p += 1 + ln + 1
    n_, a_, blen_ = struct.unpack_from('<III', d, p)
    assert (n_, blen_) == (L['n'], L['blen'])
    struct.pack_into('<I', d, p + 8, newblen)
    L2 = [x for x in txtbible.langs(bytes(d)) if x['code'] == 'E'][0]
    ram = swap16(bytes(L2['blob']))
    st = struct.unpack_from('>I', ram, newblen - 4)[0]
    assert st == start and ram[st:st + len(blk)] == blk, '되읽기 불일치'
    diff = [i for i in range(L['n']) if txtbible.text(L2, i) != txtbible.text(L, i)]
    if diff:
        raise SystemExit('⛔ 기존 UI 문자열이 바뀌었다: %s' % diff[:10])
    print('✅ 바이블 E 슬롯 %d → %d B (%+d) · 블록 시작 0x%X · UI 문자열 %d개 전부 그대로'
          % (L['blen'], newblen, delta, start, L['n']))
    return bytes(d)


def install(iso, outdir):
    import gcfst
    import isofile
    syms = syms_of(os.path.join(ROOT, 'ksub/ksub.elf'))
    blk = bytearray(open(os.path.join(outdir, 'block.bin'), 'rb').read())
    disc = open(os.path.join(outdir, 'disc.bin'), 'rb').read()
    low = open(os.path.join(ROOT, 'ksub/low.bin'), 'rb').read()
    py = sys.executable
    tmp = os.path.join(ROOT, 'work/v09')
    os.makedirs(tmp, exist_ok=True)
    # 1) 옛 자막 계통 제거
    subprocess.run([py, os.path.join(HERE, 'dolhook.py'), iso, '--reset'], check=True, env=env(),
                   stdout=subprocess.DEVNULL)
    print('  ✅ dolhook --reset')
    # 2) 레터박스 페이지 원복
    io_, it, iw = (os.path.join(tmp, n) for n in ('ingame_orig.p3d', 'ingame_base.p3d', 'ingame_lb.p3d'))
    subprocess.run([py, os.path.join(HERE, 'gcfst.py'), ORIG_ISO, '--get', INGAME, io_], check=True, env=env(), stdout=subprocess.DEVNULL)
    subprocess.run([py, os.path.join(HERE, 'gcfst.py'), iso, '--get', INGAME, it], check=True, env=env(), stdout=subprocess.DEVNULL)
    subprocess.run([py, os.path.join(HERE, 'lbrestore.py'), io_, it, '--write', iw], check=True, env=env())
    # 2') UI 한글 폰트 2배 해상도(tools/kfont2x.py) — 원본 아틀라스는 늘 work/uifont/v08/ 에서(되풀어 2배 금지)
    import kfont2x
    if UI_FONT_2X:
        pngs, graw = kfont2x.build_pages(open(os.path.join(ROOT, 'work/uifont/v08/ingame.p3d'), 'rb').read(),
                                         UI_FONT_SCALE, kfont2x.ui_syllables(), True)[:2]
        d = kfont2x.apply_pages(open(iw, 'rb').read(), pngs, graw)
        open(iw, 'wb').write(d)
    if open(iw, 'rb').read() != open(it, 'rb').read():
        subprocess.run([py, os.path.join(HERE, 'isofile.py'), iso, '--replace', INGAME, iw], check=True, env=env())
    for nm in ('frontend', 'language', 'minigame'):
        vp = '/art/frontend/scrooby/%s.p3d' % nm
        cur, new = (os.path.join(tmp, '%s_%s.p3d' % (nm, k)) for k in ('cur', 'font'))
        subprocess.run([py, os.path.join(HERE, 'gcfst.py'), iso, '--get', vp, cur], check=True, env=env(), stdout=subprocess.DEVNULL)
        src = open(os.path.join(ROOT, 'work/uifont/v08/%s.p3d' % nm), 'rb').read()
        if UI_FONT_2X:
            pngs, graw = kfont2x.build_pages(src, UI_FONT_SCALE, kfont2x.ui_syllables(), True)[:2]
            d = kfont2x.apply_pages(open(cur, 'rb').read(), pngs, graw)
        else:
            d = src
        if d != open(cur, 'rb').read():
            open(new, 'wb').write(d)
            subprocess.run([py, os.path.join(HERE, 'isofile.py'), iso, '--replace', vp, new], check=True, env=env())
            print('  ✅ %s 한글 폰트 %s' % (nm, '%.2f배 한 장' % UI_FONT_SCALE if UI_FONT_2X else 'v0.8 원래대로'))
    # 3) 줄 그림 묶음 → 가장 큰 구멍의 끝
    with open(iso, 'rb') as f:
        fsto, fsts, fst, n, ents = isofile.read_fst(f)
        f.seek(0, 2)
        disc_size = f.tell()
        dol, dol_end = isofile.dol_extent(f)
    holes = isofile.free_holes(ents, disc_size, reserved=((0, fsto + fsts), (dol, dol_end)))
    hs, hl = max(holes, key=lambda x: x[1])
    base = (hs + hl - len(disc) - 0x8000) & ~0x7FFF
    if base < hs + 0x200000:
        raise SystemExit('⛔ 빈 구멍이 모자라다')
    struct.pack_into('>I', blk, HDR - 4, base)
    with open(iso, 'r+b') as f:
        f.seek(base)
        f.write(disc)
    print('  ✅ 줄 그림 묶음 %d B → ISO 0x%X (구멍 0x%X+%d 의 끝)' % (len(disc), base, hs, hl))
    # 4) 바이블 — 원본 srr2.p3d + v0.8 UI 번역(ui_kr_boot_en6.tsv) + v0.9 덮어쓰기(UI_OVERRIDE)로 «새로» 짠다
    #    (v0.8 결과물을 이어 쓰지 않는다 → 옛 자막 표·자막 칸 예약 --big 이 애초에 없다)
    ui = {}
    for path in (UI_TSV, UI_OVERRIDE):
        for line in io.open(path, encoding='utf-8'):
            line = line.rstrip('\n')
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            k, v = line.split('\t', 1)
            ui[int(k)] = v
    uitsv = os.path.join(tmp, 'ui_v09.tsv')
    io.open(uitsv, 'w', encoding='utf-8', newline='\n').write(''.join('%d\t%s\n' % kv for kv in sorted(ui.items())))
    src = os.path.join(tmp, 'srr2_v09ui.p3d')
    subprocess.run([py, os.path.join(HERE, 'biblebuild.py'), os.path.join(ROOT, 'work/extract/srr2.p3d'), src, uitsv],
                   check=True, env=env())
    srcb = open(src, 'rb').read()
    newb = append_block(srcb, bytes(blk))
    dst = os.path.join(tmp, 'srr2_ksub.p3d')
    open(dst, 'wb').write(newb)
    subprocess.run([py, os.path.join(HERE, 'isofile.py'), iso, '--replace', BIBLE, dst], check=True, env=env())
    # 5) 적재기 + 훅
    with open(iso, 'r+b') as f:
        f.seek(0x420)
        dol = struct.unpack('>I', f.read(4))[0]
        f.seek(dol)
        h = bytes(f.read(0x100))
        off = struct.unpack_from('>18I', h, 0)
        va = struct.unpack_from('>18I', h, 0x48)
        sz = struct.unpack_from('>18I', h, 0x90)

        def va2iso(a):
            for i in range(18):
                if sz[i] and va[i] <= a < va[i] + sz[i]:
                    return dol + off[i] + (a - va[i])
            raise SystemExit('⛔ VA %08X 가 DOL 에 없다' % a)
        p = va2iso(LOW_VA)
        assert va2iso(LOW_VA + LOW_MAX - 1) == p + LOW_MAX - 1
        f.seek(p)
        if f.read(LOW_MAX) != bytes(LOW_MAX):
            raise SystemExit('⛔ 케이브 0x%08X 가 0 이 아니다 — dolhook --reset 확인' % LOW_VA)
        f.seek(p)
        f.write(low)
        print('  ✅ 적재기 %d B → VA %08X (ISO 0x%X)' % (len(low), LOW_VA, p))

        def rw(a, old, new):
            q = va2iso(a)
            f.seek(q)
            cur = struct.unpack('>I', f.read(4))[0]
            if cur == new:                       # 앞 시험판 설치가 이미 같은 훅을 넣어 둠(dolhook --reset 은 v0.8 자리만 되돌림)
                print('  ✅ VA %08X  이미 %08X' % (a, new))
                return
            if (cur >> 26) == 18:                # 앞 시험판의 우리 훅(적재기 구역으로 가는 b/bl)이면 새 자리로 바꿔 쓴다
                t = (cur & 0x03FFFFFC)
                t = (t - 0x04000000 if t & 0x02000000 else t) + a
                if LOW_VA <= (t & 0xFFFFFFFF) < LOW_VA + LOW_MAX and (cur & 3) == (new & 3):
                    old = cur
            if cur != old:
                raise SystemExit('⛔ VA %08X 원본이 아니다: %08X (기대 %08X)' % (a, cur, old))
            f.seek(q)
            f.write(struct.pack('>I', new))
            print('  ✅ VA %08X  %08X → %08X' % (a, old, new))
        rw(BIB_HOOK, BIB_ORIG, bform(BIB_HOOK, syms['hook_bib'], 0))
        rw(FRAME_HOOK, bform(FRAME_HOOK, GXDRAWDONE, 1), bform(FRAME_HOOK, syms['ksub_entry'], 1))
        rw(TUT_HOOK, bform(TUT_HOOK, TUT_ORIG_TO, 1), bform(TUT_HOOK, syms['hook_tut'], 1))
    # 6) 최종 검사
    with open(iso, 'rb') as f:
        ents = isofile.read_fst(f)[4]
        dol, dol_end = isofile.dol_extent(f)
        f.seek(base)
        if f.read(len(disc)) != disc:
            raise SystemExit('⛔ 줄 그림 묶음이 덮였다')
    for e in ents:
        i_, path, isdir, eo, es = e
        if not isdir and es and eo < base + len(disc) and base < eo + es:
            raise SystemExit('⛔ 줄 그림 묶음이 파일 %s 와 겹친다' % path)
    if dol < base + len(disc) and base < dol_end:
        raise SystemExit('⛔ 줄 그림 묶음이 DOL 과 겹친다')
    print('✅ 최종 검사: 줄 그림 묶음 ISO 0x%X~0x%X — FST 파일·DOL 과 안 겹침, 내용 일치' % (base, base + len(disc)))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='cmd', required=True)
    sp.add_parser('code')
    s = sp.add_parser('data')
    s.add_argument('tsv')
    s.add_argument('outdir')
    s = sp.add_parser('install')
    s.add_argument('iso')
    s.add_argument('outdir')
    a = ap.parse_args()
    if a.cmd == 'code':
        build_code()
    elif a.cmd == 'data':
        build_data(a.tsv, a.outdir)
    else:
        install(a.iso, a.outdir)


if __name__ == '__main__':
    main()
