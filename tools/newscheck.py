# -*- coding: utf-8 -*-
"""`loadingN.p3d` 를 되읽어 한 장으로 붙이고 «넣으려던 그림»과 대조한다."""
import argparse
import io
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p3dimg import scan


def stitch(path):
    ims = [Image.open(io.BytesIO(r)).convert('RGBA') for _, _, _, _, r in scan(path)]
    ws = sorted({im.width for im in ims}, reverse=True)
    hs = sorted({im.height for im in ims}, reverse=True)
    xs, x = {}, 0
    for w in ws:
        xs[w] = x; x += w
    ys, y = {}, 0
    for h in hs:
        ys[h] = y; y += h
    c = Image.new('RGBA', (x, y), (0, 0, 0, 0))
    put = set()
    for im in ims:
        p = (xs[im.width], ys[im.height])
        if p in put:
            continue
        c.alpha_composite(im, p); put.add(p)
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('orig_p3d'); ap.add_argument('new_p3d'); ap.add_argument('want_png')
    ap.add_argument('--save')
    a = ap.parse_args()
    o = stitch(a.orig_p3d); c = stitch(a.new_p3d)
    want = Image.open(a.want_png).convert('RGBA')
    z = np.asarray(o, dtype=int); g = np.asarray(c, dtype=int); b = np.asarray(want, dtype=int)
    da = np.abs(g[:, :, 3] - z[:, :, 3])
    inside = z[:, :, 3] >= 200
    dr = np.abs(g[:, :, :3] - b[:, :, :3]).max(axis=2)
    print('  알파 원본과 차이 최대 %d (0 이어야 한다)' % da.max())
    print('  신문 안 RGB 차이 : 최대 %d · 평균 %.2f · 8 넘는 화소 %d / %d'
          % (dr[inside].max(), dr[inside].mean(), (dr[inside] > 8).sum(), inside.sum()))
    if a.save:
        c.convert('RGB').save(a.save)
        print('  → %s' % a.save)


if __name__ == '__main__':
    main()
