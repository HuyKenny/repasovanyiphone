#!/usr/bin/env python3
"""Product photo library: one clean, self-hosted photo per (model, colour), served from our own domain.

    python3 scripts/photos.py            # update data/state/photos/ from data/raw/*.json (only new/changed source URLs are downloaded)

Sources are ALL raw shop records (also ones the offer parser skips, e.g. Allegro "Iphone 8 Plus Space Gray 64GB" without a parsable
storage), ranked: clean Apple renders first (Smarty, iPhoneMarket, iSTYLE, Aukro refurbished), then MobileGear with its
watermark removed: MobileGear puts its logo on a green wallpaper inside the front phone's display, so the green pixels give the
display area, which is painted as a switched-off black screen, then Allegro (sellers sometimes photograph the box). JabkoLevně (logo on a varying wallpaper) is never used.
The library never deletes a photo: a colour keeps its picture while no shop has it in stock.
Output: data/state/photos/<model>--<colour>-{600,300}.webp + index.json {key: {src, shop, sha}}; build.py copies them to dist/img/p/.
"""
import hashlib
import io
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP / "scripts"))
import parse as P  # noqa: E402

OUT = APP / "data/state/photos"
RANK = ["smarty", "iphonemarket", "istyle", "aukro", "mobilegear", "allegro"]   # Allegro sellers sometimes show the box
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux aarch64) RepasIphonePhotos/1.0"}


def candidates():
    """{(model, colour): [(rank, shop, url)]} from every raw record."""
    shops = {s["id"]: s for s in json.loads((APP / "data/shops.json").read_text())["shops"]}
    found = {}
    for sid in RANK:
        f = APP / "data/raw" / f"{sid}.json"
        if not f.exists():
            continue
        for r in json.loads(f.read_text()):
            if not r.get("img") or P.NOT_PHONE.search(r["t"]):
                continue
            if sid == "aukro" and r.get("fcond") not in shops.get("aukro", {}).get("fcond", ["Refurbished"]):
                continue                       # private auction photos are not product shots
            prm = r.get("prm") or {}
            m = P.model_of(prm.get("model zařízení", "")) or P.model_of(prm.get("model", "")) or P.model_of(r["t"])
            if not m:
                continue
            after_gb = re.sub(r"(?i)^.*?\d+\s?(gb|tb)\b", "", r["t"]) if re.search(r"(?i)\d\s?(gb|tb)\b", r["t"]) else ""
            no_model = re.sub(r"(?i)^.*?iphone\s*(\d+\s*(pro\s*max|pro|plus|mini|e)?|se|xs\s*max|xs|xr|x|air)\b", "", r["t"])
            c = P.color_of(m, prm.get("barevný odstín", ""), prm.get("barva", ""), prm.get("color", ""), after_gb, no_model)
            if c:
                found.setdefault((m, c), []).append((RANK.index(sid), sid, r["img"]))
    return {k: sorted(v) for k, v in found.items()}


def blank_screen(im):
    """MobileGear: paint the green wallpaper area (and the logo on it) as a switched-off screen. None if no wallpaper found."""
    small = im.convert("RGB").resize((im.width // 4, im.height // 4))
    px = small.load()
    xs, ys = [], []
    for y in range(small.height):
        for x in range(small.width):
            r, g, b = px[x, y]
            if g > 28 and g > r + 12 and g >= b - 6:          # the wallpaper: bright green and dark teal waves
                xs.append(x)
                ys.append(y)
    if len(xs) < 200:
        return None
    xs.sort()
    ys.sort()
    k = len(xs) // 100                                       # robust bounds: ignore 1 % stray pixels on each side
    box = [xs[k] * 4, ys[k] * 4, xs[-k - 1] * 4 + 4, ys[-k - 1] * 4 + 4]
    w, h = box[2] - box[0], box[3] - box[1]
    pad = int(min(w, h) * 0.04)          # cover the anti-aliased wallpaper edge in the corners too
    box = [box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad]
    out = im.convert("RGBA").copy()
    mask = Image.new("L", out.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=int(min(w, h) * 0.09), fill=255)
    screen = Image.new("RGBA", out.size, (17, 17, 19, 255))
    out.paste(screen, (0, 0), mask.filter(ImageFilter.GaussianBlur(1)))
    return out


def normalise(im):
    """On white, trimmed, square with a small margin."""
    im = im.convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    rgb = bg.convert("RGB")
    diff = Image.eval(rgb.convert("L"), lambda v: 255 if v < 246 else 0)
    box = diff.getbbox() or (0, 0, rgb.width, rgb.height)
    rgb = rgb.crop(box)
    side = int(max(rgb.size) * 1.08)
    sq = Image.new("RGB", (side, side), (255, 255, 255))
    sq.paste(rgb, ((side - rgb.width) // 2, (side - rgb.height) // 2))
    return sq


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return Image.open(io.BytesIO(r.read()))


def make(key, cands):
    """Try candidates in rank order; returns (key, entry) or (key, None)."""
    for _rank, shop, url in cands[:6]:
        try:
            im = fetch(url)
            if shop == "mobilegear":
                im = blank_screen(im)
                if im is None:
                    continue
            sq = normalise(im)
            if sq.width < 200:
                continue
            base = f"{key[0]}--{key[1]}"
            for px in (600, 300):
                sq.resize((px, px), Image.LANCZOS).save(OUT / f"{base}-{px}.webp", "WEBP", quality=82, method=6)
            return key, {"src": url, "shop": shop, "sha": hashlib.md5(url.encode()).hexdigest()[:10]}
        except Exception as e:  # noqa: BLE001 - one broken shop image must not stop the build
            print(f"  photo {key}: {shop} failed ({type(e).__name__})", file=sys.stderr)
    return key, None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    idx_p = OUT / "index.json"
    idx = json.loads(idx_p.read_text()) if idx_p.exists() else {}
    jobs = []
    for (m, c), cands in candidates().items():
        key = f"{m}|{c}"
        have = idx.get(key)
        best = cands[0]
        # (re)make when missing, or when a better-ranked shop now has the colour (e.g. a clean render replaces a patched MobileGear one)
        if not have or not (OUT / f"{m}--{c}-600.webp").exists() or RANK.index(have["shop"]) > best[0]:
            jobs.append(((m, c), cands))
    with ThreadPoolExecutor(max_workers=6) as pool:
        for (m, c), entry in pool.map(lambda j: make(*j), jobs):
            if entry:
                idx[f"{m}|{c}"] = entry
    idx_p.write_text(json.dumps(idx, indent=0, ensure_ascii=False))
    print(f"photos: {len(idx)} in library, {len(jobs)} (re)made this run", file=sys.stderr)


if __name__ == "__main__":
    main()
