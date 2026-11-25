#!/usr/bin/env python3
"""Build repasovanyiphone.cz (v3, 25. 11. 2026) into dist/ - plain static HTML + one small JS configurator, no Worker code.

    python3 scripts/photos.py && python3 scripts/build.py

The visitor picks model -> colour -> storage -> quality (Nový, A+, A, B, C) and gets the cheapest shop (price after a usable voucher
code) plus the other shops. Quality is shown ONLY on our scale; the shops' own wording appears in the converter guide alone.
Pages: / , /<model>/ (configurator), /<model>/<gb>-gb/ , category landings (what people search: levný, nový, zánovní, malý,
do 5 000 / 10 000 Kč, pro děti), /srovnani/ , /jaky-iphone-koupit/ , /obchody/ (+ shop pages), /pruvodce/<guide>/ , /o-webu/,
404, sitemap.xml (with images, lastmod = real change), robots.txt, _headers, _redirects (301 for pages that disappeared),
/go/<shop>/ redirects (scripts/golinks.py). Product photos are self-hosted from data/state/photos (scripts/photos.py).
State between builds (encrypted release asset): history.json, page-hashes.json, lastmod.json, known-paths.json, seen-models.json.
"""
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP / "scripts"))
import golinks  # noqa: E402
import parse as P  # noqa: E402

DIST = APP / "dist"
STATE = APP / "data/state"
SITE = "https://repasovanyiphone.cz"
BRAND = "Repasovaný iPhone"
E = html.escape
TODAY = dt.date.today()
GA4_ID = os.environ.get("GA4_ID", "")
STAGING = os.environ.get("VT_ENV", "production") == "staging"

SHOPS = [s for s in json.loads((APP / "data/shops.json").read_text())["shops"] if s.get("enabled", True)]
SHOP = {s["id"]: s for s in SHOPS}
SHOP_INFO = json.loads((APP / "content/shops.json").read_text())
MODELS = P.MODELS
MODEL = P.BY_SLUG
GR = P.GRADE
REFURB_G = ("aplus", "a", "b", "c")
FAMILIES = [("18", "iPhone 18"), ("17", "iPhone 17 a Air"), ("16", "iPhone 16"), ("15", "iPhone 15"), ("14", "iPhone 14"),
            ("13", "iPhone 13"), ("se", "iPhone SE"), ("12", "iPhone 12"), ("11", "iPhone 11"), ("x", "iPhone X, XS a XR"), ("8", "iPhone 7 a 8")]
GIMG = [k for k in ("aplus", "a", "b", "c") if (APP / f"static/img/ui/grade-{k}.webp").exists()]   # Canva illustrations of the grades
MONTHS = ["ledna", "února", "března", "dubna", "května", "června", "července", "srpna", "září", "října", "listopadu", "prosince"]
GONE_DAYS = 30          # a model without offers keeps an indexable page this long, then noindex (never 404)


def kc(v):
    return f"{int(v):,}".replace(",", " ") + " Kč"


def kc_plain(v):
    return kc(v).replace(" ", " ")


def date_cz(d):
    return f"{d.day}. {MONTHS[d.month - 1]} {d.year}"


def plural(n, one, few, many):
    return one if n == 1 else few if 2 <= n <= 4 else many


def num(n):
    return f"{n:,}".replace(",", " ")


def nab(n):
    return f"{num(n)} {plural(n, 'nabídka', 'nabídky', 'nabídek')}"


def obchodu(n):
    return f"{n} {plural(n, 'obchodu', 'obchodů', 'obchodů')}"


def ios_ok(m):
    """iOS 26 and 27 run on iPhone 11 and newer and on iPhone SE (2nd gen) and newer (Apple, June 2026)."""
    return m["year"] >= 2019 and not m["slug"].startswith(("iphone-xs", "iphone-xr", "iphone-x", "iphone-8", "iphone-7"))


def short_title(t, limit=65):
    """Drop trailing ' – …' parts until the title fits (Google shows ~60-65 characters)."""
    while len(t) > limit and " – " in t:
        t = t.rsplit(" – ", 1)[0]
    return t


# ---------------------------------------------------------------- photos (self-hosted, scripts/photos.py)

def photo(ctx, slug, col=None, size=600):
    """/img/p/<model>--<colour>-<size>.webp, falling back to the model's most offered colour that has a photo."""
    have = ctx["photos"]
    if col and (slug, col) in have:
        return f"/img/p/{slug}--{col}-{size}.webp"
    for c in ctx["col_rank"].get(slug, []):
        if (slug, c) in have:
            return f"/img/p/{slug}--{c}-{size}.webp"
    c = next((c for (m, c) in have if m == slug), None)
    return f"/img/p/{slug}--{c}-{size}.webp" if c else ""


def pic(ctx, slug, col, w, h=None, alt="", eager=False):
    src = photo(ctx, slug, col, 300 if w <= 160 else 600)
    if not src:
        return '<span class="noimg"></span>'
    big = photo(ctx, slug, col, 600)
    srcset = f' srcset="{src} 300w, {big} 600w" sizes="{w}px"' if w > 160 and "-300" in src else ""
    return (f'<img src="{src}"{srcset} alt="{E(alt)}" width="{w}" height="{h or w}"'
            f'{" fetchpriority=high" if eager else " loading=lazy"} decoding="async">')


def color_name(slug, col):
    c = P.color(slug, col)
    return c["name"] if c else ""


# ---------------------------------------------------------------- coupons (eHub vouchers, fetch.py --coupons)

def load_coupons():
    """{shop: [coupon]} from data/raw/coupons.json + content/coupons.json (manual), only valid today."""
    out = defaultdict(list)
    rows = []
    for f in (APP / "data/raw/coupons.json", APP / "content/coupons.json"):
        if f.exists():
            d = json.loads(f.read_text())
            rows += d if isinstance(d, list) else d.get("coupons", [])
    seen = set()
    for c in rows:
        if c.get("shop") not in SHOP or (c.get("until") or "9999") < TODAY.isoformat() or (c["shop"], c["code"].lower()) in seen:
            continue
        seen.add((c["shop"], c["code"].lower()))
        eff = P.coupon_effect(c.get("rules", ""))
        out[c["shop"]].append({**c, **eff, "label": coupon_label(c, eff)})
    return out


def coupon_label(c, eff):
    if eff["amount"]:
        t = f"−{kc(eff['amount'])}"
    elif eff["pct"]:
        t = f"−{eff['pct']} %"
    else:
        t = c.get("rules") or "sleva"
    if eff["min"]:
        t += f" při nákupu nad {kc(eff['min'])}"
    return t


def apply_coupon(o, coupons):
    """Best usable code for this offer -> (price after code, coupon or None)."""
    best, bp = None, o["p"]
    for c in coupons.get(o["shop"], []):
        if not c["auto"] or o["p"] < c["min"]:
            continue
        p = o["p"] - c["amount"] if c["amount"] else round(o["p"] * (1 - c["pct"] / 100))
        if p < bp:
            best, bp = c, p
    return bp, best


def until_cz(c):
    if not c.get("until"):
        return ""
    d = dt.date.fromisoformat(c["until"][:10])
    return f"platí do {d.day}. {d.month}. {d.year}"


# ---------------------------------------------------------------- output

class Out:
    def __init__(self, root):
        self.root = root
        self.pages = []
        self.changed = []
        hp = STATE / "page-hashes.json"
        self.old = json.loads(hp.read_text()) if hp.exists() else {}
        lp = STATE / "lastmod.json"
        self.lastmod = json.loads(lp.read_text()) if lp.exists() else {}
        self.new = {}
        self.images = defaultdict(list)       # path -> [(abs url, title)] for the image sitemap

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def page(self, path, text, index=True):
        rel = path.strip("/") + "/index.html" if path != "/" else "index.html"
        self.write(rel, text)
        self.pages.append((path, index))
        body = re.sub(r"<script.*?</script>", "", text, flags=re.S)
        body = re.sub(r"Ceny z \d+\. \w+ \d{4}|Aktualizováno \d+\. \w+ \d{4}|ceny z dnešní noci", "", body)   # the date alone is no change
        h = hashlib.md5(body.encode()).hexdigest()[:12]
        self.new[path] = h
        if self.old.get(path) != h or path not in self.lastmod:
            self.lastmod[path] = TODAY.isoformat()
            if index:
                self.changed.append(path)


def asset(src, out):
    data = (APP / "static/assets" / src).read_bytes()
    name = f"{Path(src).stem}.{hashlib.md5(data).hexdigest()[:8]}{Path(src).suffix}"
    (out / "assets").mkdir(parents=True, exist_ok=True)
    (out / "assets" / name).write_bytes(data)
    return "/assets/" + name


# ---------------------------------------------------------------- layout

def logo_mark(size=34):
    return f'<img src="/img/ui/logo.webp" alt="" width="{size}" height="{size}">'


NAV = [("/levny-iphone/", "Levné iPhony"), ("/zanovni-iphone/", "Zánovní"), ("/novy-iphone/", "Nové"), ("/srovnani/", "Srovnání"),
       ("/pruvodce/", "Průvodce")]


def layout(ctx, *, path, title, desc, body, crumbs=None, ld=None, index=True, active=None, og_img="", cfg=None, preload=""):
    canon = SITE + path
    robots = "noindex,follow" if (not index or STAGING) else "index,follow,max-image-preview:large"
    lds = list(ld or [])
    if crumbs:
        lds.append({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": n, "item": SITE + u} for i, (u, n) in enumerate(crumbs)]})
    ldtxt = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False, separators=(",", ":"))}</script>' for x in lds)
    nav = "".join(f'<a href="{u}"{" aria-current=page" if u == active else ""}>{n}</a>' for u, n in NAV)
    cr = ""
    if crumbs and len(crumbs) > 1:
        parts = [f'<a href="{u}">{E(n)}</a>' for u, n in crumbs[:-1]] + [f'<span aria-current="page">{E(crumbs[-1][1])}</span>']
        cr = '<nav class="crumbs wrap" aria-label="Drobečková navigace">' + '<span aria-hidden="true">›</span>'.join(parts) + "</nav>"
    ga, noscript = "", ""
    if GA4_ID and not STAGING:
        # Consent Mode v2: nothing is stored until the visitor agrees in the bar (app.js sends the update); GTM itself loads always.
        boot = ('window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}'
                'var g="denied";try{if(localStorage.getItem("ri-consent")==="yes")g="granted"}catch(e){}'
                'gtag("consent","default",{analytics_storage:g,ad_storage:"denied",ad_user_data:"denied",ad_personalization:"denied",wait_for_update:500});'
                'gtag("set","ads_data_redaction",true);')
        if GA4_ID.startswith("GTM-"):
            # gtm.js is injected right after the page has loaded (keeps the main thread free for the first render; page views are still counted)
            ga = (f'<meta name="ga4" content="{GA4_ID}"><script>{boot}dataLayer.push({{"gtm.start":Date.now(),event:"gtm.js"}});'
                  f'(function(){{var d=0;function l(){{if(d)return;d=1;var s=document.createElement("script");s.async=true;'
                  f's.src="https://www.googletagmanager.com/gtm.js?id={GA4_ID}";document.head.appendChild(s)}}'
                  f'if(document.readyState==="complete")setTimeout(l,800);else addEventListener("load",function(){{setTimeout(l,800)}});'
                  f'["pointerdown","keydown","scroll"].forEach(function(e){{addEventListener(e,l,{{once:true,passive:true}})}})}})();</script>')
            noscript = (f'<noscript><iframe src="https://www.googletagmanager.com/ns.html?id={GA4_ID}" height="0" width="0" '
                        'style="display:none;visibility:hidden" title="GTM"></iframe></noscript>')
        else:
            ga = (f'<meta name="ga4" content="{GA4_ID}"><script>{boot}gtag("js",new Date());gtag("config","{GA4_ID}");</script>'
                  f'<script async src="https://www.googletagmanager.com/gtag/js?id={GA4_ID}"></script>')
    top_models = sorted((m for m in MODELS if ctx["by_model"].get(m["slug"])), key=lambda m: -len(ctx["by_model"][m["slug"]]))[:12]
    fm = "".join(f'<li><a href="/{m["slug"]}/">{E(m["name"])}</a></li>' for m in sorted(top_models, key=lambda m: -m["year"]))
    cats = "".join(f'<li><a href="{c["path"]}">{E(c["short"])}</a></li>' for c in ctx["cats"])
    guides = "".join(f'<li><a href="/pruvodce/{g["slug"]}/">{E(g["short"])}</a></li>' for g in ctx["guides"])
    shops = "".join(f'<li><a href="/obchody/{s}/">{E(SHOP[s]["name"])}</a></li>' for s in ctx["shop_ids"])
    cfg_tag = f'<script type="application/json" id="cfg">{json.dumps(cfg, ensure_ascii=False, separators=(",", ":"))}</script>' if cfg else ""
    return f"""<!doctype html><html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{E(title)}</title><meta name="description" content="{E(desc)}"><link rel="canonical" href="{canon}"><meta name="robots" content="{robots}">
<meta property="og:type" content="website"><meta property="og:locale" content="cs_CZ"><meta property="og:site_name" content="{BRAND}">
<meta property="og:title" content="{E(title)}"><meta property="og:description" content="{E(desc)}"><meta property="og:url" content="{canon}"><meta property="og:image" content="{E(og_img or SITE + '/img/ui/og.png')}">
<meta name="twitter:card" content="summary_large_image">{preload}
<link rel="stylesheet" href="{ctx['css']}"><link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="icon" href="/favicon-32.png" sizes="32x32">
<link rel="apple-touch-icon" href="/favicon-180.png"><link rel="manifest" href="/site.webmanifest"><meta name="theme-color" content="#FFFFFF">{ldtxt}{ga}</head><body>{noscript}
<a class="skip" href="#obsah">Přeskočit na obsah</a>
<header class="top"><div class="wrap top-in"><a class="logo" href="/" aria-label="{BRAND} – úvod">{logo_mark()}<span>repasovaný <b>iPhone</b></span></a>
<nav class="nav" aria-label="Hlavní">{nav}</nav></div></header>
{cr}<main id="obsah">{body}</main>
<footer class="foot"><div class="wrap foot-in"><div class="about"><a class="logo" href="/">{logo_mark(30)}<span>repasovaný <b>iPhone</b></span></a>
<p>Každou noc projdeme nabídky {obchodu(len(ctx['shop_ids']))} s repasovanými, zánovními i novými iPhony a ke každé konfiguraci najdeme nejlevnější obchod
včetně platných slevových kódů. Ceny se během dne mohou změnit, platí údaj v obchodě.</p>
<p class="muted">Za nákup přes odkaz můžeme dostat provizi, cenu ani pořadí to nemění. <a href="/o-webu/">Jak web funguje</a></p></div>
<div><h2>Modely</h2><ul>{fm}</ul></div><div><h2>Kategorie</h2><ul>{cats}<li><a href="/srovnani/">Srovnání modelů</a></li><li><a href="/jaky-iphone-koupit/">Jaký iPhone koupit</a></li></ul></div>
<div><h2>Průvodce</h2><ul>{guides}</ul><h2 class="mt">Obchody</h2><ul>{shops}</ul></div></div>
<div class="wrap foot-legal"><a href="/o-webu/">O webu a kontakt</a><a href="/ochrana-osobnich-udaju/">Ochrana osobních údajů</a>{'<a href="#" data-consent-open>Nastavení cookies</a>' if ga else ''}</div></footer>
{'<div class="consent" data-consentbar role="dialog" aria-label="Souhlas s cookies" hidden><p>Smíme měřit návštěvnost (Google Analytics)? Bez souhlasu nic neukládáme. <a href="/ochrana-osobnich-udaju/">Více</a></p><div><button type="button" class="btn sm" data-consent="yes">Souhlasím</button> <button type="button" class="btn sm ghost" data-consent="no">Nesouhlasím</button></div></div>' if ga else ''}
{cfg_tag}<script src="{ctx['js']}" defer></script></body></html>"""


# ---------------------------------------------------------------- components

_LOGO_WH = {}


def logo_w(sid, h):
    """Rendered width of a shop logo at height h (width/height attributes avoid layout shift)."""
    if sid not in _LOGO_WH:
        from PIL import Image
        f = APP / "static/img/shops" / f"{sid}.webp"
        _LOGO_WH[sid] = Image.open(f).size if f.exists() else (0, 0)
    w, hh = _LOGO_WH[sid]
    return round(w * h / hh) if hh else 0


def shop_logo(sid, h=22):
    s = SHOP[sid]
    if (APP / "static/img/shops" / f"{sid}.webp").exists():
        return f'<img class="slogo" src="/img/shops/{sid}.webp" alt="{E(s["name"])}" width="{logo_w(sid, h)}" height="{h}" loading="lazy" decoding="async">'
    return f'<span class="slogo stext" style="--c:{s["color"]}">{E(s["name"])}</span>'


def grade_chip(g):
    return f'<span class="gchip g-{g}" title="{E(GR[g]["name"])}">{E(GR[g]["short"])}</span>'


def coupon_box(c, go=""):
    """Voucher ticket with copy button (app.js copies data-copy)."""
    btn = f'<a class="btn sm" href="{E(go)}" rel="sponsored nofollow noopener" target="_blank" data-copy="{E(c["code"])}">Do obchodu</a>' if go else ""
    return (f'<div class="cpn"><span class="cpn-k">Slevový kód</span><code>{E(c["code"])}</code>'
            f'<button type="button" class="cpn-copy" data-copy="{E(c["code"])}">Kopírovat</button>{btn}'
            f'<small>{E(c["label"])} · {until_cz(c)} · zadejte v košíku{"" if c["auto"] else " · podmínky ověřte u obchodu"}</small></div>')


def faq_html(items):
    return '<div class="faq">' + "".join(f"<details><summary>{E(q)}</summary><div>{a}</div></details>" for q, a in items) + "</div>"


def faq_ld(items):
    return {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": re.sub(r"<[^>]+>", "", a)}} for q, a in items]}


def product_ld(name, path, offers, image="", desc=""):
    ps = [o["p"] for o in offers]
    cond = "https://schema.org/RefurbishedCondition" if any(o["g"] != "novy" for o in offers) else "https://schema.org/NewCondition"
    d = {"@context": "https://schema.org", "@type": "Product", "name": name, "brand": {"@type": "Brand", "name": "Apple"}, "url": SITE + path,
         "offers": {"@type": "AggregateOffer", "priceCurrency": "CZK", "lowPrice": min(ps), "highPrice": max(ps), "offerCount": len(ps),
                    "itemCondition": cond, "availability": "https://schema.org/InStock"}}
    if image:
        d["image"] = image
    if desc:
        d["description"] = desc
    return d


def specs_html(m):
    def yn(b):
        return '<span class="yes">ano</span>' if b else '<span class="no">ne</span>'
    rows = [("Uveden", str(m["year"])), ("Displej", f'{str(m["display"]).replace(".", ",")}″' + (f', {m["hz"]} Hz' if m.get("hz") else "")),
            ("Čip", m["chip"]), ("Konektor", m["port"]), ("Odemykání", m["bio"]),
            ("Paměť", ", ".join(P.gb_label(v) for v in m["storage"])),
            ("Aktuální iOS 26 a 27", yn(ios_ok(m))), ("Apple Intelligence", yn(m.get("ai")))]
    if m.get("esim_only"):
        rows.append(("SIM", "jen eSIM"))
    return '<dl class="specs">' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"


def chart_html(points):
    if len(points) < 7:
        return ""
    W, H, pad = 640, 180, 34
    ps = [p for _, p in points]
    lo, hi = min(ps), max(ps)
    span = max(hi - lo, 1)
    xs = [pad + i * (W - 2 * pad) / (len(points) - 1) for i in range(len(points))]
    ys = [H - pad - (p - lo) / span * (H - 2 * pad) for p in ps]
    path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    return (f'<figure class="chart"><svg viewBox="0 0 {W} {H}" role="img" aria-label="Vývoj nejnižší ceny">'
            f'<line class="ax" x1="{pad}" x2="{W - pad}" y1="{H - pad}" y2="{H - pad}"/><path class="ln" d="{path}"/>'
            f'<text x="{pad}" y="{pad - 8}">{kc(hi)}</text><text x="{pad}" y="{H - pad + 18}">{kc(lo)}</text>'
            f'<text x="{W - pad}" y="{H - 8}" text-anchor="end">{E(points[-1][0])}</text><text x="{pad}" y="{H - 8}">{E(points[0][0])}</text></svg>'
            f'<figcaption class="muted">Nejnižší cena repasovaného kusu podle dne.</figcaption></figure>')


# ---------------------------------------------------------------- configurator

def cfg_data(ctx, m, offers, gb_pref=None):
    """Compact JSON for app.js. Rows: [colour i, storage i, grade, shop price, shop, go, battery, eSIM, price after code]; sorted by the last.
    No shop wording: quality is our scale only."""
    slug = m["slug"]
    cols = [c for c in P.COLORS.get(slug, []) if any(o["col"] == c["key"] for o in offers)]
    gbs = sorted({o["gb"] for o in offers})
    ci = {c["key"]: i for i, c in enumerate(cols)}
    gi = {g: i for i, g in enumerate(gbs)}
    shops = sorted({o["shop"] for o in offers})
    rows = []
    for o in sorted(offers, key=lambda o: (o["pc"], o["p"])):
        go = o["go"]
        pre = f"/go/{o['shop']}/?u="
        go = "~" + go[len(pre):] if go.startswith(pre) else go    # "~" = only the shop path; app.js / go_url() put /go/<shop>/?u= back
        rows.append([ci[o["col"]], gi[o["gb"]], o["g"], o["p"], o["shop"], go, o["bat"] or 0, 1 if o["esim"] else 0, o["pc"]])
    rf = [o for o in offers if o["g"] != "novy"] or offers
    dgb = gb_pref if gb_pref in gi else Counter(o["gb"] for o in rf).most_common(1)[0][0]
    pool = [o for o in rf if o["gb"] == dgb] or [o for o in offers if o["gb"] == dgb]
    dcol = Counter(o["col"] for o in pool).most_common(1)[0][0]
    here = [o for o in offers if o["gb"] == dgb and o["col"] == dcol]
    gs = {o["g"] for o in here}
    dg = "a" if "a" in gs else min(here, key=lambda o: o["pc"])["g"]
    shop_meta = {s: [SHOP[s]["name"], f"/img/shops/{s}.webp" if (APP / "static/img/shops" / f"{s}.webp").exists() else "", SHOP[s]["color"], logo_w(s, 22) / 22] for s in shops}
    cps = {}
    for s in shops:
        for c in ctx["coupons"].get(s, []):
            if c["auto"]:
                cps[s] = [c["code"], c["label"], until_cz(c)]
                break
    return {"m": slug, "name": m["name"], "cols": [[c["key"], c["name"], c["hex"], photo(ctx, slug, c["key"], 600)] for c in cols],
            "gbs": gbs, "shops": shop_meta, "newp": {str(gb): ctx["new_min"][(slug, gb)] for gb in gbs if (slug, gb) in ctx["new_min"]},
            "grades": {k: [v["short"], v["name"], v["ex"]] for k, v in GR.items()}, "gimg": GIMG, "cp": cps, "o": rows, "def": [dcol, dgb, dg]}


def configurator_html(ctx, m, cfg):
    """Server-rendered first state (works without JS, crawlable); app.js re-renders the same markup on every change."""
    cols, gbs, rows = cfg["cols"], cfg["gbs"], cfg["o"]
    dcol, dgb, dg = cfg["def"]
    ci = next(i for i, c in enumerate(cols) if c[0] == dcol)
    gi = gbs.index(dgb)
    sw = "".join(f'<button type="button" class="sw{" on" if c[0] == dcol else ""}" data-col="{c[0]}" aria-pressed="{str(c[0] == dcol).lower()}" '
                 f'aria-label="{E(c[1])}"><span class="dot" style="--h:{c[2]}"></span></button>' for c in cols)
    pills = "".join(f'<button type="button" class="pill{" on" if g == dgb else ""}" data-gb="{g}" aria-pressed="{str(g == dgb).lower()}">{P.gb_label(g)}</button>' for g in gbs)
    here = [r for r in rows if r[0] == ci and r[1] == gi]
    gcards = []
    for g, *_r in P.GRADES:
        ps = [r[8] for r in here if r[2] == g]
        gcards.append(f'<button type="button" class="gcard{" on" if g == dg else ""}{"" if ps else " off"}" data-g="{g}" aria-pressed="{str(g == dg).lower()}"{"" if ps else " disabled"}>'
                      f'<span class="gl g-{g}">{E(GR[g]["short"])}</span><span class="gn">{E(GR[g]["name"])}</span>'
                      f'<span class="gp">{"od " + kc(min(ps)) if ps else "není skladem"}</span></button>')
    res = [r for r in here if r[2] == dg]
    alt = f"{m['name']} v barvě {cols[ci][1]}"
    return f"""<section class="cfg" data-cfg aria-label="Výběr iPhonu">
<div class="cfg-photo"><div class="ph"><img src="{E(cols[ci][3])}" alt="{E(alt)}" width="600" height="600" fetchpriority="high" data-photo></div></div>
<div class="cfg-steps">
<div class="step"><h2 class="step-h"><span class="n">1</span>Barva <span class="step-v" data-v-col>{E(cols[ci][1])}</span></h2><div class="sws" data-cols>{sw}</div></div>
<div class="step"><h2 class="step-h"><span class="n">2</span>Paměť</h2><div class="pills" data-gbs>{pills}</div></div>
<div class="step"><h2 class="step-h"><span class="n">3</span>Kvalita <a class="step-help" href="/pruvodce/stavy/">co znamená A, B, C?</a></h2>
<div class="gcards" data-grades>{"".join(gcards)}</div><p class="ghint"><img data-gimg src="/img/ui/grade-{dg if dg in GIMG else "a"}.webp" alt="" width="64" height="64"{"" if dg in GIMG else " hidden"}><span data-ghint>{E(GR[dg]["ex"]).capitalize()}.</span></p></div>
<div class="result" data-result aria-live="polite">{result_html(cfg, res, dgb)}</div>
</div></section>"""


def result_html(cfg, res, gb):
    """Same markup as result() in app.js."""
    if not res:
        return '<p class="empty">Tahle kombinace teď není skladem. Zkuste jinou barvu nebo kvalitu.</p>'
    best = res[0]
    newp = cfg["newp"].get(str(gb))
    sh, cps = cfg["shops"], cfg["cp"]
    save = f'<span class="save hand">o {kc(newp - best[8])} levněji než nový</span>' if newp and newp > best[8] and best[2] != "novy" else ""
    was = f'<span class="was">{kc(best[3])} v obchodě</span>' if best[8] < best[3] else ""
    facts = []
    if best[6]:
        facts.append(f"baterie {best[6]} %")
    if best[7]:
        facts.append("jen eSIM")
    cp = cps.get(best[4]) if best[8] < best[3] else None
    cbox = (f'<div class="cpn"><span class="cpn-k">Slevový kód</span><code>{E(cp[0])}</code><button type="button" class="cpn-copy" data-copy="{E(cp[0])}">Kopírovat</button>'
            f'<small>{E(cp[1])} · {E(cp[2])} · zadejte v košíku</small></div>') if cp else ""
    per_shop = {}
    for r in res:
        per_shop.setdefault(r[4], r)
    others = [r for r in per_shop.values() if r is not best]

    def chip(r):
        c = cps.get(r[4]) if r[8] < r[3] else None
        return (f'<button type="button" class="cchip" data-copy="{E(c[0])}" data-shop="{r[4]}" aria-label="Kopírovat slevový kód {E(c[0])}">'
                f'<span>{E(c[0])}</span>{COPY_ICON}</button>') if c else ""
    olist = "".join(f'<li><span class="o-shop">{shop_mini(sh, r[4])}</span><span class="o-cp">{chip(r)}</span>'
                    f'<span class="o-p"><b>{kc(r[8])}</b>{f"<s>{kc(r[3])}</s>" if r[8] < r[3] else ""}</span>'
                    f'<a class="btn sm ghost" href="{E(go_url(r))}" rel="sponsored nofollow noopener" target="_blank" data-go="{r[4]}" data-price="{r[8]}"'
                    f'{(" data-copy=" + chr(34) + E(cps[r[4]][0]) + chr(34)) if r[8] < r[3] and r[4] in cps else ""}>Do obchodu</a></li>'
                    for r in others)
    near = next((r for r in others if r[8] < r[3] and r[4] in cps and r[8] <= best[8] * 1.03), None) if not cp else None
    hint = (f'<p class="cphint"><span class="hand">Radši se slevovým kódem?</span> {E(sh[near[4]][0])} s kódem {chip(near)} '
            f'za {kc(near[8])}{f" (jen o {kc(near[8] - best[8])} víc)" if near[8] > best[8] else ""}</p>') if near else ""
    cta = f"Koupit s kódem u {E(sh[best[4]][0])}" if cp else f"Koupit u {E(sh[best[4]][0])}"
    return (f'<div class="best"><div class="best-top"><span class="best-k">Nejlevněji</span>{shop_mini(sh, best[4], 26)}</div>'
            f'<p class="best-p"><span class="price">{kc(best[8])}</span>{was}{save}</p>'
            + (f'<p class="best-f">{" · ".join(facts)}</p>' if facts else "") + cbox
            + f'<a class="btn big" href="{E(go_url(best))}" rel="sponsored nofollow noopener" target="_blank" data-go="{best[4]}" data-price="{best[8]}"'
            + (f' data-copy="{E(cp[0])}"' if cp else "") + f'>{cta}</a>'
            f'<p class="best-n">{nab(len(res))} v této konfiguraci</p></div>' + hint
            + (f'<div class="alts"><h3>Další obchody</h3><ul>{olist}</ul></div>' if olist else ""))


COPY_ICON = ('<svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2.5" fill="none" stroke="currentColor" stroke-width="2"/>'
             '<path d="M5 15V6a2 2 0 0 1 2-2h9" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>')


def shop_mini(shops, sid, h=22):
    name, logo, color, ratio = shops[sid]
    if logo:
        return f'<img class="slogo" src="{logo}" alt="{E(name)}" width="{round(ratio * h)}" height="{h}" loading="lazy" decoding="async">'
    return f'<span class="slogo stext" style="--c:{color}">{E(name)}</span>'


def go_url(r):
    return f"/go/{r[4]}/?u={r[5][1:]}" if r[5].startswith("~") else r[5]


# ---------------------------------------------------------------- texts

def model_text(ctx, m, offers):
    rf = [o for o in offers if o["g"] != "novy"] or offers
    low = min(o["pc"] for o in rf)
    shops = sorted({SHOP[o["shop"]]["name"] for o in rf})
    age = max(TODAY.year - m["year"], 0)
    gb_c = Counter(o["gb"] for o in rf).most_common(1)[0][0]
    t = [f'<p>Právě teď je v nabídce <strong>{nab(len(rf))}</strong> repasovaného, zánovního nebo bazarového {E(m["name"])} '
         f'z {obchodu(len(shops))} ({E(", ".join(shops))}). Nejlevnější kus stojí <strong>{kc(low)}</strong>, nejčastěji se prodává verze s {P.gb_label(gb_c)}.</p>']
    sv = sorted((ctx["new_min"][(o["model"], o["gb"])] - o["pc"]) / ctx["new_min"][(o["model"], o["gb"])]
                for o in rf if o["g"] != "novy" and ctx["new_min"].get((o["model"], o["gb"]), 0) > o["pc"])
    if sv:
        t.append(f'<p>Proti nejlevnějšímu novému kusu se stejnou pamětí ušetříte typicky <strong>{round(sv[len(sv) // 2] * 100)} %</strong>.</p>')
    why = ["dostává aktuální iOS 26 i 27" if ios_ok(m) else
           "<strong>už nedostává aktuální iOS</strong> (iOS 26 a 27 začínají u iPhonu 11), časem přijde o část aplikací",
           "nabíjí se přes USB-C" if m["port"] == "USB-C" else "má ještě konektor Lightning"]
    if m.get("ai"):
        why.append("podporuje Apple Intelligence")
    if m.get("hz") == 120:
        why.append("má plynulý 120Hz displej")
    t.append(f'<p>{E(m["name"])} vyšel v roce {m["year"]} s čipem {E(m["chip"])}' + (f', je mu {age} {plural(age, "rok", "roky", "let")}' if age else "")
             + f'. Telefon {", ".join(why)}.</p>')
    bats = sum(1 for o in rf if o["bat"])
    t.append(f'<p>{"Kondici baterie uvádí " + str(bats) + " z " + str(len(rf)) + " nabídek." if bats else "Kondici baterie obchody u tohoto modelu většinou neuvádějí."} '
             'Před nákupem se na ni zeptejte, pod 80 % ji Apple považuje za opotřebovanou. <a href="/pruvodce/baterie/">Jak číst kondici baterie</a></p>')
    return "".join(t)


def model_faq(ctx, m, offers):
    rf = [o for o in offers if o["g"] != "novy"] or offers
    by_g = defaultdict(list)
    for o in rf:
        by_g[o["g"]].append(o["pc"])
    gtxt = ", ".join(f'kvalita {GR[g]["short"]} od {kc(min(v))}' for g, v in sorted(by_g.items(), key=lambda x: P.GRADE_ORDER[x[0]]))
    items = [(f'Kolik stojí repasovaný {m["name"]}?', f'Nejlevnější nabídka dnes stojí {kc(min(o["pc"] for o in rf))}. Podle kvality: {gtxt}. Ceny kontrolujeme každou noc.'),
             ("Co znamená kvalita A, B a C?",
              "Kvalita popisuje vzhled, ne funkčnost: A+ je jako nový, A má stopy viditelné jen zblízka, B jemné škrábance na rámu nebo zádech a C viditelné známky "
              'používání. Všechny obchody převádíme na tuhle jednu stupnici. <a href="/pruvodce/stavy/">Co přesně jednotlivé kvality znamenají</a>'),
             ("Jakou záruku má repasovaný iPhone?",
              "Od obchodníka 24 měsíců, u použitého zboží ji smí dohodou zkrátit na 12 měsíců. Při nákupu přes internet můžete do 14 dnů odstoupit od smlouvy bez udání důvodu. "
              '<a href="/pruvodce/zaruka/">Záruka a vrácení</a>')]
    if any(o["cp"] for o in offers):
        codes = sorted({(SHOP[o["shop"]]["name"], o["cp"]["code"]) for o in offers if o["cp"]})
        items.append(("Platí na repasovaný iPhone slevový kód?",
                      "Ano, u části obchodů: " + ", ".join(f"{E(s)} kód {E(c)}" for s, c in codes)
                      + ". Ceny „s kódem“ v konfigurátoru už slevu obsahují, kód zadáte v košíku obchodu."))
    if any(o["esim"] for o in rf):
        items.append(("Co znamená „jen eSIM“?", "Verze bez slotu na fyzickou SIM kartu (typicky telefony z USA). Fungují s eSIM, kterou vydávají všichni čeští operátoři."))
    return items


def storage_text(gb):
    if gb <= 64:
        return "<p>64 GB stačí na zprávy, pár aplikací a fotky zálohované do iCloudu. Systém si vezme kolem 20 GB, video ve 4K zabere asi 0,4 GB za minutu.</p>"
    if gb == 128:
        return "<p>128 GB je rozumný základ pro většinu lidí: tisíce fotek, běžné aplikace i offline mapy. Kdo hodně natáčí, sáhne po 256 GB.</p>"
    if gb == 256:
        return "<p>256 GB je bezstarostná volba i pro velkou knihovnu fotek a videí. Příplatek proti 128 GB bývá u repasovaných kusů menší než u nových.</p>"
    return "<p>512 GB a víc dává smysl hlavně pro natáčení videa ve vysoké kvalitě nebo pro celou knihovnu fotek offline. Pro běžné používání je to rezerva navíc.</p>"


# ---------------------------------------------------------------- pages

def model_cats(ctx, m, offers):
    """Category landings this model appears in (internal links from the model page)."""
    rf = [o for o in offers if o["g"] != "novy"]
    out = []
    low = min((o["pc"] for o in rf), default=10 ** 9)
    if ios_ok(m):
        out.append(("/levny-iphone/", "Levné iPhony"))
    if low <= 5000:
        out.append(("/iphone-do-5000-kc/", "iPhone do 5 000 Kč"))
    elif low <= 10000:
        out.append(("/iphone-do-10000-kc/", "iPhone do 10 000 Kč"))
    if any(o["g"] == "aplus" for o in offers):
        out.append(("/zanovni-iphone/", "Zánovní a rozbalené iPhony"))
    if any(o["g"] == "novy" for o in offers):
        out.append(("/novy-iphone/", "Nové iPhony"))
    if m["display"] <= 6.1 and ios_ok(m):
        out.append(("/maly-iphone/", "Malé iPhony"))
    if ios_ok(m) and low <= 9000:
        out.append(("/iphone-pro-deti/", "iPhone pro děti"))
    return out


def page_model(out, ctx, m, offers, gb=None):
    slug = m["slug"]
    path = f"/{slug}/" if gb is None else f"/{slug}/{gb}-gb/"
    rf = [o for o in offers if o["g"] != "novy"] or offers
    scope = [o for o in rf if gb is None or o["gb"] == gb]
    low = min(o["pc"] for o in scope)
    n_shops = len({o["shop"] for o in scope})
    lab = f'{m["name"]} {P.gb_label(gb)}' if gb else m["name"]
    only_new = all(o["g"] == "novy" for o in offers)
    cfg = cfg_data(ctx, m, offers, gb)
    title = short_title(f"{lab} bazar i repasovaný od {kc_plain(low)} – {n_shops} {plural(n_shops, 'obchod', 'obchody', 'obchodů')}" if not only_new
                        else f"{lab} nejlevněji od {kc_plain(low)} – srovnání {n_shops} {plural(n_shops, 'obchodu', 'obchodů', 'obchodů')}")
    desc = (f"{'Repasovaný a zánovní' if not only_new else 'Nový'} {lab}: {nab(len(scope))} od {kc(low)}. Vyberte barvu, paměť a kvalitu A, B nebo C, "
            "ukážeme nejlevnější obchod i slevové kódy.").replace(" ", " ")
    ph600 = cfg["cols"][next(i for i, c in enumerate(cfg["cols"]) if c[0] == cfg["def"][0])][3]
    preload = f'<link rel="preload" as="image" href="{ph600}" fetchpriority="high">' if ph600 else ""
    hist = ctx["hist"].get(slug if gb is None else f"{slug}|{gb}", [])
    sibs = [x for x in MODELS if x["family"] == m["family"] and x["slug"] != slug and ctx["by_model"].get(x["slug"])]
    near = [x for x in MODELS if abs(x["year"] - m["year"]) <= 1 and x["slug"] != slug and x not in sibs and ctx["by_model"].get(x["slug"])]
    rel = "".join(f'<li><a href="/{x["slug"]}/">{E(x["name"])} bazar</a></li>' for x in (sibs + near)[:10])
    gbl = "".join(f'<li><a href="/{slug}/{g}-gb/">{E(m["name"])} {P.gb_label(g)}</a></li>' for g in sorted({o["gb"] for o in rf})
                  if (slug, g) in ctx["sub_pages"] and g != gb)
    cats = "".join(f'<li><a href="{u}">{E(n)}</a></li>' for u, n in model_cats(ctx, m, offers))
    items = model_faq(ctx, m, offers)
    h1 = f"Repasovaný {E(lab)}" if not only_new else E(lab)
    body = f"""<div class="wrap">
<header class="mhead"><p class="eyebrow">Ceny z {date_cz(TODAY)} · {nab(len(scope))} z {obchodu(n_shops)}</p>
<h1>{h1}</h1><p class="lead">{'Bazarové, zánovní i nové kusy' if not only_new else 'Nové kusy'} od <strong>{kc(low)}</strong>. Vyberte barvu, paměť a kvalitu, ukážeme nejlevnější obchod.</p></header>
{configurator_html(ctx, m, cfg)}
<section class="sec"><h2>Ceník podle paměti a kvality</h2><p class="muted">Nejnižší cena v každé kombinaci (všechny barvy, včetně platných slevových kódů). Sloupec „Nový“ je nejlevnější nový kus.</p>{price_table(ctx, m, offers)}</section>
<section class="sec two"><div class="prose"><h2>Vyplatí se {E(m["name"])} z druhé ruky?</h2>{model_text(ctx, m, offers)}{storage_text(gb) if gb else ""}{chart_html(hist)}</div>
<aside class="card"><h2>Technický list</h2>{specs_html(m)}</aside></section>
<section class="sec"><h2>Časté otázky</h2>{faq_html(items)}</section>
{f'<section class="sec"><h2>{E(m["name"])} podle paměti</h2><ul class="chips">{gbl}</ul></section>' if gbl else ''}
{f'<section class="sec"><h2>Kategorie</h2><ul class="chips">{cats}</ul></section>' if cats else ''}
{f'<section class="sec"><h2>Podobné modely</h2><ul class="chips">{rel}</ul></section>' if rel else ''}
</div>
<div class="buybar" data-buybar hidden><div class="wrap buybar-in"><span class="bb-t" data-bb-t></span><a class="btn" data-bb-a href="/{slug}/" rel="sponsored nofollow noopener" target="_blank">Koupit</a></div></div>"""
    crumbs = [("/", "Repasované iPhony"), (f"/{slug}/", m["name"])] + ([(path, P.gb_label(gb))] if gb else [])
    abs_img = SITE + ph600 if ph600 else ""
    ld = [product_ld(f"{lab}" + ("" if only_new else " (repasovaný)"), path, scope, abs_img, desc), faq_ld(items)]
    idx = len(scope) >= (2 if gb is None else 3)
    out.page(path, layout(ctx, path=path, title=title, desc=desc, body=body, crumbs=crumbs, ld=ld, og_img=abs_img, cfg=cfg, preload=preload, index=idx), index=idx)
    if abs_img:
        out.images[path] = [(SITE + c[3], f"{m['name']} v barvě {c[1]}") for c in cfg["cols"] if c[3]]


def page_model_gone(out, ctx, m, last_seen):
    """A model that had offers before: keep the URL (no 404), point to the nearest models, noindex after GONE_DAYS."""
    slug = m["slug"]
    path = f"/{slug}/"
    days = (TODAY - dt.date.fromisoformat(last_seen)).days
    alts = [x for x in sorted(MODELS, key=lambda x: (abs(x["year"] - m["year"]), x["family"] != m["family"])) if ctx["by_model"].get(x["slug"])][:6]
    cards = "".join(model_card(ctx, x) for x in alts)
    body = f"""<div class="wrap"><header class="mhead"><h1>Repasovaný {E(m["name"])}</h1>
<p class="lead">{E(m["name"])} teď žádný ze sledovaných obchodů nemá skladem (naposledy {date_cz(dt.date.fromisoformat(last_seen))}). Nabídky kontrolujeme každou noc.
Podobné modely, které skladem jsou:</p></header><ul class="mgrid">{cards}</ul>
<section class="sec two"><div class="prose"><h2>O modelu</h2><p>{E(m["name"])} vyšel v roce {m["year"]} s čipem {E(m["chip"])}.</p></div><aside class="card"><h2>Technický list</h2>{specs_html(m)}</aside></section></div>"""
    out.page(path, layout(ctx, path=path, title=f"Repasovaný {m['name']} – teď není skladem, podobné modely", desc=f"{m['name']} z druhé ruky teď není skladem. Podobné modely a jejich ceny.",
                          body=body, crumbs=[("/", "Repasované iPhony"), (path, m["name"])], index=days <= GONE_DAYS), index=days <= GONE_DAYS)


def price_table(ctx, m, offers):
    slug = m["slug"]
    gbs = sorted({o["gb"] for o in offers})
    gs = [g for g in REFURB_G if any(o["g"] == g for o in offers)]
    head = "".join(f'<th>{grade_chip(g)}</th>' for g in gs)
    rows = []
    for gb in gbs:
        here = [o for o in offers if o["gb"] == gb and o["g"] != "novy"]
        low = min((o["pc"] for o in here), default=0)
        cells = []
        for g in gs:
            ps = [o["pc"] for o in here if o["g"] == g]
            cells.append(f'<td class="num{" low" if ps and min(ps) == low else ""}">{kc(min(ps))}</td>' if ps else '<td class="na">–</td>')
        nw = min((o["pc"] for o in offers if o["gb"] == gb and o["g"] == "novy"), default=0)
        name = f'<a href="/{slug}/{gb}-gb/">{P.gb_label(gb)}</a>' if (slug, gb) in ctx["sub_pages"] else P.gb_label(gb)
        rows.append(f'<tr><th scope="row">{name}</th>{"".join(cells)}<td class="num newp">{kc(nw) if nw else "–"}</td></tr>')
    return f'<div class="tscroll"><table class="ptable"><thead><tr><th>Paměť</th>{head}<th>Nový</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def model_card(ctx, m):
    of = ctx["by_model"][m["slug"]]
    rf = [o for o in of if o["g"] != "novy"] or of
    low = min(rf, key=lambda o: o["pc"])
    cols = [c for c in P.COLORS.get(m["slug"], []) if any(o["col"] == c["key"] for o in of)]
    dots = "".join(f'<span class="dot xs" style="--h:{c["hex"]}" title="{E(c["name"])}"></span>' for c in cols)
    return (f'<li><a class="mcard" href="/{m["slug"]}/">{pic(ctx, m["slug"], None, 120, alt=m["name"])}<span class="mc-n">{E(m["name"])}</span>'
            f'<span class="mc-dots">{dots}</span><span class="mc-p">od <b>{kc(low["pc"])}</b></span>'
            f'<span class="mc-c">{nab(len(rf))}{" · s kódem" if low["pc"] < low["p"] else ""}</span></a></li>')


def page_home(out, ctx):
    rf = ctx["refurb"]
    low = min(o["pc"] for o in rf)
    shops = len(ctx["shop_ids"])
    fams = []
    for fk, fname in FAMILIES:
        ms = [m for m in MODELS if m["family"] == fk and ctx["by_model"].get(m["slug"])]
        if ms:
            fams.append(f'<div class="fam"><h3>{E(fname)}</h3><ul class="mgrid">{"".join(model_card(ctx, m) for m in ms)}</ul></div>')
    deals = ctx["deals"][:6]
    dl = "".join(deal_card(ctx, o) for o in deals)
    pop = [m for m in sorted(MODELS, key=lambda m: -len(ctx["by_model"].get(m["slug"], []))) if ctx["by_model"].get(m["slug"])][:8]
    chips = "".join(f'<li><a href="/{m["slug"]}/">{E(m["name"])}</a></li>' for m in sorted(pop, key=lambda m: -m["year"]))
    ex = next((o for o in ctx["deals"] if o["model"] in ("iphone-15", "iphone-16", "iphone-15-pro", "iphone-14", "iphone-13", "iphone-16-pro") and o["gb"] <= 256),
              deals[0] if deals else None)
    note = (f'<span class="hand note-hero">{E(MODEL[ex["model"]]["name"])} o {kc(ctx["new_min"][(ex["model"], ex["gb"])] - ex["pc"])} levněji než nový</span>'
            f'<svg class="note-arrow" viewBox="0 0 80 60" aria-hidden="true"><path d="M6 8c22 2 44 12 56 38" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>'
            f'<path d="M50 40l12 7 3-14" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>') if ex else ""
    grades = "".join(f'<li class="gx">' + (f'<img src="/img/ui/grade-{k}.webp" alt="" width="120" height="120" loading="lazy">' if k in GIMG else "")
                     + f'<span class="gl g-{k}">{E(GR[k]["short"])}</span><b>{E(GR[k]["name"])}</b><small>{E(GR[k]["ex"])}</small></li>' for k in REFURB_G)
    logos = "".join(f'<li><a href="/obchody/{s}/" aria-label="{E(SHOP[s]["name"])}">{shop_logo(s, 26)}</a></li>' for s in ctx["shop_ids"])
    cps = "".join(f'<li>{shop_logo(s, 22)}{coupon_box(c, f"/go/{s}/?u=/")}</li>' for s, cl in ctx["coupons"].items() for c in cl)
    hero_img = ('<img src="/img/ui/hero.webp" srcset="/img/ui/hero-sm.webp 404w, /img/ui/hero.webp 808w" sizes="(max-width:860px) 300px, 420px" '
                'alt="Ruka s telefonem, ze kterého padají mince do druhé dlaně" width="404" height="500" fetchpriority="high">')
    items = [("Co je repasovaný iPhone?",
              "Použitý nebo vrácený telefon, který obchod vyčistil, otestoval a případně opravil (nejčastěji baterii nebo displej) a prodává ho se zárukou. "
              'Od bazarového kusu od soukromníka se liší zárukou a kontrolou. <a href="/pruvodce/repas-vs-bazar/">Repas, bazar, zánovní a rozbalený</a>'),
             ("Vyplatí se koupit repasovaný iPhone?",
              "Většinou ano: stejný model stojí o pětinu až polovinu méně než nový. Vybírejte iPhone 11 nebo novější (dostávají aktuální iOS) a hlídejte kondici baterie."),
             ("Odkud jsou ceny?", f"Z produktových exportů {obchodu(shops)}, které stahujeme každou noc, a platných slevových kódů z affiliate sítě eHub. Nakupujete vždy přímo v obchodě."),
             ("Jakou záruku má repasovaný iPhone?",
              'Od obchodníka minimálně 12 měsíců a 14 dní na vrácení při nákupu přes internet. <a href="/pruvodce/zaruka/">Podrobně o záruce</a>')]
    body = f"""<section class="hero"><div class="wrap hero-in"><div class="hero-t">
<p class="eyebrow">{nab(len(rf))} z {obchodu(shops)} · ceny z dnešní noci</p>
<h1>Repasovaný iPhone za&nbsp;cenu, která dává smysl</h1>
<p class="lead">Vyberete model, barvu, paměť a kvalitu. My projdeme obchody s repasy i bazarové nabídky, započítáme slevové kódy a ukážeme, kde je to nejlevnější. Od <strong>{kc(low)}</strong>.</p>
<ul class="chips">{chips}</ul><p><a class="btn big" href="#modely">Vybrat model</a></p></div>
<div class="hero-art">{hero_img}{note}</div></div></section>
<section class="steps wrap" aria-label="Jak to funguje"><ol>
<li><img src="/img/ui/ic-tap.webp" alt="" width="64" height="64"><b>Vyberte model</b><span>od iPhonu 7 po 18 Pro</span></li>
<li><img src="/img/ui/ic-swatches.webp" alt="" width="64" height="64"><b>Barvu a paměť</b><span>jen to, co je skladem</span></li>
<li><img src="/img/ui/ic-search.webp" alt="" width="64" height="64"><b>Kvalitu A, B nebo C</b><span>a máte nejlevnější obchod</span></li></ol></section>
<section class="sec wrap" id="modely"><h2>Vyberte model</h2>{"".join(fams)}</section>
{f'<section class="sec wrap"><h2>Slevové kódy, které teď platí</h2><p class="muted">V cenách na webu už jsou započítané. Kód zadáte v košíku obchodu.</p><ul class="cpns">{cps}</ul></section>' if cps else ''}
{f'<section class="sec wrap"><h2>Dnes se vyplatí</h2><p class="muted">Největší rozdíl proti nejlevnějšímu novému kusu se stejnou pamětí.</p><ul class="deals">{dl}</ul></section>' if dl else ''}
<section class="sec wrap"><h2>Kvalita A, B, C jednoduše</h2><p class="prose">Všechny obchody převádíme na jednu stupnici, ať se nabídky dají porovnat.
Funkčně jsou všechny telefony v pořádku, liší se vzhledem. <a href="/pruvodce/stavy/">Co přesně znamená A, B a C</a></p><ul class="grades">{grades}</ul></section>
<section class="sec wrap why"><ul>
<li><img src="/img/ui/ic-shield.webp" alt="" width="56" height="56" loading="lazy"><b>Záruka od obchodu</b><span>nejméně 12 měsíců u repasu, 24 u nového</span></li>
<li><img src="/img/ui/ic-return.webp" alt="" width="56" height="56" loading="lazy"><b>14 dní na vrácení</b><span>při nákupu přes internet bez udání důvodu</span></li>
<li><img src="/img/ui/ic-battery.webp" alt="" width="56" height="56" loading="lazy"><b>Baterie pod kontrolou</b><span>kde ji obchod uvádí, ukážeme kondici</span></li>
<li><img src="/img/ui/ic-eco.webp" alt="" width="56" height="56" loading="lazy"><b>Šetrnější volba</b><span>telefon, který už jednou vyrobili</span></li></ul></section>
<section class="sec wrap"><h2>Obchody ve srovnání</h2><ul class="logos">{logos}</ul></section>
<section class="sec wrap"><h2>Časté otázky</h2>{faq_html(items)}</section>"""
    ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": BRAND, "url": SITE + "/", "inLanguage": "cs"},
          {"@context": "https://schema.org", "@type": "Organization", "name": BRAND, "url": SITE + "/", "logo": SITE + "/favicon-512.png",
           "email": "info@repasovanyiphone.cz"}, faq_ld(items),
          {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [
              {"@type": "ListItem", "position": i + 1, "url": f'{SITE}/{m["slug"]}/', "name": m["name"]} for i, m in enumerate(pop)]}]
    title = f"Repasovaný iPhone a iPhone bazar – srovnání cen z {shops} obchodů"
    desc = (f"{nab(len(rf)).capitalize()} repasovaných, zánovních a bazarových iPhonů od {kc(low)}. Vyberte model, barvu, paměť a kvalitu A, B nebo C, "
            "ukážeme nejlevnější obchod i slevové kódy.").replace(" ", " ")
    out.page("/", layout(ctx, path="/", title=title, desc=desc, body=body, ld=ld,
                         preload='<link rel="preload" as="image" href="/img/ui/hero.webp" imagesrcset="/img/ui/hero-sm.webp 404w, /img/ui/hero.webp 808w" imagesizes="(max-width:860px) 300px, 420px">'))


def deal_card(ctx, o):
    m = MODEL[o["model"]]
    nw = ctx["new_min"][(o["model"], o["gb"])]
    href = f'/{o["model"]}/?barva={o["col"]}&pamet={o["gb"]}&kvalita={o["g"]}'
    return (f'<li><a class="deal" href="{E(href)}">{pic(ctx, o["model"], o["col"], 100, alt=m["name"] + " v barvě " + color_name(o["model"], o["col"]))}'
            f'<span class="d-t"><b>{E(m["name"])} {P.gb_label(o["gb"])}</b><span class="muted">{E(color_name(o["model"], o["col"]))} · {grade_chip(o["g"])}</span>'
            f'<span class="d-p">{kc(o["pc"])} <span class="save">−{round((nw - o["pc"]) / nw * 100)} %</span></span>'
            f'<span class="d-s">{shop_logo(o["shop"], 16)}{" · s kódem" if o["pc"] < o["p"] else ""}</span></span></a></li>')


# ---- category landings (what people search, DataForSEO 25. 11. 2026) ----

def best_per_model(ctx, pred, grades=REFURB_G):
    rows = []
    for m in MODELS:
        of = [o for o in ctx["by_model"].get(m["slug"], []) if o["g"] in grades and pred(m, o)]
        if of:
            rows.append((m, min(of, key=lambda o: o["pc"]), len(of)))
    return rows


def cat_rows(ctx, rows, limit=40):
    li = []
    for m, o, n in rows[:limit]:
        href = f'/{m["slug"]}/?barva={o["col"]}&pamet={o["gb"]}&kvalita={o["g"]}'
        cn = color_name(m["slug"], o["col"])
        li.append(f'<li><a class="crow" href="{E(href)}">{pic(ctx, m["slug"], o["col"], 80, alt=m["name"] + " v barvě " + cn)}'
                  f'<span class="cr-t"><b>{E(m["name"])}</b><span class="muted">{P.gb_label(o["gb"])} · {E(cn)} · {m["year"]}</span>'
                  f'<span>{grade_chip(o["g"])} {shop_logo(o["shop"], 16)}{"<span class=ccp>s kódem</span>" if o["pc"] < o["p"] else ""}</span></span>'
                  f'<span class="cr-p"><b>{kc(o["pc"])}</b><span class="muted">{nab(n)}</span></span></a></li>')
    return '<ul class="crows">' + "".join(li) + "</ul>"


CATS = [
    {"path": "/levny-iphone/", "short": "Levné iPhony", "h1": "Levný iPhone: nejlevnější iPhony dnes",
     "title": "Levný iPhone – nejlevnější iPhony dnes od {low}",
     "lead": "Nejlevnější kus každého modelu, seřazený od nejnižší ceny včetně slevových kódů. Modely bez aktuálního iOS jsou až na konci."},
    {"path": "/novy-iphone/", "short": "Nové iPhony", "h1": "Nový iPhone: kde je nejlevnější",
     "title": "Nový iPhone nejlevněji – ceny {n} modelů z {shops} obchodů",
     "lead": "Nové, nerozbalené iPhony s plnou zárukou a nejnižší cena u každého modelu."},
    {"path": "/zanovni-iphone/", "short": "Zánovní a rozbalené", "h1": "Zánovní a rozbalené iPhony",
     "title": "Zánovní iPhone a rozbalené kusy od {low} – kvalita A+",
     "lead": "Telefony bez viditelných stop: rozbalené kusy vrácené do 14 dnů a zánovní telefony používané jen krátce. U nás kvalita A+."},
    {"path": "/maly-iphone/", "short": "Malé iPhony", "h1": "Malý iPhone: mini, SE a kompaktní modely",
     "title": "Malý iPhone – mini a SE z druhé ruky od {low}",
     "lead": "iPhony s displejem do 6,1″, které se vejdou do jedné ruky a pořád dostávají aktuální iOS."},
    {"path": "/iphone-do-5000-kc/", "short": "iPhone do 5 000 Kč", "h1": "iPhone do 5 000 Kč",
     "title": "iPhone do 5 000 Kč – repasované a bazarové kusy dnes",
     "lead": "Co dnes koupíte do 5 000 Kč, od nejnovějšího modelu. U levných kusů hlídejte podporu iOS a baterii."},
    {"path": "/iphone-do-10000-kc/", "short": "iPhone do 10 000 Kč", "h1": "iPhone do 10 000 Kč",
     "title": "iPhone do 10 000 Kč – nejnovější modely, které se vejdou",
     "lead": "Nejnovější iPhony, které dnes seženete do 10 000 Kč."},
    {"path": "/iphone-pro-deti/", "short": "iPhone pro děti", "h1": "iPhone pro děti: levný a s podporou iOS",
     "title": "iPhone pro děti – levné repasované modely s aktuálním iOS",
     "lead": "Levný repas v kvalitě B nebo C (stejně dostane obal), který ale dostává aktuální iOS a rodičovskou kontrolu."},
]

CAT_TEXT = {
    "/levny-iphone/": "<h2>Jak koupit levný iPhone a neprodělat</h2><p>Nejlevnější bývají starší modely v kvalitě C. To je v pořádku, pokud telefon ještě dostává "
                      "aktuální iOS: iOS 26 i 27 běží na iPhonu 11 a novějších a na SE 2. generace. Starší kusy (X, XS, 8) jsou levné, ale přicházejí o aplikace.</p>"
                      "<p>Kvalita C znamená viditelné stopy, ne horší funkčnost. Pokud budete telefon nosit v obalu, ušetříte proti kvalitě A často tisíc až dva tisíce korun. "
                      "Další stovky ušetří slevový kód obchodu, který už v cenách započítáváme.</p>",
    "/novy-iphone/": "<h2>Nový, nebo repasovaný?</h2><p>Nový iPhone má 24 měsíců záruky a baterii se 100 % kondicí. Repasovaný kus v kvalitě A+ nebo A vypadá skoro stejně a stojí "
                     "o pětinu až polovinu méně. Rozdíl u konkrétního modelu uvidíte v konfigurátoru, když přepnete kvalitu.</p>",
    "/zanovni-iphone/": "<h2>Zánovní, rozbalený, nebo repasovaný?</h2><p>Rozbalený kus někdo koupil a v zákonné lhůtě vrátil, zánovní byl používaný jen krátce. Oba bývají bez stop "
                        "a s baterií nad 95 %. Proti novému ušetříte méně než u běžného repasu, ale dostanete telefon, který jako použitý nevypadá.</p>",
    "/maly-iphone/": "<h2>Který malý iPhone vybrat</h2><p>Nejmenší displej má iPhone SE (4,7″) s tlačítkem Touch ID. Modely mini mají 5,4″ a Face ID a vejdou se do dlaně. "
                     "Apple malé modely už nevyrábí, z druhé ruky jsou jediná možnost.</p>",
    "/iphone-do-5000-kc/": "<h2>Na co si dát pozor pod 5 000 Kč</h2><p>V této ceně jsou hlavně iPhony SE, 11 a starší. Kupujte modely s aktuálním iOS (iPhone 11, SE 2. generace "
                           "a novější) a ptejte se na baterii: výměna v servisu stojí kolem tisíce korun.</p>",
    "/iphone-do-10000-kc/": "<h2>Co čekat do 10 000 Kč</h2><p>Do deseti tisíc se vejdou i modely s 120Hz displejem a třemi fotoaparáty (řada Pro z let 2021 a 2022) "
                            "nebo základní iPhony s USB-C. Porovnejte si je v <a href=\"/srovnani/\">tabulce modelů</a>.</p>",
    "/iphone-pro-deti/": "<h2>Proč repas pro dítě</h2><p>Dětský telefon dostane obal, spadne a za dva roky se vymění. Repas v kvalitě B nebo C ušetří peníze a pořád podporuje "
                         "Čas u obrazovky a rodičovskou kontrolu. Vybírejte modely s aktuálním iOS a menší velikostí do ruky.</p>",
}


def cat_content(ctx, c):
    newest = lambda r: (-r[0]["year"], r[1]["pc"])  # noqa: E731
    p = c["path"]
    if p == "/levny-iphone/":
        rows = sorted(best_per_model(ctx, lambda m, o: True), key=lambda r: (not ios_ok(r[0]), r[1]["pc"]))
        return rows, ('<ul class="chips"><li><a href="/iphone-do-5000-kc/">iPhone do 5 000 Kč</a></li><li><a href="/iphone-do-10000-kc/">iPhone do 10 000 Kč</a></li>'
                      '<li><a href="/iphone-pro-deti/">iPhone pro děti</a></li><li><a href="/maly-iphone/">Malé iPhony</a></li></ul>')
    if p == "/novy-iphone/":
        return sorted(best_per_model(ctx, lambda m, o: True, grades=("novy",)), key=newest), ""
    if p == "/zanovni-iphone/":
        return sorted(best_per_model(ctx, lambda m, o: True, grades=("aplus",)), key=newest), ""
    if p == "/maly-iphone/":
        return sorted(best_per_model(ctx, lambda m, o: m["display"] <= 6.1 and ios_ok(m)), key=lambda r: (r[0]["display"], -r[0]["year"])), ""
    if p == "/iphone-do-5000-kc/":
        return sorted(best_per_model(ctx, lambda m, o: o["pc"] <= 5000), key=newest), ""
    if p == "/iphone-do-10000-kc/":
        return sorted(best_per_model(ctx, lambda m, o: o["pc"] <= 10000), key=newest), ""
    if p == "/iphone-pro-deti/":
        return sorted(best_per_model(ctx, lambda m, o: ios_ok(m) and o["pc"] <= 9000, grades=("a", "b", "c")), key=newest), ""
    return [], ""


def fam_key(m):
    return m["family"] if m["family"] in ("18", "17", "16", "15", "14", "13") else "starsi"


def cat_card(ctx, m, o, n, reason=""):
    """One offer card in the category grid: the link opens the configurator preset to this offer; the voucher chip sits outside the link."""
    href = f'/{m["slug"]}/?barva={o["col"]}&pamet={o["gb"]}&kvalita={o["g"]}'
    cn = color_name(m["slug"], o["col"])
    nw = ctx["new_min"].get((m["slug"], o["gb"]))
    save = f'<span class="cc-save">o {kc(nw - o["pc"])} levněji než nový</span>' if nw and nw > o["pc"] and o["g"] != "novy" else ""
    cp = o["cp"] if o["pc"] < o["p"] else None
    was = f"<s>{kc(o['p'])}</s>" if cp else ""
    chip = (f'<button type="button" class="cchip" data-copy="{E(cp["code"])}" data-shop="{o["shop"]}" aria-label="Kopírovat slevový kód {E(cp["code"])}">'
            f'<span>{E(cp["code"])}</span>{COPY_ICON}</button>') if cp else ""
    return (f'<li class="ccard" data-p="{o["pc"]}" data-fam="{fam_key(m)}" data-cur="{1 if m["year"] >= 2025 else 0}">'
            + (f'<p class="cc-why">{reason}</p>' if reason else "")
            + f'<a class="cc-link" href="{E(href)}">{pic(ctx, m["slug"], o["col"], 160, alt=m["name"] + " v barvě " + cn)}'
            f'<span class="cc-n">{E(m["name"])}</span><span class="cc-sub">{P.gb_label(o["gb"])} · {E(cn)} · {grade_chip(o["g"])}</span>'
            f'<span class="cc-p">{kc(o["pc"])}{was}</span>{save}'
            f'<span class="cc-cta">Vybrat barvu a paměť <span aria-hidden="true">→</span></span></a>'
            f'<div class="cc-foot">{shop_logo(o["shop"], 18)}{chip}<span class="cc-n2">{nab(n)}</span></div></li>')


def cat_filters(kind):
    if kind == "price":
        chips = [("", "Vše"), ("0-5000", "Do 5 000 Kč"), ("5000-10000", "5–10 tis."), ("10000-15000", "10–15 tis."), ("15000-999999", "Nad 15 tis.")]
        attr = "p"
    elif kind == "fam":
        chips = [("", "Vše"), ("18", "iPhone 18"), ("17", "iPhone 17 a Air"), ("16", "iPhone 16"), ("15", "iPhone 15"), ("14", "iPhone 14"), ("13", "iPhone 13"), ("starsi", "Starší")]
        attr = "fam"
    else:
        chips = [("", "Vše"), ("1", "Aktuální řada"), ("0", "Starší modely")]
        attr = "cur"
    return ('<div class="cfilter" data-cfilter="' + attr + '" role="group" aria-label="Filtr">'
            + "".join(f'<button type="button" class="pill{" on" if not v else ""}" data-v="{v}" aria-pressed="{str(not v).lower()}">{E(t)}</button>' for v, t in chips)
            + '<span class="cf-n" data-cf-n aria-live="polite"></span></div>')


def offers_of(ctx, pred, grades):
    return [o for o in ctx["offers"] if o["g"] in grades and pred(MODEL[o["model"]], o)]


def median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0


def saving_pct(ctx, offers):
    return round(median([(ctx["new_min"][(o["model"], o["gb"])] - o["pc"]) / ctx["new_min"][(o["model"], o["gb"])] * 100
                         for o in offers if ctx["new_min"].get((o["model"], o["gb"]), 0) > o["pc"]]))


def why_model(m):
    w = [f'{m["year"]}, čip {m["chip"]}']
    if m["port"] == "USB-C":
        w.append("USB-C")
    if m.get("hz") == 120:
        w.append("120Hz displej")
    if m.get("ai"):
        w.append("Apple Intelligence")
    w.append("aktuální iOS" if ios_ok(m) else "bez aktuálního iOS")
    return ", ".join(w)


def link_m(m, word="bazar"):
    return f'<a href="/{m["slug"]}/">{E(m["name"])}{" " + word if word else ""}</a>'


def seo_levny(ctx, rows):
    rf = offers_of(ctx, lambda m, o: True, REFURB_G)
    cheapest = min(rf, key=lambda o: o["pc"])
    ok = [o for o in rf if ios_ok(MODEL[o["model"]])]
    cheap_ok = min(ok, key=lambda o: o["pc"])
    mid = sorted((o for o in ok if o["pc"] <= 10000 and o["g"] in ("aplus", "a", "b")), key=lambda o: (-MODEL[o["model"]]["year"], o["pc"]))
    mid = mid[0] if mid else None
    taken = {cheap_ok["model"], mid["model"] if mid else ""}
    usbc = min((o for o in ok if MODEL[o["model"]]["port"] == "USB-C" and o["model"] not in taken), key=lambda o: o["pc"], default=None)
    news = [o for o in ctx["offers"] if o["g"] == "novy"]
    cheap_new = min(news, key=lambda o: o["pc"]) if news else None
    M = lambda o: MODEL[o["model"]]  # noqa: E731
    tips = [(cheap_ok, f"Nejlevnější s aktuálním iOS"), (mid, "Nejnovější do 10 000 Kč v dobrém stavu")] + ([(usbc, "Nejlevnější s USB-C")] if usbc else [])
    tips = [(o, r) for o, r in tips if o]
    lead = (f'Nejlevnější iPhone dnes stojí <strong>{kc(cheapest["pc"])}</strong> – {E(M(cheapest)["name"])}. Nejlevnější iPhone s aktuálním iOS je '
            f'{E(M(cheap_ok)["name"])} za <strong>{kc(cheap_ok["pc"])}</strong>. Ceny včetně slevových kódů.')
    brackets = []
    for lo, hi, lab, url in ((0, 5000, "do 5 000 Kč", "/iphone-do-5000-kc/"), (5000, 10000, "5 000–10 000 Kč", "/iphone-do-10000-kc/"),
                             (10000, 15000, "10 000–15 000 Kč", ""), (15000, 20000, "15 000–20 000 Kč", "")):
        inb = [o for o in ok if lo < o["pc"] <= hi and o["g"] in ("aplus", "a", "b")]
        if not inb:
            continue
        top = max(inb, key=lambda o: (M(o)["year"], -o["pc"]))
        brackets.append(f'<tr><td>{f"<a href={chr(34)}{url}{chr(34)}>iPhone {lab}</a>" if url else "iPhone " + lab}</td><td>{link_m(M(top), "")}</td>'
                        f'<td class="num">{kc(min(o["pc"] for o in inb if o["model"] == top["model"]))}</td><td class="num">{len({o["model"] for o in inb})}</td></tr>')
    codes = "".join(f'<li>{E(SHOP[s]["name"])}: kód <strong>{E(c["code"])}</strong> ({E(c["label"])})</li>' for s, cl in ctx["coupons"].items() for c in cl)
    mrows = []
    for m in sorted((m for m in MODELS if ios_ok(m) and any(o["model"] == m["slug"] for o in ok)), key=lambda m: min(o["pc"] for o in ok if o["model"] == m["slug"]))[:14]:
        nw = [o["pc"] for o in news if o["model"] == m["slug"]]
        mrows.append(f'<tr><th scope="row">{link_m(m)}</th><td>{m["year"]}</td><td class="num">{kc(min(o["pc"] for o in ok if o["model"] == m["slug"]))}</td>'
                     f'<td class="num newp">{kc(min(nw)) if nw else "–"}</td></tr>')
    model_rows = "".join(mrows)
    sec = f"""<h2>Který levný iPhone se vyplatí v roce {TODAY.year}</h2>
<p>Hranici dělá podpora systému. iOS 26 i iOS 27 dostává iPhone 11 a novější a iPhone SE 2. generace. Starší iPhone X, XS, XR a 8 jsou ještě levnější,
ale bez aktuálního iOS časem přijdou o nové verze aplikací. Za nejmenší peníze dnes dává největší smysl:</p><ul>
<li>{link_m(M(cheap_ok))} od {kc(cheap_ok["pc"])} – {E(why_model(M(cheap_ok)))}. Nejlevnější vstup do iPhonu, který ještě dostává aktualizace.</li>
{f'<li>{link_m(M(mid))} od {kc(mid["pc"])} – {E(why_model(M(mid)))}. Nejnovější model, který se vejde do 10 000 Kč v kvalitě B a lepší.</li>' if mid else ''}
{f'<li>{link_m(M(usbc))} od {kc(usbc["pc"])} – {E(why_model(M(usbc)))}. Nejlevnější iPhone, který se nabíjí stejným kabelem jako notebook.</li>' if usbc else ''}</ul>
<h2>Ceny nejlevnějších iPhonů podle modelu</h2><p>Nejnižší cena z druhé ruky a nejnižší cena nového kusu u modelů, které dostávají aktuální iOS:</p>
<div class="tscroll"><table class="ptable cmp"><thead><tr><th>Model</th><th>Rok</th><th>Z druhé ruky od</th><th>Nový od</th></tr></thead><tbody>{model_rows}</tbody></table></div>
<h2>Proč jsou repasované iPhony tak levné</h2><p>iPhony drží cenu déle než většina telefonů, ale po dvou až třech letech stojí z druhé ruky zlomek původní ceny.
Obchody je vykupují od lidí, kteří přecházejí na novou generaci, otestují je, případně vymění baterii a prodávají se zárukou. Cenu pak určuje hlavně vzhled (kvalita A+ až C)
a paměť, výkon je u stejného modelu stejný. Proto se vyplatí porovnávat: stejný iPhone 13 se 128 GB se dnes mezi obchody a kvalitami liší i o několik tisíc korun.</p>
<h2>Levný iPhone podle rozpočtu</h2><p>Nejnovější model, který dnes seženete v kvalitě B a lepší s aktuálním iOS:</p>
<div class="tscroll"><table class="ptable cmp"><thead><tr><th>Rozpočet</th><th>Nejnovější model</th><th>Cena od</th><th>Modelů</th></tr></thead><tbody>{"".join(brackets)}</tbody></table></div>
{f'<h2>Nejlevnější nový iPhone</h2><p>Úplně nový, nerozbalený iPhone dnes nejlevněji pořídíte jako {link_m(M(cheap_new), "")} za <strong>{kc(cheap_new["pc"])}</strong> ({E(SHOP[cheap_new["shop"]]["name"])}). Všechny nové kusy najdete v přehledu <a href="/novy-iphone/">nové iPhony</a>.</p>' if cheap_new else ''}
<h2>Kde koupit levný iPhone a nenaletět</h2><ul>
<li><strong>Obchod místo bazaru.</strong> Repasovaný iPhone od obchodu má záruku nejméně 12 měsíců a při nákupu přes internet ho můžete do 14 dnů vrátit. Od soukromníka nemáte nic z toho.</li>
<li><strong>Kvalita C není horší telefon.</strong> Popisuje jen vzhled (viditelné škrábance). Pokud telefon nosíte v obalu, ušetříte proti kvalitě A často tisíce korun. <a href="/pruvodce/stavy/">Co znamená A, B, C</a></li>
<li><strong>Hlídejte baterii.</strong> Pod 80&nbsp;% kondice ji Apple považuje za opotřebovanou, výměna stojí kolem tisíce korun. <a href="/pruvodce/baterie/">Jak číst kondici baterie</a></li>
<li><strong>Aktivační zámek.</strong> Telefon musí jít nastavit s vaším Apple účtem, jinak ho vraťte. <a href="/pruvodce/kontrola/">Kontrola po převzetí</a></li>
{f'<li><strong>Slevové kódy.</strong> V cenách výše jsou už započítané:<ul>{codes}</ul></li>' if codes else ''}</ul>"""
    faq = [("Jaký je nejlevnější iPhone?", f'Dnes {E(M(cheapest)["name"])} za {kc(cheapest["pc"])}. Pokud chcete telefon s aktuálním iOS, nejlevnější je {E(M(cheap_ok)["name"])} za {kc(cheap_ok["pc"])}.'),
           ("Kde koupit iPhone nejlevněji?", "Nejlevněji vycházejí repasované kusy z obchodů s kvalitou B nebo C. Srovnáváme "
            + E(", ".join(SHOP[s]["name"] for s in ctx["shop_ids"])) + " a ke každé konfiguraci ukážeme nejlevnější obchod včetně slevových kódů."),
           ("Vyplatí se ještě iPhone 11?", "Ano, pokud chcete co nejlevnější iPhone s podporou: dostává iOS 26 i iOS 27. Nemá ale 5G ani USB-C a baterie bývá u starších kusů opotřebovaná."),
           ("Je levný repasovaný iPhone horší než nový?", "Funkčně ne, obchod ho otestoval a dává na něj záruku. Liší se vzhledem podle kvality (A+ až C) a kondicí baterie.")]
    if cheap_new:
        faq.insert(1, ("Jaký je nejlevnější nový iPhone?", f'{E(M(cheap_new)["name"])} za {kc(cheap_new["pc"])} ({E(SHOP[cheap_new["shop"]]["name"])}).'))
    return lead, tips, sec, faq


def seo_zanovni(ctx, rows):
    ap = offers_of(ctx, lambda m, o: True, ("aplus",))
    rf = offers_of(ctx, lambda m, o: True, ("a", "b", "c"))
    pa, pr = saving_pct(ctx, ap), saving_pct(ctx, rf)
    cheapest = min(ap, key=lambda o: o["pc"])
    newest = max(ap, key=lambda o: (MODEL[o["model"]]["year"], -o["pc"]))
    best_sv = max((o for o in ap if ctx["new_min"].get((o["model"], o["gb"]), 0) > o["pc"]),
                  key=lambda o: (ctx["new_min"][(o["model"], o["gb"])] - o["pc"]), default=None)
    M = lambda o: MODEL[o["model"]]  # noqa: E731
    tips = [(cheapest, "Nejlevnější zánovní iPhone"), (newest, "Nejnovější model jako nový")] + ([(best_sv, "Největší úspora proti novému")] if best_sv else [])
    zr = []
    for m in sorted({o["model"] for o in ap}, key=lambda k: -MODEL[k]["year"]):
        mo = [o for o in ap if o["model"] == m]
        b0 = min(mo, key=lambda o: o["pc"])
        nw = ctx["new_min"].get((m, b0["gb"]))
        pct = f'{round((nw - b0["pc"]) / nw * 100)}\u00a0%' if nw and nw > b0["pc"] else "–"
        zr.append(f'<tr><th scope="row">{link_m(MODEL[m], "")}</th><td class="num">{kc(b0["pc"])} <small class="muted">({P.gb_label(b0["gb"])})</small></td>'
                  f'<td class="num newp">{kc(nw) if nw else "–"}</td><td class="num">{pct}</td></tr>')
    zrows = "".join(zr[:16])
    lead = (f'{nab(len(ap)).capitalize()} zánovních a rozbalených iPhonů ({len({o["model"] for o in ap})} modelů) od <strong>{kc(cheapest["pc"])}</strong>. '
            f'Vypadají jako nové a proti novému kusu ušetříte typicky <strong>{pa} %</strong>.')
    sec = f"""<h2>Co je zánovní a rozbalený iPhone</h2>
<p><strong>Rozbalený</strong> iPhone někdo koupil a v zákonné lhůtě 14 dnů vrátil, takže je prakticky nový. <strong>Zánovní</strong> telefon byl používaný jen krátce
a nemá viditelné stopy. Obchody jim říkají různě (zánovní, rozbalený, premium, jako nový); u nás mají všechny kvalitu <strong>A+</strong>.</p>
<h2>Zánovní, rozbalený, repasovaný, nebo z bazaru?</h2>
<div class="tscroll"><table class="ptable cmp"><thead><tr><th></th><th>Vzhled</th><th>Záruka od obchodu</th><th>Cena proti novému</th></tr></thead><tbody>
<tr><td>Nový</td><td>nerozbalený</td><td>24 měsíců</td><td>plná cena</td></tr>
<tr><td><strong>Zánovní / rozbalený (A+)</strong></td><td>bez stop</td><td>12–24 měsíců</td><td>typicky −{pa}&nbsp;%</td></tr>
<tr><td>Repasovaný (A, B, C)</td><td>drobné až viditelné stopy</td><td>nejméně 12 měsíců</td><td>typicky −{pr}&nbsp;%</td></tr>
<tr><td>Bazar od soukromníka</td><td>podle štěstí</td><td>žádná</td><td>nejnižší, ale bez jistoty</td></tr></tbody></table></div>
<p>Zánovní iPhone je kompromis pro toho, kdo chce telefon, který jako použitý nevypadá, ale nechce platit plnou cenu. Kdo telefon stejně nosí v obalu,
ušetří víc s <a href="/levny-iphone/">levným repasem</a> v kvalitě B nebo C.</p>
<h2>Zánovní iPhony podle modelu</h2><p>Nejlevnější zánovní nebo rozbalený kus u každého modelu a rozdíl proti nejlevnějšímu novému se stejnou pamětí:</p>
<div class="tscroll"><table class="ptable cmp"><thead><tr><th>Model</th><th>Zánovní od</th><th>Nový od</th><th>Ušetříte</th></tr></thead><tbody>{zrows}</tbody></table></div>
<h2>Jak vybrat zánovní iPhone</h2><ul>
<li><strong>Paměť:</strong> 128 GB stačí většině lidí, kdo hodně fotí a natáčí, ať sáhne po 256 GB. Příplatek za větší paměť je u zánovních kusů často menší než u nových.</li>
<li><strong>Velikost:</strong> modely mini a SE se vejdou do jedné ruky, Plus a Pro Max mají displej 6,7″ a víc. <a href="/maly-iphone/">Malé iPhony</a></li>
<li><strong>Generace:</strong> USB-C mají modely od iPhonu 15, Apple Intelligence iPhone 15 Pro a novější. Aktuální iOS dostávají všechny od iPhonu 11.</li></ul>
<h2>Na co si dát pozor u zánovního iPhonu</h2><ul>
<li><strong>Záruka:</strong> u rozbaleného kusu bývá plných 24 měsíců, u zánovního ji obchod smí zkrátit na 12. <a href="/pruvodce/zaruka/">Záruka a vrácení</a></li>
<li><strong>Baterie:</strong> zánovní kusy mívají kondici nad 95&nbsp;%, i tak se na ni zeptejte. <a href="/pruvodce/baterie/">Kondice baterie</a></li>
<li><strong>Původ:</strong> verze „jen eSIM“ jsou telefony z USA bez slotu na SIM kartu; v konfigurátoru je označujeme.</li>
<li><strong>Díly a historie servisu:</strong> v Nastavení → Obecné → Informace ověříte, že nic nebylo měněné. <a href="/pruvodce/kontrola/">Kontrola po převzetí</a></li></ul>"""
    faq = [("Co znamená zánovní iPhone?", "Telefon používaný jen krátce, bez viditelných stop. Je to nejlepší stav, ve kterém se prodávají použité iPhony; u nás kvalita A+."),
           ("Je rozbalený iPhone nový?", "Prakticky ano: někdo ho koupil a do 14 dnů vrátil. Prodává se jako rozbalený, protože už neprošel jako nový kus."),
           ("Jakou záruku má zánovní iPhone?", "Od obchodu 24 měsíců, u použitého zboží ji obchod smí dohodou zkrátit na 12 měsíců. Rozbalené kusy mívají plnou záruku."),
           ("Kolik ušetřím za zánovní iPhone?", f"Proti nejlevnějšímu novému kusu se stejnou pamětí typicky {pa} %. Nejlevnější zánovní iPhone dnes stojí {kc(cheapest['pc'])} ({E(M(cheapest)['name'])}).")]
    return lead, tips, sec, faq


def seo_novy(ctx, rows):
    news = offers_of(ctx, lambda m, o: True, ("novy",))
    cheapest = min(news, key=lambda o: o["pc"])
    M = lambda o: MODEL[o["model"]]  # noqa: E731
    lineup = [m for m in MODELS if m["year"] >= 2025]
    top_year = max(m["year"] for m in lineup)
    newest = [m for m in lineup if m["year"] == top_year]
    cur = [o for o in news if M(o)["year"] >= 2025]
    cheap_cur = min(cur, key=lambda o: o["pc"]) if cur else None
    pro = min((o for o in cur if "Pro" in M(o)["name"]), key=lambda o: (-M(o)["year"], o["pc"]), default=None)
    tips = [(cheapest, "Nejlevnější nový iPhone"), (cheap_cur, "Nejlevnější z aktuální řady"), (pro, "Nejnovější Pro za nejnižší cenu")]
    tips = [(o, r) for o, r in tips if o]
    lead = (f'Nové, nerozbalené iPhony s plnou zárukou z {obchodu(len({o["shop"] for o in news}))}. Nejlevnější nový iPhone je dnes '
            f'<strong>{E(M(cheapest)["name"])} za {kc(cheapest["pc"])}</strong>.')
    trs = []
    for m in lineup:
        nw = [o["pc"] for o in news if o["model"] == m["slug"]]
        rf = [o["pc"] for o in ctx["by_model"].get(m["slug"], []) if o["g"] != "novy"]
        trs.append(f'<tr><th scope="row">{link_m(m, "")}</th><td>{m["year"]}</td><td>{E(m["chip"])}</td><td>{str(m["display"]).replace(".", ",")}″</td>'
                   f'<td class="num">{kc(min(nw)) if nw else "–"}</td><td class="num">{kc(min(rf)) if rf else "–"}</td></tr>')
    pairs = []
    for m in lineup + [x for x in MODELS if x["year"] in (2023, 2024)]:
        nw = [o for o in news if o["model"] == m["slug"]]
        rf = [o for o in ctx["by_model"].get(m["slug"], []) if o["g"] in ("aplus", "a")]
        if nw and rf:
            n0, r0 = min(nw, key=lambda o: o["pc"]), min(rf, key=lambda o: o["pc"])
            if n0["pc"] > r0["pc"]:
                pairs.append(f'<li>{link_m(m, "")}: nový od {kc(n0["pc"])}, v kvalitě {GR[r0["g"]]["short"]} od {kc(r0["pc"])} – o {kc(n0["pc"] - r0["pc"])} méně.</li>')
    shops_new = sorted({SHOP[o["shop"]]["name"] for o in news})
    sec = f"""<h2>Jaký je nejnovější iPhone</h2>
<p>Nejnovější jsou {" a ".join(E(m["name"]) for m in newest)} ({top_year}){" s čipem " + E(newest[0]["chip"]) if len({m["chip"] for m in newest}) == 1 else ""}.
Dál se prodává řada uvedená v roce 2025 (iPhone 17, iPhone Air, 17 Pro a 17 Pro Max) a levnější iPhone 17e. Všechny dostávají aktuální iOS a podporují Apple Intelligence.</p>
<h2>Aktuální iPhony a jejich ceny</h2>
<div class="tscroll"><table class="ptable cmp"><thead><tr><th>Model</th><th>Rok</th><th>Čip</th><th>Displej</th><th>Nový od</th><th>Z druhé ruky od</th></tr></thead><tbody>{"".join(trs)}</tbody></table></div>
<h2>Který nový iPhone vybrat</h2><ul>
<li><strong>Nejlevnější vstup:</strong> iPhone 17e a 16e – základní fotoaparát, displej 6,1″, plná podpora systému i Apple Intelligence.</li>
<li><strong>Zlatá střední cesta:</strong> iPhone 17 – 120Hz displej 6,3″ a dva fotoaparáty, za výrazně méně než řada Pro.</li>
<li><strong>Nejtenčí:</strong> iPhone Air – displej 6,5″, jen eSIM, jeden zadní fotoaparát.</li>
<li><strong>Nejlepší fotoaparáty:</strong> řada Pro a Pro Max s teleobjektivem; největší displej 6,9″ mají modely Pro Max.</li></ul>
<h2>Který nový iPhone vybrat</h2><ul>
<li><strong>Nejlevnější vstup:</strong> iPhone 17e a 16e – základní fotoaparát, displej 6,1″, plná podpora systému i Apple Intelligence.</li>
<li><strong>Zlatá střední cesta:</strong> iPhone 17 – 120Hz displej 6,3″ a dva fotoaparáty, za výrazně méně než řada Pro.</li>
<li><strong>Nejtenčí:</strong> iPhone Air – displej 6,5″, jen eSIM, jeden zadní fotoaparát.</li>
<li><strong>Nejlepší fotoaparáty:</strong> řada Pro a Pro Max s teleobjektivem; největší displej 6,9″ mají modely Pro Max.</li></ul>
<h2>Nový, nebo repasovaný?</h2><p>Nový iPhone má 24 měsíců záruky a baterii se 100&nbsp;% kondicí. Zánovní nebo repasovaný kus v kvalitě A+ či A vypadá skoro stejně a stojí méně:</p>
<ul>{"".join(pairs[:6])}</ul>
<p>Úplný přehled telefonů bez stop najdete v sekci <a href="/zanovni-iphone/">zánovní a rozbalené iPhony</a>.</p>
<h2>Kde koupit nový iPhone nejlevněji</h2><p>Nové kusy srovnáváme z obchodů {E(", ".join(shops_new))}. iSTYLE je autorizovaný prodejce Applu (Apple Premium Partner).
Ceny se mezi obchody liší i o tisíce korun, proto u každého modelu ukazujeme nejlevnější obchod{" včetně slevových kódů, které platí i na nové kusy" if any(o["pc"] < o["p"] for o in news) else ""}.</p>"""
    faq = [("Jaký je nejnovější iPhone?", f'{" a ".join(E(m["name"]) for m in newest)}, uvedené v roce {top_year}.'),
           ("Kolik stojí nový iPhone?", f'Nejlevnější nový iPhone ({E(M(cheapest)["name"])}) dnes stojí {kc(cheapest["pc"])}'
            + (f', nejlevnější z aktuální řady ({E(M(cheap_cur)["name"])}) {kc(cheap_cur["pc"])}.' if cheap_cur else ".")),
           ("Jakou záruku má nový iPhone?", "Od obchodníka 24 měsíců. Při nákupu přes internet navíc 14 dní na vrácení bez udání důvodu."),
           ("Vyplatí se místo nového koupit zánovní iPhone?", "Pokud vám nevadí kratší záruka (12–24 měsíců), ušetříte za telefon, který vypadá jako nový. Rozdíly u konkrétních modelů jsou v seznamu výše.")]
    return lead, tips, sec, faq


CAT_SEO = {"/levny-iphone/": ("price", seo_levny), "/zanovni-iphone/": ("fam", seo_zanovni), "/novy-iphone/": ("cur", seo_novy)}
CAT_META = {
    "/levny-iphone/": ("Levný iPhone – nejlevnější iPhony dnes od {low}",
                       "Nejlevnější iPhony dnes od {low}: repasované, zánovní i nové, ceny včetně slevových kódů. Který levný iPhone se vyplatí a kde koupit iPhone levně."),
    "/zanovni-iphone/": ("Zánovní iPhone a rozbalené iPhony od {low}",
                         "Zánovní a rozbalené iPhony bez stop od {low}. Kolik ušetříte proti novému, jakou mají záruku a na co si dát pozor. Ceny každý den."),
    "/novy-iphone/": ("Nový iPhone nejlevněji – ceny aktuálních iPhonů",
                      "Nový iPhone nejlevněji: ceny iPhonu 18 Pro, 17, Air, 17e i starších modelů z více obchodů. Nový, nebo zánovní? Srovnání cen každý den."),
}


def page_cats(out, ctx):
    for c in CATS:
        rows, extra = cat_content(ctx, c)
        if not rows:
            continue
        low = min(r[1]["pc"] for r in rows)
        kind, seo = CAT_SEO.get(c["path"], ("price", None))
        lead, tips, sec, faq = (seo(ctx, rows) if seo else (E(c["lead"]), [], CAT_TEXT.get(c["path"], ""), []))
        tm = CAT_META.get(c["path"])
        title = short_title((tm[0] if tm else c["title"]).format(low=kc_plain(low), shops=len(ctx["shop_ids"]), n=len(rows)))
        desc = (tm[1].format(low=kc_plain(low)) if tm else f'{c["lead"]} Ceny z {date_cz(TODAY)}.').replace(" ", " ")
        cnt = {}
        for m, o, n in rows:
            cnt[m["slug"]] = n
        tip_html = "".join(cat_card(ctx, MODEL[o["model"]], o, len([x for x in ctx["by_model"][o["model"]] if x["g"] == o["g"]]), E(r)) for o, r in tips)
        grid = "".join(cat_card(ctx, m, o, n) for m, o, n in rows)
        body = f"""<div class="wrap"><header class="mhead"><p class="eyebrow">Ceny z {date_cz(TODAY)} · {len(rows)} {plural(len(rows), "model", "modely", "modelů")}</p>
<h1>{E(c["h1"])}</h1><p class="lead">{lead}</p></header>
{f'<section class="sec ctips"><h2 class="sr">Naše tipy</h2><ul class="cgrid tipgrid">{tip_html}</ul></section>' if tip_html else ''}
<section class="sec"><h2>{"Všechny modely od nejnižší ceny" if kind == "price" else "Všechny modely"}</h2>{cat_filters(kind)}<ul class="cgrid" data-cgrid>{grid}</ul>{extra}</section>
<section class="sec prose catseo">{sec}</section>
{f'<section class="sec"><h2>Časté otázky</h2>{faq_html(faq)}</section>' if faq else ''}</div>"""
        ld = [{"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "url": f'{SITE}/{m["slug"]}/', "name": m["name"]} for i, (m, o, n) in enumerate(rows[:30])]}]
        if faq:
            ld.append(faq_ld(faq))
        out.page(c["path"], layout(ctx, path=c["path"], title=title, desc=desc, body=body, ld=ld, active=c["path"],
                                   crumbs=[("/", "Repasované iPhony"), (c["path"], c["short"])]))


def page_compare(out, ctx):
    rows = []
    for m in MODELS:
        of = ctx["by_model"].get(m["slug"])
        if not of:
            continue
        rf = [o for o in of if o["g"] != "novy"] or of
        rows.append(f'<tr><th scope="row"><a href="/{m["slug"]}/">{E(m["name"])}</a></th><td>{m["year"]}</td><td>{str(m["display"]).replace(".", ",")}″</td>'
                    f'<td>{E(m["chip"])}</td><td>{m["port"]}</td><td>{"ano" if ios_ok(m) else "ne"}</td><td>{"ano" if m.get("ai") else "ne"}</td>'
                    f'<td class="num">{kc(min(o["pc"] for o in rf))}</td></tr>')
    body = f"""<div class="wrap"><header class="mhead"><h1>Srovnání iPhonů z druhé ruky</h1>
<p class="lead">Všechny modely, které se dnes dají koupit, v jedné tabulce: rok, displej, čip, konektor, podpora aktuálního iOS a nejnižší cena.</p></header>
<div class="card"><div class="tscroll"><table class="ptable cmp"><thead><tr><th>Model</th><th>Rok</th><th>Displej</th><th>Čip</th><th>Konektor</th><th>iOS 26/27</th>
<th>Apple Intelligence</th><th>Cena od</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></div>
<section class="sec prose"><h2>Jak tabulku číst</h2><p><strong>iOS 26/27</strong>: Apple aktuální systém vydává pro iPhone 11 a novější a pro SE 2. generace. Starší modely fungují dál,
ale nové funkce a časem i některé aplikace jim chybí. <strong>Apple Intelligence</strong> mají iPhony 15 Pro, celá řada 16 a novější. <strong>USB-C</strong> mají modely od iPhonu 15.</p>
<p>Nevíte, který vybrat? <a href="/jaky-iphone-koupit/">Doporučení podle rozpočtu</a></p></section></div>"""
    out.page("/srovnani/", layout(ctx, path="/srovnani/", title="Srovnání iPhonů – parametry a ceny z druhé ruky",
                                  desc="Všechny iPhony z druhé ruky v jedné tabulce: rok, displej, čip, konektor, podpora iOS 26 a 27 a nejnižší cena.",
                                  body=body, crumbs=[("/", "Repasované iPhony"), ("/srovnani/", "Srovnání")], active="/srovnani/"))


def page_buy(out, ctx):
    tiers = [(0, 6000, "do 6 000 Kč"), (6000, 10000, "6 000 až 10 000 Kč"), (10000, 15000, "10 000 až 15 000 Kč"),
             (15000, 22000, "15 000 až 22 000 Kč"), (22000, 10 ** 9, "nad 22 000 Kč")]
    sec = []
    for lo, hi, lab in tiers:
        rows = best_per_model(ctx, lambda m, o, lo=lo, hi=hi: lo <= o["pc"] < hi and ios_ok(m), grades=("aplus", "a", "b"))
        rows.sort(key=lambda r: (-r[0]["year"], -("Pro" in r[0]["name"]), r[1]["pc"]))
        if rows:
            top = rows[0][0]
            sec.append(f'<h2>Rozpočet {lab}</h2><p>Nejnovější model, který se vejde v dobré kvalitě: <strong>{E(top["name"])}</strong> ({top["year"]}, čip {E(top["chip"])}).</p>'
                       + cat_rows(ctx, rows, 5))
    body = f"""<div class="wrap"><header class="mhead"><p class="eyebrow">Podle cen z {date_cz(TODAY)}</p><h1>Jaký iPhone koupit? Doporučení podle rozpočtu</h1>
<p class="lead">Pro každý rozpočet nejnovější modely, které se do něj dnes vejdou v kvalitě B a lepší a dostávají aktuální iOS. Přepočítává se každou noc.</p></header>
<div class="buyguide">{"".join(sec)}</div></div>"""
    out.page("/jaky-iphone-koupit/", layout(ctx, path="/jaky-iphone-koupit/", title=f"Jaký iPhone koupit v roce {TODAY.year} – podle rozpočtu",
                                            desc="Který iPhone koupit za 6, 10, 15 nebo 22 tisíc? Doporučení podle dnešních cen, podpory iOS a kvality.",
                                            body=body, crumbs=[("/", "Repasované iPhony"), ("/jaky-iphone-koupit/", "Jaký iPhone koupit")]))


def page_shops(out, ctx):
    li = "".join(f'<li><a class="shopc" href="/obchody/{s}/">{shop_logo(s, 30)}<span>{nab(ctx["shop_count"][s])}'
                 f'{" · slevový kód" if ctx["coupons"].get(s) else ""}</span></a></li>' for s in ctx["shop_ids"])
    body = f'<div class="wrap"><header class="mhead"><h1>Obchody ve srovnání</h1><p class="lead">Odkud bereme nabídky, kolik jich má který obchod a jaké slevové kódy platí.</p></header><ul class="shopgrid">{li}</ul></div>'
    out.page("/obchody/", layout(ctx, path="/obchody/", title="Obchody s repasovanými iPhony ve srovnání", desc="Přehled obchodů s repasovanými, zánovními a novými iPhony a jejich slevové kódy.",
                                 body=body, crumbs=[("/", "Repasované iPhony"), ("/obchody/", "Obchody")]))
    for s in ctx["shop_ids"]:
        sh, of = SHOP[s], [o for o in ctx["offers"] if o["shop"] == s]
        info = SHOP_INFO.get(s, {})
        gc = Counter(o["g"] for o in of)
        dist = "".join(f'<li>{grade_chip(g)} {E(GR[g]["name"])} <b>{num(gc[g])}</b></li>' for g, *_r in P.GRADES if gc.get(g))
        rows = sorted(best_per_model(ctx, lambda m, o, s=s: o["shop"] == s, grades=tuple(GR)), key=lambda r: (-r[0]["year"], r[1]["pc"]))
        cbox = "".join(coupon_box(c, f"/go/{s}/?u=/") for c in ctx["coupons"].get(s, []))
        body = f"""<div class="wrap"><header class="mhead shophead">{shop_logo(s, 40)}<h1>{E(sh["name"])}: iPhony a ceny</h1><p class="lead">{info.get("lead", "")}</p>{cbox}</header>
<section class="sec two"><div class="prose">{info.get("text", "")}<h2>Nabídka podle kvality</h2><ul class="gdist">{dist}</ul></div>
<aside class="card"><dl class="specs"><dt>Nabídek</dt><dd>{num(len(of))}</dd><dt>Cena od</dt><dd>{kc(min(o["pc"] for o in of))}</dd><dt>Web</dt><dd>{E(sh["domain"])}</dd></dl></aside></section>
<section class="sec"><h2>Nejlevnější kus každého modelu</h2>{cat_rows(ctx, rows, 30)}</section></div>"""
        out.page(f"/obchody/{s}/", layout(ctx, path=f"/obchody/{s}/", title=f"{sh['name']} – iPhony, ceny a slevové kódy",
                                          desc=f"iPhony z {sh['name']}: {nab(len(of))} od {kc(min(o['pc'] for o in of))}, kvalita na jedné stupnici a platné slevové kódy.".replace(" ", " "),
                                          body=body, crumbs=[("/", "Repasované iPhony"), ("/obchody/", "Obchody"), (f"/obchody/{s}/", sh["name"])], index=len(of) >= 5),
                 index=len(of) >= 5)


def load_guides():
    gs = []
    for f in sorted((APP / "content/guides").glob("*.html")):
        txt = f.read_text()
        m = re.match(r"<!--(.*?)-->\s*", txt, re.S)
        meta = json.loads(m.group(1))
        meta["html"], meta["slug"] = txt[m.end():], f.stem
        gs.append(meta)
    return sorted(gs, key=lambda g: g.get("order", 99))


def grade_table(ctx):
    """The only place where the shops' own wording appears: the converter in /pruvodce/stavy/."""
    seen = defaultdict(lambda: defaultdict(Counter))
    for o in ctx["offers"]:
        if o["sg"] and o["g"] != "novy":
            seen[o["g"]][SHOP[o["shop"]]["name"]][o["sg"]] += 1
    rows = []
    for k in REFURB_G:
        shops = "<br>".join(f"{E(s)}: " + ", ".join(f"„{E(w)}“" for w, _ in ws.most_common()) for s, ws in sorted(seen[k].items())) or "–"
        rows.append(f'<tr><td>{grade_chip(k)} <strong>{E(GR[k]["name"])}</strong><br><small>{E(GR[k]["ex"])}</small></td><td>{shops}</td></tr>')
    return f'<table><thead><tr><th>Kvalita u nás</th><th>Jak ji píšou obchody</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'


def page_guides(out, ctx):
    li = "".join(f'<li><a href="/pruvodce/{g["slug"]}/"><img src="/img/ui/ic-{g.get("icon", "search")}.webp" alt="" width="56" height="56" loading="lazy">'
                 f'<b>{E(g["h1"])}</b><span>{E(g["desc"])}</span></a></li>' for g in ctx["guides"])
    out.page("/pruvodce/", layout(ctx, path="/pruvodce/", title="Průvodce nákupem iPhonu z druhé ruky",
                                  desc="Kvalita A, B, C, baterie, záruka a kontrola po převzetí: co vědět před nákupem repasovaného iPhonu.",
                                  body=f'<div class="wrap"><header class="mhead"><h1>Průvodce nákupem</h1><p class="lead">Krátce a k věci: co znamená kvalita, jak číst baterii a jaká máte práva.</p></header><ul class="glist">{li}</ul></div>',
                                  crumbs=[("/", "Repasované iPhony"), ("/pruvodce/", "Průvodce")], active="/pruvodce/"))
    for g in ctx["guides"]:
        path = f'/pruvodce/{g["slug"]}/'
        html_ = g["html"].replace("{{GRADE_TABLE}}", grade_table(ctx))
        others = "".join(f'<li><a href="/pruvodce/{x["slug"]}/">{E(x["short"])}</a></li>' for x in ctx["guides"] if x is not g)
        body = f'<div class="wrap"><article class="prose art"><h1>{E(g["h1"])}</h1>{html_}</article><section class="sec"><h2>Další průvodci</h2><ul class="chips">{others}</ul></section></div>'
        ld = [{"@context": "https://schema.org", "@type": "Article", "headline": g["h1"], "description": g["desc"], "inLanguage": "cs",
               "datePublished": "2026-11-25", "dateModified": g.get("updated", TODAY.isoformat()),
               "author": {"@type": "Organization", "name": BRAND, "url": SITE + "/o-webu/"},
               "publisher": {"@type": "Organization", "name": BRAND, "logo": {"@type": "ImageObject", "url": SITE + "/favicon-512.png"}}}]
        out.page(path, layout(ctx, path=path, title=short_title(g["title"]), desc=g["desc"], body=body, ld=ld, active="/pruvodce/",
                              crumbs=[("/", "Repasované iPhony"), ("/pruvodce/", "Průvodce"), (path, g["short"])]))


def page_about(out, ctx):
    shops = ", ".join(SHOP[s]["name"] for s in ctx["shop_ids"])
    body = f"""<div class="wrap"><article class="prose art"><h1>O webu</h1>
<p>Repasovanyiphone.cz je nezávislé srovnání repasovaných, zánovních, bazarových i nových iPhonů. Každou noc stáhneme produktové exporty obchodů ({E(shops)}),
z názvu a parametrů rozpoznáme model, paměť, oficiální barvu, kvalitu a baterii a ke každé konfiguraci najdeme nejlevnější obchod.</p>
<h2>Slevové kódy</h2><p>Platné kódy bereme z affiliate sítě eHub. Když kód jde jednoznačně uplatnit (pevná sleva, splněný minimální nákup), započítáme ho do ceny a podle ní řadíme.
Kódy s podmínkami, které neumíme ověřit, jen zobrazíme. Kód zadáte v košíku obchodu, rozhoduje vždy obchod.</p>
<h2>Jak vyděláváme</h2><p>Když přes odkaz nakoupíte, obchod nám může zaplatit provizi přes affiliate síť (eHub, CJ). Cenu pro vás to nemění a pořadí neovlivňuje: řadíme jen podle ceny.</p>
<h2>Jedna stupnice kvality</h2><p>Obchody používají vlastní označení stavu. Převádíme je na Nový, A+, A, B a C a na webu ukazujeme jen tuhle stupnici. Nabídky, jejichž stav neumíme
spolehlivě zařadit, do srovnání nebereme. <a href="/pruvodce/stavy/">Převodník stavů</a></p>
<h2>Co nezaručujeme</h2><p>Ceny a dostupnost se během dne mění. Platí vždy údaj v obchodě, nákup i reklamaci řešíte přímo s ním.</p>
<h2>Kontakt</h2><p>Chyba v nabídce, nový obchod nebo spolupráce: <a href="mailto:info@repasovanyiphone.cz">info@repasovanyiphone.cz</a></p></article></div>"""
    out.page("/o-webu/", layout(ctx, path="/o-webu/", title="O webu – jak srovnáváme iPhony a jak vyděláváme", desc="Odkud jsou data, jak převádíme kvalitu, jak počítáme slevové kódy a jak web vydělává.",
                                body=body, crumbs=[("/", "Repasované iPhony"), ("/o-webu/", "O webu")]))


OPERATOR = {"name": "Ha Duy Huy", "address": "Bartáková 36, 140 00 Praha", "ico": "07876823", "vat": "není plátce DPH",
            "email": "info@repasovanyiphone.cz"}   # public business-register data (ARES), same operator as the other portfolio sites


def page_privacy(out, ctx):
    o = OPERATOR
    body = f"""<div class="wrap"><article class="prose art"><h1>Ochrana osobních údajů a cookies</h1>
<h2>Správce údajů</h2><p>{o["name"]}, {o["address"]}, IČO {o["ico"]}, {o["vat"]}. Kontakt: <a href="mailto:{o["email"]}">{o["email"]}</a>.
Dozorovým úřadem je Úřad pro ochranu osobních údajů (uoou.cz), u kterého můžete podat stížnost.</p>
<p>Repasovanyiphone.cz nemá registraci, účty ani formuláře a neukládá o vás žádné osobní údaje. Nic neprodáváme, objednávky vyřizují obchody, na které odkazujeme.</p>
<h2>Měření návštěvnosti</h2><p>Používáme Google Tag Manager a Google Analytics (Google Ireland Ltd.) v režimu souhlasu (Google Consent Mode). Dokud v liště nedáte souhlas,
neukládají se žádné analytické cookies ani identifikátory a do Googlu jde jen anonymní signál bez cookies. Po souhlasu měříme, které stránky lidé čtou, na které obchody klikají
a které slevové kódy kopírují, abychom web zlepšovali. Souhlas můžete kdykoli změnit odkazem „Nastavení cookies“ v patičce. Reklamní cookies nepoužíváme.</p>
<h2>Odkazy do obchodů</h2><p>Odkazy do e-shopů vedou přes affiliate sítě eHub a CJ, které si mohou uložit cookie, aby obchod poznal, že jste přišli od nás. Řídí se zásadami těchto sítí a obchodu.</p>
<h2>Slevové kódy</h2><p>Tlačítko „Kopírovat“ jen vloží kód do schránky vašeho zařízení. Kód nikam neodesíláme.</p></article></div>"""
    out.page("/ochrana-osobnich-udaju/", layout(ctx, path="/ochrana-osobnich-udaju/", title="Ochrana osobních údajů a cookies | Repasovaný iPhone",
                                                desc="Kdo provozuje repasovanyiphone.cz, jak měříme návštěvnost se souhlasem a jak fungují odkazy do obchodů a slevové kódy.",
                                                body=body, crumbs=[("/", "Repasované iPhony"), ("/ochrana-osobnich-udaju/", "Ochrana osobních údajů")]))


def page_404(out, ctx):
    pop = "".join(f'<li><a href="/{m["slug"]}/">{E(m["name"])}</a></li>' for m in MODELS if len(ctx["by_model"].get(m["slug"], [])) >= 20)
    body = f'<div class="wrap"><header class="mhead"><h1>Tahle stránka neexistuje</h1><p class="lead">Telefony se rychle prodávají a nabídka mohla zmizet. Zkuste model:</p><ul class="chips">{pop}</ul></header></div>'
    out.write("404.html", layout(ctx, path="/404/", title="Stránka nenalezena | " + BRAND, desc="Stránka nenalezena.", body=body, index=False))


# ---------------------------------------------------------------- main

def history(refurb):
    hp = STATE / "history.json"
    h = json.loads(hp.read_text()) if hp.exists() else {}
    day = {}
    for o in refurb:
        for k in (o["model"], f'{o["model"]}|{o["gb"]}'):
            day[k] = min(day.get(k, 10 ** 9), o["pc"])
    h[TODAY.isoformat()] = day
    h = dict(sorted(h.items())[-400:])
    hp.write_text(json.dumps(h, separators=(",", ":")))
    per = defaultdict(list)
    for d, v in h.items():
        dd = dt.date.fromisoformat(d)
        for k, p in v.items():
            per[k].append((f"{dd.day}. {dd.month}.", p))
    return per


def redirects(out, current):
    """301 for every path that existed in an earlier build and is gone now (Workers static assets read dist/_redirects)."""
    kp = STATE / "known-paths.json"
    known = set(json.loads(kp.read_text())) if kp.exists() else set()
    known |= set(out.old)
    lines = []
    for p in sorted(known - current):
        m = re.match(r"^/(iphone-[a-z0-9-]+)/\d+-gb/$", p)
        if m and f"/{m.group(1)}/" in current:
            to = f"/{m.group(1)}/"
        elif p.startswith("/obchody/"):
            to = "/obchody/"
        elif p.startswith("/pruvodce/"):
            to = "/pruvodce/"
        else:
            to = "/"
        lines.append(f"{p} {to} 301")
    kp.write_text(json.dumps(sorted(known | current)))
    out.write("_redirects", "\n".join(lines[:1900]) + "\n")
    return len(lines)


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    offers, stats, report = P.load_all(APP / "data/raw", SHOPS)
    seen, uniq = set(), []
    for o in offers:
        if (o["shop"], o["id"]) not in seen:
            seen.add((o["shop"], o["id"]))
            uniq.append(o)
    offers = uniq
    coupons = load_coupons()
    for o in offers:
        o["pc"], o["cp"] = apply_coupon(o, coupons)
    refurb = [o for o in offers if o["g"] != "novy"]
    new_min = {}
    for o in offers:
        if o["g"] == "novy":
            k = (o["model"], o["gb"])
            new_min[k] = min(new_min.get(k, 10 ** 9), o["p"])
    for k, v in list(new_min.items()):     # a "new" price below the median refurbished one, or double it, is a bad reference
        rs = sorted(o["p"] for o in refurb if (o["model"], o["gb"]) == k)
        if rs and (v < rs[len(rs) // 2] or v > 2 * rs[len(rs) // 2]):
            del new_min[k]
    if len(refurb) < 300:
        sys.exit(f"only {len(refurb)} refurbished offers - refusing to build a near-empty site")
    go_tpl, go_stats = golinks.local_go([{"offers": offers}])
    by_model = defaultdict(list)
    for o in offers:
        by_model[o["model"]].append(o)
    sub_pages = {(m, gb) for m, of in by_model.items() for gb, n in Counter(o["gb"] for o in of if o["g"] != "novy").items() if n >= 3}
    deals, seen_m = [], set()
    for o in sorted((o for o in refurb if o["g"] in ("aplus", "a", "b") and new_min.get((o["model"], o["gb"]), 0) > o["pc"] and ios_ok(MODEL[o["model"]])),
                    key=lambda o: -(new_min[(o["model"], o["gb"])] - o["pc"]) / new_min[(o["model"], o["gb"])]):
        if o["model"] not in seen_m:
            seen_m.add(o["model"])
            deals.append(o)
    sm_p = STATE / "seen-models.json"
    seen_models = json.loads(sm_p.read_text()) if sm_p.exists() else {}
    for m in by_model:
        seen_models[m] = TODAY.isoformat()
    sm_p.write_text(json.dumps(seen_models))

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    for p in (APP / "static").iterdir():
        if p.name != "assets":
            (shutil.copytree if p.is_dir() else shutil.copy)(p, DIST / p.name)
    photo_dir = STATE / "photos"
    pidx = json.loads((photo_dir / "index.json").read_text()) if (photo_dir / "index.json").exists() else {}
    (DIST / "img/p").mkdir(parents=True, exist_ok=True)
    have = set()
    for key in pidx:
        m, c = key.split("|")
        for px in (600, 300):
            f = photo_dir / f"{m}--{c}-{px}.webp"
            if f.exists():
                shutil.copy(f, DIST / "img/p" / f.name)
                have.add((m, c))
    col_rank = {m: [c for c, _ in Counter(o["col"] for o in of).most_common()] for m, of in by_model.items()}
    shop_count = Counter(o["shop"] for o in offers)
    ctx = {"offers": offers, "refurb": refurb, "new_min": new_min, "by_model": by_model, "sub_pages": sub_pages, "shop_count": shop_count,
           "shop_ids": [s["id"] for s in SHOPS if shop_count.get(s["id"])], "guides": load_guides(), "hist": history(refurb),
           "photos": have, "col_rank": col_rank, "deals": deals, "cats": CATS, "coupons": coupons}
    ctx["css"] = asset("site.css", DIST)
    ctx["js"] = asset("app.js", DIST)
    out = Out(DIST)
    page_home(out, ctx)
    for m in MODELS:
        of = by_model.get(m["slug"])
        if not of:
            if m["slug"] in seen_models:
                page_model_gone(out, ctx, m, seen_models[m["slug"]])
            continue
        page_model(out, ctx, m, of)
        for gb in sorted({o["gb"] for o in of}):
            if (m["slug"], gb) in sub_pages:
                page_model(out, ctx, m, of, gb)
    page_cats(out, ctx)
    page_compare(out, ctx)
    page_buy(out, ctx)
    page_shops(out, ctx)
    page_guides(out, ctx)
    page_about(out, ctx)
    page_privacy(out, ctx)
    page_404(out, ctx)
    golinks.write_go(out, go_tpl, SHOP)
    n_redir = redirects(out, {p for p, _ in out.pages})

    idx = [p for p, i in out.pages if i]
    sm = []
    for p in idx:
        imgs = "".join(f"<image:image><image:loc>{E(u)}</image:loc><image:title>{E(t)}</image:title></image:image>" for u, t in out.images.get(p, [])[:8])
        sm.append(f"<url><loc>{SITE}{p}</loc><lastmod>{out.lastmod.get(p, TODAY.isoformat())}</lastmod>{imgs}</url>")
    out.write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
                             f'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">{"".join(sm)}</urlset>')
    out.write("robots.txt", "User-agent: *\nDisallow: /\n" if STAGING else f"User-agent: *\nDisallow: /go/\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n")
    key = os.environ.get("INDEXNOW_KEY", "")
    if key:
        out.write(f"{key}.txt", key)
    ga = bool(GA4_ID)
    out.write("_headers", f"""/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=(), interest-cohort=()
  X-Frame-Options: DENY
  Strict-Transport-Security: max-age=31536000; includeSubDomains
  Content-Security-Policy: default-src 'self'; img-src 'self' data:{' https://*.google-analytics.com https://*.googletagmanager.com https://*.g.doubleclick.net https://www.google.com https://www.google.cz' if ga else ''}; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'{' https://www.googletagmanager.com https://*.googletagmanager.com' if ga else ''}; connect-src 'self'{' https://*.google-analytics.com https://*.analytics.google.com https://*.googletagmanager.com https://*.g.doubleclick.net' if ga else ''}; frame-src{' https://www.googletagmanager.com' if ga else " 'none'"}; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'
/assets/*
  Cache-Control: public, max-age=31536000, immutable
/fonts/*
  Cache-Control: public, max-age=31536000, immutable
/img/*
  Cache-Control: public, max-age=604800, stale-while-revalidate=86400
/go/*
  X-Robots-Tag: noindex, nofollow
""")
    (STATE / "page-hashes.json").write_text(json.dumps(out.new))
    (STATE / "lastmod.json").write_text(json.dumps({p: d for p, d in out.lastmod.items() if p in out.new}))
    (STATE / "changed.txt").write_text("\n".join(out.changed))
    no_photo = sorted({f'{o["model"]}|{o["col"]}' for o in offers if (o["model"], o["col"]) not in have})
    rep = {"date": TODAY.isoformat(), "shops": stats, "skipped": report, "refurb": len(refurb), "offers": len(offers), "new_ref": len(new_min),
           "models": len(by_model), "pages": len(out.pages), "indexable": len(idx), "changed": len(out.changed), "go": go_stats,
           "coupons": {s: [c["code"] for c in cl] for s, cl in coupons.items()}, "with_code": sum(1 for o in offers if o["cp"]),
           "photos": len(have), "no_photo": no_photo, "redirects": n_redir}
    (STATE / "build-report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    print(json.dumps({k: rep[k] for k in ("refurb", "offers", "models", "pages", "indexable", "coupons", "with_code", "photos", "no_photo", "redirects")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
