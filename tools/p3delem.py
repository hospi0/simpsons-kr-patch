# -*- coding: utf-8 -*-
"""⛔⛔ 이 도구가 하려던 «청크 종류 바꿔치기»는 2026-09-11 실측으로 **반증됐다.** 쓰지 말 것.

   튜토리얼 상자를 스프라이트 요소 → 폰트 텍스트 요소로 바꾸면 될 줄 알았으나,
   실기 RAM 에서 두 요소의 구조가 아예 다르다는 게 확인됐다 —
       폰트 텍스트 요소  vtbl 0x80397354 · 문자열을 «+0x38 에 바이블 포인터»로
       스프라이트 글자 요소 vtbl 0x80396B3C · 문자열을 «+0xAC 의 자기 문자열 객체»로
   HUD 코드가 그 요소를 Sprite 로 잡아 자기 setter 로 글을 넣으므로, 청크만 바꾸면 형이 안 맞는다.
   자세한 내용과 «그럼 어떻게 해야 하는가»는 docs/07 §7 을 볼 것.

   아래 --list 는 요소 종류를 훑어보는 데 여전히 쓸 만하다.
"""
import argparse
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p3d import walk

PAGE, SPR, TXT, KEYS = 0x00018002, 0x00018006, 0x00018007, 0x0001800B


def pstr_read(d, p):
    n = d[p]
    return d[p + 1:p + 1 + n].rstrip(b'\0').decode('latin1'), p + 1 + n


def pstr(s):
    """길이 바이트 + 4바이트 정렬 NUL 패딩 (원본 규약: 선언 길이가 패딩을 포함한다)."""
    b = s.encode('latin1')
    n = (len(b) + 4) & ~3            # 실측: 'srr2'->4, 'font1_14'->8, 'DISABLE_TUTORIAL'->16
    if n <= len(b):
        n = len(b) + 4
    return bytes([n]) + b + bytes(n - len(b))


def chunk(cid, data, children=b''):
    dsz = 12 + len(data)
    return struct.pack('<III', cid, dsz, dsz + len(children)) + data + children


def tree(d):
    return list(walk(d, 12))


def owner_page(d, ch, off):
    best = None
    for dep, cid, o, ds, cs in ch:
        if cid == PAGE and o < off < o + cs:
            best = pstr_read(d, o + 12)[0]
    return best


def find_elem(d, page, elem):
    ch = tree(d)
    for dep, cid, o, ds, cs in ch:
        if cid not in (SPR, TXT):
            continue
        nm = pstr_read(d, o + 12)[0]
        if nm == elem and owner_page(d, ch, o) == page:
            return cid, o, ds, cs
    raise SystemExit('⛔ %s / %s 를 못 찾았다' % (page, elem))


def resize_parents(d, off, delta):
    """바뀐 청크를 감싸는 모든 부모의 dataSize·chunkSize 를 고친다.
       ★ dataSize 는 «첫 자식까지의 거리»라, 자식이 커진 경우 dataSize 는 그대로 두고
         chunkSize 만 늘린다. 단 바뀐 청크가 부모의 «머리» 안에 있으면 둘 다 늘린다."""
    out = bytearray(d)
    for dep, cid, o, ds, cs in tree(d):
        if o < off < o + cs and o != off:
            ncs = cs + delta
            nds = ds + delta if off < o + ds else ds
            struct.pack_into('<II', out, o + 4, nds, ncs)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst', nargs='?')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--page')
    ap.add_argument('--elem')
    ap.add_argument('--font', default='boulderK16')
    ap.add_argument('--keys', default='', help='쉼표로 구분한 후보 키 이름들 (순서 = 색인)')
    ap.add_argument('--fields', default='', help='u32 10개, 쉼표 구분 (없으면 원본에서 옮겨 온다)')
    a = ap.parse_args()

    d = open(a.src, 'rb').read()
    ch = tree(d)

    if a.list or not a.dst:
        for dep, cid, o, ds, cs in ch:
            if cid not in (SPR, TXT):
                continue
            nm = pstr_read(d, o + 12)[0]
            body, p = pstr_read(d, o + 12)
            vals = [struct.unpack_from('<I', d, p + 4 * i)[0] for i in range(10)]
            kind = '스프라이트' if cid == SPR else '폰트'
            if cid == SPR and b'letterA' not in d[o + 12:o + ds]:
                kind = '스프라이트(글자아님)'
            print('%-22s %-22s %-14s data=%-5d %s'
                  % (owner_page(d, ch, o), nm, kind, ds,
                     ' '.join(str(v) if v < 0x10000 else '0x%08X' % v for v in vals)))
        return

    cid, off, ds, cs = find_elem(d, a.page, a.elem)
    nm, p = pstr_read(d, off + 12)
    old = [struct.unpack_from('<I', d, p + 4 * i)[0] for i in range(11)]
    print('원본 %s/%s : 종류 0x%05X · data=%d total=%d' % (a.page, a.elem, cid, ds, cs))
    print('   u32 11개 %s' % ' '.join(str(v) if v < 0x10000 else '0x%08X' % v for v in old))

    if a.fields:
        f = [int(x, 0) & 0xFFFFFFFF for x in a.fields.split(',')]
        if len(f) != 10:
            raise SystemExit('⛔ --fields 는 10개여야 한다')
    else:
        # 원본에서 옮겨 온다 — (1,x,y,?,?,정렬,?,색,0,0) → (17,x,y,폭,크기,정렬,2,색,0,0)
        f = [17, old[1], old[2], 420, 18, old[5], 2, old[7], 0, 0]
    print('   새 u32 10개 %s' % ' '.join(str(v) if v < 0x10000 else '0x%08X' % v for v in f))

    body = pstr(nm) + b''.join(struct.pack('<I', x) for x in f) + pstr(a.font)
    kids = b''
    keys = [k for k in a.keys.split(',') if k]
    for k in keys:
        kids += chunk(KEYS, pstr('srr2') + pstr(k))
    new = chunk(TXT, body, kids)
    print('   새 청크 %d B (자식 %d개) · 원본 %d B → %+d' % (len(new), len(keys), cs, len(new) - cs))

    out = resize_parents(d, off, len(new) - cs)
    out[off:off + cs] = new
    open(a.dst, 'wb').write(bytes(out))

    # 되읽어 검산
    d2 = open(a.dst, 'rb').read()
    assert d2[:4] == b'P3D\xff'
    n = 0
    for dep, c2, o2, ds2, cs2 in tree(d2):
        n += 1
    print('✅ %s  %d B → %d B · 청크 %d개 (원본 %d개) 파싱 OK'
          % (a.dst, len(d), len(d2), n, len(ch)))
    c3, o3, ds3, cs3 = find_elem(d2, a.page, a.elem)
    print('   되읽기: 종류 0x%05X · data=%d total=%d' % (c3, ds3, cs3))


if __name__ == '__main__':
    main()
