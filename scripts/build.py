#!/usr/bin/env python3
"""Build repasovanyiphone.cz into dist/ from data/raw/*.json (fetch.py) - plain static HTML, no Worker code.

    python3 scripts/build.py

Pages: / , /<model>/ , /<model>/<gb>-gb/ , /srovnani/ , /jaky-iphone-koupit/ , /obchody/ (+ shop pages), /pruvodce/<guide>/ ,
/o-webu/ , 404, sitemap.xml, robots.txt, _headers, /go/<shop>/ redirects.
State kept between builds (encrypted release asset): data/state/history.json (daily lowest prices), build-report.json, changed.txt.
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
MODELS = P.MODELS
MODEL = P.BY_SLUG
FAMILY_NAMES = {"18": "iPhone 18", "17": "iPhone 17 a Air", "16": "iPhone 16", "15": "iPhone 15", "14": "iPhone 14", "13": "iPhone 13",
                "12": "iPhone 12", "11": "iPhone 11", "se": "iPhone SE", "x": "iPhone X, XS a XR", "8": "iPhone 8"}
MONTHS = ["ledna", "února", "března", "dubna", "května", "června", "července", "srpna", "září", "října", "listopadu", "prosince"]


def kc(v):
    return f"{int(v):,}".replace(",", " ") + " Kč"


def date_cz(d):
    return f"{d.day}. {MONTHS[d.month - 1]} {d.year}"


def plural(n, one, few, many):
    return one if n == 1 else few if 2 <= n <= 4 else many


def nab(n):
    return f"{n} {plural(n, 'nabídka', 'nabídky', 'nabídek')}"


def ios_ok(m):
    """iOS 26 and iOS 27 run on iPhone 11 and newer and on iPhone SE (2nd gen) and newer (Apple, June 2026)."""
    return m["year"] >= 2019 and not m["slug"].startswith(("iphone-xs", "iphone-xr", "iphone-x", "iphone-8"))


# ---------------------------------------------------------------- output

class Out:
    def __init__(self, root):
        self.root = root
        self.pages = []           # (path, indexable)
        self.changed = []
        self.old = {}
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
    """Copy a static asset under a content-hashed name (cached for a year)."""
    data = (APP / "static/assets" / src).read_bytes()
    name = f"{Path(src).stem}.{hashlib.md5(data).hexdigest()[:8]}{Path(src).suffix}"
    (out / "assets").mkdir(parents=True, exist_ok=True)
    (out / "assets" / name).write_bytes(data)
    return "/assets/" + name


def img(url, w):
    if not url:
        return ""
    return f"https://wsrv.nl/?url={quote(url, safe='')}&w={w}&h={w}&fit=contain&cbg=white&output=webp&q=78"


# ---------------------------------------------------------------- layout

LOGO = ('<svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true"><path d="M9 3h14a3 3 0 0 1 3 3v20a3 3 0 0 1-3 3H9a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3z" '
        'fill="#fff" stroke="#14171B" stroke-width="2.2"/><path d="M12.5 6.2h7" stroke="#14171B" stroke-width="2" stroke-linecap="round"/>'
        '<path d="M11 17.5l3.4 3.4 6.6-7" fill="none" stroke="#0B7A57" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>')

NAV = [("/", "Modely"), ("/srovnani/", "Srovnání"), ("/jaky-iphone-koupit/", "Jaký koupit"), ("/obchody/", "Obchody"), ("/pruvodce/", "Průvodce")]


def layout(ctx, *, path, title, desc, body, crumbs=None, ld=None, index=True, active=None, og_img=""):
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
        cr = '<nav class="crumbs" aria-label="Drobečková navigace">' + '<span aria-hidden="true">/</span>'.join(parts) + "</nav>"
    ga = ""
    if GA4_ID and not STAGING:
        ga = (f'<script async src="https://www.googletagmanager.com/gtag/js?id={GA4_ID}"></script><script>window.dataLayer=window.dataLayer||[];'
              f'function gtag(){{dataLayer.push(arguments)}}gtag("consent","default",{{analytics_storage:"denied",ad_storage:"denied",ad_user_data:"denied",ad_personalization:"denied"}});'
              f'gtag("js",new Date());gtag("config","{GA4_ID}");</script>')
    fam = defaultdict(list)
    for m in MODELS:
        if ctx["by_model"].get(m["slug"]):
            fam[m["family"]].append(m)
    foot_models = "".join(f'<li><a href="/{m["slug"]}/">{E(m["name"])}</a></li>' for m in sorted(
        (m for m in MODELS if ctx["by_model"].get(m["slug"])), key=lambda m: -len(ctx["by_model"][m["slug"]]))[:10])
    return f"""<!doctype html><html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(title)}</title><meta name="description" content="{E(desc)}"><link rel="canonical" href="{canon}"><meta name="robots" content="{robots}">
<meta property="og:type" content="website"><meta property="og:locale" content="cs_CZ"><meta property="og:site_name" content="{BRAND}">
<meta property="og:title" content="{E(title)}"><meta property="og:description" content="{E(desc)}"><meta property="og:url" content="{canon}">{f'<meta property="og:image" content="{E(og_img)}">' if og_img else ''}
<link rel="preload" href="/fonts/brico-a.woff2" as="font" type="font/woff2" crossorigin><link rel="stylesheet" href="{ctx['css']}">
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="icon" href="/favicon-32.png" sizes="32x32"><link rel="apple-touch-icon" href="/favicon-180.png">
<meta name="theme-color" content="#F1F3EE">{ldtxt}{ga}</head><body>
<header class="top"><div class="wrap"><a class="logo" href="/" aria-label="{BRAND} – úvod">{LOGO}<span>repasovaný<b>iPhone</b></span></a><nav class="nav" aria-label="Hlavní">{nav}</nav></div></header>
<main class="wrap">{cr}{body}</main>
<footer class="foot"><div class="wrap"><div class="about"><h2>O webu</h2><p>Každou noc projdeme nabídky obchodů s repasovanými, zánovními a rozbalenými iPhony a seřadíme je podle ceny, stavu a baterie. Ceny se mohou během dne změnit, platí údaj v obchodě.</p>
<p>Za nákup přes odkaz můžeme dostat provizi, cenu to nemění. <a href="/o-webu/">Jak web funguje</a></p></div>
<div><h2>Modely</h2><ul>{foot_models}</ul></div>
<div><h2>Průvodce</h2><ul>{''.join(f'<li><a href="/pruvodce/{g["slug"]}/">{E(g["short"])}</a></li>' for g in ctx['guides'])}<li><a href="/jaky-iphone-koupit/">Jaký iPhone koupit</a></li></ul></div>
<div><h2>Obchody</h2><ul>{''.join(f'<li><a href="/obchody/{s}/">{E(SHOP[s]["name"])}</a></li>' for s in ctx['shop_ids'])}<li><a href="/o-webu/">O webu a kontakt</a></li></ul></div>
</div></footer>{ctx['js_tag'] if 'data-offers' in body else ''}</body></html>"""


# ---------------------------------------------------------------- components

def facts_html(o):
    lab = P.GRADE[o["g"]][0]
    li = [f'<li class="g g-{o["g"]}">{E(lab)}</li>']
    if o["sg"] and o["sg"].lower() != lab.lower():
        li.append(f'<li class="sg">u obchodu: {E(o["sg"])}</li>')
    if o["bat"]:
        li.append(f'<li class="bat">baterie {o["bat"]} %</li>')
    if o["esim"]:
        li.append('<li class="esim" title="Bez slotu na fyzickou SIM kartu">jen eSIM</li>')
    if o["col"]:
        li.append(f'<li>{E(o["col"])}</li>')
    return '<ul class="facts">' + "".join(li) + "</ul>"


def tag_html(o, ctx, heading="h3", eager=False):
    m = MODEL[o["model"]]
    ref = ctx["new_min"].get((o["model"], o["gb"]))
    vs = ""
    if ref and ref > o["p"] and not o["new"]:
        vs = f'<span class="vs">o {kc(ref - o["p"])} levněji než nový</span>'
    was = f'<span class="was">{kc(o["was"])}</span> ' if o["was"] > o["p"] else ""
    shop = SHOP[o["shop"]]["name"]
    pic = img(o["img"], 176)
    im = (f'<img src="{E(pic)}" alt="" width="88" height="88" loading="{"eager" if eager else "lazy"}" decoding="async">' if pic
          else '<span aria-hidden="true"></span>')
    name = f'{m["name"]} {P.gb_label(o["gb"])}'
    return (f'<li class="tag" data-gb="{o["gb"]}" data-g="{o["g"]}" data-shop="{o["shop"]}" data-p="{o["p"]}" data-bat="{o["bat"] or 0}">{im}'
            f'<div><{heading}>{E(name)}</{heading}>{facts_html(o)}</div>'
            f'<div class="buy"><span><span class="price num">{was}{kc(o["p"])}</span>{vs}</span>'
            f'<span><span class="shopname">{E(shop)}</span><a class="btn" href="{E(o["go"])}" rel="sponsored nofollow noopener" target="_blank" '
            f'data-go="{o["shop"]}">Do obchodu</a></span></div></li>')


def faq_html(items):
    return '<div class="faq">' + "".join(f"<details><summary>{E(q)}</summary><div>{a}</div></details>" for q, a in items) + "</div>"


def faq_ld(items):
    return {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": re.sub(r"<[^>]+>", "", a)}} for q, a in items]}


def product_ld(name, path, offers, image=""):
    ps = [o["p"] for o in offers]
    d = {"@context": "https://schema.org", "@type": "Product", "name": name, "brand": {"@type": "Brand", "name": "Apple"},
         "url": SITE + path, "offers": {"@type": "AggregateOffer", "priceCurrency": "CZK", "lowPrice": min(ps), "highPrice": max(ps),
                                        "offerCount": len(ps), "itemCondition": "https://schema.org/RefurbishedCondition"}}
    if image:
        d["image"] = image
    return d


def matrix_html(slug, offers, ctx, link=True):
    """Lowest price per storage x grade, plus the new-phone reference."""
    gbs = sorted({o["gb"] for o in offers})
    gr = [g for g, _, _ in P.GRADES if g != "novy" and any(o["g"] == g for o in offers)]
    head = "".join(f"<th>{E(P.GRADE[g][0])}</th>" for g in gr)
    rows = []
    for gb in gbs:
        cells = []
        here = [o for o in offers if o["gb"] == gb]
        low = min(o["p"] for o in here)
        for g in gr:
            ps = [o["p"] for o in here if o["g"] == g]
            cells.append(f'<td class="num{" best" if ps and min(ps) == low else ""}">{kc(min(ps)) if ps else "–"}</td>' if ps else '<td class="na">–</td>')
        new = ctx["new_min"].get((slug, gb))
        lab = P.gb_label(gb)
        cnt = len(here)
        name = f'<a href="/{slug}/{gb}-gb/">{lab}</a>' if link and (slug, gb) in ctx["sub_pages"] else lab
        rows.append(f'<tr><td>{name} <small class="muted">({cnt})</small></td>{"".join(cells)}<td class="num newp">{kc(new) if new else "–"}</td></tr>')
    return (f'<div class="tscroll"><table class="matrix"><thead><tr><th>Paměť</th>{head}<th>Nový</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def filters_html(offers, gb_fixed=None):
    gbs = sorted({o["gb"] for o in offers})
    shops = Counter(o["shop"] for o in offers)
    gb = "" if gb_fixed else ('<label>Paměť <select name="gb"><option value="">všechny</option>' +
                              "".join(f'<option value="{v}">{P.gb_label(v)}</option>' for v in gbs) + "</select></label>")
    g = ('<label>Stav <select name="g"><option value="">jakýkoli</option><option value="jako-novy">jako nový</option>'
         '<option value="vyborny">výborný a lepší</option><option value="velmi-dobry">velmi dobrý a lepší</option></select></label>')
    sh = ('<label>Obchod <select name="shop"><option value="">všechny</option>' +
          "".join(f'<option value="{s}">{E(SHOP[s]["name"])} ({n})</option>' for s, n in shops.most_common()) + "</select></label>")
    so = ('<label>Řadit <select name="sort"><option value="p">od nejlevnějšího</option><option value="g">nejlepší stav</option>'
          '<option value="bat">nejlepší baterie</option><option value="pd">od nejdražšího</option></select></label>')
    return f'<form class="filters" data-filters onsubmit="return false" aria-label="Filtr nabídek">{gb}{g}{sh}{so}<span class="count" data-count aria-live="polite"></span></form>'


def offers_block(offers, ctx, gb_fixed=None):
    offers = sorted(offers, key=lambda o: o["p"])
    return (filters_html(offers, gb_fixed) + '<ul class="offers" data-offers>' +
            "".join(tag_html(o, ctx, eager=i < 2) for i, o in enumerate(offers)) + "</ul>" +
            ('<p class="more"><button class="btn ghost" type="button" data-more hidden>Zobrazit další</button></p>'))


def specs_html(m, offers):
    def yn(b):
        return '<span class="yes">ano</span>' if b else '<span class="no">ne</span>'
    rows = [("Uveden", str(m["year"])), ("Displej", f'{str(m["display"]).replace(".", ",")}″' + (f', {m["hz"]} Hz' if m.get("hz") else "")),
            ("Čip", m["chip"]), ("Konektor", m["port"]), ("Odemykání", m["bio"]),
            ("Paměť (od výrobce)", ", ".join(P.gb_label(v) for v in m["storage"])),
            ("Aktuální iOS (26 a 27)", yn(ios_ok(m))), ("Apple Intelligence", yn(m.get("ai")))]
    if m.get("esim_only"):
        rows.append(("SIM", "jen eSIM"))
    return "<dl class=\"specs\">" + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"


def chart_html(points):
    """Tiny SVG line of the daily lowest price (needs >= 7 days)."""
    if len(points) < 7:
        return ""
    W, H, pad = 640, 180, 34
    ps = [p for _, p in points]
    lo, hi = min(ps), max(ps)
    span = max(hi - lo, 1)
    xs = [pad + i * (W - 2 * pad) / (len(points) - 1) for i in range(len(points))]
    ys = [H - pad - (p - lo) / span * (H - 2 * pad) for p in ps]
    path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    d0, d1 = points[0][0], points[-1][0]
    return (f'<figure class="chart"><svg viewBox="0 0 {W} {H}" role="img" aria-label="Vývoj nejnižší ceny od {E(d0)} do {E(d1)}">'
            f'<line class="ax" x1="{pad}" x2="{W - pad}" y1="{H - pad}" y2="{H - pad}"/><line class="ax" x1="{pad}" x2="{W - pad}" y1="{pad}" y2="{pad}"/>'
            f'<path class="ln" d="{path}"/><text x="{pad}" y="{pad - 8}">{kc(hi)}</text><text x="{pad}" y="{H - pad + 18}">{kc(lo)}</text>'
            f'<text x="{W - pad}" y="{H - 8}" text-anchor="end">{E(d1)}</text><text x="{pad}" y="{H - 8}">{E(d0)}</text></svg>'
            f'<figcaption class="muted">Nejnižší cena repasovaného kusu podle dne (všechny paměti a stavy).</figcaption></figure>')


# ---------------------------------------------------------------- texts

def model_text(m, offers, ctx):
    """Data-driven paragraph about whether the model is worth buying refurbished."""
    low = min(o["p"] for o in offers)
    shops = sorted({SHOP[o["shop"]]["name"] for o in offers})
    age = TODAY.year - m["year"]
    gb_c = Counter(o["gb"] for o in offers).most_common(1)[0][0]
    t = [f'<p>Právě teď evidujeme <strong>{nab(len(offers))}</strong> repasovaného nebo zánovního {E(m["name"])} '
         f'z {len(shops)} {plural(len(shops), "obchodu", "obchodů", "obchodů")} ({E(", ".join(shops))}). '
         f'Nejlevnější kus stojí <strong>{kc(low)}</strong>, nejčastěji se prodává verze s {P.gb_label(gb_c)}.</p>']
    savings = [(ctx["new_min"][(o["model"], o["gb"])] - o["p"]) / ctx["new_min"][(o["model"], o["gb"])]
               for o in offers if (o["model"], o["gb"]) in ctx["new_min"] and ctx["new_min"][(o["model"], o["gb"])] > o["p"]]
    if savings:
        s = sorted(savings)[len(savings) // 2]
        t.append(f'<p>Proti nejlevnějšímu novému kusu se stejnou pamětí ušetříte typicky <strong>{round(s * 100)} %</strong> '
                 f'(medián přes všechny nabídky, které mají srovnatelný nový kus).</p>')
    why = []
    if ios_ok(m):
        why.append(f'dostává aktuální iOS 26 i iOS 27 (Apple je vydává pro iPhone 11 a novější)')
    else:
        why.append('<strong>už nedostává aktuální iOS</strong> (iOS 26 a 27 začínají u iPhonu 11), takže časem přijde o nové funkce a část aplikací')
    if m["port"] == "USB-C":
        why.append("nabíjí se přes USB-C stejným kabelem jako notebook")
    else:
        why.append("má ještě konektor Lightning, počítejte s jiným kabelem")
    if m.get("ai"):
        why.append("podporuje Apple Intelligence")
    if m.get("hz") == 120:
        why.append("displej s obnovovací frekvencí 120 Hz je při posouvání znatelně plynulejší")
    t.append(f'<p>{E(m["name"])} vyšel v roce {m["year"]} s čipem {E(m["chip"])} ({age} {plural(age, "rok", "roky", "let")} od uvedení). '
             + "; ".join(why[:1]).capitalize() + ("; " + "; ".join(why[1:]) if why[1:] else "") + ".</p>")
    bats = [o["bat"] for o in offers if o["bat"]]
    if bats:
        t.append(f'<p>Kondici baterie uvádí {len(bats)} z {len(offers)} nabídek. U kusů bez údaje se na ni před nákupem zeptejte; '
                 f'pod 80 % ji Apple považuje za opotřebovanou. <a href="/pruvodce/baterie/">Jak číst kondici baterie</a></p>')
    else:
        t.append('<p>Kondici baterie většina nabídek u tohoto modelu neuvádí. Před nákupem se na ni obchodu zeptejte, pod 80 % ji Apple '
                 'považuje za opotřebovanou. <a href="/pruvodce/baterie/">Jak číst kondici baterie</a></p>')
    return "".join(t)


def model_faq(m, offers, ctx):
    low = min(o["p"] for o in offers)
    by_g = defaultdict(list)
    for o in offers:
        by_g[o["g"]].append(o["p"])
    gtxt = ", ".join(f'{P.GRADE[g][0].lower()} od {kc(min(v))}' for g, v in sorted(by_g.items(), key=lambda x: P.GRADE_ORDER[x[0]]))
    esim = sum(1 for o in offers if o["esim"])
    items = [(f'Kolik stojí repasovaný {m["name"]}?',
              f'Nejlevnější nabídka dnes stojí {kc(low)}. Podle stavu: {gtxt}. Ceny kontrolujeme každou noc.'),
             ("Jaký je rozdíl mezi stavem „výborný“ a „velmi dobrý“?",
              'Oba telefony fungují stejně, liší se vzhledem. „Výborný“ má stopy viditelné jen zblízka, „velmi dobrý“ jemné škrábance na rámu nebo zádech. '
              'Každý obchod stav pojmenovává jinak, proto u nabídky uvádíme i jeho původní označení. <a href="/pruvodce/stavy/">Převodník stavů</a>'),
             ("Jakou záruku má repasovaný iPhone?",
              "Od obchodníka máte jako spotřebitel nárok na záruku 24 měsíců; u použitého zboží ji smí zkrátit na 12 měsíců, ale musí to být dohodnuté "
              "(obvykle v obchodních podmínkách). Při nákupu na internetu můžete navíc do 14 dnů odstoupit od smlouvy bez udání důvodu. "
              '<a href="/pruvodce/zaruka/">Záruka a vrácení podrobně</a>')]
    if esim:
        items.append(("Co znamená „jen eSIM“?",
                      f'{esim} z {len(offers)} nabídek jsou verze bez slotu na fyzickou SIM kartu (typicky telefony z USA). Fungují s eSIM, kterou dnes vydávají '
                      'všichni čeští operátoři, jen si ji musíte u operátora vyžádat.'))
    return items


# ---------------------------------------------------------------- pages

def page_model(out, ctx, m, offers):
    slug, path = m["slug"], f'/{m["slug"]}/'
    low = min(o["p"] for o in offers)
    n_shops = len({o["shop"] for o in offers})
    title = f'Repasovaný {m["name"]} od {kc(low)} – {nab(len(offers))}'.replace(" ", " ")
    desc = (f'{m["name"]} repasovaný, zánovní i bazarový: {nab(len(offers))} z {n_shops} '
            f'{plural(n_shops, "obchodu", "obchodů", "obchodů")}, od {kc(low)}. Porovnejte stav, baterii a cenu proti novému.').replace(" ", " ")
    hero_img = next((o["img"] for o in offers if o["shop"] == "jabkolevne" and o["img"]), "") or next((o["img"] for o in offers if o["img"]), "")
    hist = ctx["hist_model"].get(slug, [])
    items = model_faq(m, offers, ctx)
    sibs = [x for x in MODELS if x["family"] == m["family"] and x["slug"] != slug and ctx["by_model"].get(x["slug"])]
    near = [x for x in MODELS if abs(x["year"] - m["year"]) == 1 and x["slug"] != slug and ctx["by_model"].get(x["slug"])][:6]
    rel = "".join(f'<li><a href="/{x["slug"]}/">{E(x["name"])}</a></li>' for x in (sibs + [n for n in near if n not in sibs])[:10])
    body = f"""<section class="hero"><span class="stamp">Ceny z {date_cz(TODAY)}</span>
<h1>Repasovaný {E(m["name"])}</h1>
<p class="lead">Repasované, zánovní a rozbalené kusy {E(m["name"])} z {n_shops} {plural(n_shops, "obchodu", "obchodů", "obchodů")} na jednom místě.
Od <strong class="num">{kc(low)}</strong>, seřazené podle ceny, stavu a baterie.</p></section>
<div class="box shadow"><h2 style="margin-top:0">Nejnižší ceny podle paměti a stavu</h2>{matrix_html(slug, offers, ctx)}
<p class="muted" style="margin:10px 0 0;font-size:.88rem">Sloupec „Nový“ je nejnižší cena nového kusu ze sledovaných obchodů. V závorce je počet nabídek.</p></div>
<h2 id="nabidky">Všechny nabídky</h2>{offers_block(offers, ctx)}
<div class="cols"><div class="prose"><h2>Vyplatí se repasovaný {E(m["name"])}?</h2>{model_text(m, offers, ctx)}{chart_html(hist)}</div>
<aside class="box"><h2 style="margin-top:0">Technický list</h2>{specs_html(m, offers)}</aside></div>
<h2>Časté otázky</h2>{faq_html(items)}
{f'<h2>Podobné modely</h2><ul class="chips">{rel}</ul>' if rel else ''}"""
    ld = [product_ld(f'{m["name"]} (repasovaný)', path, offers, hero_img), faq_ld(items)]
    out.page(path, layout(ctx, path=path, title=title, desc=desc, body=body, ld=ld, og_img=img(hero_img, 600),
                          crumbs=[("/", "Repasované iPhony"), (path, m["name"])]), index=len(offers) >= 2)


def page_sub(out, ctx, m, gb, offers):
    slug = m["slug"]
    path = f"/{slug}/{gb}-gb/"
    lab = P.gb_label(gb)
    low = min(o["p"] for o in offers)
    new = ctx["new_min"].get((slug, gb))
    title = f'Repasovaný {m["name"]} {lab} od {kc(low)}'.replace(" ", " ")
    desc = (f'{m["name"]} {lab} repasovaný nebo z bazaru: {nab(len(offers))}, nejlevnější za {kc(low)}'
            + (f', nový od {kc(new)}' if new else "") + ". Stav, baterie a obchod přehledně.").replace(" ", " ")
    others = [g for g in sorted({o["gb"] for o in ctx["by_model"][slug]}) if g != gb and (slug, g) in ctx["sub_pages"]]
    oth = "".join(f'<li><a href="/{slug}/{g}-gb/">{m["name"]} {P.gb_label(g)}</a></li>' for g in others)
    save = f' Nový kus se stejnou pamětí stojí od <strong class="num">{kc(new)}</strong>.' if new else ""
    body = f"""<section class="hero"><span class="stamp">Ceny z {date_cz(TODAY)}</span>
<h1>Repasovaný {E(m["name"])} {lab}</h1>
<p class="lead">{nab(len(offers)).capitalize()} repasovaného, zánovního nebo rozbaleného {E(m["name"])} s pamětí {lab}, nejlevnější za
<strong class="num">{kc(low)}</strong>.{save}</p>
<p><a href="/{slug}/">Všechny paměti {E(m["name"])}</a></p></section>
{offers_block(offers, ctx, gb_fixed=gb)}
<div class="cols"><div class="prose"><h2>Stačí {lab}?</h2>{storage_text(gb)}</div><aside class="box"><h2 style="margin-top:0">Technický list</h2>{specs_html(m, offers)}</aside></div>
{f'<h2>Další paměti</h2><ul class="chips">{oth}</ul>' if oth else ''}"""
    ld = [product_ld(f'{m["name"]} {lab} (repasovaný)', path, offers)]
    out.page(path, layout(ctx, path=path, title=title, desc=desc, body=body, ld=ld,
                          crumbs=[("/", "Repasované iPhony"), (f"/{slug}/", m["name"]), (path, lab)]), index=len(offers) >= 3)


def storage_text(gb):
    if gb <= 64:
        return ("<p>64 GB dnes stačí jen na základní používání: zprávy, pár aplikací a fotky zálohované do iCloudu. Systém a aplikace si vezmou "
                "kolem 20 GB a 4K video zabere asi 0,4 GB za minutu. Pokud fotíte hodně, sáhněte po 128 GB.</p>")
    if gb == 128:
        return ("<p>128 GB je rozumný základ pro většinu lidí. Vejde se tisíce fotek, běžné aplikace i několik offline map. Pokud natáčíte hodně videa "
                "ve 4K nebo nechcete platit za iCloud, vyplatí se 256 GB.</p>")
    if gb == 256:
        return ("<p>256 GB je bezstarostná volba: místo vám nedojde ani s velkou knihovnou fotek a videí. Příplatek proti 128 GB bývá u repasovaných "
                "kusů nižší než u nových, porovnejte si tabulku na stránce modelu.</p>")
    return ("<p>512 GB a víc dává smysl hlavně pro natáčení videa ve vysoké kvalitě (ProRes, 4K 60 snímků) nebo pro ty, kdo si chtějí nosit celou "
            "knihovnu fotek offline. Pro běžné používání to je rezerva navíc.</p>")


def page_home(out, ctx):
    refurb = ctx["refurb"]
    low = min(o["p"] for o in refurb)
    shops = len({o["shop"] for o in refurb})
    fams = []
    for fk, fname in FAMILY_NAMES.items():
        ms = [m for m in MODELS if m["family"] == fk and ctx["by_model"].get(m["slug"])]
        if not ms:
            continue
        cards = []
        for m in ms:
            of = ctx["by_model"][m["slug"]]
            mlow = min(o["p"] for o in of)
            pic = next((o["img"] for o in of if o["shop"] == "jabkolevne" and o["img"]), "") or next((o["img"] for o in of if o["img"]), "")
            cards.append(f'<li><a class="mcard" href="/{m["slug"]}/">{f"<img src={chr(34)}{E(img(pic, 128))}{chr(34)} alt={chr(34)}{chr(34)} width=64 height=64 loading=lazy decoding=async>" if pic else "<span></span>"}'
                         f'<span><h3>{E(m["name"])}</h3><span class="from num">od {kc(mlow)}</span><br><span class="sub">{nab(len(of))}</span></span></a></li>')
        fams.append(f'<div class="fam"><h3>{E(fname)}</h3><ul class="models">{"".join(cards)}</ul></div>')
    # one sentence comparing a popular model new vs refurbished
    ex = ""
    for slug in ("iphone-15", "iphone-16", "iphone-15-pro", "iphone-13", "iphone-14"):
        of = ctx["by_model"].get(slug) or []
        pairs = [(o, ctx["new_min"][(slug, o["gb"])]) for o in of if (slug, o["gb"]) in ctx["new_min"] and ctx["new_min"][(slug, o["gb"])] > o["p"]]
        if pairs:
            o, nw = min(pairs, key=lambda x: x[0]["p"])
            ex = (f'<div class="bigstat"><dl><dt>{E(MODEL[slug]["name"])} {P.gb_label(o["gb"])} nový</dt><dd class="num">od {kc(nw)}</dd>'
                  f'<dt>Repasovaný, stav {E(P.GRADE[o["g"]][0].lower())}</dt><dd class="num">od {kc(o["p"])}</dd>'
                  f'<dt>Ušetříte</dt><dd class="num save">{kc(nw - o["p"])} ({round((nw - o["p"]) / nw * 100)} %)</dd></dl>'
                  f'<p style="margin:12px 0 0"><a class="btn" href="/{slug}/">Nabídky {E(MODEL[slug]["name"])}</a></p></div>')
            break
    pop = [m for m in MODELS if len(ctx["by_model"].get(m["slug"], [])) >= 5][:10]
    chips = "".join(f'<li><a href="/{m["slug"]}/">{E(m["name"])}</a></li>' for m in pop)
    grades = "".join(f'<li class="gl-{k}"><b>{E(lab)}</b><small>{E(ex_)}</small></li>' for k, lab, ex_ in P.GRADES if k != "novy")
    shop_li = "".join(f'<li><a class="shop" href="/obchody/{s}/"><span class="bar" style="background:{SHOP[s]["color"]}"></span><div><b>{E(SHOP[s]["name"])}</b>'
                      f'<span class="muted">{nab(ctx["shop_count"][s])}</span></div></a></li>' for s in ctx["shop_ids"])
    items = [("Co je repasovaný iPhone?",
              "Použitý nebo vrácený telefon, který obchod vyčistil, otestoval a případně opravil (nejčastěji baterii nebo displej) a prodává ho se zárukou. "
              'Od bazarového kusu od soukromníka se liší hlavně zárukou a kontrolou. <a href="/pruvodce/repas-vs-bazar/">Repas, bazar, zánovní a rozbalený</a>'),
             ("Vyplatí se koupit repasovaný iPhone?",
              "Většinou ano: stejný model stojí o pětinu až polovinu méně než nový a iPhony dostávají aktualizace dlouho. Vybírejte model, který dostává aktuální iOS "
              "(iPhone 11 a novější), a hlídejte kondici baterie."),
             ("Odkud jsou ceny?",
              f"Z nabídek {shops} obchodů, které každou noc stahujeme z jejich produktových exportů. Nákup probíhá vždy přímo v obchodě."),
             ("Jakou záruku má repasovaný iPhone?",
              'Od obchodníka minimálně 12 měsíců (u použitého zboží ji smí zkrátit z 24 na 12 měsíců dohodou) a 14 dní na vrácení při nákupu přes internet. '
              '<a href="/pruvodce/zaruka/">Podrobně o záruce</a>')]
    body = f"""<section class="hero"><div class="hero-grid"><div><span class="stamp">Aktualizováno {date_cz(TODAY)}</span>
<h1>Repasovaný iPhone za férovou cenu</h1>
<p class="lead">Srovnáváme <strong>{nab(len(refurb))}</strong> repasovaných, zánovních a rozbalených iPhonů z {shops} {plural(shops, "obchodu", "obchodů", "obchodů")}.
Nejlevnější je k mání od <strong class="num">{kc(low)}</strong>. Jeden přehled stavů, baterie a ceny proti novému kusu.</p>
<ul class="chips">{chips}</ul></div>{ex}</div></section>
<h2>Vyberte model</h2>{"".join(fams)}
<h2>Jak čteme stav telefonu</h2><p class="prose">Každý obchod stav pojmenovává jinak (A-, třída B, „téměř výborný“…). Převádíme to na jednu stupnici, ať se dají nabídky porovnat.
<a href="/pruvodce/stavy/">Převodník stavů</a></p><ul class="grades">{grades}</ul>
<h2>Obchody ve srovnání</h2><ul class="shops">{shop_li}</ul>
<h2>Časté otázky</h2>{faq_html(items)}"""
    ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": BRAND, "url": SITE + "/"}, faq_ld(items)]
    title = f"Repasovaný iPhone – srovnání cen z {shops} obchodů | bazar i zánovní"
    desc = (f"{nab(len(refurb)).capitalize()} repasovaných a zánovních iPhonů od {kc(low)}. Porovnejte stav, baterii a cenu proti novému, "
            "ceny aktualizujeme každou noc.").replace(" ", " ")
    out.page("/", layout(ctx, path="/", title=title, desc=desc, body=body, ld=ld, active="/"))


def page_compare(out, ctx):
    rows = []
    for m in MODELS:
        of = ctx["by_model"].get(m["slug"])
        if not of:
            continue
        low = min(o["p"] for o in of)
        rows.append(f'<tr><td><a href="/{m["slug"]}/">{E(m["name"])}</a></td><td>{m["year"]}</td><td>{str(m["display"]).replace(".", ",")}″</td>'
                    f'<td>{E(m["chip"])}</td><td>{m["port"]}</td><td>{"ano" if ios_ok(m) else "ne"}</td><td>{"ano" if m.get("ai") else "ne"}</td>'
                    f'<td class="num">{kc(low)}</td><td>{len(of)}</td></tr>')
    body = f"""<section class="hero"><h1>Srovnání repasovaných iPhonů</h1>
<p class="lead">Všechny modely, které se teď dají koupit repasované, v jedné tabulce: rok uvedení, displej, čip, konektor, podpora aktuálního iOS a nejnižší cena.</p></section>
<div class="box"><div class="tscroll"><table class="matrix"><thead><tr><th>Model</th><th>Rok</th><th>Displej</th><th>Čip</th><th>Konektor</th><th>iOS 26/27</th>
<th>Apple Intelligence</th><th>Cena od</th><th>Nabídek</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></div>
<div class="prose"><h2>Jak tabulku číst</h2><p>Sloupec <strong>iOS 26/27</strong> říká, jestli model dostává aktuální systém. Apple ho vydává pro iPhone 11 a novější a pro iPhone SE
2. generace. Starší modely (X, XS, XR, 8) fungují dál, ale nové funkce a časem i některé aplikace jim chybí.</p>
<p><strong>Apple Intelligence</strong> (AI funkce v češtině zatím omezené) mají iPhony 15 Pro, celá řada 16 a novější. <strong>USB-C</strong> mají modely od iPhonu 15,
starší používají Lightning.</p><p>Nevíte, který vybrat? <a href="/jaky-iphone-koupit/">Doporučení podle rozpočtu</a></p></div>"""
    out.page("/srovnani/", layout(ctx, path="/srovnani/", title="Srovnání repasovaných iPhonů – parametry a ceny v jedné tabulce",
                                  desc="Všechny repasované iPhony v jedné tabulce: rok, displej, čip, konektor, podpora iOS 26 a 27 a nejnižší cena.",
                                  body=body, crumbs=[("/", "Repasované iPhony"), ("/srovnani/", "Srovnání")], active="/srovnani/"))


def page_buy(out, ctx):
    """Data-driven buying guide: the best model per budget tier from today's prices."""
    tiers = [(0, 6000, "do 6 000 Kč"), (6000, 10000, "6 000 až 10 000 Kč"), (10000, 15000, "10 000 až 15 000 Kč"),
             (15000, 22000, "15 000 až 22 000 Kč"), (22000, 10 ** 9, "nad 22 000 Kč")]
    sec = []
    for lo, hi, lab in tiers:
        cands = []
        for m in MODELS:
            of = [o for o in ctx["by_model"].get(m["slug"], []) if lo <= o["p"] < hi and o["g"] in ("jako-novy", "vyborny", "velmi-dobry")]
            if of and ios_ok(m):
                cands.append((m, min(of, key=lambda o: o["p"]), len(of)))
        cands.sort(key=lambda x: (-x[0]["year"], -("Pro" in x[0]["name"]), x[1]["p"]))
        if not cands:
            continue
        li = "".join(f'<li><a href="/{m["slug"]}/">{E(m["name"])}</a> od <strong class="num">{kc(o["p"])}</strong> '
                     f'<span class="muted">({P.gb_label(o["gb"])}, stav {E(P.GRADE[o["g"]][0].lower())}, {nab(n)} v tomto rozpočtu)</span></li>' for m, o, n in cands[:5])
        top = cands[0][0]
        sec.append(f'<h2>Rozpočet {lab}</h2><p>Nejnovější model, který se do rozpočtu vejde v dobrém stavu, je <strong>{E(top["name"])}</strong> ({top["year"]}, čip {E(top["chip"])}).</p><ul>{li}</ul>')
    body = f"""<section class="hero"><span class="stamp">Podle cen z {date_cz(TODAY)}</span><h1>Jaký iPhone koupit? Doporučení podle rozpočtu</h1>
<p class="lead">Žádné obecné rady: pro každý rozpočet ukazujeme nejnovější modely, které se do něj dnes vejdou v dobrém stavu a dostávají aktuální iOS.
Seznam se přepočítává každou noc podle skutečných nabídek.</p></section>
<div class="prose">{"".join(sec)}
<h2>Na co se dívat kromě ceny</h2><ul><li><strong>Podpora iOS:</strong> kupujte iPhone 11 nebo novější. Starší modely už aktuální iOS 26 a 27 nedostávají.</li>
<li><strong>Baterie:</strong> pod 80&nbsp;% kondice počítejte s výměnou. <a href="/pruvodce/baterie/">Jak číst kondici baterie</a></li>
<li><strong>Velikost:</strong> „Plus“ a „Pro Max“ mají displej 6,7″ a víc, „mini“ a SE jsou nejmenší.</li>
<li><strong>Konektor:</strong> od iPhonu 15 je USB-C, starší mají Lightning.</li></ul></div>"""
    out.page("/jaky-iphone-koupit/", layout(ctx, path="/jaky-iphone-koupit/", title="Jaký iPhone koupit v roce " + str(TODAY.year) + " – doporučení podle rozpočtu",
                                            desc="Který repasovaný iPhone koupit za 6, 10, 15 nebo 22 tisíc? Doporučení podle dnešních cen, podpory iOS a stavu.",
                                            body=body, crumbs=[("/", "Repasované iPhony"), ("/jaky-iphone-koupit/", "Jaký iPhone koupit")],
                                            active="/jaky-iphone-koupit/"))


def page_shops(out, ctx):
    li = "".join(f'<li><a class="shop" href="/obchody/{s}/"><span class="bar" style="background:{SHOP[s]["color"]}"></span><div><b>{E(SHOP[s]["name"])}</b>'
                 f'<span class="muted">{nab(ctx["shop_count"][s])}</span></div></a></li>' for s in ctx["shop_ids"])
    body = f"""<section class="hero"><h1>Obchody s repasovanými iPhony</h1><p class="lead">Odkud bereme nabídky a jak jednotlivé obchody označují stav telefonu.</p></section>
<ul class="shops">{li}</ul>"""
    out.page("/obchody/", layout(ctx, path="/obchody/", title="Obchody s repasovanými iPhony ve srovnání",
                                 desc="Přehled obchodů s repasovanými a zánovními iPhony: kolik nabídek mají, za kolik a jak značí stav.",
                                 body=body, crumbs=[("/", "Repasované iPhony"), ("/obchody/", "Obchody")], active="/obchody/"))
    info = json.loads((APP / "content/shops.json").read_text())
    for s in ctx["shop_ids"]:
        sh, of = SHOP[s], [o for o in ctx["refurb"] if o["shop"] == s]
        about = info.get(s, {})
        models = Counter(o["model"] for o in of).most_common(12)
        ml = "".join(f'<li><a href="/{k}/">{E(MODEL[k]["name"])}</a> <span class="muted">({n})</span></li>' for k, n in models)
        sg = Counter((o["sg"] or "–", o["g"]) for o in of).most_common()
        sgt = "".join(f'<tr><td>{E(a)}</td><td>{E(P.GRADE[g][0])}</td><td>{n}</td></tr>' for (a, g), n in sg)
        body = f"""<section class="hero"><h1>{E(sh["name"])}: repasované iPhony</h1><p class="lead">{about.get("lead", "")}</p></section>
<div class="cols"><div class="prose">{about.get("text", "")}
<h2>Jak {E(sh["name"])} značí stav</h2><table><thead><tr><th>Označení v obchodě</th><th>U nás</th><th>Nabídek</th></tr></thead><tbody>{sgt}</tbody></table>
<h2>Nejvíc nabídek</h2><ul>{ml}</ul></div>
<aside class="box"><dl class="specs"><dt>Nabídek</dt><dd>{len(of)}</dd><dt>Cena od</dt><dd class="num">{kc(min(o["p"] for o in of))}</dd>
<dt>Web</dt><dd>{E(sh["domain"])}</dd></dl></aside></div>
<h2>Nejlevnější nabídky</h2><ul class="offers">{"".join(tag_html(o, ctx) for o in sorted(of, key=lambda o: o["p"])[:12])}</ul>"""
        out.page(f"/obchody/{s}/", layout(ctx, path=f"/obchody/{s}/", title=f"{sh['name']} – repasované iPhony, stavy a ceny",
                                          desc=f"Repasované iPhony z {sh['name']}: {len(of)} nabídek od {kc(min(o['p'] for o in of))}, jak obchod značí stav a co nabízí.".replace(" ", " "),
                                          body=body, crumbs=[("/", "Repasované iPhony"), ("/obchody/", "Obchody"), (f"/obchody/{s}/", sh["name"])]),
                 index=len(of) >= 5)


def load_guides():
    gs = []
    for f in sorted((APP / "content/guides").glob("*.html")):
        txt = f.read_text()
        m = re.match(r"<!--(.*?)-->\s*", txt, re.S)
        meta = json.loads(m.group(1))
        meta["html"] = txt[m.end():]
        meta["slug"] = f.stem
        gs.append(meta)
    return sorted(gs, key=lambda g: g.get("order", 99))


def page_guides(out, ctx):
    li = "".join(f'<li><a href="/pruvodce/{g["slug"]}/"><h3>{E(g["h1"])}</h3><p>{E(g["desc"])}</p></a></li>' for g in ctx["guides"])
    li += '<li><a href="/jaky-iphone-koupit/"><h3>Jaký iPhone koupit podle rozpočtu</h3><p>Doporučení přepočítané každou noc podle skutečných cen.</p></a></li>'
    out.page("/pruvodce/", layout(ctx, path="/pruvodce/", title="Průvodce nákupem repasovaného iPhonu",
                                  desc="Stavy, baterie, záruka a kontrola po převzetí: vše, co potřebujete vědět před nákupem repasovaného iPhonu.",
                                  body=f'<section class="hero"><h1>Průvodce nákupem</h1><p class="lead">Krátce a k věci: co znamenají stavy, jak číst baterii a jaká práva máte.</p></section><ul class="glist">{li}</ul>',
                                  crumbs=[("/", "Repasované iPhony"), ("/pruvodce/", "Průvodce")], active="/pruvodce/"))
    for g in ctx["guides"]:
        path = f'/pruvodce/{g["slug"]}/'
        html_ = g["html"].replace("{{GRADE_TABLE}}", grade_table(ctx))
        others = "".join(f'<li><a href="/pruvodce/{x["slug"]}/">{E(x["short"])}</a></li>' for x in ctx["guides"] if x is not g)
        body = f'<article class="prose"><h1>{E(g["h1"])}</h1>{html_}</article><h2>Další průvodci</h2><ul class="chips">{others}</ul>'
        ld = [{"@context": "https://schema.org", "@type": "Article", "headline": g["h1"], "description": g["desc"], "inLanguage": "cs",
               "dateModified": g.get("updated", TODAY.isoformat()), "author": {"@type": "Organization", "name": BRAND, "url": SITE + "/o-webu/"}}]
        out.page(path, layout(ctx, path=path, title=g["title"], desc=g["desc"], body=body, ld=ld,
                              crumbs=[("/", "Repasované iPhony"), ("/pruvodce/", "Průvodce"), (path, g["short"])], active="/pruvodce/"))


def grade_table(ctx):
    seen = defaultdict(lambda: defaultdict(Counter))
    for o in ctx["refurb"]:
        if o["sg"]:
            seen[o["g"]][SHOP[o["shop"]]["name"]][o["sg"]] += 1
    rows = []
    for k, lab, ex in P.GRADES:
        if k == "novy":
            continue
        shops = "<br>".join(f'{E(s)}: ' + ", ".join(f"„{E(w)}“" for w, _ in ws.most_common()) for s, ws in sorted(seen[k].items())) or "–"
        rows.append(f"<tr><td><strong>{E(lab)}</strong><br><small>{E(ex)}</small></td><td>{shops}</td></tr>")
    return f'<table><thead><tr><th>Stav u nás</th><th>Jak ho píšou obchody</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'


def page_about(out, ctx):
    shops = ", ".join(SHOP[s]["name"] for s in ctx["shop_ids"])
    body = f"""<article class="prose"><h1>O webu</h1>
<p>Repasovanyiphone.cz je nezávislé srovnání repasovaných, zánovních a rozbalených iPhonů. Každou noc stáhneme produktové exporty obchodů
({E(shops)}), z názvu a parametrů rozpoznáme model, paměť, stav, barvu a baterii a nabídky seřadíme.</p>
<h2>Jak vyděláváme</h2><p>Když přes odkaz „Do obchodu“ nakoupíte, obchod nám může zaplatit provizi přes affiliate síť (eHub, CJ). Cenu pro vás to nemění
a pořadí nabídek neovlivňuje: řadíme podle ceny, stavu nebo baterie, jak si vyberete.</p>
<h2>Jak převádíme stavy</h2><p>Obchody používají vlastní stupnice. Převádíme je na pět stupňů (nový, jako nový, výborný, velmi dobrý, dobrý) a u každé nabídky
necháváme i původní označení obchodu. <a href="/pruvodce/stavy/">Převodník stavů</a></p>
<h2>Co nezaručujeme</h2><p>Ceny a dostupnost se mohou během dne změnit. Platí vždy údaj v obchodě, nákup i reklamace řešíte přímo s ním.</p>
<h2>Kontakt</h2><p>Chyba v nabídce, nový obchod nebo spolupráce: <a href="mailto:info@repasovanyiphone.cz">info@repasovanyiphone.cz</a></p></article>"""
    out.page("/o-webu/", layout(ctx, path="/o-webu/", title="O webu repasovanyiphone.cz – jak srovnáváme a jak vyděláváme",
                                desc="Jak funguje srovnání repasovaných iPhonů: odkud jsou data, jak převádíme stavy a jak web vydělává.",
                                body=body, crumbs=[("/", "Repasované iPhony"), ("/o-webu/", "O webu")]))


def page_404(out, ctx):
    pop = "".join(f'<li><a href="/{m["slug"]}/">{E(m["name"])}</a></li>' for m in MODELS if len(ctx["by_model"].get(m["slug"], [])) >= 5)
    body = f'<section class="hero"><h1>Tahle stránka neexistuje</h1><p class="lead">Nabídka mohla zmizet, telefony se rychle prodávají. Zkuste model:</p><ul class="chips">{pop}</ul></section>'
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
            if "|" not in k:
                per[k].append((f"{dd.day}. {dd.month}.", p))
    return per


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    offers, stats = P.load_all(APP / "data/raw", SHOPS)
    seen, uniq = set(), []
    for o in offers:
        if (o["shop"], o["id"]) not in seen:
            seen.add((o["shop"], o["id"]))
            uniq.append(o)
    offers = uniq
    refurb = [o for o in offers if not o["new"]]
    new_min = {}
    for o in offers:
        if o["new"]:
            k = (o["model"], o["gb"])
            new_min[k] = min(new_min.get(k, 10 ** 9), o["p"])
    # a "new" price below a refurbished one is a bad reference (grey import, mislabelled used phone): drop it
    for k, v in list(new_min.items()):
        rs = sorted(o["p"] for o in refurb if (o["model"], o["gb"]) == k)
        if rs and v < rs[len(rs) // 2]:
            del new_min[k]
    if len(refurb) < 50:
        sys.exit(f"only {len(refurb)} refurbished offers - refusing to build a near-empty site")
    go_tpl, go_stats = golinks.local_go([{"offers": refurb}])
    by_model = defaultdict(list)
    for o in refurb:
        by_model[o["model"]].append(o)
    sub_pages = {(m, gb) for m, of in by_model.items() for gb, n in Counter(o["gb"] for o in of).items() if n >= 2}
    shop_count = Counter(o["shop"] for o in refurb)

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    for p in (APP / "static").iterdir():
        if p.name == "assets":
            continue
        (shutil.copytree if p.is_dir() else shutil.copy)(p, DIST / p.name)
    ctx = {"refurb": refurb, "new_min": new_min, "by_model": by_model, "sub_pages": sub_pages, "shop_count": shop_count,
           "shop_ids": [s["id"] for s in SHOPS if shop_count.get(s["id"])], "guides": load_guides(), "hist_model": history(refurb)}
    ctx["css"] = asset("site.css", DIST)
    ctx["js_tag"] = f'<script src="{asset("app.js", DIST)}" defer></script>'
    out = Out(DIST)
    page_home(out, ctx)
    for m in MODELS:
        of = by_model.get(m["slug"])
        if not of:
            continue
        page_model(out, ctx, m, of)
        for gb in sorted({o["gb"] for o in of}):
            if (m["slug"], gb) in sub_pages:
                page_sub(out, ctx, m, gb, [o for o in of if o["gb"] == gb])
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
    out.write("robots.txt", ("User-agent: *\nDisallow: /\n" if STAGING else f"User-agent: *\nDisallow: /go/\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n"))
    key = os.environ.get("INDEXNOW_KEY", "")
    if key:
        out.write(f"{key}.txt", key)
    img_hosts = "https://wsrv.nl"
    out.write("_headers", f"""/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=(), interest-cohort=()
  X-Frame-Options: DENY
  Strict-Transport-Security: max-age=31536000; includeSubDomains
  Content-Security-Policy: default-src 'self'; img-src 'self' data: {img_hosts}{' https:' if GA4_ID else ''}; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'{' https://www.googletagmanager.com' if GA4_ID else ''}; connect-src 'self'{' https://*.google-analytics.com https://*.analytics.google.com https://www.googletagmanager.com' if GA4_ID else ''}; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'
/assets/*
  Cache-Control: public, max-age=31536000, immutable
/fonts/*
  Cache-Control: public, max-age=31536000, immutable
/go/*
  X-Robots-Tag: noindex, nofollow
""")
    (STATE / "page-hashes.json").write_text(json.dumps(out.new))
    (STATE / "changed.txt").write_text("\n".join(out.changed))
    rep = {"date": TODAY.isoformat(), "shops": stats, "refurb": len(refurb), "new_ref": len(new_min), "models": len(by_model),
           "pages": len(out.pages), "indexable": len(idx), "changed": len(out.changed), "go": go_stats}
    (STATE / "build-report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep))


if __name__ == "__main__":
    main()
