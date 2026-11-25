#!/usr/bin/env python3
"""Build repasovanyiphone.cz (v2, 25. 11. 2026) into dist/ - plain static HTML + one small JS configurator, no Worker code.

    python3 scripts/build.py

The visitor picks model -> colour -> storage -> quality (Nový, A+, A, B, C) and gets the cheapest shop plus the other shops.
Pages: / , /<model>/ (configurator), /<model>/<gb>-gb/ , category landings (what people search: levný, nový, zánovní, malý,
do 5 000 / 10 000 Kč, pro děti), /srovnani/ , /jaky-iphone-koupit/ , /obchody/ (+ shop pages), /pruvodce/<guide>/ , /o-webu/,
404, sitemap.xml, robots.txt, _headers, /go/<shop>/ redirects (scripts/golinks.py).
State between builds (encrypted release asset): data/state/history.json (daily lowest prices), build-report.json, changed.txt.
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
from urllib.parse import quote

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
IMG_PREF = ["smarty", "iphonemarket", "aukro", "istyle", "mall", "allegro"]   # clean Apple renders; MobileGear and JabkoLevně put their logo on the screen
GIMG = [k for k in ("aplus", "a", "b", "c") if (APP / f"static/img/ui/grade-{k}.webp").exists()]   # Canva illustrations of the grades
MONTHS = ["ledna", "února", "března", "dubna", "května", "června", "července", "srpna", "září", "října", "listopadu", "prosince"]


def kc(v):
    return f"{int(v):,}".replace(",", " ") + " Kč"


def kc_plain(v):
    return kc(v).replace(" ", " ")


def date_cz(d):
    return f"{d.day}. {MONTHS[d.month - 1]} {d.year}"


def plural(n, one, few, many):
    return one if n == 1 else few if 2 <= n <= 4 else many


def num(n):
    return f"{n:,}".replace(",", "\u00a0")


def nab(n):
    return f"{num(n)}\u00a0{plural(n, 'nabídka', 'nabídky', 'nabídek')}"


def obchodu(n):
    return f"{n} {plural(n, 'obchodu', 'obchodů', 'obchodů')}"


def ios_ok(m):
    """iOS 26 and 27 run on iPhone 11 and newer and on iPhone SE (2nd gen) and newer (Apple, June 2026)."""
    return m["year"] >= 2019 and not m["slug"].startswith(("iphone-xs", "iphone-xr", "iphone-x", "iphone-8", "iphone-7"))


def img(url, w):
    if not url:
        return ""
    return f"https://wsrv.nl/?url={quote(url, safe='')}&w={w}&h={w}&fit=contain&cbg=white&output=webp&q=80"


# ---------------------------------------------------------------- output

class Out:
    def __init__(self, root):
        self.root = root
        self.pages = []
        self.changed = []
        hp = STATE / "page-hashes.json"
        self.old = json.loads(hp.read_text()) if hp.exists() else {}
        self.new = {}

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def page(self, path, text, index=True):
        rel = path.strip("/") + "/index.html" if path != "/" else "index.html"
        self.write(rel, text)
        self.pages.append((path, index))
        body = re.sub(r"<script.*?</script>", "", text, flags=re.S)
        h = hashlib.md5(body.encode()).hexdigest()[:12]
        self.new[path] = h
        if index and self.old.get(path) != h:
            self.changed.append(path)


def asset(src, out):
    data = (APP / "static/assets" / src).read_bytes()
    name = f"{Path(src).stem}.{hashlib.md5(data).hexdigest()[:8]}{Path(src).suffix}"
    (out / "assets").mkdir(parents=True, exist_ok=True)
    (out / "assets" / name).write_bytes(data)
    return "/assets/" + name


# ---------------------------------------------------------------- layout

def logo_mark(size=34):
    if (APP / "static/img/ui/logo.webp").exists():
        return f'<img src="/img/ui/logo.webp" alt="" width="{size}" height="{size}">'
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 40 40" aria-hidden="true"><rect x="10" y="3" width="20" height="34" rx="5.5" fill="#fff" '
            'stroke="#18181A" stroke-width="2.6"/><path d="M17 7.4h6" stroke="#18181A" stroke-width="2.2" stroke-linecap="round"/>'
            '<path d="M26.5 25.5a6.8 6.8 0 1 1-2.6-6.7" fill="none" stroke="#2BA35F" stroke-width="3" stroke-linecap="round"/>'
            '<path d="M22.4 16.6l2.6 2.4-3.1 1.6" fill="none" stroke="#2BA35F" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>')


NAV = [("/levny-iphone/", "Levné iPhony"), ("/zanovni-iphone/", "Zánovní"), ("/novy-iphone/", "Nové"), ("/srovnani/", "Srovnání"),
       ("/pruvodce/", "Průvodce")]


def layout(ctx, *, path, title, desc, body, crumbs=None, ld=None, index=True, active=None, og_img="", cfg=None):
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
    ga = ""
    if GA4_ID and not STAGING:
        ga = (f'<script async src="https://www.googletagmanager.com/gtag/js?id={GA4_ID}"></script><script>window.dataLayer=window.dataLayer||[];'
              f'function gtag(){{dataLayer.push(arguments)}}gtag("consent","default",{{analytics_storage:"denied",ad_storage:"denied",ad_user_data:"denied",ad_personalization:"denied"}});'
              f'gtag("js",new Date());gtag("config","{GA4_ID}");</script>')
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
<link rel="stylesheet" href="{ctx['css']}"><link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="icon" href="/favicon-32.png" sizes="32x32">
<link rel="apple-touch-icon" href="/favicon-180.png"><link rel="manifest" href="/site.webmanifest"><meta name="theme-color" content="#FFFFFF">{ldtxt}{ga}</head><body>
<a class="skip" href="#obsah">Přeskočit na obsah</a>
<header class="top"><div class="wrap top-in"><a class="logo" href="/" aria-label="{BRAND} – úvod">{logo_mark()}<span>repasovaný <b>iPhone</b></span></a>
<nav class="nav" aria-label="Hlavní">{nav}</nav></div></header>
{cr}<main id="obsah">{body}</main>
<footer class="foot"><div class="wrap foot-in"><div class="about"><a class="logo" href="/">{logo_mark(30)}<span>repasovaný <b>iPhone</b></span></a>
<p>Každou noc projdeme nabídky {obchodu(len(ctx['shop_ids']))} s repasovanými, zánovními i novými iPhony a ke každé konfiguraci najdeme nejlevnější obchod.
Ceny se během dne mohou změnit, platí údaj v obchodě.</p><p class="muted">Za nákup přes odkaz můžeme dostat provizi, cenu ani pořadí to nemění. <a href="/o-webu/">Jak web funguje</a></p></div>
<div><h2>Modely</h2><ul>{fm}</ul></div><div><h2>Kategorie</h2><ul>{cats}<li><a href="/srovnani/">Srovnání modelů</a></li><li><a href="/jaky-iphone-koupit/">Jaký iPhone koupit</a></li></ul></div>
<div><h2>Průvodce</h2><ul>{guides}</ul><h2 class="mt">Obchody</h2><ul>{shops}</ul></div></div></footer>
{cfg_tag}<script src="{ctx['js']}" defer></script></body></html>"""


# ---------------------------------------------------------------- components

def shop_logo(sid, h=22):
    s = SHOP[sid]
    if (APP / "static/img/shops" / f"{sid}.webp").exists():
        return f'<img class="slogo" src="/img/shops/{sid}.webp" alt="{E(s["name"])}" height="{h}" loading="lazy" decoding="async">'
    return f'<span class="slogo stext" style="--c:{s["color"]}">{E(s["name"])}</span>'


def grade_chip(g):
    return f'<span class="gchip g-{g}" title="{E(GR[g]["name"])}">{E(GR[g]["short"])}</span>'


def faq_html(items):
    return '<div class="faq">' + "".join(f"<details><summary>{E(q)}</summary><div>{a}</div></details>" for q, a in items) + "</div>"


def faq_ld(items):
    return {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": re.sub(r"<[^>]+>", "", a)}} for q, a in items]}


def product_ld(name, path, offers, image=""):
    ps = [o["p"] for o in offers]
    cond = "https://schema.org/RefurbishedCondition" if any(o["g"] != "novy" for o in offers) else "https://schema.org/NewCondition"
    d = {"@context": "https://schema.org", "@type": "Product", "name": name, "brand": {"@type": "Brand", "name": "Apple"}, "url": SITE + path,
         "offers": {"@type": "AggregateOffer", "priceCurrency": "CZK", "lowPrice": min(ps), "highPrice": max(ps), "offerCount": len(ps), "itemCondition": cond}}
    if image:
        d["image"] = image
    return d


def model_photo(ctx, slug, col=None):
    return ctx["photos"].get((slug, col)) or ctx["photos"].get((slug, None)) or ""


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
    """Compact JSON for app.js: colours, storages, shops and offers as rows [colour i, storage i, grade, price, shop, go, shop wording, battery, eSIM]."""
    slug = m["slug"]
    cols = [c for c in P.COLORS.get(slug, []) if any(o["col"] == c["key"] for o in offers)]
    gbs = sorted({o["gb"] for o in offers})
    ci = {c["key"]: i for i, c in enumerate(cols)}
    gi = {g: i for i, g in enumerate(gbs)}
    shops = sorted({o["shop"] for o in offers})
    rows = []
    for o in sorted(offers, key=lambda o: o["p"]):
        go = o["go"]
        pre = f"/go/{o['shop']}/?u="
        go = go[len(pre):] if go.startswith(pre) else go          # app.js puts the prefix back
        rows.append([ci[o["col"]], gi[o["gb"]], o["g"], o["p"], o["shop"], go, o["sg"], o["bat"] or 0, 1 if o["esim"] else 0])
    # default: the most offered storage, its most offered colour, grade A if there is one (else the cheapest grade there)
    rf = [o for o in offers if o["g"] != "novy"] or offers
    dgb = gb_pref if gb_pref in gi else Counter(o["gb"] for o in rf).most_common(1)[0][0]
    pool = [o for o in rf if o["gb"] == dgb] or [o for o in offers if o["gb"] == dgb]
    dcol = Counter(o["col"] for o in pool).most_common(1)[0][0]
    here = [o for o in offers if o["gb"] == dgb and o["col"] == dcol]
    gs = {o["g"] for o in here}
    dg = "a" if "a" in gs else min(here, key=lambda o: o["p"])["g"]
    shop_meta = {s: [SHOP[s]["name"], f"/img/shops/{s}.webp" if (APP / "static/img/shops" / f"{s}.webp").exists() else "", SHOP[s]["color"]] for s in shops}
    return {"m": slug, "name": m["name"], "cols": [[c["key"], c["name"], c["hex"], img(model_photo(ctx, slug, c["key"]), 600)] for c in cols],
            "gbs": gbs, "shops": shop_meta, "newp": {str(gb): ctx["new_min"][(slug, gb)] for gb in gbs if (slug, gb) in ctx["new_min"]},
            "grades": {k: [v["short"], v["name"], v["ex"]] for k, v in GR.items()}, "gimg": GIMG, "o": rows, "def": [dcol, dgb, dg]}


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
        ps = [r[3] for r in here if r[2] == g]
        gcards.append(f'<button type="button" class="gcard{" on" if g == dg else ""}{"" if ps else " off"}" data-g="{g}" aria-pressed="{str(g == dg).lower()}"{"" if ps else " disabled"}>'
                      f'<span class="gl g-{g}">{E(GR[g]["short"])}</span><span class="gn">{E(GR[g]["name"])}</span>'
                      f'<span class="gp">{"od " + kc(min(ps)) if ps else "není skladem"}</span></button>')
    res = [r for r in here if r[2] == dg]
    return f"""<section class="cfg" data-cfg aria-label="Výběr iPhonu">
<div class="cfg-photo"><div class="ph"><img src="{E(cols[ci][3])}" alt="{E(m['name'])}, {E(cols[ci][1])}" width="600" height="600" fetchpriority="high" data-photo></div></div>
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
    save = f'<span class="save hand">o {kc(newp - best[3])} levněji než nový</span>' if newp and newp > best[3] and best[2] != "novy" else ""
    facts = [f"u obchodu: {E(best[6])}"] if best[6] else []
    if best[7]:
        facts.append(f"baterie {best[7]} %")
    if best[8]:
        facts.append("jen eSIM")
    per_shop = {}
    for r in res:
        per_shop.setdefault(r[4], r)
    others = [r for r in per_shop.values() if r is not best]
    sh = cfg["shops"]
    olist = "".join(f'<li><span class="o-shop">{shop_mini(sh, r[4])}</span><span class="o-sg">{E(r[6])}</span>'
                    f'<span class="o-p">{kc(r[3])}</span><a class="btn sm ghost" href="{E(go_url(r))}" rel="sponsored nofollow noopener" target="_blank" data-go="{r[4]}">Do obchodu</a></li>'
                    for r in others)
    return (f'<div class="best"><div class="best-top"><span class="best-k">Nejlevněji</span>{shop_mini(sh, best[4], 26)}</div>'
            f'<p class="best-p"><span class="price">{kc(best[3])}</span>{save}</p>'
            f'<p class="best-f">{" · ".join(facts)}</p>'
            f'<a class="btn big" href="{E(go_url(best))}" rel="sponsored nofollow noopener" target="_blank" data-go="{best[4]}">Koupit u {E(sh[best[4]][0])}</a>'
            f'<p class="best-n">{nab(len(res))} v této konfiguraci</p></div>'
            + (f'<div class="alts"><h3>Další obchody</h3><ul>{olist}</ul></div>' if olist else ""))


def shop_mini(shops, sid, h=22):
    name, logo, color = shops[sid]
    if logo:
        return f'<img class="slogo" src="{logo}" alt="{E(name)}" height="{h}" loading="lazy" decoding="async">'
    return f'<span class="slogo stext" style="--c:{color}">{E(name)}</span>'


def go_url(r):
    return r[5] if r[5].startswith(("http", "/")) else f"/go/{r[4]}/?u={r[5]}"


# ---------------------------------------------------------------- texts

def model_text(ctx, m, offers):
    rf = [o for o in offers if o["g"] != "novy"] or offers
    low = min(o["p"] for o in rf)
    shops = sorted({SHOP[o["shop"]]["name"] for o in rf})
    age = max(TODAY.year - m["year"], 0)
    gb_c = Counter(o["gb"] for o in rf).most_common(1)[0][0]
    t = [f'<p>Právě teď je v nabídce <strong>{nab(len(rf))}</strong> repasovaného, zánovního nebo bazarového {E(m["name"])} '
         f'z {obchodu(len(shops))} ({E(", ".join(shops))}). Nejlevnější kus stojí <strong>{kc(low)}</strong>, nejčastěji se prodává verze s {P.gb_label(gb_c)}.</p>']
    sv = sorted((ctx["new_min"][(o["model"], o["gb"])] - o["p"]) / ctx["new_min"][(o["model"], o["gb"])]
                for o in rf if o["g"] != "novy" and ctx["new_min"].get((o["model"], o["gb"]), 0) > o["p"])
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
        by_g[o["g"]].append(o["p"])
    gtxt = ", ".join(f'kvalita {GR[g]["short"]} od {kc(min(v))}' for g, v in sorted(by_g.items(), key=lambda x: P.GRADE_ORDER[x[0]]))
    items = [(f'Kolik stojí repasovaný {m["name"]}?', f'Nejlevnější nabídka dnes stojí {kc(min(o["p"] for o in rf))}. Podle kvality: {gtxt}. Ceny kontrolujeme každou noc.'),
             ("Co znamená kvalita A, B a C?",
              "Kvalita popisuje vzhled, ne funkčnost: A+ je jako nový, A má stopy viditelné jen zblízka, B jemné škrábance na rámu nebo zádech a C viditelné známky "
              'používání. Každý obchod píše stav jinak, proto u nabídky necháváme i jeho původní označení. <a href="/pruvodce/stavy/">Převodník stavů</a>'),
             ("Jakou záruku má repasovaný iPhone?",
              "Od obchodníka 24 měsíců, u použitého zboží ji smí dohodou zkrátit na 12 měsíců. Při nákupu přes internet můžete do 14 dnů odstoupit od smlouvy bez udání důvodu. "
              '<a href="/pruvodce/zaruka/">Záruka a vrácení</a>')]
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

def page_model(out, ctx, m, offers, gb=None):
    slug = m["slug"]
    path = f"/{slug}/" if gb is None else f"/{slug}/{gb}-gb/"
    rf = [o for o in offers if o["g"] != "novy"] or offers
    scope = [o for o in rf if gb is None or o["gb"] == gb]
    low = min(o["p"] for o in scope)
    n_shops = len({o["shop"] for o in scope})
    lab = f'{m["name"]} {P.gb_label(gb)}' if gb else m["name"]
    only_new = all(o["g"] == "novy" for o in offers)
    cfg = cfg_data(ctx, m, offers, gb)
    title = (f"{lab} bazar i repasovaný od {kc_plain(low)} – {n_shops} {plural(n_shops, 'obchod', 'obchody', 'obchodů')}" if not only_new
             else f"{lab} nejlevněji od {kc_plain(low)} – srovnání {n_shops} {plural(n_shops, 'obchodu', 'obchodů', 'obchodů')}")
    desc = (f"{'Repasovaný a zánovní' if not only_new else 'Nový'} {lab}: {nab(len(scope))} od {kc(low)}. Vyberte barvu, paměť a kvalitu, "
            "ukážeme nejlevnější obchod i další nabídky.").replace(" ", " ")
    photo = model_photo(ctx, slug)
    hist = ctx["hist"].get(slug if gb is None else f"{slug}|{gb}", [])
    sibs = [x for x in MODELS if x["family"] == m["family"] and x["slug"] != slug and ctx["by_model"].get(x["slug"])]
    near = [x for x in MODELS if abs(x["year"] - m["year"]) <= 1 and x["slug"] != slug and x not in sibs and ctx["by_model"].get(x["slug"])]
    rel = "".join(f'<li><a href="/{x["slug"]}/">{E(x["name"])}</a></li>' for x in (sibs + near)[:10])
    gbl = "".join(f'<li><a href="/{slug}/{g}-gb/">{E(m["name"])} {P.gb_label(g)}</a></li>' for g in sorted({o["gb"] for o in rf})
                  if (slug, g) in ctx["sub_pages"] and g != gb)
    items = model_faq(ctx, m, offers)
    h1 = f"Repasovaný {E(lab)}" if not only_new else E(lab)
    body = f"""<div class="wrap">
<header class="mhead"><p class="eyebrow">Ceny z {date_cz(TODAY)} · {nab(len(scope))} z {obchodu(n_shops)}</p>
<h1>{h1}</h1><p class="lead">{'Bazarové, zánovní i nové kusy' if not only_new else 'Nové kusy'} od <strong>{kc(low)}</strong>. Vyberte barvu, paměť a kvalitu, ukážeme nejlevnější obchod.</p></header>
{configurator_html(ctx, m, cfg)}
<section class="sec"><h2>Ceník podle paměti a kvality</h2><p class="muted">Nejnižší cena v každé kombinaci (všechny barvy). Sloupec „Nový“ je nejlevnější nový kus.</p>{price_table(ctx, m, offers)}</section>
<section class="sec two"><div class="prose"><h2>Vyplatí se {E(m["name"])} z druhé ruky?</h2>{model_text(ctx, m, offers)}{storage_text(gb) if gb else ""}{chart_html(hist)}</div>
<aside class="card"><h2>Technický list</h2>{specs_html(m)}</aside></section>
<section class="sec"><h2>Časté otázky</h2>{faq_html(items)}</section>
{f'<section class="sec"><h2>{E(m["name"])} podle paměti</h2><ul class="chips">{gbl}</ul></section>' if gbl else ''}
{f'<section class="sec"><h2>Podobné modely</h2><ul class="chips">{rel}</ul></section>' if rel else ''}
</div>
<div class="buybar" data-buybar hidden><div class="wrap buybar-in"><span class="bb-t" data-bb-t></span><a class="btn" data-bb-a href="#" rel="sponsored nofollow noopener" target="_blank">Koupit</a></div></div>"""
    crumbs = [("/", "Repasované iPhony"), (f"/{slug}/", m["name"])] + ([(path, P.gb_label(gb))] if gb else [])
    ld = [product_ld(f"{lab}" + ("" if only_new else " (repasovaný)"), path, scope, photo), faq_ld(items)]
    out.page(path, layout(ctx, path=path, title=title, desc=desc, body=body, crumbs=crumbs, ld=ld, og_img=img(photo, 600), cfg=cfg),
             index=len(scope) >= (2 if gb is None else 3))


def price_table(ctx, m, offers):
    slug = m["slug"]
    gbs = sorted({o["gb"] for o in offers})
    gs = [g for g in REFURB_G if any(o["g"] == g for o in offers)]
    head = "".join(f'<th>{grade_chip(g)}</th>' for g in gs)
    rows = []
    for gb in gbs:
        here = [o for o in offers if o["gb"] == gb and o["g"] != "novy"]
        low = min((o["p"] for o in here), default=0)
        cells = []
        for g in gs:
            ps = [o["p"] for o in here if o["g"] == g]
            cells.append(f'<td class="num{" low" if ps and min(ps) == low else ""}">{kc(min(ps))}</td>' if ps else '<td class="na">–</td>')
        nw = min((o["p"] for o in offers if o["gb"] == gb and o["g"] == "novy"), default=0)
        name = f'<a href="/{slug}/{gb}-gb/">{P.gb_label(gb)}</a>' if (slug, gb) in ctx["sub_pages"] else P.gb_label(gb)
        rows.append(f'<tr><th scope="row">{name}</th>{"".join(cells)}<td class="num newp">{kc(nw) if nw else "–"}</td></tr>')
    return f'<div class="tscroll"><table class="ptable"><thead><tr><th>Paměť</th>{head}<th>Nový</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def model_card(ctx, m):
    of = ctx["by_model"][m["slug"]]
    rf = [o for o in of if o["g"] != "novy"] or of
    low = min(o["p"] for o in rf)
    cols = [c for c in P.COLORS.get(m["slug"], []) if any(o["col"] == c["key"] for o in of)]
    dots = "".join(f'<span class="dot xs" style="--h:{c["hex"]}" title="{E(c["name"])}"></span>' for c in cols)
    pic = model_photo(ctx, m["slug"])
    im = f'<img src="{E(img(pic, 280))}" alt="" width="140" height="140" loading="lazy" decoding="async">' if pic else '<span class="noimg"></span>'
    return (f'<li><a class="mcard" href="/{m["slug"]}/">{im}<span class="mc-n">{E(m["name"])}</span>'
            f'<span class="mc-dots">{dots}</span><span class="mc-p">od <b>{kc(low)}</b></span>'
            f'<span class="mc-c">{nab(len(rf))}</span></a></li>')


def page_home(out, ctx):
    rf = ctx["refurb"]
    low = min(o["p"] for o in rf)
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
    ex = next((o for o in deals if o["model"] in ("iphone-15", "iphone-16", "iphone-15-pro", "iphone-14", "iphone-13", "iphone-16-pro")), deals[0] if deals else None)
    note = (f'<span class="hand note-hero">{E(MODEL[ex["model"]]["name"])} o {kc(ctx["new_min"][(ex["model"], ex["gb"])] - ex["p"])} levněji než nový</span>'
            f'<svg class="note-arrow" viewBox="0 0 80 60" aria-hidden="true"><path d="M6 8c22 2 44 12 56 38" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>'
            f'<path d="M50 40l12 7 3-14" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>') if ex else ""
    grades = "".join(f'<li class="gx">' + (f'<img src="/img/ui/grade-{k}.webp" alt="" width="120" height="120" loading="lazy">' if k in GIMG else "")
                     + f'<span class="gl g-{k}">{E(GR[k]["short"])}</span><b>{E(GR[k]["name"])}</b><small>{E(GR[k]["ex"])}</small></li>' for k in REFURB_G)
    logos = "".join(f'<li><a href="/obchody/{s}/" aria-label="{E(SHOP[s]["name"])}">{shop_logo(s, 26)}</a></li>' for s in ctx["shop_ids"])
    hero_img = ('<img src="/img/ui/hero.webp" alt="" width="520" height="520" fetchpriority="high">' if (APP / "static/img/ui/hero.webp").exists()
                else f'<img src="{E(img(model_photo(ctx, "iphone-15-pro"), 520))}" alt="" width="520" height="520" fetchpriority="high">')
    items = [("Co je repasovaný iPhone?",
              "Použitý nebo vrácený telefon, který obchod vyčistil, otestoval a případně opravil (nejčastěji baterii nebo displej) a prodává ho se zárukou. "
              'Od bazarového kusu od soukromníka se liší zárukou a kontrolou. <a href="/pruvodce/repas-vs-bazar/">Repas, bazar, zánovní a rozbalený</a>'),
             ("Vyplatí se koupit repasovaný iPhone?",
              "Většinou ano: stejný model stojí o pětinu až polovinu méně než nový. Vybírejte iPhone 11 nebo novější (dostávají aktuální iOS) a hlídejte kondici baterie."),
             ("Odkud jsou ceny?", f"Z produktových exportů {obchodu(shops)}, které stahujeme každou noc. Nakupujete vždy přímo v obchodě."),
             ("Jakou záruku má repasovaný iPhone?",
              'Od obchodníka minimálně 12 měsíců a 14 dní na vrácení při nákupu přes internet. <a href="/pruvodce/zaruka/">Podrobně o záruce</a>')]
    body = f"""<section class="hero"><div class="wrap hero-in"><div class="hero-t">
<p class="eyebrow">{nab(len(rf))} z {obchodu(shops)} · ceny z dnešní noci</p>
<h1>Repasovaný iPhone za&nbsp;cenu, která dává smysl</h1>
<p class="lead">Vyberete model, barvu, paměť a kvalitu. My projdeme obchody s repasy i bazarové nabídky a ukážeme, kde je to nejlevnější. Od <strong>{kc(low)}</strong>.</p>
<ul class="chips">{chips}</ul><p><a class="btn big" href="#modely">Vybrat model</a></p></div>
<div class="hero-art">{hero_img}{note}</div></div></section>
<section class="steps wrap" aria-label="Jak to funguje"><ol>
<li><img src="/img/ui/ic-tap.webp" alt="" width="64" height="64"><b>Vyberte model</b><span>od iPhonu 7 po 18 Pro</span></li>
<li><img src="/img/ui/ic-swatches.webp" alt="" width="64" height="64"><b>Barvu a paměť</b><span>jen to, co je skladem</span></li>
<li><img src="/img/ui/ic-search.webp" alt="" width="64" height="64"><b>Kvalitu A, B nebo C</b><span>a máte nejlevnější obchod</span></li></ol></section>
<section class="sec wrap" id="modely"><h2>Vyberte model</h2>{"".join(fams)}</section>
{f'<section class="sec wrap"><h2>Dnes se vyplatí</h2><p class="muted">Největší rozdíl proti nejlevnějšímu novému kusu se stejnou pamětí.</p><ul class="deals">{dl}</ul></section>' if dl else ''}
<section class="sec wrap"><h2>Kvalita A, B, C jednoduše</h2><p class="prose">Obchody píšou stav každý jinak („Stav A-“, „Kategorie B“, „Velmi dobrý+“). Převádíme ho na jednu stupnici.
Funkčně jsou všechny telefony v pořádku, liší se vzhledem. <a href="/pruvodce/stavy/">Převodník stavů</a></p><ul class="grades">{grades}</ul></section>
<section class="sec wrap why"><ul>
<li><img src="/img/ui/ic-shield.webp" alt="" width="56" height="56" loading="lazy"><b>Záruka od obchodu</b><span>nejméně 12 měsíců u repasu, 24 u nového</span></li>
<li><img src="/img/ui/ic-return.webp" alt="" width="56" height="56" loading="lazy"><b>14 dní na vrácení</b><span>při nákupu přes internet bez udání důvodu</span></li>
<li><img src="/img/ui/ic-battery.webp" alt="" width="56" height="56" loading="lazy"><b>Baterie pod kontrolou</b><span>kde ji obchod uvádí, ukážeme kondici</span></li>
<li><img src="/img/ui/ic-eco.webp" alt="" width="56" height="56" loading="lazy"><b>Šetrnější volba</b><span>telefon, který už jednou vyrobili</span></li></ul></section>
<section class="sec wrap"><h2>Obchody ve srovnání</h2><ul class="logos">{logos}</ul></section>
<section class="sec wrap"><h2>Časté otázky</h2>{faq_html(items)}</section>"""
    ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": BRAND, "url": SITE + "/"}, faq_ld(items),
          {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [
              {"@type": "ListItem", "position": i + 1, "url": f'{SITE}/{m["slug"]}/', "name": m["name"]} for i, m in enumerate(pop)]}]
    title = f"Repasovaný iPhone a iPhone bazar – srovnání cen z {shops} obchodů"
    desc = (f"{nab(len(rf)).capitalize()} repasovaných, zánovních a bazarových iPhonů od {kc(low)}. Vyberte model, barvu, paměť a kvalitu A, B nebo C, "
            "ukážeme nejlevnější obchod.").replace(" ", " ")
    out.page("/", layout(ctx, path="/", title=title, desc=desc, body=body, ld=ld))


def deal_card(ctx, o):
    m = MODEL[o["model"]]
    nw = ctx["new_min"][(o["model"], o["gb"])]
    c = P.color(o["model"], o["col"])
    href = f'/{o["model"]}/?barva={o["col"]}&pamet={o["gb"]}&kvalita={o["g"]}'
    pic = model_photo(ctx, o["model"], o["col"])
    return (f'<li><a class="deal" href="{E(href)}"><img src="{E(img(pic, 200))}" alt="" width="100" height="100" loading="lazy" decoding="async">'
            f'<span class="d-t"><b>{E(m["name"])} {P.gb_label(o["gb"])}</b><span class="muted">{E(c["name"])} · {grade_chip(o["g"])}</span>'
            f'<span class="d-p">{kc(o["p"])} <span class="save">−{round((nw - o["p"]) / nw * 100)} %</span></span>'
            f'<span class="d-s">{shop_logo(o["shop"], 16)}</span></span></a></li>')


# ---- category landings (what people search, DataForSEO 25. 11. 2026) ----

def best_per_model(ctx, pred, grades=REFURB_G):
    rows = []
    for m in MODELS:
        of = [o for o in ctx["by_model"].get(m["slug"], []) if o["g"] in grades and pred(m, o)]
        if of:
            rows.append((m, min(of, key=lambda o: o["p"]), len(of)))
    return rows


def cat_rows(ctx, rows, limit=40):
    li = []
    for m, o, n in rows[:limit]:
        c = P.color(m["slug"], o["col"])
        href = f'/{m["slug"]}/?barva={o["col"]}&pamet={o["gb"]}&kvalita={o["g"]}'
        pic = model_photo(ctx, m["slug"], o["col"])
        li.append(f'<li><a class="crow" href="{E(href)}"><img src="{E(img(pic, 160))}" alt="" width="80" height="80" loading="lazy" decoding="async">'
                  f'<span class="cr-t"><b>{E(m["name"])}</b><span class="muted">{P.gb_label(o["gb"])} · {E(c["name"])} · {m["year"]}</span>'
                  f'<span>{grade_chip(o["g"])} {shop_logo(o["shop"], 16)}</span></span>'
                  f'<span class="cr-p"><b>{kc(o["p"])}</b><span class="muted">{nab(n)}</span></span></a></li>')
    return '<ul class="crows">' + "".join(li) + "</ul>"


CATS = [
    {"path": "/levny-iphone/", "short": "Levné iPhony", "h1": "Levný iPhone: nejlevnější iPhony dnes",
     "title": "Levný iPhone – nejlevnější iPhony dnes od {low} | {shops} obchodů",
     "lead": "Nejlevnější kus každého modelu, seřazený od nejnižší ceny. Modely bez aktuálního iOS jsou až na konci."},
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
                      "<p>Kvalita C znamená viditelné stopy, ne horší funkčnost. Pokud budete telefon nosit v obalu, ušetříte proti kvalitě A často tisíc až dva tisíce korun.</p>",
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
    newest = lambda r: (-r[0]["year"], r[1]["p"])  # noqa: E731
    p = c["path"]
    if p == "/levny-iphone/":
        rows = sorted(best_per_model(ctx, lambda m, o: True), key=lambda r: (not ios_ok(r[0]), r[1]["p"]))
        return rows, ('<ul class="chips"><li><a href="/iphone-do-5000-kc/">iPhone do 5 000 Kč</a></li><li><a href="/iphone-do-10000-kc/">iPhone do 10 000 Kč</a></li>'
                      '<li><a href="/iphone-pro-deti/">iPhone pro děti</a></li><li><a href="/maly-iphone/">Malé iPhony</a></li></ul>')
    if p == "/novy-iphone/":
        return sorted(best_per_model(ctx, lambda m, o: True, grades=("novy",)), key=newest), ""
    if p == "/zanovni-iphone/":
        return sorted(best_per_model(ctx, lambda m, o: True, grades=("aplus",)), key=newest), ""
    if p == "/maly-iphone/":
        return sorted(best_per_model(ctx, lambda m, o: m["display"] <= 6.1 and ios_ok(m)), key=lambda r: (r[0]["display"], -r[0]["year"])), ""
    if p == "/iphone-do-5000-kc/":
        return sorted(best_per_model(ctx, lambda m, o: o["p"] <= 5000), key=newest), ""
    if p == "/iphone-do-10000-kc/":
        return sorted(best_per_model(ctx, lambda m, o: o["p"] <= 10000), key=newest), ""
    if p == "/iphone-pro-deti/":
        return sorted(best_per_model(ctx, lambda m, o: ios_ok(m) and o["p"] <= 9000, grades=("a", "b", "c")), key=newest), ""
    return [], ""


def page_cats(out, ctx):
    for c in CATS:
        rows, extra = cat_content(ctx, c)
        if not rows:
            continue
        low = min(r[1]["p"] for r in rows)
        title = c["title"].format(low=kc_plain(low), shops=len(ctx["shop_ids"]), n=len(rows))
        desc = f'{c["lead"]} Ceny z {date_cz(TODAY)}.'
        body = f"""<div class="wrap"><header class="mhead"><p class="eyebrow">Ceny z {date_cz(TODAY)} · {len(rows)} {plural(len(rows), "model", "modely", "modelů")}</p>
<h1>{E(c["h1"])}</h1><p class="lead">{E(c["lead"])}</p>{extra}</header>
{cat_rows(ctx, rows)}<section class="sec prose">{CAT_TEXT.get(c["path"], "")}</section></div>"""
        ld = [{"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "url": f'{SITE}/{m["slug"]}/', "name": m["name"]} for i, (m, o, n) in enumerate(rows[:30])]}]
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
                    f'<td class="num">{kc(min(o["p"] for o in rf))}</td></tr>')
    body = f"""<div class="wrap"><header class="mhead"><h1>Srovnání iPhonů z druhé ruky</h1>
<p class="lead">Všechny modely, které se dnes dají koupit, v jedné tabulce: rok, displej, čip, konektor, podpora aktuálního iOS a nejnižší cena.</p></header>
<div class="card"><div class="tscroll"><table class="ptable cmp"><thead><tr><th>Model</th><th>Rok</th><th>Displej</th><th>Čip</th><th>Konektor</th><th>iOS 26/27</th>
<th>Apple Intelligence</th><th>Cena od</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></div>
<section class="sec prose"><h2>Jak tabulku číst</h2><p><strong>iOS 26/27</strong>: Apple aktuální systém vydává pro iPhone 11 a novější a pro SE 2. generace. Starší modely fungují dál,
ale nové funkce a časem i některé aplikace jim chybí. <strong>Apple Intelligence</strong> mají iPhony 15 Pro, celá řada 16 a novější. <strong>USB-C</strong> mají modely od iPhonu 15.</p>
<p>Nevíte, který vybrat? <a href="/jaky-iphone-koupit/">Doporučení podle rozpočtu</a></p></section></div>"""
    out.page("/srovnani/", layout(ctx, path="/srovnani/", title="Srovnání iPhonů – parametry a ceny z druhé ruky v jedné tabulce",
                                  desc="Všechny iPhony z druhé ruky v jedné tabulce: rok, displej, čip, konektor, podpora iOS 26 a 27 a nejnižší cena.",
                                  body=body, crumbs=[("/", "Repasované iPhony"), ("/srovnani/", "Srovnání")], active="/srovnani/"))


def page_buy(out, ctx):
    tiers = [(0, 6000, "do 6 000 Kč"), (6000, 10000, "6 000 až 10 000 Kč"), (10000, 15000, "10 000 až 15 000 Kč"),
             (15000, 22000, "15 000 až 22 000 Kč"), (22000, 10 ** 9, "nad 22 000 Kč")]
    sec = []
    for lo, hi, lab in tiers:
        rows = best_per_model(ctx, lambda m, o, lo=lo, hi=hi: lo <= o["p"] < hi and ios_ok(m), grades=("aplus", "a", "b"))
        rows.sort(key=lambda r: (-r[0]["year"], -("Pro" in r[0]["name"]), r[1]["p"]))
        if rows:
            top = rows[0][0]
            sec.append(f'<h2>Rozpočet {lab}</h2><p>Nejnovější model, který se vejde v dobré kvalitě: <strong>{E(top["name"])}</strong> ({top["year"]}, čip {E(top["chip"])}).</p>'
                       + cat_rows(ctx, rows, 5))
    body = f"""<div class="wrap"><header class="mhead"><p class="eyebrow">Podle cen z {date_cz(TODAY)}</p><h1>Jaký iPhone koupit? Doporučení podle rozpočtu</h1>
<p class="lead">Pro každý rozpočet nejnovější modely, které se do něj dnes vejdou v kvalitě B a lepší a dostávají aktuální iOS. Přepočítává se každou noc.</p></header>
<div class="buyguide">{"".join(sec)}</div></div>"""
    out.page("/jaky-iphone-koupit/", layout(ctx, path="/jaky-iphone-koupit/", title=f"Jaký iPhone koupit v roce {TODAY.year} – doporučení podle rozpočtu",
                                            desc="Který iPhone koupit za 6, 10, 15 nebo 22 tisíc? Doporučení podle dnešních cen, podpory iOS a kvality.",
                                            body=body, crumbs=[("/", "Repasované iPhony"), ("/jaky-iphone-koupit/", "Jaký iPhone koupit")]))


def page_shops(out, ctx):
    li = "".join(f'<li><a class="shopc" href="/obchody/{s}/">{shop_logo(s, 30)}<span>{nab(ctx["shop_count"][s])}</span></a></li>' for s in ctx["shop_ids"])
    body = f'<div class="wrap"><header class="mhead"><h1>Obchody ve srovnání</h1><p class="lead">Odkud bereme nabídky a jak jednotlivé obchody značí stav telefonu.</p></header><ul class="shopgrid">{li}</ul></div>'
    out.page("/obchody/", layout(ctx, path="/obchody/", title="Obchody s repasovanými iPhony ve srovnání", desc="Přehled obchodů s repasovanými, zánovními a novými iPhony a jak značí stav.",
                                 body=body, crumbs=[("/", "Repasované iPhony"), ("/obchody/", "Obchody")]))
    for s in ctx["shop_ids"]:
        sh, of = SHOP[s], [o for o in ctx["offers"] if o["shop"] == s]
        info = SHOP_INFO.get(s, {})
        sg = Counter((o["sg"] or "–", o["g"]) for o in of).most_common()
        sgt = "".join(f'<tr><td>{E(a)}</td><td>{grade_chip(g)} {E(GR[g]["name"])}</td><td class="num">{n}</td></tr>' for (a, g), n in sg)
        rows = sorted(best_per_model(ctx, lambda m, o, s=s: o["shop"] == s, grades=tuple(GR)), key=lambda r: (-r[0]["year"], r[1]["p"]))
        body = f"""<div class="wrap"><header class="mhead shophead">{shop_logo(s, 40)}<h1>{E(sh["name"])}: iPhony a ceny</h1><p class="lead">{info.get("lead", "")}</p></header>
<section class="sec two"><div class="prose">{info.get("text", "")}<h2>Jak {E(sh["name"])} značí stav</h2><table><thead><tr><th>Označení v obchodě</th><th>U nás</th><th>Kusů</th></tr></thead><tbody>{sgt}</tbody></table></div>
<aside class="card"><dl class="specs"><dt>Nabídek</dt><dd>{len(of)}</dd><dt>Cena od</dt><dd>{kc(min(o["p"] for o in of))}</dd><dt>Web</dt><dd>{E(sh["domain"])}</dd></dl></aside></section>
<section class="sec"><h2>Nejlevnější kus každého modelu</h2>{cat_rows(ctx, rows, 30)}</section></div>"""
        out.page(f"/obchody/{s}/", layout(ctx, path=f"/obchody/{s}/", title=f"{sh['name']} – iPhony, stavy a ceny",
                                          desc=f"iPhony z {sh['name']}: {nab(len(of))} od {kc(min(o['p'] for o in of))}, jak obchod značí stav a co nabízí.".replace(" ", " "),
                                          body=body, crumbs=[("/", "Repasované iPhony"), ("/obchody/", "Obchody"), (f"/obchody/{s}/", sh["name"])]), index=len(of) >= 5)


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
               "dateModified": g.get("updated", TODAY.isoformat()), "author": {"@type": "Organization", "name": BRAND, "url": SITE + "/o-webu/"}}]
        out.page(path, layout(ctx, path=path, title=g["title"], desc=g["desc"], body=body, ld=ld, active="/pruvodce/",
                              crumbs=[("/", "Repasované iPhony"), ("/pruvodce/", "Průvodce"), (path, g["short"])]))


def page_about(out, ctx):
    shops = ", ".join(SHOP[s]["name"] for s in ctx["shop_ids"])
    body = f"""<div class="wrap"><article class="prose art"><h1>O webu</h1>
<p>Repasovanyiphone.cz je nezávislé srovnání repasovaných, zánovních, bazarových i nových iPhonů. Každou noc stáhneme produktové exporty obchodů ({E(shops)}),
z názvu a parametrů rozpoznáme model, paměť, oficiální barvu, kvalitu a baterii a ke každé konfiguraci najdeme nejlevnější obchod.</p>
<h2>Jak vyděláváme</h2><p>Když přes odkaz nakoupíte, obchod nám může zaplatit provizi přes affiliate síť (eHub, CJ). Cenu pro vás to nemění a pořadí neovlivňuje: řadíme jen podle ceny.</p>
<h2>Jak převádíme kvalitu</h2><p>Obchody používají vlastní stupnice. Převádíme je na Nový, A+, A, B a C a u každé nabídky necháváme původní označení obchodu. Nabídky, jejichž stav neumíme
spolehlivě zařadit, do srovnání nebereme. <a href="/pruvodce/stavy/">Převodník stavů</a></p>
<h2>Co nezaručujeme</h2><p>Ceny a dostupnost se během dne mění. Platí vždy údaj v obchodě, nákup i reklamaci řešíte přímo s ním.</p>
<h2>Kontakt</h2><p>Chyba v nabídce, nový obchod nebo spolupráce: <a href="mailto:info@repasovanyiphone.cz">info@repasovanyiphone.cz</a></p></article></div>"""
    out.page("/o-webu/", layout(ctx, path="/o-webu/", title="O webu – jak srovnáváme iPhony a jak vyděláváme", desc="Odkud jsou data, jak převádíme kvalitu a jak web vydělává.",
                                body=body, crumbs=[("/", "Repasované iPhony"), ("/o-webu/", "O webu")]))


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
            day[k] = min(day.get(k, 10 ** 9), o["p"])
    h[TODAY.isoformat()] = day
    h = dict(sorted(h.items())[-400:])
    hp.write_text(json.dumps(h, separators=(",", ":")))
    per = defaultdict(list)
    for d, v in h.items():
        dd = dt.date.fromisoformat(d)
        for k, p in v.items():
            per[k].append((f"{dd.day}. {dd.month}.", p))
    return per


def photos(offers):
    """Best product photo per (model, colour) and per model: shops with clean white renders first."""
    rank = {s: i for i, s in enumerate(IMG_PREF)}
    ph = {}
    for o in sorted(offers, key=lambda o: (rank.get(o["shop"], 99), o["g"] != "aplus")):
        if o["img"] and o["shop"] in rank:
            ph.setdefault((o["model"], o["col"]), o["img"])
            ph.setdefault((o["model"], None), o["img"])
    return ph


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    offers, stats, report = P.load_all(APP / "data/raw", SHOPS)
    seen, uniq = set(), []
    for o in offers:
        if (o["shop"], o["id"]) not in seen:
            seen.add((o["shop"], o["id"]))
            uniq.append(o)
    offers = uniq
    refurb = [o for o in offers if o["g"] != "novy"]
    new_min = {}
    for o in offers:
        if o["g"] == "novy":
            k = (o["model"], o["gb"])
            new_min[k] = min(new_min.get(k, 10 ** 9), o["p"])
    for k, v in list(new_min.items()):     # a "new" price below the median refurbished one is a bad reference (grey import, mislabelled used)
        rs = sorted(o["p"] for o in refurb if (o["model"], o["gb"]) == k)
        if rs and v < rs[len(rs) // 2]:
            del new_min[k]
    if len(refurb) < 300:
        sys.exit(f"only {len(refurb)} refurbished offers - refusing to build a near-empty site")
    go_tpl, go_stats = golinks.local_go([{"offers": offers}])
    by_model = defaultdict(list)
    for o in offers:
        by_model[o["model"]].append(o)
    sub_pages = {(m, gb) for m, of in by_model.items() for gb, n in Counter(o["gb"] for o in of if o["g"] != "novy").items() if n >= 3}
    deals, seen_m = [], set()
    for o in sorted((o for o in refurb if o["g"] in ("aplus", "a", "b") and new_min.get((o["model"], o["gb"]), 0) > o["p"] and ios_ok(MODEL[o["model"]])),
                    key=lambda o: -(new_min[(o["model"], o["gb"])] - o["p"]) / new_min[(o["model"], o["gb"])]):
        if o["model"] not in seen_m:
            seen_m.add(o["model"])
            deals.append(o)

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    for p in (APP / "static").iterdir():
        if p.name != "assets":
            (shutil.copytree if p.is_dir() else shutil.copy)(p, DIST / p.name)
    shop_count = Counter(o["shop"] for o in offers)
    ctx = {"offers": offers, "refurb": refurb, "new_min": new_min, "by_model": by_model, "sub_pages": sub_pages, "shop_count": shop_count,
           "shop_ids": [s["id"] for s in SHOPS if shop_count.get(s["id"])], "guides": load_guides(), "hist": history(refurb),
           "photos": photos(offers), "deals": deals, "cats": CATS}
    ctx["css"] = asset("site.css", DIST)
    ctx["js"] = asset("app.js", DIST)
    out = Out(DIST)
    page_home(out, ctx)
    for m in MODELS:
        of = by_model.get(m["slug"])
        if not of:
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
    page_404(out, ctx)
    golinks.write_go(out, go_tpl, SHOP)

    idx = [p for p, i in out.pages if i]
    sm = "".join(f"<url><loc>{SITE}{p}</loc><lastmod>{TODAY.isoformat()}</lastmod></url>" for p in idx)
    out.write("sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>')
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
  Content-Security-Policy: default-src 'self'; img-src 'self' data: https://wsrv.nl{' https:' if ga else ''}; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'{' https://www.googletagmanager.com' if ga else ''}; connect-src 'self'{' https://*.google-analytics.com https://*.analytics.google.com https://www.googletagmanager.com' if ga else ''}; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'
/assets/*
  Cache-Control: public, max-age=31536000, immutable
/fonts/*
  Cache-Control: public, max-age=31536000, immutable
/img/*
  Cache-Control: public, max-age=604800
/go/*
  X-Robots-Tag: noindex, nofollow
""")
    (STATE / "page-hashes.json").write_text(json.dumps(out.new))
    (STATE / "changed.txt").write_text("\n".join(out.changed))
    rep = {"date": TODAY.isoformat(), "shops": stats, "skipped": report, "refurb": len(refurb), "offers": len(offers), "new_ref": len(new_min),
           "models": len(by_model), "pages": len(out.pages), "indexable": len(idx), "changed": len(out.changed), "go": go_stats}
    (STATE / "build-report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    print(json.dumps({k: rep[k] for k in ("refurb", "offers", "models", "pages", "indexable", "go")}))


if __name__ == "__main__":
    main()
