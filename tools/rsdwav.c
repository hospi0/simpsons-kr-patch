/* RSD4/GADP(Radical, GC DSP ADPCM 모노) → WAV(16bit, 원래 표본율)
 *
 *   rsdwav <iso> <목록.txt> <출력폴더>
 *   목록 한 줄 = «이름 ISO오프셋 크기»(10진)
 *
 * 머리(실측, docs/08): 0x00 "RSD4" · 0x04 "GADP" · 0x08 채널(u32 LE) · 0x0C 비트 · 0x10 표본율(LE)
 *                      0x14 계수 16개(s16 «LE») · 데이터 0x800~
 * DSP ADPCM 프레임 8 B = [예측번호<<4 | 배율] + 4비트 표본 14개.
 * 빌드: zig cc -O2 -o rsdwav.exe rsdwav.c
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

static int16_t clamp16(int v) { return v > 32767 ? 32767 : v < -32768 ? -32768 : (int16_t)v; }

static void wr32(FILE *f, uint32_t v) { fputc(v & 255, f); fputc((v >> 8) & 255, f); fputc((v >> 16) & 255, f); fputc(v >> 24, f); }
static void wr16(FILE *f, uint32_t v) { fputc(v & 255, f); fputc((v >> 8) & 255, f); }

int main(int argc, char **argv)
{
    FILE *iso, *lst;
    char line[1024], name[512], path[1200];
    long long off, size;
    int ok = 0, bad = 0;
    if (argc < 4) { fprintf(stderr, "rsdwav <iso> <list> <outdir>\n"); return 1; }
    iso = fopen(argv[1], "rb");
    lst = fopen(argv[2], "r");
    if (!iso || !lst) { fprintf(stderr, "open fail\n"); return 1; }
    while (fgets(line, sizeof line, lst)) {
        unsigned char *b;
        int16_t coef[16];
        uint32_t rate, ch, nfr, i, k, ns = 0;
        int16_t *pcm;
        int h1 = 0, h2 = 0;
        FILE *o;
        if (sscanf(line, "%511s %lld %lld", name, &off, &size) != 3) continue;
        b = (unsigned char *)malloc((size_t)size);
        _fseeki64(iso, off, SEEK_SET);
        if (fread(b, 1, (size_t)size, iso) != (size_t)size || memcmp(b, "RSD4GADP", 8) || size < 0x808) {
            fprintf(stderr, "skip %s\n", name); free(b); bad++; continue;
        }
        ch = b[8] | b[9] << 8;
        rate = b[16] | b[17] << 8 | b[18] << 16 | (uint32_t)b[19] << 24;
        if (ch != 1) { fprintf(stderr, "skip %s (ch %u)\n", name, ch); free(b); bad++; continue; }
        for (i = 0; i < 16; i++) coef[i] = (int16_t)(b[0x14 + 2 * i] | b[0x15 + 2 * i] << 8);
        nfr = (uint32_t)((size - 0x800) / 8);
        pcm = (int16_t *)malloc(nfr * 14 * 2);
        for (i = 0; i < nfr; i++) {
            unsigned char *fr = b + 0x800 + i * 8;
            int ps = fr[0], idx = (ps >> 4) & 7, sc = 1 << (ps & 15);
            int c1 = coef[idx * 2], c2 = coef[idx * 2 + 1];
            for (k = 0; k < 14; k++) {
                int nib = (k & 1) ? (fr[1 + k / 2] & 15) : (fr[1 + k / 2] >> 4);
                int s, v;
                if (nib >= 8) nib -= 16;
                v = ((nib * sc) << 11) + 1024 + c1 * h1 + c2 * h2;
                s = clamp16(v >> 11);
                h2 = h1; h1 = s;
                pcm[ns++] = (int16_t)s;
            }
        }
        snprintf(path, sizeof path, "%s/%s.wav", argv[3], name);
        o = fopen(path, "wb");
        if (!o) { fprintf(stderr, "write fail %s\n", path); free(b); free(pcm); bad++; continue; }
        fwrite("RIFF", 1, 4, o); wr32(o, 36 + ns * 2); fwrite("WAVEfmt ", 1, 8, o);
        wr32(o, 16); wr16(o, 1); wr16(o, 1); wr32(o, rate); wr32(o, rate * 2); wr16(o, 2); wr16(o, 16);
        fwrite("data", 1, 4, o); wr32(o, ns * 2);
        fwrite(pcm, 2, ns, o);
        fclose(o);
        free(b); free(pcm);
        ok++;
    }
    printf("ok %d bad %d\n", ok, bad);
    return 0;
}
