# -*- coding: utf-8 -*-
"""Pure3D 인라인 폰트 판독기 (심슨 히트 앤 런 GC 실측).

  python tools/p3dfont.py <p3d…>                 # 폰트 요약
  python tools/p3dfont.py <p3d…> --codes         # 글리프 문자 코드 전량
  python tools/p3dfont.py <p3d…> --glyphs        # 글리프 항목 전량(UV·폭·코드)
  python tools/p3dfont.py <p3d…> --png <디렉터리>  # 아틀라스 PNG 추출
  python tools/p3dfont.py <p3d…> --view <디렉터리> # 어두운 바탕에 합성한 «보는» PNG (PIL 필요)

⛔ FST 에 `fonts/` 디렉터리는 없다. 폰트는 UI p3d «안에» 인라인으로 들어 있다.
   `fontX_YY.p3d` 는 참조 청크(0x00018104)에 적힌 제작 시점 경로일 뿐이다.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p3d import walk

FONT, GLYPHS, TEXTURE, IMGHDR, IMGDATA = 0x00022000, 0x00022001, 0x00019000, 0x00019001, 0x00019002


def pstr(d, p):
    """길이 바이트 + «그 길이만큼의» 이름 필드(NUL 패딩). 길이 바이트는 자기를 안 센다."""
    n = d[p]
    return d[p + 1:p + 1 + n].rstrip(b'\x00').decode('latin1'), p + 1 + n


def read_font(d, off, dsz):
    """0x00022000 머리. 실측 배치:
         u32 version(0) · u8 len(=12) · char name[len] · u8 ?(0) · f32 ×4 · u32 텍스처수
       f32 4개 = 크기 · ? · 높이 · 베이스라인 (예: boulder_16 → 16 16 19 15)"""
    p = off + 12
    ver = struct.unpack_from('<I', d, p)[0]
    name, p = pstr(d, p + 4)
    p += 1                                   # ★ 이름 필드 뒤 1바이트
    f = struct.unpack_from('<4f', d, p)
    ntex = struct.unpack_from('<I', d, p + 16)[0]
    return dict(ver=ver, name=name, size=f[0], f1=f[1], height=f[2], base=f[3], ntex=ntex)


def read_glyphs(d, off, dsz):
    """0x00022001. u32 개수 + 개수 × 40 B.
       40 B = u32 텍스처번호 · f32 u0,v0,u1,v1 · f32 좌베어링,우베어링 · f32 폭 · f32 전진 · u32 문자코드
       ★ 실측 항등식: 전진 = 좌베어링 + 폭 + 우베어링"""
    n = struct.unpack_from('<I', d, off + 12)[0]
    per = (dsz - 16) // n
    out = []
    for i in range(n):
        b = off + 16 + i * per
        tex = struct.unpack_from('<I', d, b)[0]
        u0, v0, u1, v1, b0, b1, w, adv = struct.unpack_from('<8f', d, b + 4)
        code = struct.unpack_from('<I', d, b + 36)[0]
        out.append(dict(tex=tex, u0=u0, v0=v0, u1=u1, v1=v1, b0=b0, b1=b1, w=w, adv=adv, code=code))
    return per, out


def imginfo(b):
    i = b.find(b'\x89PNG')
    if i >= 0:
        w, h = struct.unpack_from('>II', b, i + 16)
        return 'PNG %dx%d %dbpp type%d' % (w, h, b[i + 24], b[i + 25]), i
    j = b.find(b'DDS ')
    if j >= 0:
        h, w = struct.unpack_from('<II', b, j + 12)
        return 'DDS %dx%d' % (w, h), j
    return '?', -1


def scan(path):
    """[(폰트정보, 텍스처이름, 이미지설명, PNG바이트, 글리프목록)…]"""
    d = open(path, 'rb').read()
    assert d[:4] == b'P3D\xff', path
    out, cur = [], None
    for depth, cid, off, dsz, csz in walk(d, 12):
        if cid == FONT:
            cur = dict(font=read_font(d, off, dsz), tex=None, img=None, png=None, glyphs=None, size=csz)
        elif cur is None:
            continue
        elif cid == TEXTURE:
            cur['tex'] = pstr(d, off + 12)[0]
        elif cid == IMGDATA:
            b = d[off + 12:off + dsz]
            cur['img'], i = imginfo(b)
            if i >= 0:
                cur['png'] = b[i:]
        elif cid == GLYPHS:
            cur['per'], cur['glyphs'] = read_glyphs(d, off, dsz)
            out.append(cur)
            cur = None
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    opt = [a for a in sys.argv[1:] if a.startswith('--')]
    outdir = None
    for i, a in enumerate(sys.argv):
        if a in ('--png', '--view') and i + 1 < len(sys.argv):
            outdir = sys.argv[i + 1]
            if outdir in args:
                args.remove(outdir)
    for path in args:
        print('########## %s' % path)
        for f in scan(path):
            ft, g = f['font'], f['glyphs']
            codes = [x['code'] for x in g]
            print('  %-14s 크기 %g (%g/%g/%g) 텍스처 %d개 · %s · %s'
                  % (ft['name'], ft['size'], ft['f1'], ft['height'], ft['base'],
                     ft['ntex'], f['tex'], f['img']))
            print('    글리프 %d개 (항목 %dB) · 정렬됨=%s · 텍스처번호 %s'
                  % (len(g), f['per'], codes == sorted(codes),
                     sorted({x['tex'] for x in g})))
            if '--codes' in opt:
                print('    코드:', ' '.join('%d' % c if c < 0x80 else 'U+%04X' % c for c in codes))
            if '--glyphs' in opt:
                for x in g:
                    print('      U+%04X %-3s uv=(%.4f,%.4f)-(%.4f,%.4f) b=(%g,%g) w=%g adv=%g tex=%d'
                          % (x['code'], repr(chr(x['code'])) if 32 <= x['code'] < 127 else '',
                             x['u0'], x['v0'], x['u1'], x['v1'], x['b0'], x['b1'], x['w'], x['adv'], x['tex']))
            if outdir and f['png']:
                os.makedirs(outdir, exist_ok=True)
                p = os.path.join(outdir, 'font_%s.png' % ft['name'])
                open(p, 'wb').write(f['png'])
                if '--view' in opt:
                    from PIL import Image
                    im = Image.open(p).convert('RGBA')
                    bg = Image.new('RGBA', im.size, (0, 0, 60, 255))
                    bg.alpha_composite(im)
                    v = os.path.join(outdir, 'view_%s.png' % ft['name'])
                    bg.convert('RGB').resize((im.width * 2, im.height * 2), Image.NEAREST).save(v)
                    print('    -> %s · %s' % (p, v))
                else:
                    print('    -> %s' % p)


if __name__ == '__main__':
    main()
