#!/usr/bin/env python3
"""Technical SEO check of dist/ after the build (runs in Actions; prints a summary, exits 1 only on HARD errors).

    python3 scripts/seo_lint.py [dist]

HARD (exit 1): broken internal link or image, missing/duplicate <title>, page without exactly one <h1>, canonical not pointing to itself,
              invalid JSON-LD, indexable page missing from sitemap.xml, sitemap URL that is not a page.
soft (report): title > 65 or description outside 70-165 characters, duplicate description, image without width/height or alt attribute.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SITE = "https://repasovanyiphone.cz"


def main():
    dist = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    pages = {}
    for f in dist.rglob("index.html"):
        rel = "/" + str(f.parent.relative_to(dist)).strip(".") + "/"
        pages[rel.replace("//", "/")] = f.read_text()
    redirects = {ln.split()[0] for ln in (dist / "_redirects").read_text().splitlines() if ln.strip()} if (dist / "_redirects").exists() else set()
    files = {"/" + str(p.relative_to(dist)) for p in dist.rglob("*") if p.is_file()}
    hard, soft = defaultdict(list), defaultdict(list)
    titles, descs = Counter(), Counter()
    for path, h in pages.items():
        if path.startswith("/go/"):
            continue
        t = re.search(r"<title>(.*?)</title>", h)
        d = re.search(r'<meta name="description" content="(.*?)"', h)
        if not t:
            hard["no title"].append(path)
            continue
        titles[t.group(1)] += 1
        if len(t.group(1)) > 65:
            soft["title > 65"].append(f"{path} ({len(t.group(1))})")
        if d:
            descs[d.group(1)] += 1
            if not 70 <= len(d.group(1)) <= 165:
                soft["description length"].append(f"{path} ({len(d.group(1))})")
        if len(re.findall(r"<h1[ >]", h)) != 1:
            hard["h1 count != 1"].append(path)
        c = re.search(r'<link rel="canonical" href="([^"]+)"', h)
        if not c or c.group(1) != SITE + path:
            hard["canonical"].append(path)
        for blob in re.findall(r'<script type="application/ld\+json">(.*?)</script>', h, re.S):
            try:
                json.loads(blob)
            except ValueError:
                hard["bad JSON-LD"].append(path)
        for u in re.findall(r'(?:href|src)="(/[^"#?]*)', h):
            if u.startswith("/go/"):
                continue
            if u in files or (u.endswith("/") and u in pages) or u in redirects:
                continue
            hard["broken internal link"].append(f"{path} -> {u}")
        for im in re.findall(r"<img [^>]*>", h):
            if 'alt="' not in im:
                soft["img without alt"].append(path)
            if "width=" not in im or "height=" not in im:
                soft["img without size"].append(path)
    for t, n in titles.items():
        if n > 1:
            hard["duplicate title"].append(t)
    soft["duplicate description"] = [d for d, n in descs.items() if n > 1]
    sm = (dist / "sitemap.xml").read_text()
    in_sm = {u.replace(SITE, "") for u in re.findall(r"<loc>(https://[^<]+)</loc>", sm) if "/img/" not in u}
    indexable = {p for p, h in pages.items() if 'content="index,' in h}
    for p in indexable - in_sm:
        hard["indexable page not in sitemap"].append(p)
    for p in in_sm - set(pages):
        hard["sitemap URL is not a page"].append(p)
    rep = {"pages": len(pages), "indexable": len(indexable), "in_sitemap": len(in_sm),
           "hard": {k: {"count": len(v), "examples": v[:5]} for k, v in hard.items() if v},
           "soft": {k: {"count": len(v), "examples": v[:3]} for k, v in soft.items() if v}}
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    sys.exit(1 if rep["hard"] else 0)


if __name__ == "__main__":
    main()
