#!/usr/bin/env python3
"""Shop logos without the white box: near-white pixels become transparent (soft "colour to alpha" on the anti-aliased
edge), including letter counters. Only for logos without white as a brand colour (SKIP lists the others). Then the logo is trimmed to its content + 2 px.
Idempotent: a logo that is already transparent at the corners is skipped. Originals are in git history.

  python3 scripts/logos_alpha.py            # all static/img/shops/*.webp
  python3 scripts/logos_alpha.py --nasucho  # only report
"""
import sys
from pathlib import Path

from PIL import Image

DIR = Path(__file__).resolve().parent.parent / "static/img/shops"
LIGHT = 200          # min(r,g,b) above this counts as "background" while flooding from the border
FULL = 247           # min(r,g,b) above this is fully transparent
SKIP = {"mobilegear"}   # dark badge with a white wordmark: keep as it is


def unwhite(im):
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()
    # all near-white pixels, not only those connected to the border: letter counters ("e", "a", the ".cz" box) are white too.
    # None of the shop logos uses white as a brand colour; a logo that does must be skipped (SKIP).
    bg = [[min(px[x, y][:3]) >= LIGHT for x in range(w)] for y in range(h)]
    edge = [[bg[y][x] or any(0 <= x + dx < w and 0 <= y + dy < h and bg[y + dy][x + dx] for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
             for x in range(w)] for y in range(h)]
    for y in range(h):
        for x in range(w):
            if not edge[y][x]:
                continue
            r, g, b, a = px[x, y]
            m = min(r, g, b)
            if bg[y][x] and m >= FULL:
                px[x, y] = (255, 255, 255, 0)
                continue
            alpha = max(255 - r, 255 - g, 255 - b) / 255          # white -> 0, the logo colour -> 1
            if alpha <= 0:
                px[x, y] = (255, 255, 255, 0)
                continue
            un = lambda c: max(0, min(255, round((c - 255 * (1 - alpha)) / alpha)))
            px[x, y] = (un(r), un(g), un(b), round(a * alpha))
    box = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if box:
        l, t, rr, bb = box
        im = im.crop((max(0, l - 2), max(0, t - 2), min(w, rr + 2), min(h, bb + 2)))
    return im


def main():
    dry = "--nasucho" in sys.argv
    for f in sorted(DIR.glob("*.webp")):
        if f.stem in SKIP:
            print(f"{f.name}: skip (white is part of the logo)")
            continue
        im = Image.open(f).convert("RGBA")
        w, h = im.size
        corners = [im.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
        if not all(c[3] > 200 and min(c[:3]) >= LIGHT for c in corners):
            print(f"{f.name}: skip (corners not white or already transparent)")
            continue
        out = unwhite(im)
        print(f"{f.name}: {im.size} -> {out.size}")
        if not dry:
            out.save(f, "WEBP", quality=90, alpha_quality=100, method=6)


if __name__ == "__main__":
    main()
