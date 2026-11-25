#!/usr/bin/env python3
"""Canva exports (scratch design DAHaRE_5Ko4) -> web assets in static/img/ui/.

White background -> transparent by flood fill from the edges (pixels with every channel >= 240), so white details inside
a drawing stay white; then trim and save WebP. Pattern taken from apps/casinoportal/scripts/canva-assets.py.

    python3 scripts/canva_assets.py icons <sheet.png>      # 4x3 icon grid -> ic-<name>.webp (96 + 192 px)
    python3 scripts/canva_assets.py grades <strip.png>     # 4 phones in a row -> grade-aplus/a/b/c.webp
    python3 scripts/canva_assets.py image <file.png> <name> [max_px]   # one illustration -> <name>.webp
"""
import sys
from collections import deque
from pathlib import Path

from PIL import Image

APP = Path(__file__).resolve().parent.parent
UI = APP / "static/img/ui"
ICONS = ["tap", "swatches", "search", "bag", "battery", "shield", "return", "esim", "van", "coins", "eco", "tools"]


def cutout(im):
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()
    seen = bytearray(w * h)
    q = deque((x, y) for x in range(w) for y in (0, h - 1))
    q.extend((x, y) for y in range(h) for x in (0, w - 1))
    while q:
        x, y = q.popleft()
        i = y * w + x
        if seen[i]:
            continue
        seen[i] = 1
        r, g, b, a = px[x, y]
        if a and min(r, g, b) < 240:
            continue
        px[x, y] = (255, 255, 255, 0)
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx]:
                q.append((nx, ny))
    box = im.getbbox()
    return im.crop(box) if box else im


def square(im, side, pad=0.06):
    inner = int(side * (1 - 2 * pad))
    im = im.copy()
    im.thumbnail((inner, inner), Image.LANCZOS)
    out = Image.new("RGBA", (side, side), (255, 255, 255, 0))
    out.alpha_composite(im, ((side - im.width) // 2, (side - im.height) // 2))
    return out


def save(im, name, sizes):
    UI.mkdir(parents=True, exist_ok=True)
    for s in sizes:
        out = square(im, s) if isinstance(s, int) else im
        suffix = "" if s == sizes[0] else f"-{s}"
        out.save(UI / f"{name}{suffix}.webp", "WEBP", quality=88, method=6)
    print("saved", name, sizes)


def main():
    kind, src = sys.argv[1], Path(sys.argv[2])
    im = Image.open(src).convert("RGB")
    W, H = im.size
    if kind == "icons":
        cw, ch = W / 4, H / 3
        for i, name in enumerate(ICONS):
            c, r = i % 4, i // 4
            cell = im.crop((int(c * cw), int(r * ch), int((c + 1) * cw), int((r + 1) * ch)))
            save(cutout(cell), "ic-" + name, [96, 192])
    elif kind == "grades":
        cw = W / 4
        for i, name in enumerate(["aplus", "a", "b", "c"]):
            cell = im.crop((int(i * cw), 0, int((i + 1) * cw), H))
            save(cutout(cell), "grade-" + name, [160, 320])
    elif kind == "image":
        name, mx = sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 1000
        cut = cutout(im)
        cut.thumbnail((mx, mx), Image.LANCZOS)
        UI.mkdir(parents=True, exist_ok=True)
        cut.save(UI / f"{name}.webp", "WEBP", quality=86, method=6)
        small = cut.copy()
        small.thumbnail((mx // 2, mx // 2), Image.LANCZOS)
        small.save(UI / f"{name}-sm.webp", "WEBP", quality=84, method=6)
        print("saved", name, cut.size)


if __name__ == "__main__":
    main()
