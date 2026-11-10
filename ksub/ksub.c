/* 심슨 히트 앤 런 (GC GHQE) v0.9 — «소리 재생 상태»로 자막을 직접 그리는 코드.  docs/08_v0.9_소리재생훅.md
 *
 * 구역
 *   LOW  0x80004888~ (DOL text0 0 구간, 확실히 실린다): 적재기 ksub_entry · 바이블 훅 · 공유 변수
 *   HIGH 0x8048AC00~ (스택 끝~아레나 사이 8KB): 본체 — 블록에서 적재기가 한 번 복사
 * 불리는 곳: pddiDisplay::SwapBuffers 0x80276D20 «bl GXDrawDone» → «bl ksub_entry»
 *
 * 매 프레임
 *   1) 사운드 재생기 리스트(머리 [0x80476BA0], 다음 +4) 중 daSoundClipStreamPlayer(vtbl 0x8037F998)의
 *      리소스(+0x5C) 첫 파일 키 [[res+8]] 를 자막 표(키 오름차순)에서 찾는다.
 *        상태(+0x44) 4 = 실제 재생 → 표시할 줄 · 상태 1~3 = 준비 중 → 미리 읽을 줄
 *   2) 줄 그림(빌더가 미리 그린 I4 텍스처)을 디스크 절대 위치에서 DVDReadAbsAsyncPrio 로 버퍼(2개)에 읽는다.
 *   3) 표시할 줄이 버퍼에 다 읽혔으면 GX 로 화면 아래 가운데에 그린다(텍스처 1.5배 → 화면 1배).
 * ⚠ 게임 r2/r13 을 쓰지 않는다 — 빌더가 기계어 전체를 검사한다.
 */
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
typedef int s32;
typedef short s16;

#define R32(a) (*(volatile u32 *)(a))

/* ── 게임 SDK 함수 (docs/08 표) ── */
#define GXClearVtxDesc     ((void (*)(void))0x8032A198)
#define GXSetVtxDesc       ((void (*)(u32, u32))0x80329CD0)
#define GXSetVtxAttrFmt    ((void (*)(u32, u32, u32, u32, u32))0x8032A1D0)
#define GXSetNumTexGens    ((void (*)(u32))0x8032ACA8)
#define GXSetTexCoordGen2  ((void (*)(u32, u32, u32, u32, u32, u32))0x8032A9D8)
#define GXBegin            ((void (*)(u32, u32, u32))0x8032B3E4)
#define GXSetCullMode      ((void (*)(u32))0x8032B648)
#define GXSetNumChans      ((void (*)(u32))0x8032C474)
#define GXInitTexObj       ((void (*)(void *, void *, u32, u32, u32, u32, u32, u32))0x8032C7A8)
#define GXLoadTexObj       ((void (*)(void *, u32))0x8032CDA0)
#define GXInvalidateTexAll ((void (*)(void))0x8032D054)
#define GXSetTevDirect     ((void (*)(u32))0x8032D88C)
#define GXSetTevColorIn    ((void (*)(u32, u32, u32, u32, u32))0x8032DA50)
#define GXSetTevAlphaIn    ((void (*)(u32, u32, u32, u32, u32))0x8032DA94)
#define GXSetTevColorOp    ((void (*)(u32, u32, u32, u32, u32, u32))0x8032DAD8)
#define GXSetTevAlphaOp    ((void (*)(u32, u32, u32, u32, u32, u32))0x8032DB40)
#define GXSetAlphaCompare  ((void (*)(u32, u32, u32, u32, u32))0x8032DE54)
#define GXSetTevOrder      ((void (*)(u32, u32, u32, u32))0x8032DF2C)
#define GXSetNumTevStages  ((void (*)(u32))0x8032E104)
#define GXSetBlendMode     ((void (*)(u32, u32, u32, u32))0x8032E3E4)
#define GXSetColorUpdate   ((void (*)(u32))0x8032E438)
#define GXSetZMode         ((void (*)(u32, u32, u32))0x8032E490)
#define GXSetProjection    ((void (*)(const float *, u32))0x8032E77C)
#define GXLoadPosMtxImm    ((void (*)(const float *, u32))0x8032E8F0)
#define GXSetCurrentMtx    ((void (*)(u32))0x8032E990)
#define GXDrawDone         ((void (*)(void))0x8032AF68)
#define DCFlushRange       ((void (*)(void *, u32))0x8030A074)
#define DCInvalidateRange  ((void (*)(void *, u32))0x8030A048)
#define ICInvalidateRange  ((void (*)(void *, u32))0x8030A100)
#define DVDReadAbsAsyncPrio ((s32 (*)(void *, void *, s32, s32, void *, s32))0x803141B0)
#define DVDGetCommandBlockStatus ((s32 (*)(void *))0x80314610)

#define FIFO_F (*(volatile float *)0xCC008000)

#define LOWTEXT __attribute__((section(".lowtext"), noinline))
#define LOWDATA __attribute__((section(".lowdata")))
#define HIGH_VA 0x8048AC00u

#define PLAYER_HEAD   0x80476BA0u
#define POOL_PTR      0x80476BD8u
#define VT_STREAM     0x8037F998u
#define POOL_N_OFF    0x186C0u
#define KSUB_MAGIC    0x4B535542u   /* 'KSUB' */

/* 자막 블록 머리 (RAM, 빅엔디안) — tools/ksub.py 와 같아야 한다 */
typedef struct {
    u32 magic;      /* 'KSUB' */
    u32 nlines;     /* 자막 그림 수(쪽 포함) */
    u32 off_lines;  /* KLine[nlines] — key·pg 오름차순 */
    u32 off_buf;    /* 텍스처 버퍼 2개(블록 기준, +32 여유 — 런타임에 32 정렬) */
    u32 bufsize;    /* 버퍼 하나 크기(32 배수) */
    u16 bottom;     /* 화면 아래에서 자막 아랫변까지(화면 px) */
    u16 scale_num;  /* 화면 크기 = 텍스처 크기 × num/den */
    u16 scale_den;
    u16 pad;
    u32 off_code;   /* 본체 코드 이미지 → HIGH_VA 로 복사 */
    u32 code_size;
    /* ── 튜토리얼 상자 (v0.9) ── */
    u32 off_tut;    /* KLine[ntut] — key = 영문 문장 FNV-1a(u16) · t = 아이콘 수 · pg = 첫 아이콘 번호 */
    u32 ntut;
    u32 off_ticon;  /* TIcon[] */
    u32 off_iconimg;/* 아이콘 그림 32×32 RGB5A3 × n (2,048 B 씩, 32 정렬) */
    u16 tut_dy;     /* 상자 요소 윗변 → 한글 그림 윗변(화면 px) */
    u16 bottom_tut; /* 튜토리얼 떠 있을 때 자막 bottom(«튜토리얼 끄기» 표시를 피해 위로) */
    u32 disc_base;  /* 줄 그림 묶음의 디스크 절대 오프셋(설치 때 기록, 32 정렬) — 반드시 마지막 */
} KHead;

/* doff = disc_base 기준(32 정렬) · 한 대사가 여러 쪽이면 같은 key 로 pg 0,1,2… 이어진다(key·pg 오름차순)
   t = 그 쪽이 나오는 시각(재생 시작 = 상태 4 부터, 1/100 초) */
typedef struct { u32 key; u32 doff; u16 w; u16 h; u16 t; u16 pg; } KLine;
/* 튜토리얼 아이콘 자리 — 한글 그림(텍스처 px) 기준 왼쪽 위 · w·h 도 텍스처 px */
typedef struct { u8 id; u8 pad; s16 x; s16 y; u8 w; u8 h; } TIcon;
typedef char chk_khead[sizeof(KHead) == 0x3C ? 1 : -1];   /* tools/ksub.py HDR 과 같아야 */
typedef char chk_ticon[sizeof(TIcon) == 8 ? 1 : -1];

#define TUT_NAME0 0xD7431C37u   /* 요소 +8/+C = 이름 해시 «TutorialMessage» (스테이트 실측, Tutorial.pag·Hud.pag 둘 다) */
#define TUT_NAME1 0xB1410A6Bu
#define DrawSpriteText ((void (*)(u32))0x802133C8)

/* ── 저메모리 상태(적재기와 공유) ── */
LOWDATA u32 g_lang = 0;
LOWDATA u32 g_ready = 0;
LOWDATA u32 g_lowdbg[2] = { 0, 0 };

/* ── 본체 상태 ── */
typedef struct { const KLine *ln; u32 st; } KBuf;   /* st: 0 빔 · 1 읽는 중 · 2 다 읽음 */
static KBuf g_buf[2];
static s32 g_rd = -1;                  /* 읽는 중인 버퍼 */
static u32 g_cmd[16];                  /* DVDCommandBlock (0x30 B) + 여유 */
static u32 g_texobj[8];
u32 g_dbg[8];  /* [0]프레임 [1]마지막 상태4 키 [2]그린 횟수 [3]읽기 요청 [4]읽기 완료 [5]읽기 실패 [6]튜토리얼 가림 [7]마지막 튜토리얼 해시 */
static const KLine *g_pfirst = 0;      /* 지금 재생 중 대사의 첫 쪽 */
static u32 g_pt0;                      /* 그 대사 재생 시작 시각(시간 기준 레지스터) */
static const KLine *g_tut = 0;         /* 이번 프레임 HUD 가 그리려던 튜토리얼 문장 */
static u32 g_tute = 0;                 /* 그 상자 요소 */
static u8 *g_icons = 0;                /* 32 정렬로 옮긴 아이콘 그림(블록 시작이 RAM 에서 32 정렬이 아닐 수 있다) */

/* 아이콘 그림을 블록 안 32 정렬 자리로 한 번 옮긴다 — 빌더가 뒤에 32 B 여유를 둔다. 텍스처는 32 정렬 필수(시험 10 줄무늬) */
static u8 *icons(KHead *H)
{
    if (!g_icons) {
        u8 *src = (u8 *)H + H->off_iconimg;
        u8 *dst = (u8 *)(((u32)src + 31) & ~31u);
        u32 n = 7 * 2048, k;
        if (dst != src)
            for (k = n; k > 0; k--) dst[k - 1] = src[k - 1];   /* 겹침 — 뒤에서부터 */
        DCFlushRange(dst, n);
        g_icons = dst;
    }
    return g_icons;
}
#define TB_PER_CS 405000u              /* 시간 기준 40.5 MHz(버스 162 MHz / 4) → 1/100 초 */

/* 750(Gekko)은 시간 기준을 mftb(371) 로만 읽는다 — 컴파일러는 mfspr 268 을 내므로 명령어를 직접 쓴다(mftb r3) */
static inline u32 mftbl(void) { u32 x; __asm__ volatile(".long 0x7C6C42E6; mr %0,3" : "=r"(x) : : "r3"); return x; }

#define INRAM(a) ((a) >= 0x80000000u && (a) < 0x81800000u)

LOWTEXT static KHead *ksub_block(void)
{
    u32 L = g_lang, blob, blen, st;
    if (L < 0x80000000u || L >= 0x81800000u) return 0;
    blob = R32(L + 0x28);
    blen = R32(L + 0x18);
    if (blob < 0x7E000000u || blen < 64) return 0;
    st = R32(blob + blen - 4);
    if (st >= blen - 4) return 0;
    if (R32(blob + st) != KSUB_MAGIC) return 0;
    return (KHead *)(blob + st);
}

/* 키 오름차순 표에서 key 의 첫 칸 */
static const KLine *find_key(const KLine *T, u32 n, u32 key)
{
    s32 lo = 0, hi = (s32)n - 1;
    while (lo <= hi) {
        s32 m = (lo + hi) >> 1;
        if (T[m].key == key) {
            while (m > 0 && T[m - 1].key == key) m--;     /* 첫 쪽 */
            return &T[m];
        }
        if (T[m].key < key) lo = m + 1; else hi = m - 1;
    }
    return 0;
}

static const KLine *lookup(KHead *H, u32 key)
{
    return find_key((const KLine *)((u8 *)H + H->off_lines), H->nlines, key);
}

/* HUD 가 스프라이트 글자 요소를 그리기 직전(0x80213110)에 불린다.
   튜토리얼 상자이고 번역이 있으면 1 → 영문을 그리지 않는다(한글은 ksub_frame 이 그린다). */
__attribute__((noinline)) u32 ksub_tut(u32 e)
{
    KHead *H = ksub_block();
    u32 s, b, h, k;
    const KLine *L;
    if (!H || !H->ntut) return 0;
    if (R32(e + 8) != TUT_NAME0 || R32(e + 12) != TUT_NAME1) return 0;
    s = R32(e + 0xAC);
    if (!INRAM(s)) return 0;
    b = R32(s);
    if (!INRAM(b)) return 0;
    h = 2166136261u;
    for (k = 0; k < 400; k++) {
        u32 c = *(volatile u16 *)(b + 2 * k);
        if (!c) break;
        h ^= c;
        h *= 16777619u;
    }
    g_dbg[7] = h;
    L = find_key((const KLine *)((u8 *)H + H->off_tut), H->ntut, h);
    if (!L) return 0;
    g_tut = L;
    g_tute = e;
    g_dbg[6]++;
    return 1;
}

/* 재생기를 훑어 «재생 중(4)» 줄과 «준비 중(1~3)» 줄을 찾는다 */
static void scan(KHead *H, const KLine **play, const KLine **pre)
{
    u32 pool = R32(POOL_PTR), b0, b1, o;
    s32 n = 0;
    *play = 0; *pre = 0;
    if (pool < 0x80000000u || pool >= 0x81800000u) return;
    b0 = pool + 0x20;
    b1 = b0 + R32(pool + POOL_N_OFF) * 0x14;
    o = R32(PLAYER_HEAD);
    while (o >= 0x80000000u && o < 0x81800000u && n < 256) {
        u32 st;
        n++;
        st = R32(o + 0x44);
        if (R32(o) == VT_STREAM && st >= 1 && st <= 4) {
            u32 r = R32(o + 0x5C), kp;
            if (r >= b0 && r < b1 && ((r - b0) % 0x14) == 0) {
                kp = R32(r + 8);
                if (kp >= 0x80000000u && kp < 0x81800000u) {
                    const KLine *L = lookup(H, R32(kp));
                    if (st == 4) g_dbg[1] = R32(kp);
                    if (L) {
                        if (st == 4) { if (!*play) *play = L; }
                        else if (!*pre) *pre = L;
                    }
                }
            }
        }
        o = R32(o + 4);
    }
}

static u8 *bufptr(KHead *H, s32 i)
{
    return (u8 *)((((u32)H + H->off_buf) + 31) & ~31u) + i * H->bufsize;
}

static u32 imgsize(const KLine *L) { return ((u32)L->w * L->h / 2 + 31) & ~31u; }

static s32 find_buf(const KLine *L)
{
    s32 i;
    for (i = 0; i < 2; i++) if (g_buf[i].ln == L && g_buf[i].st) return i;
    return -1;
}

/* 비동기 읽기 진행·요청.  원하는 순서 = 재생 중 자막 · 튜토리얼 · 미리 읽기(다음 쪽/준비 중 대사).
   버퍼 2개 — 재생 중 자막·튜토리얼을 담은 버퍼는 지키고 남는 쪽에 읽는다(튜토리얼이 떠 있으면 미리 읽기는 쉰다). */
static void pump(KHead *H, const KLine *play, const KLine *tut, const KLine *pre)
{
    const KLine *wl[3];
    s32 i, k, n = 0;
    if (g_rd >= 0) {
        s32 s = DVDGetCommandBlockStatus(g_cmd);
        if (s == 0) {                           /* DVD_STATE_END */
            g_buf[g_rd].st = 2;
            GXInvalidateTexAll();
            g_dbg[4]++;
            g_rd = -1;
        } else if (s == -1 || s >= 10) {        /* FATAL · CANCELED 등 */
            g_buf[g_rd].st = 0;
            g_buf[g_rd].ln = 0;
            g_dbg[5]++;
            g_rd = -1;
        } else {
            return;                             /* 아직 읽는 중 */
        }
    }
    if (play) wl[n++] = play;
    if (tut) wl[n++] = tut;
    if (pre) wl[n++] = pre;
    for (k = 0; k < n; k++) {
        const KLine *want = wl[k];
        if (find_buf(want) >= 0) continue;
        if (imgsize(want) > H->bufsize) continue;
        /* 지킬 것(play·tut)을 담지 않은 버퍼, 빈 버퍼 우선 */
        i = -1;
        if (!g_buf[0].st) i = 0;
        else if (!g_buf[1].st) i = 1;
        if (i < 0) {
            s32 j;
            for (j = 0; j < 2; j++)
                if (g_buf[j].ln != play && g_buf[j].ln != tut) { i = j; break; }
        }
        if (i < 0) return;
        g_buf[i].ln = want;
        g_buf[i].st = 1;
        DCInvalidateRange(bufptr(H, i), imgsize(want));
        if (DVDReadAbsAsyncPrio(g_cmd, bufptr(H, i), (s32)imgsize(want), (s32)(H->disc_base + want->doff), 0, 2)) {
            g_rd = i;
            g_dbg[3]++;
        } else {
            g_buf[i].st = 0;
            g_buf[i].ln = 0;
            g_dbg[5]++;
        }
        return;                                 /* 한 번에 하나 */
    }
}

static const float mtx_id[12] = { 1, 0, 0, 0,  0, 1, 0, 0,  0, 0, 1, 0 };

/* 화면 640×480 직교 투영 + 텍스처 사각형 공통 상태 */
static void gx_setup(void)
{
    float proj[16];
    s32 k;
    for (k = 0; k < 16; k++) proj[k] = 0.0f;
    /* MTXOrtho(t=0, b=480, l=0, r=640, n=0, f=1) */
    proj[0] = 2.0f / 640.0f;  proj[3] = -1.0f;
    proj[5] = -2.0f / 480.0f; proj[7] = 1.0f;
    proj[10] = -1.0f;         proj[11] = -1.0f;
    proj[15] = 1.0f;

    GXSetProjection(proj, 1);
    GXLoadPosMtxImm(mtx_id, 0);
    GXSetCurrentMtx(0);

    GXClearVtxDesc();
    GXSetVtxDesc(9, 1);
    GXSetVtxDesc(13, 1);
    GXSetVtxAttrFmt(0, 9, 1, 4, 0);
    GXSetVtxAttrFmt(0, 13, 1, 4, 0);

    GXSetNumChans(0);
    GXSetNumTexGens(1);
    GXSetTexCoordGen2(0, 1, 4, 60, 0, 125);
    GXSetNumTevStages(1);
    GXSetTevDirect(0);
    GXSetTevOrder(0, 0, 0, 0xFF);
    GXSetAlphaCompare(7, 0, 0, 7, 0);
    GXSetBlendMode(1, 4, 5, 0);
    GXSetZMode(0, 7, 0);
    GXSetCullMode(0);
    GXSetColorUpdate(1);
}

/* fmt 0 = I4 글자 그림(색=(I-0.5)×2 · 알파=I×4) · fmt 5 = RGB5A3 아이콘(그대로) */
static void quad(u8 *tex, u32 tw, u32 th, u32 fmt, float x0, float y0, float x1, float y1)
{
    GXInitTexObj(g_texobj, tex, tw, th, fmt, 0, 0, 0);
    GXLoadTexObj(g_texobj, 0);
    if (fmt == 0) {
        GXSetTevColorIn(0, 15, 15, 15, 8);
        GXSetTevColorOp(0, 0, 2, 1, 1, 0);
        GXSetTevAlphaIn(0, 7, 7, 7, 4);
        GXSetTevAlphaOp(0, 0, 0, 2, 1, 0);
    } else {
        GXSetTevColorIn(0, 15, 15, 15, 8);
        GXSetTevColorOp(0, 0, 0, 0, 1, 0);
        GXSetTevAlphaIn(0, 7, 7, 7, 4);
        GXSetTevAlphaOp(0, 0, 0, 0, 1, 0);
    }
    GXBegin(0x80, 0, 4);
    FIFO_F = x0; FIFO_F = y0; FIFO_F = -0.5f; FIFO_F = 0.0f; FIFO_F = 0.0f;
    FIFO_F = x1; FIFO_F = y0; FIFO_F = -0.5f; FIFO_F = 1.0f; FIFO_F = 0.0f;
    FIFO_F = x1; FIFO_F = y1; FIFO_F = -0.5f; FIFO_F = 1.0f; FIFO_F = 1.0f;
    FIFO_F = x0; FIFO_F = y1; FIFO_F = -0.5f; FIFO_F = 0.0f; FIFO_F = 1.0f;
    g_dbg[2]++;
}

static float sc(KHead *H, u32 v) { return (float)v * (float)H->scale_num / (float)H->scale_den; }

static void draw_sub(KHead *H, const KLine *L, u8 *tex, u32 bottom)
{
    float w = sc(H, L->w), h = sc(H, L->h);
    float x0 = (640.0f - w) * 0.5f, y1 = 480.0f - (float)bottom;
    quad(tex, L->w, L->h, 0, x0, y1 - h, x0 + w, y1);
}

/* 튜토리얼: 상자 요소 위치(+7C·+80 = 640 기준 정규화 x·y(아래에서), +88·+8C = 폭·높이)로 자리 잡는다 */
static void draw_tut(KHead *H, const KLine *L, u8 *tex, u32 e)
{
    float ex = *(volatile float *)(e + 0x7C) * 640.0f;
    float ey = *(volatile float *)(e + 0x80) * 640.0f;
    float ew = (float)R32(e + 0x88), eh = (float)R32(e + 0x8C);
    float w = sc(H, L->w), h = sc(H, L->h);
    float x0 = ex + ew * 0.5f - w * 0.5f;
    float y0 = 480.0f - (ey + eh) + (float)H->tut_dy;
    const TIcon *I = (const TIcon *)((u8 *)H + H->off_ticon) + L->pg;
    u8 *img = icons(H);
    u32 k;
    if (ex < 0.0f || ex > 640.0f || ey < 0.0f || ey > 640.0f) return;
    quad(tex, L->w, L->h, 0, x0, y0, x0 + w, y0 + h);
    for (k = 0; k < L->t; k++, I++) {
        float ix = x0 + sc(H, (u32)(s32)I->x), iy = y0 + sc(H, (u32)(s32)I->y);
        quad(img + I->id * 2048, 32, 32, 5, ix, iy, ix + sc(H, I->w), iy + sc(H, I->h));
    }
}

__attribute__((noinline)) void ksub_frame(KHead *H)
{
    const KLine *play, *pre, *tut;
    const KLine *T, *end, *nx;
    u32 e;
    s32 b, bt;
    g_dbg[0]++;
    tut = g_tut; e = g_tute;
    g_tut = 0;                                  /* HUD 가 매 프레임 다시 알려 준다 */
    scan(H, &play, &pre);
    if (play != g_pfirst) { g_pfirst = play; g_pt0 = mftbl(); }
    if (play) {
        /* 쪽 넘김: 재생 시작부터 흐른 시간으로 쪽을 고르고, 다음 쪽을 미리 읽는다 */
        u32 el = (mftbl() - g_pt0) / TB_PER_CS;
        T = (const KLine *)((u8 *)H + H->off_lines);
        end = T + H->nlines;
        while (play + 1 < end && play[1].key == play->key && el >= play[1].t) play++;
        nx = (play + 1 < end && play[1].key == play->key) ? play + 1 : 0;
        if (nx) pre = nx;
    }
    pump(H, play, tut, pre);
    b = play ? find_buf(play) : -1;
    bt = tut ? find_buf(tut) : -1;
    if ((b >= 0 && g_buf[b].st == 2) || (bt >= 0 && g_buf[bt].st == 2)) {
        gx_setup();
        if (bt >= 0 && g_buf[bt].st == 2) draw_tut(H, tut, bufptr(H, bt), e);
        if (b >= 0 && g_buf[b].st == 2) draw_sub(H, play, bufptr(H, b), tut ? H->bottom_tut : H->bottom);
    }
}

/* SwapBuffers 0x80276D20 의 «bl GXDrawDone» 자리에서 불린다. */
LOWTEXT void ksub_entry(void)
{
    KHead *H;
    g_lowdbg[0]++;
    H = ksub_block();
    if (H) {
        if (!g_ready && H->code_size && H->code_size <= 0x1F00) {
            volatile u8 *s = (volatile u8 *)H + H->off_code;
            volatile u8 *d = (volatile u8 *)HIGH_VA;
            u32 i;
            for (i = 0; i < H->code_size; i++) d[i] = s[i];
            DCFlushRange((void *)HIGH_VA, H->code_size);
            ICInvalidateRange((void *)HIGH_VA, H->code_size);
            g_lowdbg[1] = H->code_size;
            g_ready = 1;
        }
        if (g_ready) ksub_frame(H);
    }
    GXDrawDone();
}

/* HUD 0x80213110 «bl 0x802133C8(스프라이트 글자 그리기)» → 여기. 튜토리얼 번역이 있으면 영문을 건너뛴다. */
LOWTEXT void hook_tut(u32 e)
{
    if (g_ready && ksub_tut(e)) return;
    DrawSpriteText(e);
}
