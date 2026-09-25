# -*- coding: utf-8 -*-
"""심슨 히트 앤 런(GC USA, GHQE) DOL 안의 «대사 이벤트 / 캐릭터» 표를 뽑는다.

  python tools/doltables.py <iso> [--events] [--chars] [--dis VA LEN]

## 실측 확정 (2026-09-08)

```
DOL ISO 오프셋 0x1EC00 · 진입점 0x80005304 · r13(SDA) = 0x80473E20
text0 VA 0x80003100 / text1 VA 0x80005880 (0x331DE0)

이벤트 종류 표   VA 0x80379C08  항목 0x10 B  45개
   +0 이름ptr · +4 0 · +8 이벤트ID · +0xC 표시시간(ms)
   개수 변수    VA 0x8046FAD8 (= r13-0x4348)
   접근자       VA 0x80132C28   GetEventType(i) → &표[i] (범위 밖이면 NULL)
   개수 반환    VA 0x80132C4C
캐릭터 표        VA 0x80379F50  항목 0x18 B
   +8 3글자코드('Hom') · +0x10 긴이름('homer')
대사 이벤트 처리 VA 0x80131D44 ~ 0x80132538
   이벤트ID로 분기(0x11F=convinit, 0x124=noboxconv, 0x9B=Mfail …)
   0x80132520  bl 0x80135308  (재생/대기열)   ※ r5 는 3D 좌표 버퍼
등록 루프        VA 0x80132578  GetEventTypeCount→GetEventType(i)→+8(ID) 로 리스너 등록
```

★ 대사 리소스 이름은 `.spt`(scripts.rcf, 평문)의 `create daSoundResourceData named
C_accuse_1_convinit_Hom_L1M7` 와 1:1이고, 엔진은 «이벤트명 + 3글자 화자코드 + 미션»으로
그 이름을 만든다(부품이 전부 SDA 상수에 있다).
"""
import argparse
import struct
import sys

DOL_ISO = 0x1EC00
EVENTS = 0x80379C08
EVENTS_N = 45
CHARS = 0x80379F50
R13 = 0x80473E20


class Dol(object):
    def __init__(self, iso, base=DOL_ISO, size=0x3D3440):
        f = open(iso, 'rb')
        f.seek(base)
        self.d = f.read(size)
        h = self.d[:0x100]
        off = struct.unpack_from('>18I', h, 0x00)
        adr = struct.unpack_from('>18I', h, 0x48)
        siz = struct.unpack_from('>18I', h, 0x90)
        self.sec = [(off[i], adr[i], siz[i], i) for i in range(18) if siz[i]]
        self.entry = struct.unpack_from('>I', h, 0xE0)[0]

    def v2f(self, v):
        for o, a, s, i in self.sec:
            if a <= v < a + s:
                return o + (v - a)

    def w(self, v):
        p = self.v2f(v)
        return struct.unpack_from('>I', self.d, p)[0] if p is not None else None

    def cstr(self, v, maxlen=64):
        p = self.v2f(v)
        if p is None:
            return None
        e = self.d.find(b'\x00', p)
        s = self.d[p:e]
        return s.decode('latin1') if 0 < len(s) < maxlen and all(32 <= c < 127 for c in s) else None


def events(dol):
    print('== 대사 이벤트 종류 표  VA 0x%08X · %d개 ==' % (EVENTS, EVENTS_N))
    print('  #  이벤트ID  시간ms  이름')
    for k in range(EVENTS_N):
        va = EVENTS + k * 0x10
        n, _z, i, t = struct.unpack_from('>4I', dol.d, dol.v2f(va))
        print('  %2d   0x%03X   %5d  %s' % (k, i, t, dol.cstr(n)))


def chars(dol):
    print('== 캐릭터 표  VA 0x%08X · 항목 0x18 B (+8 코드3, +0x10 긴이름) ==' % CHARS)
    k = 0
    while True:
        va = CHARS + k * 0x18
        if dol.v2f(va) is None:
            break
        c3 = dol.cstr(dol.w(va + 8) or 0)
        ln = dol.cstr(dol.w(va + 0x10) or 0)
        if not c3 or len(c3) != 3:
            break
        print('  %2d  %-4s %s' % (k, c3, ln or ''))
        k += 1
    print('  총 %d명' % k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('iso')
    ap.add_argument('--events', action='store_true')
    ap.add_argument('--chars', action='store_true')
    a = ap.parse_args()
    dol = Dol(a.iso)
    if not (a.events or a.chars):
        a.events = a.chars = True
    if a.events:
        events(dol)
        print()
    if a.chars:
        chars(dol)


if __name__ == '__main__':
    main()
