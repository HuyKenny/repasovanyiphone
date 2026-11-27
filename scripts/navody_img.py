#!/usr/bin/env python3
"""Screenshots of the shop checkouts (puppeteer, 390 px @2x, numbered markers) -> static/img/navody/<shop>-<step>.webp.

    python3 scripts/navody_img.py <dir with mg-01-cookies.png …>
"""
import sys
from pathlib import Path

from PIL import Image

PREFIX = {"mg": "mobilegear", "jl": "jabkolevne", "im": "iphonemarket", "sm": "smarty", "au": "aukro", "is": "istyle", "al": "allegro"}
OUT = Path(__file__).resolve().parent.parent / "static/img/navody"


def main():
    src = Path(sys.argv[1])
    OUT.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted(src.glob("*-[0-9][0-9]-*.png")):
        p, rest = f.stem.split("-", 1)
        if p not in PREFIX:
            continue
        im = Image.open(f).convert("RGB")
        if im.width != 780:
            im = im.resize((780, round(im.height * 780 / im.width)), Image.LANCZOS)
        im.save(OUT / f"{PREFIX[p]}-{rest}.webp", "WEBP", quality=72, method=6)
        n += 1
    print(n, "images ->", OUT)


if __name__ == "__main__":
    main()
