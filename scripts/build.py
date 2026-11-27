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
import i18n  # noqa: E402
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
        self.trs = [i18n.Tr(lang) for lang in i18n.ACTIVE]
        self.lpages = []                       # (lang, prefix, cs path, indexable)
        self.js_keys = []
        self.share = {}                        # "/ua/…" -> share of untranslated words

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def page(self, path, text, index=True):
        rel = path.strip("/") + "/index.html" if path != "/" else "index.html"
        self.write(rel, text)
        self.pages.append((path, index))
        for tr in self.trs:
            lt, li, sh = tr.translate(text, path, SITE, index and not STAGING, self.js_keys)
            note = I18N_NOTE.get(tr.lang, "") if ('id="cfg"' in text or path == "/") else ""
            lt = lt.replace("<!--l10n-note-->", note, 1)
            self.write(tr.pfx.strip("/") + "/" + rel, lt)
            self.lpages.append((tr.lang, tr.pfx, path, li))
            self.share[tr.pfx + path] = round(sh, 3)
        body = re.sub(r"<script.*?</script>", "", text, flags=re.S)
        body = re.sub(r"Ceny z \d+\. \w+ \d{4}|Aktualizováno \d+\. \w+ \d{4}|ceny z dnešní noci", "", body)   # the date alone is no change
        h = hashlib.md5(body.encode()).hexdigest()[:12]
        self.new[path] = h
        if self.old.get(path) != h or path not in self.lastmod:
            self.lastmod[path] = TODAY.isoformat()
            if index:
                self.changed.append(path)


def minify_css(css):
    """Drop comments and needless whitespace (the CSS is inlined into every page)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"\s+", " ", css)
    css = re.sub(r"\s*([{}:;,>])\s*", r"\1", css)
    return css.replace(";}", "}").strip()


def csp_hashes(root):
    """SHA-256 of every inline script that runs (not JSON / JSON-LD / speculation rules) across the built pages."""
    import base64
    hs = set()
    for f in root.rglob("*.html"):
        for attrs, code in re.findall(r"<script([^>]*)>(.*?)</script>", f.read_text(), re.S):
            if "src=" in attrs or "application/" in attrs:        # data, not code (speculation rules are hashed too: Chrome needs it next to 'strict-dynamic')
                continue
            hs.add("'sha256-" + base64.b64encode(hashlib.sha256(code.encode()).digest()).decode() + "'")
    return sorted(hs)


def asset(src, out):
    data = (APP / "static/assets" / src).read_bytes()
    name = f"{Path(src).stem}.{hashlib.md5(data).hexdigest()[:8]}{Path(src).suffix}"
    (out / "assets").mkdir(parents=True, exist_ok=True)
    (out / "assets" / name).write_bytes(data)
    return "/assets/" + name


# ---------------------------------------------------------------- layout

FONT_PRELOAD = '<link rel="preload" href="/fonts/cav-a.woff2" as="font" type="font/woff2" crossorigin>'
# instant page changes: prerender a link when the finger/mouse starts on it, prefetch visible cards; never the affiliate redirects
SPECULATION = ('<script type="speculationrules">' + json.dumps({
    "prerender": [{"where": {"and": [{"href_matches": "/*"}, {"not": {"href_matches": "/go/*"}}]}, "eagerness": "moderate"}],
    "prefetch": [{"where": {"and": [{"selector_matches": ".mcard, .cc-link, .chips a, .nav a"}, {"not": {"href_matches": "/go/*"}}]}, "eagerness": "eager"}],
}, separators=(",", ":")) + "</script>")


def logo_mark(size=34):
    return f'<img src="/img/ui/logo.webp" alt="" width="{size}" height="{size}">'


FOOT_MODELS = ["iphone-17-pro", "iphone-16", "iphone-15", "iphone-14", "iphone-13", "iphone-11", "iphone-12"]
FOOT_SHOP = [("/levny-iphone/", "Levné iPhony"), ("/iphone-bazar/", "iPhone bazar"), ("/zanovni-iphone/", "Zánovní iPhony"), ("/novy-iphone/", "Nové iPhony"),
             ("/srovnani/", "Srovnání modelů"), ("/jaky-iphone-koupit/", "Jaký iPhone koupit"),
             ("/ceny-iphonu/", "Vývoj cen"), ("/vykup-iphonu/", "Výkup iPhonu"), ("/iphone-na-splatky/", "iPhone na splátky")]
FOOT_GUIDES = [("co-znamena-repasovany-iphone", "Co je repasovaný iPhone"), ("stavy", "Kvalita A, B, C"), ("baterie", "Kondice baterie"),
               ("podpora-ios", "Podpora iOS"), ("iphone-z-bazaru", "iPhone z bazaru")]
NAV = [("/#modely", "Modely"), ("/levny-iphone/", "Levné iPhony"), ("/iphone-bazar/", "Bazar"), ("/zanovni-iphone/", "Zánovní"), ("/novy-iphone/", "Nové"), ("/srovnani/", "Srovnání"),
       ("/pruvodce/", "Průvodce")]


# Czech is the site; /ua/ and /ru/ are translated copies (scripts/i18n.py). hreflang uses "uk" for Ukrainian, the URL "ua".
LANG_ALT = [("cs", "")] + [(lg, "/" + i18n.LANGS[lg]) for lg in i18n.ACTIVE]
LANG_SW = [(h, p, (p.strip("/") or "cs").upper()) for h, p in LANG_ALT] if i18n.ACTIVE else []
# every language version is for people in Czechia (Czech shops, prices in Kč): hreflang language + region, never just "uk"/"ru",
# so Google does not offer /ua/ to searchers in Ukraine or /ru/ in Russia
HREFLANG = {"cs": "cs-CZ", "uk": "uk-CZ", "ru": "ru-CZ"}
# first visit with a Ukrainian/Russian browser (before Czech/Slovak in its list) -> the same page in that language; any choice in the
# switcher is remembered (ri-lang) and never overridden. Bots send no such language and stay on Czech.
LANG_AUTO = ('(function(){var d=document.documentElement;if(d.lang!=="cs")return;try{if(localStorage.getItem("ri-lang"))return}catch(e){return}'
             'var L=navigator.languages||[navigator.language||""];for(var i=0;i<L.length;i++){var l=String(L[i]).slice(0,2).toLowerCase();'
             'if(l==="cs"||l==="sk")return;var M=' + json.dumps({lg: i18n.LANGS[lg] for lg in i18n.ACTIVE}, separators=(",", ":")) + ';'
             'if(M[l]){location.replace("/"+M[l]+location.pathname+location.search+location.hash);return}}})();')

# RU/UA pages of the configurator and the homepage: how to buy in a Czech shop (written in the language, not translated)
I18N_NOTE = {lang: ((APP / f"content/i18n/note-{lang}.html").read_text() if (APP / f"content/i18n/note-{lang}.html").exists() else "") for lang in i18n.LANGS}


# Seznam Webmaster ownership tag (public by design, homepage only; Kenny 25. 11. 2026)
SEZNAM_WMT = '<meta name="seznam-wmt" content="aVqd5hujvnUVu19cMEtJuIQ4shXRjLgr">'


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
            # gtm.js loads when the browser is idle after the page has loaded (or at the first interaction), never inside a speculative prerender
            ga = (f'<meta name="ga4" content="{GA4_ID}"><script>{boot}dataLayer.push({{"gtm.start":Date.now(),event:"gtm.js"}});'
                  f'(function(){{var d=0;function l(){{if(d)return;d=1;var s=document.createElement("script");s.async=true;'
                  f's.src="https://www.googletagmanager.com/gtm.js?id={GA4_ID}";document.head.appendChild(s)}}'
                  f'function idle(){{(window.requestIdleCallback||function(f){{setTimeout(f,1)}})(l,{{timeout:3500}})}}'
                  f'function go(){{if(document.readyState==="complete")setTimeout(idle,3500);else addEventListener("load",function(){{setTimeout(idle,3500)}});'
                  f'["pointerdown","keydown","scroll","touchstart"].forEach(function(e){{addEventListener(e,l,{{once:true,passive:true}})}})}}'
                  f'if(document.prerendering)document.addEventListener("prerenderingchange",go,{{once:true}});else go()}})();</script>')
            noscript = (f'<noscript><iframe src="https://www.googletagmanager.com/ns.html?id={GA4_ID}" height="0" width="0" '
                        'style="display:none;visibility:hidden" title="GTM"></iframe></noscript>')
        else:
            ga = (f'<meta name="ga4" content="{GA4_ID}"><script>{boot}gtag("js",new Date());gtag("config","{GA4_ID}");</script>'
                  f'<script async src="https://www.googletagmanager.com/gtag/js?id={GA4_ID}"></script>')
    # footer: short on purpose (Kenny 25. 11.) - the full lists live on the hubs (/#modely, /pruvodce/, /obchody/)
    top_models = [MODEL[x] for x in FOOT_MODELS if ctx["by_model"].get(x)][:6]   # most searched (DataForSEO 25. 11.: "iphone N bazar/použitý")
    fm = "".join(f'<li><a href="/{m["slug"]}/">{E(m["name"])}</a></li>' for m in top_models)
    fm += '<li><a class="more" href="/#modely">Všechny modely →</a></li>'
    cats = "".join(f'<li><a href="{u}">{t}</a></li>' for u, t in FOOT_SHOP)
    have = {g["slug"] for g in ctx["guides"]}
    guides = "".join(f'<li><a href="/pruvodce/{u}/">{t}</a></li>' for u, t in FOOT_GUIDES if u in have)
    guides += '<li><a class="more" href="/pruvodce/">Všichni průvodci →</a></li>'
    alt = ("".join(f'<link rel="alternate" hreflang="{HREFLANG[h]}" href="{SITE}{p}{path}">' for h, p in LANG_ALT) +
           f'<link rel="alternate" hreflang="x-default" href="{SITE}{path}">') if i18n.ACTIVE else ""
    langs = "".join(f'<a href="{p}{path}" hreflang="{h}" lang="{h}" data-lang="{h}">{n}</a>' for h, p, n in LANG_SW)
    cfg_tag = f'<script type="application/json" id="cfg">{json.dumps(cfg, ensure_ascii=False, separators=(",", ":"))}</script>' if cfg else ""
    return f"""<!doctype html><html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{E(title)}</title><meta name="description" content="{E(desc)}"><link rel="canonical" href="{canon}"><meta name="robots" content="{robots}">
<meta property="og:type" content="website"><meta property="og:locale" content="cs_CZ"><meta property="og:site_name" content="{BRAND}">
<meta property="og:title" content="{E(title)}"><meta property="og:description" content="{E(desc)}"><meta property="og:url" content="{canon}"><meta property="og:image" content="{E(og_img or SITE + '/img/ui/og.png')}">
<meta name="twitter:card" content="summary_large_image">{SEZNAM_WMT if path == "/" else ""}{preload}
<style>{ctx['css']}</style>{FONT_PRELOAD if "hand" in body else ""}<link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="icon" href="/favicon-32.png" sizes="32x32">
<link rel="apple-touch-icon" href="/favicon-180.png"><link rel="manifest" href="/site.webmanifest"><meta name="theme-color" content="#FFFFFF">{alt}{f"<script>{LANG_AUTO}</script>" if i18n.ACTIVE else ""}{ldtxt}{ga}</head><body>{noscript}
<a class="skip" href="#obsah">Přeskočit na obsah</a>
<header class="top"><div class="wrap top-in"><a class="logo" href="/" aria-label="{BRAND} – úvod">{logo_mark()}<span>repasovaný <b>iPhone</b></span></a>
<nav class="nav" aria-label="Hlavní">{nav}</nav>{f'<nav class="langs" aria-label="Jazyk">{langs}</nav>' if langs else ""}</div></header>
{cr}<main id="obsah">{body}<!--l10n-note--></main>
<footer class="foot"><div class="wrap foot-in"><div class="about"><a class="logo" href="/">{logo_mark(30)}<span>repasovaný <b>iPhone</b></span></a>
<p>Každou noc srovnáme nabídky obchodů s repasovanými iPhony včetně slevových kódů. Za nákup přes odkaz můžeme dostat provizi, cenu ani pořadí to nemění.
<a href="/o-webu/">Jak web funguje</a></p></div>
<div><h2>Modely</h2><ul>{fm}</ul></div><div><h2>Nakupujte</h2><ul>{cats}</ul></div><div><h2>Průvodce</h2><ul>{guides}</ul></div></div>
<div class="wrap foot-legal"><a href="/o-webu/">O webu a kontakt</a><a href="/obchody/">Obchody ve srovnání</a><a href="/pro-obchody/">Pro obchody</a><a href="/ochrana-osobnich-udaju/">Ochrana osobních údajů</a>{'<a href="#" data-consent-open>Nastavení cookies</a>' if ga else ''}<span>© {TODAY.year} {BRAND}</span></div></footer>
{'<div class="consent" data-consentbar role="dialog" aria-label="Souhlas s cookies" hidden><p>Smíme měřit návštěvnost (Google Analytics)? Bez souhlasu nic neukládáme. <a href="/ochrana-osobnich-udaju/">Více</a></p><div><button type="button" class="btn sm" data-consent="yes">Souhlasím</button> <button type="button" class="btn sm ghost" data-consent="no">Nesouhlasím</button></div></div>' if ga else ''}
{cfg_tag}<script type="application/json" id="l10n">{{}}</script><script>{ctx['js']}</script>{SPECULATION}</body></html>"""


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


LOGO_RATIO = 3.6   # typical width/height of a shop logo
_LOGO_INK = {}


def _ink(sid):
    """(width/height, share of opaque pixels) of a logo file; a solid badge (MobileGear) counts as a wordmark (cap 0.45)."""
    if sid not in _LOGO_INK:
        from PIL import Image
        f = APP / "static/img/shops" / f"{sid}.webp"
        if not f.exists():
            _LOGO_INK[sid] = None
        else:
            im = Image.open(f).convert("RGBA")
            w, h = im.size
            _LOGO_INK[sid] = (w / h, min(0.45, sum(im.getchannel("A").getdata()) / 255 / (w * h)))
    return _LOGO_INK[sid]


def logo_k(sid):
    """Optical size factor so all shop logos look about equally big at the same nominal height: the geometric mean of
    equal bounding-box area (h ~ 1/sqrt(w/h)) and equal ink (h ~ 1/sqrt(w/h * opaque share), against the median logo).
    Thin wordmarks (iPhoneMarket) grow, wide or heavy ones (Smarty, iSTYLE) shrink. Clamped to 0.75-1.2."""
    me = _ink(sid)
    if not me:
        return 1.0
    allv = sorted(r * d for r, d in filter(None, (_ink(f.stem) for f in (APP / "static/img/shops").glob("*.webp"))))
    med = allv[len(allv) // 2]
    r, d = me
    k = ((LOGO_RATIO / r) ** 0.5 * (med / (r * d)) ** 0.5) ** 0.5
    return round(min(1.2, max(0.75, k)), 3)


def logo_src(sid):
    """Shop logo URL with a content hash: /img/* is cached for 30 days, a changed logo must not show the old file."""
    f = APP / "static/img/shops" / f"{sid}.webp"
    return f"/img/shops/{sid}.webp?v={hashlib.sha256(f.read_bytes()).hexdigest()[:8]}"

def shop_logo(sid, h=22):
    s = SHOP[sid]
    if (APP / "static/img/shops" / f"{sid}.webp").exists():
        k = logo_k(sid)
        return (f'<img class="slogo" src="{logo_src(sid)}" alt="{E(s["name"])}" width="{logo_w(sid, round(h * k))}" height="{round(h * k)}" '
                f'style="--k:{k}" loading="lazy" decoding="async">')
    return f'<span class="slogo stext" style="--c:{s["color"]}">{E(s["name"])}</span>'


def grade_chip(g):
    return f'<span class="gchip g-{g}" title="{E(GR[g]["name"])}">{E(GR[g]["short"])}</span>'


def href_attr(go):
    """Copy buttons carry the shop link: app.js opens this page with the code in a new tab and sends the current tab
    through /go/ (the coupon-site pattern), so a copied code still goes through our affiliate link."""
    return f' data-href="{E(go)}"' if go else ""


def coupon_box(c, go="", buttons=True):
    """Voucher ticket with copy button (app.js copies data-copy). buttons=False: just the code (the page has its own copy-and-go button)."""
    sm = re.match(r"/go/([a-z0-9-]+)/", go)
    btn = (f'<a class="btn sm" href="{E(go)}" rel="sponsored nofollow noopener" target="_blank" data-copy="{E(c["code"])}"'
           + (f' data-go="{sm.group(1)}"' if sm else "") + '>Do obchodu</a>') if go and buttons else ""
    shop_attr = f' data-shop="{sm.group(1)}"' if sm else ""
    copy_btn = f'<button type="button" class="cpn-copy" data-copy="{E(c["code"])}"{shop_attr}{href_attr(go)}>Kopírovat</button>' if buttons else ""
    return (f'<div class="cpn"><span class="cpn-k">Slevový kód</span><code data-kod="{E(c["code"])}">{E(c["code"])}</code>'
            f'{copy_btn}{btn}'
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
                    "itemCondition": cond, "availability": "https://schema.org/InStock",
                    "eligibleRegion": {"@type": "Country", "name": "CZ"}}}
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

def offer_facts(o):
    """What the buyer gets with this offer, for the offer card: (battery, battery level, warranty, warranty level, type, shipping, proven).
    Sources, in this order: the offer text (parse.battery_info / warranty_of), then the shop's own terms for that grade
    (data/shops.json "terms", read on the shop's website, see "src" and "checked"). Nothing is assumed: unknown stays "neuvádí".
    Levels: "ok" = documented, "info" = stated only as an average or on the shop's page, "no" = not stated."""
    t = SHOP[o["shop"]].get("terms") or {}
    sg = (o.get("sg") or "").strip()
    st = t.get("sg", {}).get(sg.lower()) or t.get("sg", {}).get("*") or {}
    kind, val = o.get("batk") or (None, None)
    if not kind and st.get("bat"):
        kind, val = st["bat"]
    war = o.get("war") or st.get("war") or 0
    novy = o["g"] == "novy"
    if novy:
        bat, bl = "", "ok"
    elif kind == "kus":
        bat, bl = f"Baterie tohoto kusu {val}\u00a0%", "ok"
    elif kind == "nova":
        bat, bl = "Nová baterie", "ok"
    elif kind == "min":
        bat, bl = (f"Baterie {val}\u00a0% podle prodejce" if int(val) >= 100 else f"Prodejce garantuje baterii min. {val}\u00a0%"), "ok"
    elif kind == "avg":
        bat, bl = f"Baterie v průměru {val}\u00a0% (údaj prodejce pro tento stav)", "info"
    elif kind == "web":
        bat, bl = "Kondici baterie prodejce uvádí u kusu na svém webu", "info"
    else:
        bat, bl = "Kondici baterie prodejce v nabídce neuvádí", "no"
    if war:
        wt, wl = f"Záruka {war} měsíců", "ok"
    elif t.get("market"):
        wt, wl = "Záruka podle prodejce na tržišti", "no"
    else:
        wt, wl = "Záruku nabídka neuvádí", "no"
    if novy:
        typ = "Nový, nerozbalený kus"
    else:
        typ = f"Stav {GR[o['g']]['short']} ({GR[o['g']]['name'].lower()})" + (f", u prodejce „{sg}“" if sg and sg.lower() != GR[o["g"]]["name"].lower() else "")
    if t.get("market"):
        typ += f", nabídka z tržiště {SHOP[o['shop']]['name']}"
    proven = not novy and kind in ("kus", "nova", "min") and int(val or 0) >= 80 and war > 0
    bs = ("nový kus" if novy else f"baterie {val}\u00a0%" if kind == "kus" or (kind == "min" and int(val) >= 100) else "nová baterie" if kind == "nova"
          else f"baterie min. {val}\u00a0%" if kind == "min" else f"baterie ø\u00a0{val}\u00a0%" if kind == "avg"
          else "baterie na webu obchodu" if kind == "web" else "baterie neuvedena")
    short = bs + " · " + (f"záruka {war}\u00a0měs." if war else "záruka neuvedena")
    return (bat, bl, wt, wl, typ, t.get("ship", ""), 1 if proven else 0, short)


def facts_html(f):
    """Same markup as facts() in app.js."""
    bat, bl, wt, wl, typ, ship = f[:6]
    li = ([f'<li class="of of-b {bl}">{E(bat)}</li>'] if bat else []) + [f'<li class="of of-w {wl}">{E(wt)}</li>', f'<li class="of of-t">{E(typ)}</li>']
    if ship:
        li.append(f'<li class="of of-d">{E(ship[0].upper() + ship[1:])}</li>')
    return f'<ul class="ofacts">{"".join(li)}</ul>'


def cfg_data(ctx, m, offers, gb_pref=None, gkey=None):
    """Compact JSON for app.js. Rows: [colour i, storage i, grade, shop price, shop, go, battery, eSIM, price after code, facts i]; sorted by price after code.
    "f": distinct offer facts (offer_facts()), "low": cheapest refurbished combination of the page (set by page_model).
    No shop wording: quality is our scale only."""
    slug = m["slug"]
    gk = gkey or (lambda o: o["g"])     # the zánovní configurator passes its own step 3 (rozbalený / zánovní)
    cols = [c for c in P.COLORS.get(slug, []) if any(o["col"] == c["key"] for o in offers)]
    gbs = sorted({o["gb"] for o in offers})
    ci = {c["key"]: i for i, c in enumerate(cols)}
    gi = {g: i for i, g in enumerate(gbs)}
    shops = sorted({o["shop"] for o in offers})
    rows, fidx = [], {}
    for o in sorted(offers, key=lambda o: (o["pc"], o["p"])):
        go = o["go"]
        pre = f"/go/{o['shop']}/?u="
        go = "~" + go[len(pre):] if go.startswith(pre) else go    # "~" = only the shop path; app.js / go_url() put /go/<shop>/?u= back
        f = offer_facts(o)
        if f not in fidx:
            fidx[f] = len(fidx)
        rows.append([ci[o["col"]], gi[o["gb"]], gk(o), o["p"], o["shop"], go, o["bat"] or 0, 1 if o["esim"] else 0, o["pc"], fidx[f]])
    rf = [o for o in offers if o["g"] != "novy"] or offers
    dgb = gb_pref if gb_pref in gi else Counter(o["gb"] for o in rf).most_common(1)[0][0]
    pool = [o for o in rf if o["gb"] == dgb] or [o for o in offers if o["gb"] == dgb]
    dcol = Counter(o["col"] for o in pool).most_common(1)[0][0]
    here = [o for o in offers if o["gb"] == dgb and o["col"] == dcol]
    gs = {gk(o) for o in here}
    dg = "a" if "a" in gs else gk(min(here, key=lambda o: o["pc"]))
    shop_meta = {s: [SHOP[s]["name"], logo_src(s) if (APP / "static/img/shops" / f"{s}.webp").exists() else "", SHOP[s]["color"], logo_w(s, 22) / 22,
                     logo_k(s)] for s in shops}
    cps = {}
    for s in shops:
        for c in ctx["coupons"].get(s, []):
            if c["auto"]:
                cps[s] = [c["code"], c["label"], until_cz(c)]
                break
    return {"m": slug, "name": m["name"], "cols": [[c["key"], c["name"], c["hex"], photo(ctx, slug, c["key"], 600)] for c in cols],
            "gbs": gbs, "shops": shop_meta, "newp": {str(gb): ctx["new_min"][(slug, gb)] for gb in gbs if (slug, gb) in ctx["new_min"]},
            "grades": {k: [v["short"], v["name"], v["ex"]] for k, v in GR.items()}, "gimg": GIMG, "cp": cps, "o": rows, "def": [dcol, dgb, dg],
            "f": [list(f) for f in fidx]}


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
    G = cfg["grades"]
    for g in cfg.get("order") or [k for k, *_r in P.GRADES]:
        ps = [r[8] for r in here if r[2] == g]
        gcards.append(f'<button type="button" class="gcard{" on" if g == dg else ""}{"" if ps else " off"}" data-g="{g}" aria-pressed="{str(g == dg).lower()}"{"" if ps else " disabled"}>'
                      f'<span class="gl g-{g}">{E(G[g][0])}</span><span class="gn">{E(G[g][1])}</span>'
                      f'<span class="gp">{"od " + kc(min(ps)) if ps else "není skladem"}</span></button>')
    res = [r for r in here if r[2] == dg]
    s3 = cfg.get("step3") or ("Kvalita", "/pruvodce/stavy/", "co znamená A, B, C?")
    gimg = cfg["gimg"]
    alt = f"{m['name']} v barvě {cols[ci][1]}"
    return f"""<section class="cfg" data-cfg aria-label="Výběr iPhonu">
<div class="cfg-photo"><div class="ph"><img src="{E(cols[ci][3])}" alt="{E(alt)}" width="600" height="600" fetchpriority="high" data-photo></div></div>
<div class="cfg-steps">
<div class="step"><h2 class="step-h"><span class="n">1</span>Barva <span class="step-v" data-v-col>{E(cols[ci][1])}</span></h2><div class="sws" data-cols>{sw}</div></div>
<div class="step"><h2 class="step-h"><span class="n">2</span>Paměť</h2><div class="pills" data-gbs>{pills}</div></div>
<div class="step"><h2 class="step-h"><span class="n">3</span>{E(s3[0])} <a class="step-help" href="{s3[1]}">{E(s3[2])}</a></h2>
<div class="gcards{" two" if cfg.get("order") and len(cfg["order"]) == 2 else ""}" data-grades>{"".join(gcards)}</div><p class="ghint"><img data-gimg src="/img/ui/grade-{dg if dg in gimg else "a"}.webp" alt="" width="64" height="64"{"" if dg in gimg else " hidden"}><span data-ghint>{E(G[dg][2]).capitalize()}.</span></p></div>
<div class="result" data-result aria-live="polite">{result_html(cfg, res, dgb)}</div>
</div></section>"""


def result_html(cfg, res, gb):
    """Same markup as result() in app.js."""
    if not res:
        return '<p class="empty">Tahle kombinace teď není skladem. Zkuste jinou barvu nebo kvalitu.</p>'
    best = res[0]
    F = cfg["f"]
    newp = cfg["newp"].get(str(gb))
    sh, cps = cfg["shops"], cfg["cp"]
    save = f'<span class="save hand">o {kc(newp - best[8])} levněji než nový</span>' if newp and newp > best[8] and best[2] != "novy" else ""
    was = f'<span class="was">{kc(best[3])} v obchodě</span>' if best[8] < best[3] else ""
    low = cfg.get("low")
    lowl = ""
    if low and best[8] > low[3]:
        cname = next((c[1] for c in cfg["cols"] if c[0] == low[0]), "")
        lowl = (f'<a class="lowlink" href="?barva={low[0]}&amp;pamet={low[1]}&amp;kvalita={low[2]}" data-low>Nejlevnější {E(cfg["name"])} za <b>{kc(low[3])}</b>'
                f' · stav {E(cfg["grades"][low[2]][0])}, {P.gb_label(low[1])}, {E(cname.lower())}</a>')
    cp = cps.get(best[4]) if best[8] < best[3] else None
    cbox = (f'<div class="cpn"><span class="cpn-k">Slevový kód</span><code>{E(cp[0])}</code><button type="button" class="cpn-copy" data-copy="{E(cp[0])}" data-shop="{best[4]}"{href_attr(go_url(best))}>Kopírovat</button>'
            f'<small>{E(cp[1])} · {E(cp[2])} · zadejte v košíku</small></div>') if cp else ""
    per_shop = {}
    for r in res:
        per_shop.setdefault(r[4], r)
    others = [r for r in per_shop.values() if r is not best]

    def chip(r):
        c = cps.get(r[4]) if r[8] < r[3] else None
        return (f'<button type="button" class="cchip" data-copy="{E(c[0])}" data-shop="{r[4]}" data-sp="chip"{href_attr(go_url(r))} aria-label="Kopírovat slevový kód {E(c[0])}">'
                f'<span>{E(c[0])}</span>{COPY_ICON}</button>') if c else ""

    def short(r):
        return f'<span class="o-f">{E(F[r[9]][7])}</span>'
    olist = "".join(f'<li><span class="o-shop">{shop_mini(sh, r[4])}{short(r)}</span><span class="o-cp">{chip(r)}</span>'
                    f'<span class="o-p"><b>{kc(r[8])}</b>{f"<s>{kc(r[3])}</s>" if r[8] < r[3] else ""}</span>'
                    f'<a class="btn sm ghost" href="{E(go_url(r))}" rel="sponsored nofollow noopener" target="_blank" data-go="{r[4]}" data-price="{r[8]}" data-sp="alt"'
                    f'{(" data-copy=" + chr(34) + E(cps[r[4]][0]) + chr(34)) if r[8] < r[3] and r[4] in cps else ""}>Do obchodu</a></li>'
                    for r in others)
    near = next((r for r in others if r[8] < r[3] and r[4] in cps and r[8] <= best[8] * 1.03), None) if not cp else None
    hint = (f'<p class="cphint"><span class="hand">Radši se slevovým kódem?</span> {E(sh[near[4]][0])} s kódem {chip(near)} '
            f'za {kc(near[8])}{f" (jen o {kc(near[8] - best[8])} víc)" if near[8] > best[8] else ""}</p>') if near else ""
    pr = None if F[best[9]][6] else next((r for r in res if F[r[9]][6]), None)
    proven = ""
    if pr:
        pc = cps.get(pr[4]) if pr[8] < pr[3] else None
        proven = (f'<div class="proven"><p class="pv-k">Nejlevnější s doloženou baterií a zárukou</p>'
                  f'<div class="pv-row">{shop_mini(sh, pr[4])}<span class="pv-p"><b>{kc(pr[8])}</b><small>o {kc(pr[8] - best[8])} víc</small></span>'
                  f'<a class="btn sm" href="{E(go_url(pr))}" rel="sponsored nofollow noopener" target="_blank" data-go="{pr[4]}" data-price="{pr[8]}" data-sp="proven"'
                  + (f' data-copy="{E(pc[0])}"' if pc else "") + f'>Do obchodu</a></div>{facts_html(F[pr[9]])}</div>')
    cta = f"Koupit s kódem u {E(sh[best[4]][0])}" if cp else f"Koupit u {E(sh[best[4]][0])}"
    return (f'<div class="best"><div class="best-top"><span class="best-k">Nejlevněji</span>{shop_mini(sh, best[4], 26)}</div>'
            f'<p class="best-p"><span class="price">{kc(best[8])}</span>{was}{save}</p>{lowl}'
            + facts_html(F[best[9]]) + ('<p class="best-f">jen eSIM</p>' if best[7] else "") + cbox
            + f'<a class="btn big" href="{E(go_url(best))}" rel="sponsored nofollow noopener" target="_blank" data-go="{best[4]}" data-price="{best[8]}" data-sp="best"'
            + (f' data-copy="{E(cp[0])}"' if cp else "") + f'>{cta}</a>'
            f'<p class="best-n">{nab(len(res))} v této konfiguraci</p>'
            + (f'<a class="loanrow" href="{LOAN}?z={cfg["m"]}" data-loan="card">{HC_LOGO.format(w=40, h=17)}<span>Chcete platit postupně? <b>iPhone na splátky</b></span></a>'
               if best[8] >= LOAN_MIN else "")
            + '</div>' + repup_html(cfg, best, best[0], best[1]) + proven + hint
            + (f'<div class="alts"><h3>Další obchody</h3><ul>{olist}</ul></div>' if olist else ""))


COPY_ICON = ('<svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2.5" fill="none" stroke="currentColor" stroke-width="2"/>'
             '<path d="M5 15V6a2 2 0 0 1 2-2h9" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>')


def shop_mini(shops, sid, h=22):
    name, logo, color, ratio, k = shops[sid]
    if logo:
        hk = round(h * k)
        return f'<img class="slogo" src="{logo}" alt="{E(name)}" width="{round(ratio * hk)}" height="{hk}" style="--k:{k}" loading="lazy" decoding="async">'
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
    t = [f'<p>Právě teď srovnáváme <strong>{nab(len(rf))}</strong> repasovaného, zánovního nebo bazarového {E(m["name"])} '
         f'z {"obchodu" if len(shops) == 1 else "obchodů"} {E(", ".join(shops))}. Nejlevnější kus stojí <strong>{kc(low)}</strong>, nejčastěji se prodává verze s {P.gb_label(gb_c)}.</p>']
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
    return "".join(t) + model_text_more(ctx, m, offers)


# Vodafone (eHub, PPL tariff order / lead / prepaid). Text links only, no logo; click_shop event with shop=vodafone (data-go).
VODAFONE_AFF = "https://ehub.cz/system/scripts/click.php?a_aid=052443b7&a_bid=aface625"
VODAFONE = "/go/vodafone/"    # the affiliate URL lives only in go/vodafone/index.html


def vf(text, place):
    return f'<a href="{VODAFONE}" rel="sponsored nofollow noopener" target="_blank" data-go="vodafone" data-place="{place}">{text}</a>'


LAST_IOS = {"iphone-7": "iOS 15", "iphone-7-plus": "iOS 15", "iphone-8": "iOS 16", "iphone-8-plus": "iOS 16", "iphone-x": "iOS 16",
            "iphone-xs": "iOS 18", "iphone-xs-max": "iOS 18", "iphone-xr": "iOS 18"}


def tier(m):
    n = m["name"]
    for t in ("Pro Max", "Pro", "Plus", "mini", "Air"):
        if n.endswith(" " + t):
            return t
    if "SE" in n:
        return "SE"
    return "e" if re.search(r"\de$", n) else "base"


def neighbours(ctx, m):
    """Previous and next generation in the same tier that is on sale (for the 'older or newer?' paragraph)."""
    same = [x for x in MODELS if tier(x) == tier(m) and x["slug"] != m["slug"] and ctx["by_model"].get(x["slug"])]
    prev = max((x for x in same if x["year"] < m["year"]), key=lambda x: x["year"], default=None)
    nxt = min((x for x in same if x["year"] > m["year"]), key=lambda x: x["year"], default=None)
    return prev, nxt


def spec_diffs(a, b):
    """What model b has over a (plain Czech phrases, only from models.json)."""
    d = []
    if a["chip"] != b["chip"]:
        d.append(f'čip {b["chip"]} místo {a["chip"]}')
    if a["port"] != b["port"]:
        d.append(f'{b["port"]} místo {a["port"]}')
    if (b.get("hz") or 60) > (a.get("hz") or 60):
        d.append(f'{b["hz"]}Hz displej')
    if b.get("ai") and not a.get("ai"):
        d.append("Apple Intelligence")
    if b["display"] != a["display"]:
        d.append(f'{"větší" if b["display"] > a["display"] else "menší"} displej ({str(b["display"]).replace(".", ",")}″ proti {str(a["display"]).replace(".", ",")}″)')
    if a["bio"] != b["bio"]:
        d.append(f'{b["bio"]} místo {a["bio"]}')
    if ios_ok(b) and not ios_ok(a):
        d.append("aktuální iOS")
    return d


def low_of(ctx, slug, grades=None):
    of = [o for o in ctx["by_model"].get(slug, []) if (o["g"] != "novy" if grades is None else o["g"] in grades)]
    return min((o["pc"] for o in of), default=None)


def model_text_more(ctx, m, offers):
    """Second half of the model text: price by quality, battery, older/newer generation, what to watch out for."""
    rf = [o for o in offers if o["g"] != "novy"] or offers
    t = []
    by_g = defaultdict(list)
    for o in rf:
        by_g[o["g"]].append(o["pc"])
    if len(by_g) > 1:
        li = "".join(f'<li><strong>{E(GR[g]["name"])} ({E(GR[g]["short"])}):</strong> {nab(len(v))}, od {kc(min(v))}, '
                     f'běžně kolem {kc(sorted(v)[len(v) // 2])}</li>' for g, v in sorted(by_g.items(), key=lambda x: P.GRADE_ORDER[x[0]]))
        t.append(f'<h3>Kolik stojí použitý {E(m["name"])} podle kvality</h3><ul>{li}</ul>'
                 '<p>Kvalita popisuje jen vzhled. Pokud telefon nosíte v obalu, horší kvalita ušetří peníze bez rozdílu v používání. '
                 '<a href="/pruvodce/stavy/">Co znamenají kvality A+, A, B a C</a></p>')
    bats = [o["bat"] for o in rf if o["bat"]]
    if len(bats) >= 3:
        hi = sum(1 for b in bats if b >= 90)
        t.append(f'<p>U nabídek, které kondici baterie uvádějí, je typická hodnota <strong>{sorted(bats)[len(bats) // 2]}&nbsp;%</strong> '
                 f'a {hi} z {len(bats)} má 90&nbsp;% a víc.</p>')
    prev, nxt = neighbours(ctx, m)
    for other, older in ((prev, True), (nxt, False)):
        if not other:
            continue
        lo, lm = low_of(ctx, other["slug"]), low_of(ctx, m["slug"])
        if not lo or not lm:
            continue
        a, b = (other, m) if older else (m, other)
        diffs = spec_diffs(a, b)
        dtxt = f' Novější {E(b["name"])} přináší {", ".join(diffs)}.' if diffs else ""
        cmp_link = vs_link(a["slug"], b["slug"])
        t.append(f'<p><strong>{"Starší" if older else "Novější"} {link_m(other, "")}</strong> ({other["year"]}) stojí z druhé ruky od {kc(lo)}, '
                 f'tedy o {kc(abs(lo - lm))} {"méně" if lo < lm else "víc"}.{dtxt}'
                 + (f' <a href="{cmp_link}">{E(a["name"])} vs. {E(b["name"])}: podrobné srovnání</a>' if cmp_link else "") + '</p>')
    warn = []
    if not ios_ok(m):
        warn.append(f'<li><strong>Bez aktuálního iOS:</strong> poslední systém je {LAST_IOS.get(m["slug"], "starší verze")}. Bankovní a další aplikace časem přestanou fungovat. '
                    '<a href="/pruvodce/podpora-ios/">Které iPhony mají podporu</a></li>')
    if m["year"] >= 2022 and tier(m) != "SE":
        warn.append('<li><strong>Verze jen s eSIM:</strong> kusy z USA nemají slot na SIM kartu. Fungují s eSIM českých operátorů, ale fyzickou kartu nevložíte.</li>')
    if m["port"] != "USB-C":
        warn.append("<li><strong>Lightning:</strong> nabíjí se starším kabelem Lightning, ne USB-C jako modely od iPhonu 15.</li>")
    warn.append('<li><strong>Vyměněné díly:</strong> v Nastavení → Obecné → Informace → Díly a historie servisu uvidíte, jestli má telefon neoriginální displej nebo baterii. '
                '<a href="/pruvodce/dily-a-historie-servisu/">Jak to číst</a></li>')
    warn.append('<li><strong>Zámek aktivace:</strong> u kusu z bazaru trvejte na tom, aby se prodávající před vámi odhlásil z Apple ID a telefon vymazal. '
                '<a href="/pruvodce/kontrola-imei-icloud/">Kontrola IMEI a iCloudu</a></li>')
    t.append(f'<h3>Na co si dát pozor u {E(m["name"])} z druhé ruky</h3><ul>{"".join(warn)}</ul>')
    return "".join(t)



def tariff_box(m):
    """Quiet partner box under the spec sheet: phone bought separately -> SIM-only tariff (Vodafone affiliate)."""
    esim = " Pokud kupujete kus jen s eSIM, operátor vám ji vydá rovnou k tarifu." if m["year"] >= 2022 else ""
    return (f'<div class="card tbox"><h2>Tarif k iPhonu</h2><p>Telefon kupujete zvlášť, takže ho nemusíte splácet operátorovi v paušálu. '
            f'Stačí samotný tarif s daty, třeba od {vf("Vodafonu", "model-box")}.{esim}</p>'
            '<p><a href="/pruvodce/tarif-k-iphonu/">Telefon zvlášť, tarif zvlášť: proč se to vyplatí</a></p></div>')


def model_reading(ctx, m):
    """Guides worth reading before buying this model + comparisons it appears in."""
    g = [("/pruvodce/stavy/", "Co znamená kvalita A, B, C"), ("/pruvodce/baterie/", "Kondice baterie"), ("/pruvodce/kontrola/", "Kontrola po převzetí")]
    if not ios_ok(m):
        g.insert(0, ("/pruvodce/podpora-ios/", "Podpora iOS"))
    g.append(("/pruvodce/iphone-z-bazaru/", "iPhone z bazaru bezpečně"))
    have = {x["slug"] for x in ctx["guides"]}
    gl = "".join(f'<li><a href="{u}">{E(n)}</a></li>' for u, n in g if u.split("/")[2] in have)
    vs = "".join(f'<li><a href="/srovnani/{a}-vs-{b}/">{E(MODEL[a]["name"])} vs. {E(MODEL[b]["name"])}</a></li>' for a, b in VS_PAIRS if m["slug"] in (a, b))
    return ((f'<section class="sec"><h2>Před nákupem si přečtěte</h2><ul class="chips">{gl}</ul></section>' if gl else "")
            + (f'<section class="sec"><h2>Srovnání s jinými modely</h2><ul class="chips">{vs}</ul></section>' if vs else ""))


VS_PAIRS = [("iphone-13", "iphone-14"), ("iphone-14", "iphone-15"), ("iphone-15", "iphone-16"), ("iphone-16", "iphone-17"), ("iphone-13", "iphone-15"),
            ("iphone-15", "iphone-15-pro"), ("iphone-16", "iphone-16e"), ("iphone-se-2020", "iphone-se-2022"), ("iphone-12-mini", "iphone-13-mini"),
            ("iphone-17", "iphone-17-pro"), ("iphone-17", "iphone-air"), ("iphone-17-pro", "iphone-17-pro-max"), ("iphone-16-pro", "iphone-17-pro"),
            ("iphone-17", "iphone-17e"), ("iphone-15-pro", "iphone-16-pro"), ("iphone-16", "iphone-16-pro"), ("iphone-14-pro", "iphone-15-pro"),
            ("iphone-13", "iphone-13-pro"), ("iphone-11", "iphone-12"), ("iphone-12", "iphone-13"), ("iphone-15", "iphone-16e")]


VS_NOTES = {
    ("iphone-13", "iphone-14"): "iPhone 14 má stejný čip A15 Bionic, ale s pětijádrovou grafikou, lepší hlavní fotoaparát, přední kameru s automatickým ostřením a detekci autonehody. Kusy z USA jsou od iPhonu 14 jen s eSIM.",
    ("iphone-14", "iphone-15"): "iPhone 15 přidává Dynamic Island místo výřezu, 48Mpx hlavní fotoaparát a USB-C.",
    ("iphone-15", "iphone-16"): "iPhone 16 přidává tlačítko Akce a tlačítko Ovládání fotoaparátu.",
    ("iphone-16", "iphone-17"): "iPhone 17 má větší displej s plynulými 120 Hz a základní paměť 256 GB.",
    ("iphone-13", "iphone-15"): "Mezi nimi jsou dvě generace: iPhone 15 má Dynamic Island, 48Mpx hlavní fotoaparát a USB-C.",
    ("iphone-15", "iphone-15-pro"): "Verze Pro má titanový rám, teleobjektiv, tlačítko Akce a rychlejší USB-C.",
    ("iphone-16", "iphone-16e"): "iPhone 16e je levnější varianta: má jen jeden zadní fotoaparát, výřez místo Dynamic Island a nepodporuje MagSafe. Čip A18 a Apple Intelligence má stejně jako iPhone 16.",
    ("iphone-se-2020", "iphone-se-2022"): "SE 2022 vypadá stejně, ale má rychlejší čip A15 Bionic, 5G a delší výdrž baterie.",
    ("iphone-12-mini", "iphone-13-mini"): "iPhone 13 mini má výrazně delší výdrž baterie, menší výřez v displeji a základní paměť 128 GB.",
    ("iphone-17", "iphone-17-pro"): "Verze Pro má čip A19 Pro, trojitý fotoaparát s teleobjektivem a výkonnější chlazení.",
    ("iphone-17", "iphone-air"): "iPhone Air je extrémně tenký, má jen jeden zadní fotoaparát a funguje výhradně s eSIM.",
    ("iphone-17-pro", "iphone-17-pro-max"): "Pro Max má větší displej a delší výdrž baterie, jinak stejnou výbavu.",
    ("iphone-16-pro", "iphone-17-pro"): "iPhone 17 Pro přechází z titanu na hliníkové tělo a má novou generaci čipu a fotoaparátů.",
    ("iphone-15-pro", "iphone-16-pro"): "iPhone 16 Pro má větší displej, tlačítko Ovládání fotoaparátu a pětinásobný teleobjektiv i u menší verze.",
    ("iphone-16", "iphone-16-pro"): "Verze Pro má titanový rám, teleobjektiv a displej s funkcí Always-On.",
    ("iphone-14-pro", "iphone-15-pro"): "iPhone 15 Pro má titanový rám, tlačítko Akce a rychlejší USB-C.",
    ("iphone-13", "iphone-13-pro"): "Verze Pro má teleobjektiv a umí makro fotografie.",
    ("iphone-11", "iphone-12"): "iPhone 12 má OLED displej místo LCD, 5G, MagSafe a odolnější sklo Ceramic Shield.",
    ("iphone-12", "iphone-13"): "iPhone 13 má delší výdrž baterie, menší výřez a základní paměť 128 GB místo 64 GB.",
    ("iphone-15", "iphone-16e"): "iPhone 16e má navíc tlačítko Akce, ale jen jeden zadní fotoaparát, výřez místo Dynamic Island a nepodporuje MagSafe.",
}


def vs_link(a, b):
    if (a, b) in VS_PAIRS:
        return f"/srovnani/{a}-vs-{b}/"
    if (b, a) in VS_PAIRS:
        return f"/srovnani/{b}-vs-{a}/"
    return ""


def vs_verdict(older, newer, lo_old, lo_new, diffs):
    years = newer["year"] - older["year"]
    if not (lo_new and lo_old):
        return "Jeden z modelů teď z druhé ruky není skladem, ceny se aktualizují každou noc."
    if lo_new <= lo_old:
        return f'{E(newer["name"])} je dnes z druhé ruky stejně drahý nebo levnější, takže je jasná volba.'
    pct = round((lo_new - lo_old) / lo_old * 100)
    s = f'Za {E(newer["name"])} připlatíte zhruba {pct}&nbsp;%. '
    if years > 0:
        s += f'Je o {years} {plural(years, "rok", "roky", "let")} mladší, takže aktualizace iOS dostane o něco déle. '
    if pct < 15:
        s += f'Při tak malém rozdílu se vyplatí sáhnout po {E(newer["name"])}.'
    elif diffs:
        s += f'Pokud nepotřebujete {", ".join(diffs[:2])}, {E(older["name"])} je rozumnější nákup.'
    else:
        s += f'Rozhoduje rozpočet: {E(older["name"])} je levnější, {E(newer["name"])} vydrží déle.'
    return s


def page_vs(out, ctx):
    for sa, sb in VS_PAIRS:
        a, b = MODEL[sa], MODEL[sb]
        path = f"/srovnani/{sa}-vs-{sb}/"
        la, lb = low_of(ctx, sa), low_of(ctx, sb)
        newer, older = (b, a) if (b["year"], b["chip"]) >= (a["year"], a["chip"]) else (a, b)
        diffs = spec_diffs(older, newer)
        lo_new, lo_old = (lb, la) if newer is b else (la, lb)
        if lo_new and lo_old:
            gap = lo_new - lo_old
            price_s = (f'Z druhé ruky dnes koupíte {E(older["name"])} od <strong>{kc(lo_old)}</strong> a {E(newer["name"])} od <strong>{kc(lo_new)}</strong>, '
                       + (f'novější model je tedy dražší o {kc(gap)}.' if gap > 0 else f'novější model je dokonce levnější o {kc(-gap)}.' if gap < 0 else 'oba stojí stejně.'))
        else:
            price_s = "Jeden z modelů teď z druhé ruky není skladem, ceny se aktualizují každou noc."
        note = VS_NOTES.get((sa, sb), "")
        diff_s = ", ".join(diffs) if diffs else "stejnou velikost displeje i základní parametry"
        intro = f'<p>{E(newer["name"])} ({newer["year"]}) má proti {E(older["name"])} ({older["year"]}) {diff_s}. {E(note)} {price_s}</p>'

        def cell(m, key):
            return {"year": str(m["year"]), "display": f'{str(m["display"]).replace(".", ",")}″', "hz": f'{m.get("hz") or 60} Hz', "chip": E(m["chip"]),
                    "bio": E(m["bio"]), "port": m["port"], "ai": "ano" if m.get("ai") else "ne",
                    "ios": "ano" if ios_ok(m) else f'ne ({LAST_IOS.get(m["slug"], "starší")})',
                    "storage": ", ".join(P.gb_label(v) for v in m["storage"])}[key]
        spec_rows = [("Rok vydání", "year"), ("Displej", "display"), ("Obnovovací frekvence", "hz"), ("Čip", "chip"), ("Odemykání", "bio"), ("Konektor", "port"),
                     ("Apple Intelligence", "ai"), ("Aktuální iOS 26 a 27", "ios"), ("Paměti", "storage")]
        trs = "".join(f'<tr><th scope="row">{k}</th><td>{cell(a, key)}</td><td>{cell(b, key)}</td></tr>' for k, key in spec_rows)
        prow = []
        for g in ("aplus", "a", "b", "c", "novy"):
            pa, pb = low_of(ctx, sa, (g,)), low_of(ctx, sb, (g,))
            if pa or pb:
                prow.append(f'<tr><th scope="row">{grade_chip(g)} {E(GR[g]["name"])}</th><td class="num">{kc(pa) if pa else "–"}</td>'
                            f'<td class="num">{kc(pb) if pb else "–"}</td></tr>')
        verdict = vs_verdict(older, newer, lo_old, lo_new, diffs)
        plain = lambda h: re.sub(r"<[^>]+>", "", h).replace("&nbsp;", " ")  # noqa: E731
        faq = [(f'Co je lepší, {a["name"]} nebo {b["name"]}?', plain(verdict)),
               (f'Jaký je rozdíl mezi {a["name"]} a {b["name"]}?', f'{newer["name"]} má proti {older["name"]} {plain(diff_s)}. {note}'.strip()),
               (f'Kolik stojí {a["name"]} a {b["name"]} z druhé ruky?',
                f'{a["name"]} od {kc(la) if la else "– (není skladem)"}, {b["name"]} od {kc(lb) if lb else "– (není skladem)"}; ceny včetně platných slevových kódů z {date_cz(TODAY)}.')]
        others = "".join(f'<li><a href="/srovnani/{x}-vs-{y}/">{E(MODEL[x]["name"])} vs. {E(MODEL[y]["name"])}</a></li>' for x, y in VS_PAIRS if (x, y) != (sa, sb))
        title = short_title(f'{a["name"]} vs {b["name"]} – rozdíly a ceny z druhé ruky')
        low2 = min((x for x in (la, lb) if x), default=None)
        desc = (f'{a["name"]}, nebo {b["name"]}? Displej, čip, konektor, podpora iOS a dnešní ceny repasovaných kusů'
                + (f' od {kc_plain(low2)}' if low2 else "") + ". Který se vyplatí víc.")
        body = f"""<div class="wrap"><article class="prose art vs"><p class="eyebrow">Ceny z {date_cz(TODAY)}</p>
<h1>{E(a["name"])} vs. {E(b["name"])}: rozdíly a ceny z druhé ruky</h1>{intro}
<h2>Parametry vedle sebe</h2><div class="tscroll"><table class="ptable cmp"><thead><tr><th></th><th>{link_m(a, "")}</th><th>{link_m(b, "")}</th></tr></thead><tbody>{trs}</tbody></table></div>
<h2>Ceny podle kvality</h2><p>Nejnižší dnešní cena v každé kvalitě (všechny paměti a barvy, se slevovými kódy).</p>
<div class="tscroll"><table class="ptable cmp"><thead><tr><th>Kvalita</th><th>{E(a["name"])}</th><th>{E(b["name"])}</th></tr></thead><tbody>{"".join(prow)}</tbody></table></div>
<h2>Který si vybrat?</h2><p>{verdict}</p>
<p class="vs-cta"><a class="btn" href="/{sa}/">Vybrat {E(a["name"])}{f" od {kc(la)}" if la else ""}</a> <a class="btn ghost" href="/{sb}/">Vybrat {E(b["name"])}{f" od {kc(lb)}" if lb else ""}</a></p>
<h2>Časté otázky</h2>{faq_html(faq)}</article>
<section class="sec"><h2>Další srovnání</h2><ul class="chips">{others}</ul></section></div>"""
        out.page(path, layout(ctx, path=path, title=title, desc=desc, body=body, ld=[faq_ld(faq)], active="/srovnani/",
                              crumbs=[("/", "Repasované iPhony"), ("/srovnani/", "Srovnání"), (path, f'{a["name"]} vs. {b["name"]}')]))


def model_faq(ctx, m, offers):
    rf = [o for o in offers if o["g"] != "novy"] or offers
    by_g = defaultdict(list)
    for o in rf:
        by_g[o["g"]].append(o["pc"])
    gtxt = ", ".join(f'kvalita {GR[g]["short"]} od {kc(min(v))}' for g, v in sorted(by_g.items(), key=lambda x: P.GRADE_ORDER[x[0]]))
    sup = (f'{m["name"]} dostává aktuální iOS 26 i 27. Apple konec podpory dopředu neoznamuje; iPhony historicky dostávají nové verze iOS zhruba 5–7 let od vydání, '
           f'u modelu z roku {m["year"]} tedy odhadem do let {m["year"] + 6}–{m["year"] + 7}. Bezpečnostní opravy chodí obvykle ještě déle. '
           '<a href="/pruvodce/podpora-ios/">Podpora iOS u všech modelů</a>') if ios_ok(m) else (
           f'Aktuální iOS 26 a 27 už nedostává, posledním systémem je {LAST_IOS.get(m["slug"], "starší verze iOS")}. Telefon funguje dál, ale nové funkce a postupně '
           'i některé aplikace mu chybí. <a href="/pruvodce/podpora-ios/">Podpora iOS u všech modelů</a>')
    age = max(TODAY.year - m["year"], 0)
    new_low = low_of(ctx, m["slug"], ("novy",))
    items = [(f'Kolik stojí {m["name"]}?', f'Repasovaný nebo použitý {m["name"]} stojí dnes od {kc(min(o["pc"] for o in rf))}. Podle kvality: {gtxt}.'
              + (f' Nový kus stojí od {kc(new_low)}.' if new_low else '') + ' Ceny kontrolujeme každou noc.'),
             (f'Kdy vyšel {m["name"]}?', f'{m["name"]} Apple představil v roce {m["year"]}' + (f', dnes je mu {age} {plural(age, "rok", "roky", "let")}' if age else '')
              + f'. Má čip {m["chip"]}, displej {str(m["display"]).replace(".", ",")}″ a konektor {m["port"]}.'),
             ((f'Kdy skončí podpora {m["name"]}?' if ios_ok(m) else f'Dostává {m["name"]} ještě aktualizace iOS?'), sup),
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
        items.append(("Co znamená „jen eSIM“?", "Verze bez slotu na fyzickou SIM kartu (typicky telefony z USA). Fungují s eSIM, kterou vydávají všichni čeští operátoři, "
                      "třeba " + vf("Vodafone", "faq-esim") + " i k novému tarifu."))
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
    elif low <= 15000:
        out.append(("/iphone-do-15000-kc/", "iPhone do 15 000 Kč"))
    if m["slug"] in ctx["zan_all"]:
        zl = min(o["pc"] for o in ctx["zan"] if o["model"] == m["slug"])
        out.append((zan_path(m["slug"]), f'Zánovní {m["name"]} od {kc(zl)}'))
    elif any(zan_typ(o) for o in offers):
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
    olow = min(scope, key=lambda o: (o["pc"], o["p"]))
    cfg["low"] = [olow["col"], olow["gb"], olow["g"], olow["pc"]]
    low_href = f'?barva={olow["col"]}&amp;pamet={olow["gb"]}&amp;kvalita={olow["g"]}'
    plab = re.sub(r"\s*\((\d{4})\)", r" \1", lab)     # "iPhone SE (2022)" -> "iPhone SE 2022" (how people search)
    title = short_title(f"{plab}: cena, bazar a repasovaný od {kc_plain(low)}" if not only_new
                        else f"{lab} nejlevněji od {kc_plain(low)} – srovnání obchodů")
    desc = (f"{'Repasovaný, použitý i bazarový' if not only_new else 'Nový'} {lab}: {nab(len(scope))} od {kc(low)}. "
            "Vyberte barvu, paměť a kvalitu, ukážeme nejlevnější obchod a slevové kódy.").replace(" ", " ")
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
    h1 = f"Repasovaný a použitý {E(lab)}" if not only_new else E(lab)
    body = f"""<div class="wrap">
<header class="mhead"><p class="eyebrow">Ceny z {date_cz(TODAY)} · {nab(len(scope))}</p>
<h1>{h1}</h1><p class="lead">{'Repasované, zánovní, bazarové i nové kusy' if not only_new else 'Nové kusy'} od <a href="{low_href}" data-low><strong>{kc(low)}</strong> (stav {GR[olow["g"]]["short"]})</a>. Vyberte barvu, paměť a kvalitu, ukážeme nejlevnější obchod.</p></header>
{configurator_html(ctx, m, cfg)}
<section class="sec"><h2>Ceník podle paměti a kvality</h2><p class="muted">Nejnižší cena v každé kombinaci (všechny barvy, včetně platných slevových kódů). Sloupec „Nový“ je nejlevnější nový kus.</p>{price_table(ctx, m, offers)}</section>
<section class="sec two"><div class="prose"><h2>Vyplatí se {E(m["name"])} z druhé ruky?</h2>{model_text(ctx, m, offers)}{storage_text(gb) if gb else ""}{chart_html(hist)}<p class="muted">Jak se ceny mění u dalších modelů, ukazuje <a href="/ceny-iphonu/">vývoj cen repasovaných iPhonů</a> (graf, CSV a metodika).</p></div>
<aside><div class="card"><h2>Technický list</h2>{specs_html(m)}</div>{tariff_box(m)}</aside></section>
<section class="sec"><h2>Časté otázky</h2>{faq_html(items)}<p class="muted">Prodáváte starý iPhone? <a href="/vykup-iphonu/">Kde ho vykoupí a kolik si říct</a>.</p></section>
{f'<section class="sec"><h2>{E(m["name"])} podle paměti</h2><ul class="chips">{gbl}</ul></section>' if gbl else ''}
{f'<section class="sec"><h2>Kategorie</h2><ul class="chips">{cats}</ul></section>' if cats else ''}
{f'<section class="sec"><h2>Podobné modely</h2><ul class="chips">{rel}</ul></section>' if rel else ''}
{model_reading(ctx, m)}
</div>
<div class="buybar" data-buybar hidden><div class="wrap buybar-in"><span class="bb-t" data-bb-t></span><a class="btn" data-bb-a data-sp="bar" href="/{slug}/" rel="sponsored nofollow noopener" target="_blank">Koupit</a></div></div>"""
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


BUDGETS = [(5000, "/iphone-do-5000-kc/"), (10000, "/iphone-do-10000-kc/"), (15000, "/iphone-do-15000-kc/")]
TIER_RANK = {"Pro Max": 5, "Pro": 4, "Plus": 3, "Air": 3, "base": 2, "e": 1, "mini": 1, "SE": 0}


def budget_tips(ctx, limit):
    """Three picks for a budget band from tonight's offers (grade A+, A or B, price between the previous budget and this one, so each
    budget shows what the extra money buys): the newest model, the most phone (highest tier) and the cheapest one with current iOS.
    Each with the reason, computed from models.json only."""
    floor = max((b for b, _ in BUDGETS if b < limit), default=0)
    best = {}
    for o in ctx["refurb"]:
        if o["g"] in ("aplus", "a", "b") and floor < o["pc"] <= limit and (o["model"] not in best or o["pc"] < best[o["model"]]["pc"]):
            best[o["model"]] = o
    cand = [(MODEL[k], o) for k, o in best.items() if k in MODEL]
    cur = [c for c in cand if ios_ok(c[0])] or cand
    if not cur:
        return []
    cheap = min(cur, key=lambda c: c[1]["pc"])
    newest = max(cur, key=lambda c: (c[0]["year"], TIER_RANK.get(tier(c[0]), 2), -c[1]["pc"]))
    most = max(cur, key=lambda c: (TIER_RANK.get(tier(c[0]), 2), c[0]["year"], -c[1]["pc"]))
    out, seen = [], set()
    for lab, (m, o) in (("Nejnovější", newest), ("Nejvíc telefonu", most), ("Nejlevnější s aktuálním iOS", cheap)):
        if m["slug"] in seen:
            continue
        seen.add(m["slug"])
        if m is cheap[0]:
            why = f'{m["year"]}, {str(m["display"]).replace(".", ",")}″, {m["port"]}' + (", aktuální iOS" if ios_ok(m) else "")
        else:
            d = spec_diffs(cheap[0], m)[:2] or [f'novější ({m["year"]})']
            why = ", ".join(d) + (f', o {kc(o["pc"] - cheap[1]["pc"])} dráž' if o["pc"] > cheap[1]["pc"] else "")
        out.append({"lab": lab, "m": m, "o": o, "why": why})
    return out


def budget_html(ctx, limit, path, h="h3", more=True):
    tips = budget_tips(ctx, limit)
    if not tips:
        return ""
    li = "".join(
        f'<li><span class="bt-k">{E(t["lab"])}</span><a class="bt-m" href="/{t["m"]["slug"]}/?barva={t["o"]["col"]}&amp;pamet={t["o"]["gb"]}&amp;kvalita={t["o"]["g"]}">'
        f'<b>{E(t["m"]["name"])}</b> <span class="muted">{P.gb_label(t["o"]["gb"])}, stav {GR[t["o"]["g"]]["short"]}</span></a>'
        f'<span class="bt-p">{kc(t["o"]["pc"])}</span><span class="bt-w">{E(t["why"])}</span></li>' for t in tips)
    floor = max((b for b, _ in BUDGETS if b < limit), default=0)
    head = f'<{h} class="bt-h">{"Do " + kc(limit) if not floor else kc_plain(floor).replace(" Kč", "") + "–" + kc(limit)}</{h}>'
    return (f'<div class="bcard">{head}<ol class="btips">{li}</ol>'
            + (f'<a class="bt-more" href="{path}">Všechny iPhony do {kc(limit)}</a>' if more else "") + '</div>')


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
             ("Odkud jsou ceny?", f"Z produktových exportů obchodů s iPhony, které stahujeme každou noc, a platných slevových kódů z affiliate sítě eHub. Nakupujete vždy přímo v obchodě."),
             ("Jakou záruku má repasovaný iPhone?",
              'Od obchodníka minimálně 12 měsíců a 14 dní na vrácení při nákupu přes internet. <a href="/pruvodce/zaruka/">Podrobně o záruce</a>')]
    body = f"""<section class="hero"><div class="wrap hero-in"><div class="hero-t">
<p class="eyebrow">{nab(len(rf))} · ceny z dnešní noci</p>
<h1>Repasovaný iPhone za&nbsp;cenu, která dává smysl</h1>
<p class="lead">Vyberete model, barvu, paměť a kvalitu. My projdeme obchody s repasy i bazarové nabídky, započítáme slevové kódy a ukážeme, kde je to nejlevnější. Od <strong>{kc(low)}</strong>.</p>
<ul class="chips">{chips}</ul><p class="hero-cta"><a class="btn big" href="#modely">Vybrat model</a><a class="btn big ghost" href="#rozpocet">Vybrat podle rozpočtu</a></p></div>
<div class="hero-art">{hero_img}{note}</div></div></section>
<section class="steps wrap" aria-label="Jak to funguje"><ol>
<li><img src="/img/ui/ic-tap.webp" alt="" width="64" height="64"><b>Vyberte model</b><span>od iPhonu 7 po 18 Pro</span></li>
<li><img src="/img/ui/ic-swatches.webp" alt="" width="64" height="64"><b>Barvu a paměť</b><span>jen to, co je skladem</span></li>
<li><img src="/img/ui/ic-search.webp" alt="" width="64" height="64"><b>Kvalitu A, B nebo C</b><span>a máte nejlevnější obchod</span></li></ol></section>
<section class="sec wrap" id="modely"><h2>Vyberte model</h2>{"".join(fams)}</section>
{f'<section class="sec wrap"><h2>Slevové kódy, které teď platí</h2><p class="muted">V cenách na webu už jsou započítané. Kód zadáte v košíku obchodu.</p><ul class="cpns">{cps}</ul></section>' if cps else ''}
<section class="sec wrap" id="rozpocet"><h2>Vyberte podle rozpočtu</h2><p class="muted">Tři tipy pro každý rozpočet z dnešních nabídek ve stavu A+, A nebo B, s tím, co za příplatek dostanete.</p>
<div class="bgrid">{"".join(budget_html(ctx, b, u) for b, u in BUDGETS)}</div>
<p class="bnote">Nemáte celou částku najednou? {loan_link("home", "home")} v obchodě nebo s půjčkou Home Credit.</p></section>
{f'<section class="sec wrap"><h2>Dnes se vyplatí</h2><p class="muted">Největší rozdíl proti nejlevnějšímu novému kusu se stejnou pamětí.</p><ul class="deals">{dl}</ul></section>' if dl else ''}
<section class="sec wrap"><h2>Kvalita A, B, C jednoduše</h2><p class="prose">Všechny obchody převádíme na jednu stupnici, ať se nabídky dají porovnat.
Funkčně jsou všechny telefony v pořádku, liší se vzhledem. <a href="/pruvodce/stavy/">Co přesně znamená A, B a C</a></p><ul class="grades">{grades}</ul></section>
<section class="sec wrap why"><ul>
<li><img src="/img/ui/ic-shield.webp" alt="" width="56" height="56" loading="lazy"><b>Záruka od obchodu</b><span>nejméně 12 měsíců u repasu, 24 u nového</span></li>
<li><img src="/img/ui/ic-return.webp" alt="" width="56" height="56" loading="lazy"><b>14 dní na vrácení</b><span>při nákupu přes internet bez udání důvodu</span></li>
<li><img src="/img/ui/ic-battery.webp" alt="" width="56" height="56" loading="lazy"><b>Baterie pod kontrolou</b><span>kde ji obchod uvádí, ukážeme kondici</span></li>
<li><img src="/img/ui/ic-eco.webp" alt="" width="56" height="56" loading="lazy"><b>Šetrnější volba</b><span>telefon, který už jednou vyrobili</span></li></ul></section>
<section class="sec wrap"><h2>Obchody ve srovnání</h2><ul class="logos">{logos}</ul></section>
<section class="sec wrap prose catseo"><h2>Repasovaný, zánovní, nebo z bazaru?</h2>
<p><strong>Repasovaný iPhone</strong> je použitý telefon, který obchod vyčistil, otestoval a podle potřeby opravil, nejčastěji vyměnil baterii. Prodává ho se zárukou
nejméně 12 měsíců. <strong>Zánovní</strong> a rozbalené kusy jsou prakticky nové (u nás kvalita A+), <strong>bazarový</strong> telefon od soukromníka bývá nejlevnější,
ale bez záruky a bez možnosti vrácení.</p>
<p>Ve srovnání máme dnes {nab(len(rf))} z obchodů s repasy i z tržišť. Nejlevnější iPhone stojí {kc(low)}, rozumná volba s aktuálním iOS a dlouhou podporou začíná u iPhonu 13.
Rozdíly mezi typy prodejců rozebíráme v článku <a href="/pruvodce/co-znamena-repasovany-iphone/">co znamená repasovaný iPhone</a>, použité kusy se zárukou najdete
v sekci <a href="/iphone-bazar/">iPhone bazar</a>.</p>
<h2>Jak vybíráme nejlevnější obchod</h2>
<p>Každou noc projdeme nabídky obchodů, z názvu a parametrů rozpoznáme model, paměť, oficiální barvu, kvalitu a kondici baterie a připočteme platné slevové kódy.
Řadíme jen podle konečné ceny, provize od obchodů pořadí neovlivňuje. <a href="/o-webu/">Jak web funguje</a></p></section>
<section class="sec wrap"><h2>Časté otázky</h2>{faq_html(items)}</section>"""
    ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": BRAND, "url": SITE + "/", "inLanguage": "cs"},
          {"@context": "https://schema.org", "@type": "Organization", "name": BRAND, "url": SITE + "/", "logo": SITE + "/favicon-512.png",
           "email": "info@repasovanyiphone.cz", "areaServed": {"@type": "Country", "name": "CZ"}}, faq_ld(items),
          {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [
              {"@type": "ListItem", "position": i + 1, "url": f'{SITE}/{m["slug"]}/', "name": m["name"]} for i, m in enumerate(pop)]}]
    title = f"Repasovaný iPhone – srovnání cen obchodů od {kc_plain(low)}"
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
    {"path": "/iphone-bazar/", "short": "iPhone bazar", "h1": "iPhone bazar: použité iPhony se zárukou",
     "title": "iPhone bazar – použité iPhony od {low} se zárukou",
     "lead": "Použité a bazarové iPhony z obchodů a od firem na Aukru a Allegru, se zárukou a kvalitou na jedné stupnici."},
    {"path": "/levny-iphone/", "short": "Levné iPhony", "h1": "Levný iPhone: nejlevnější iPhony dnes",
     "title": "Levný iPhone – iPhone levně dnes od {low}",
     "lead": "Nejlevnější kus každého modelu, seřazený od nejnižší ceny včetně slevových kódů. Modely bez aktuálního iOS jsou až na konci."},
    {"path": "/novy-iphone/", "short": "Nové iPhony", "h1": "Nový iPhone: kde je nejlevnější",
     "title": "Nový iPhone nejlevněji – ceny {n} modelů",
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
    {"path": "/iphone-do-15000-kc/", "short": "iPhone do 15 000 Kč", "h1": "iPhone do 15 000 Kč",
     "title": "iPhone do 15 000 Kč – nejnovější modely, které se vejdou",
     "lead": "Nejnovější iPhony, které dnes seženete do 15 000 Kč, včetně modelů s USB-C a Apple Intelligence."},
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
    "/iphone-do-15000-kc/": "<h2>Co čekat do 15 000 Kč</h2><p>Do patnácti tisíc se vejdou iPhony 14 Pro a 15, v lepší kvalitě i iPhone 15 Pro nebo základní iPhone 16. "
                            "Od iPhonu 15 mají USB-C a od 15 Pro podporu Apple Intelligence. Rozdíly mezi sousedními modely ukazují <a href=\"/srovnani/\">srovnání modelů</a>, doporučení podle rozpočtu je v článku <a href=\"/jaky-iphone-koupit/\">jaký iPhone koupit</a>.</p>"
                            "<p>Když nechcete platit najednou, některé obchody nabízejí splátky při objednávce a na telefon od 10 000 Kč jde i půjčka, viz <a href=\"/iphone-na-splatky/?z=iphone-do-15000-kc\" data-loan=\"cat\">iPhone na splátky</a>.</p>",
    "/iphone-pro-deti/": "<h2>Proč repas pro dítě</h2><p>Dětský telefon dostane obal, spadne a za dva roky se vymění. Repas v kvalitě B nebo C ušetří peníze a pořád podporuje "
                         "Čas u obrazovky a rodičovskou kontrolu. Vybírejte modely s aktuálním iOS a menší velikostí do ruky.</p>",
}


def cat_content(ctx, c):
    newest = lambda r: (-r[0]["year"], r[1]["pc"])  # noqa: E731
    p = c["path"]
    if p == "/levny-iphone/":
        rows = sorted(best_per_model(ctx, lambda m, o: True), key=lambda r: (not ios_ok(r[0]), r[1]["pc"]))
        return rows, ('<ul class="chips"><li><a href="/iphone-do-5000-kc/">iPhone do 5 000 Kč</a></li><li><a href="/iphone-do-10000-kc/">iPhone do 10 000 Kč</a></li><li><a href="/iphone-do-15000-kc/">iPhone do 15 000 Kč</a></li>'
                      '<li><a href="/iphone-pro-deti/">iPhone pro děti</a></li><li><a href="/maly-iphone/">Malé iPhony</a></li></ul>')
    if p == "/novy-iphone/":
        return sorted(best_per_model(ctx, lambda m, o: True, grades=("novy",)), key=newest), ""
    if p == "/iphone-bazar/":
        return sorted(best_per_model(ctx, lambda m, o: True, grades=("a", "b", "c")), key=newest), ""
    if p == "/zanovni-iphone/":
        return sorted(best_per_model(ctx, lambda m, o: True, grades=("aplus",)), key=newest), ""
    if p == "/maly-iphone/":
        return sorted(best_per_model(ctx, lambda m, o: m["display"] <= 6.1 and ios_ok(m)), key=lambda r: (r[0]["display"], -r[0]["year"])), ""
    if p == "/iphone-do-5000-kc/":
        return sorted(best_per_model(ctx, lambda m, o: o["pc"] <= 5000), key=newest), ""
    if p == "/iphone-do-10000-kc/":
        return sorted(best_per_model(ctx, lambda m, o: o["pc"] <= 10000), key=newest), ""
    if p == "/iphone-do-15000-kc/":
        return sorted(best_per_model(ctx, lambda m, o: o["pc"] <= 15000), key=newest), ""
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
    chip = (f'<button type="button" class="cchip" data-copy="{E(cp["code"])}" data-shop="{o["shop"]}"{href_attr(o["go"])} aria-label="Kopírovat slevový kód {E(cp["code"])}">'
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
    lead = (f'Kde koupit iPhone levně: nejlevnější iPhone dnes stojí <strong>{kc(cheapest["pc"])}</strong> – {E(M(cheapest)["name"])}. Nejlevnější iPhone s aktuálním iOS je '
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
           ("Kde koupit iPhone levně?", "Nejlevněji vycházejí repasované kusy z obchodů s kvalitou B nebo C. Srovnáváme "
            + E(", ".join(SHOP[s]["name"] for s in ctx["shop_ids"])) + " a ke každé konfiguraci ukážeme nejlevnější obchod včetně slevových kódů."),
           ("Vyplatí se ještě iPhone 11?", "Ano, pokud chcete co nejlevnější iPhone s podporou: dostává iOS 26 i iOS 27. Nemá ale 5G ani USB-C a baterie bývá u starších kusů opotřebovaná."),
           ("Je levný repasovaný iPhone horší než nový?", "Funkčně ne, obchod ho otestoval a dává na něj záruku. Liší se vzhledem podle kvality (A+ až C) a kondicí baterie.")]
    if cheap_new:
        faq.insert(1, ("Jaký je nejlevnější nový iPhone?", f'{E(M(cheap_new)["name"])} za {kc(cheap_new["pc"])} ({E(SHOP[cheap_new["shop"]]["name"])}).'))
        faq.insert(2, ("Jde koupit nepoužitý iPhone levně?", f'Nejlevnější nový, nerozbalený iPhone je dnes {E(M(cheap_new)["name"])} za {kc(cheap_new["pc"])}. '
                       'Levnější cestou k nepoužitému telefonu jsou rozbalené kusy bez stop používání, najdete je mezi <a href="/zanovni-iphone/">zánovními iPhony</a>.'))
    return lead, tips, sec, faq


# ---- zánovní landing (Kenny 25. 11. 2026: only really "zánovní" / "rozbalený" pieces, buy straight from the list) ----

ZAN_WORDS = {"zánovní": "z", "rozbaleno": "r", "rozbalený": "r"}   # the shop's own wording; "Premium" is a top refurb, not zánovní
ZAN_SUB_MIN = 3          # model sub-landing /zanovni-iphone/<model>/ from this many offers


def zan_typ(o):
    return ZAN_WORDS.get((o.get("sg") or "").strip().lower(), "") if o["g"] == "aplus" else ""


def zan_path(slug):
    return f"/zanovni-iphone/{slug}/"


def zan_trust(offs):
    wars = sorted({offer_facts(o)[2] for o in offs})
    ws = [int(re.search(r"\d+", w).group()) for w in wars if re.search(r"\d+", w)]
    war = (f"Záruka {min(ws)}–{max(ws)} měsíců podle obchodu" if ws and min(ws) != max(ws) else f"Záruka {ws[0]} měsíců" if ws else "Záruka podle obchodu")
    items = [war, "14 dní na vrácení při nákupu online", "Baterie a záruka u každé nabídky", "Ceny po slevovém kódu"]
    return '<ul class="ztrust">' + "".join(f"<li>{E(x)}</li>" for x in items) + "</ul>"


def zan_model_card(ctx, s, of):
    """Model card like on the homepage, but price, count and colour dots from the zánovní offers only; opens the zánovní sub-page."""
    m = MODEL[s]
    seen = {o["col"] for o in of}
    cols = [c for c in P.COLORS.get(s, []) if c["key"] in seen]
    dots = "".join(f'<span class="dot xs" style="--h:{c["hex"]}" title="{E(c["name"])}"></span>' for c in cols)
    return (f'<li><a class="mcard" href="{zan_path(s)}">{pic(ctx, s, of[0]["col"], 120, alt="Zánovní " + m["name"])}<span class="mc-n">{E(m["name"])}</span>'
            f'<span class="mc-dots">{dots}</span><span class="mc-p">od <b>{kc(of[0]["pc"])}</b></span>'
            f'<span class="mc-c">{nab(len(of))}{"" if ios_ok(m) else " · starší iOS"}</span></a></li>')


def zan_by_model(ctx):
    by = defaultdict(list)
    for o in ctx["zan"]:
        by[o["model"]].append(o)
    for v in by.values():
        v.sort(key=lambda o: o["pc"])
    return by


def zan_texts(ctx):
    zan = ctx["zan"]
    rf = offers_of(ctx, lambda m, o: True, ("a", "b", "c"))
    return saving_pct(ctx, zan), saving_pct(ctx, rf)


def page_zanovni(out, ctx):
    zan, by = ctx["zan"], zan_by_model(ctx)
    path = "/zanovni-iphone/"
    pa, pr = zan_texts(ctx)
    low = min(o["pc"] for o in zan)
    models = sorted(by, key=lambda s: (-MODEL[s]["year"], by[s][0]["pc"]))
    fams = []
    for fk, fname in FAMILIES:
        ms = [m for m in MODELS if m["family"] == fk and m["slug"] in by]
        if ms:
            fams.append(f'<div class="fam"><h3>{E(fname)}</h3><ul class="mgrid">{"".join(zan_model_card(ctx, m["slug"], by[m["slug"]]) for m in ms)}</ul></div>')
    cheapest = min(zan, key=lambda o: o["pc"])
    lead = (f'Rozbalené a jako nové iPhony se zárukou od <strong>{kc(low)}</strong>, proti novému typicky o {pa}&nbsp;% levněji. '
            'Vyberte model a uvidíte všechny jeho zánovní kusy.')
    sec = f"""<h2 id="co-je">Co je zánovní a rozbalený iPhone</h2>
<p><strong>Rozbalený</strong> iPhone někdo koupil a v zákonné lhůtě 14 dnů vrátil, takže je prakticky nový. <strong>Zánovní</strong> telefon byl používaný jen krátce
a nemá viditelné stopy. Na stránce jsou jen nabídky, které obchod takto sám označuje.</p>
<h2>Proč tu nejsou kusy „Premium“</h2>
<p>Některé obchody mají nad stavem „výborný“ ještě třídu Premium. Jsou to nejlepší repasované kusy, často po výměně dílů, ne krátce používané telefony. V konfigurátoru
každého modelu je najdete spolu se zánovními ve stavu <strong>A+</strong>. Sem patří jen zánovní a rozbalené kusy.</p>
<h2>Zánovní, rozbalený, repasovaný, nebo z bazaru?</h2>
<div class="tscroll"><table class="ptable cmp"><thead><tr><th scope="col">Typ</th><th>Vzhled</th><th>Záruka od obchodu</th><th>Cena proti novému</th></tr></thead><tbody>
<tr><th scope="row">Nový</th><td>nerozbalený</td><td>24 měsíců</td><td>plná cena</td></tr>
<tr><th scope="row"><strong>Zánovní / rozbalený</strong></th><td>bez stop</td><td>12–24 měsíců</td><td>typicky −{pa}&nbsp;%</td></tr>
<tr><th scope="row">Repasovaný (A, B, C)</th><td>drobné až viditelné stopy</td><td>nejméně 12 měsíců</td><td>typicky −{pr}&nbsp;%</td></tr>
<tr><th scope="row">Bazar od soukromníka</th><td>podle štěstí</td><td>žádná</td><td>nejnižší, ale bez jistoty</td></tr></tbody></table></div>
<p>Kdo telefon stejně nosí v obalu, ušetří víc s <a href="/levny-iphone/">levným repasem</a> v kvalitě B nebo C.</p>
<h2>Jak vybrat a na co si dát pozor</h2><ul>
<li><strong>Záruka:</strong> u rozbaleného kusu bývá plných 24 měsíců, u zánovního ji obchod smí zkrátit na 12. U každé nabídky ji vypisujeme. <a href="/pruvodce/zaruka/">Záruka a vrácení</a></li>
<li><strong>Baterie:</strong> u zánovního kusu čekejte vysokou kondici, ověřte ale údaj u konkrétní nabídky. <a href="/pruvodce/baterie/">Kondice baterie</a></li>
<li><strong>Paměť:</strong> 128 GB stačí většině lidí, kdo hodně fotí a natáčí, ať sáhne po 256 GB. <a href="/pruvodce/jaka-pamet/">Kolik paměti stačí</a></li>
<li><strong>Generace:</strong> USB-C mají modely od iPhonu 15, Apple Intelligence iPhone 15 Pro a novější. Aktuální iOS dostávají všechny od iPhonu 11.</li>
<li><strong>Jen eSIM:</strong> verze z USA nemají slot na SIM kartu, u nabídek je označujeme.</li>
<li><strong>Po převzetí:</strong> v Nastavení → Obecné → Informace zkontrolujte díly a historii servisu. <a href="/pruvodce/kontrola/">Kontrola po převzetí</a></li></ul>"""
    faq = [("Co znamená zánovní iPhone?", "Telefon používaný jen krátce, bez viditelných stop. Je to nejlepší stav, ve kterém se prodávají použité iPhony."),
           ("Jaký je rozdíl mezi zánovním a rozbaleným iPhonem?", "Rozbalený kus někdo koupil a do 14 dnů vrátil, většinou ho skoro nepoužíval. Zánovní telefon mohl být používaný déle, ale stopy na něm nejsou vidět."),
           ("Jakou záruku má zánovní iPhone?", "Od obchodu 24 měsíců, u použitého zboží ji obchod smí dohodou zkrátit na 12 měsíců. Záruku uvádíme u každé nabídky."),
           ("Kolik ušetřím za zánovní iPhone?", f"Proti nejlevnějšímu novému kusu se stejnou pamětí typicky {pa} %. Nejlevnější zánovní iPhone dnes stojí {kc(cheapest['pc'])} ({E(MODEL[cheapest['model']]['name'])})."),
           ("Proč tu nejsou iPhony ve stavu Premium?", "Premium je nejvyšší třída repasovaných telefonů, ne krátce používaný kus. Najdete je u každého modelu ve stavu A+.")]
    body = f"""<div class="wrap"><header class="mhead zhero"><p class="eyebrow">Ceny z {date_cz(TODAY)} · aktualizace každou noc</p>
<h1>Zánovní iPhone</h1><p class="lead">{lead}</p>{zan_trust(zan)}</header>
<section class="sec" id="modely"><h2>Vyberte model</h2>{"".join(fams)}</section>
<aside class="repband"><p><b>Chcete ušetřit ještě víc?</b> Repasované iPhony ve stavu A mají jen drobné stopy viditelné zblízka a proti novým stojí typicky o {pr}&nbsp;% méně.</p>
<a class="btn ghost" href="/#modely">Vybrat repasovaný iPhone</a></aside>
<section class="sec prose catseo">{sec}</section>
<section class="sec"><h2>Časté otázky</h2>{faq_html(faq)}</section></div>"""
    items = []
    for i, s in enumerate(models[:30]):
        pl = product_ld(f'{MODEL[s]["name"]} zánovní', zan_path(s), by[s])
        pl.pop("@context", None)
        items.append({"@type": "ListItem", "position": i + 1, "item": pl})
    ld = [{"@context": "https://schema.org", "@type": "ItemList", "name": "Zánovní a rozbalené iPhony", "itemListElement": items}, faq_ld(faq)]
    out.page(path, layout(ctx, path=path, title=short_title(f"Zánovní iPhone – rozbalené iPhony jako nové od {kc_plain(low)}"),
                          desc=(f"Zánovní a rozbalené iPhony od {kc_plain(low)} se zárukou: jen kusy, které obchody označují jako zánovní nebo rozbalené. "
                                "Ceny dnes, baterie a záruka u každé nabídky.").replace(" ", " "),
                          body=body, ld=ld, active=path, crumbs=[("/", "Repasované iPhony"), (path, "Zánovní iPhony")]))


ZAN_GRADES = {"r": ["Rozbalený", "Prakticky nový", "vrácený do 14 dnů od nákupu, prakticky nepoužívaný"],
              "z": ["Zánovní", "Krátce používaný", "krátce používaný, bez viditelných stop"]}


def zan_cfg(ctx, m, of):
    """The model configurator over the zánovní offers only; step 3 is the shop's wording (rozbalený / zánovní) instead of quality A+…C."""
    cfg = cfg_data(ctx, m, of, gkey=zan_typ)
    cfg.update({"grades": ZAN_GRADES, "order": ["r", "z"], "gimg": [], "glab": "jako",
                "step3": ("Stav", "/zanovni-iphone/#co-je", "rozbalený, nebo zánovní?")})
    lo = min(of, key=lambda o: (o["pc"], o["p"]))
    cfg["low"] = [lo["col"], lo["gb"], zan_typ(lo), lo["pc"]]
    cfg["rep"] = zan_repas(ctx, m, cfg)
    cfg["rgr"] = {g: GR[g]["short"] for g in ("a", "b", "c")}
    return cfg, lo


def zan_repas(ctx, m, cfg):
    """"Want to save more?": for every colour × storage of the zánovní configurator the cheapest ordinary refurb (A first, else B/C; never A+,
    which holds the Premium refurbs). Same colour if there is one, else any colour in that storage. {"ci,gi": [colour key, colour name, grade, price]}"""
    rf = [o for o in ctx["by_model"].get(m["slug"], []) if o["g"] in ("a", "b", "c")]
    pick = lambda c: min(c, key=lambda o: (o["g"] != "a", o["pc"])) if c else None   # noqa: E731
    out = {}
    for gi, gb in enumerate(cfg["gbs"]):
        same_gb = [o for o in rf if o["gb"] == gb]
        for ci, c in enumerate(cfg["cols"]):
            o = pick([o for o in same_gb if o["col"] == c[0]]) or pick(same_gb)
            if o:
                out[f"{ci},{gi}"] = [o["col"], color_name(m["slug"], o["col"]), o["g"], o["pc"]]
    return out


def repup_html(cfg, best, ci, gi):
    """Same markup as repup() in app.js."""
    r = (cfg.get("rep") or {}).get(f"{ci},{gi}")
    if not r or r[3] > best[8] - 300:
        return ""
    gb = cfg["gbs"][gi]
    return (f'<a class="repup" href="/{cfg["m"]}/?barva={r[0]}&amp;pamet={gb}&amp;kvalita={r[2]}"><span><b>Chcete ušetřit víc?</b> '
            f'Repasovaný {E(cfg["name"])} {P.gb_label(gb)}, {E(r[1].lower())} ve stavu {GR[r[2]]["short"]} od <b>{kc(r[3])}</b>'
            f' · o {kc(best[8] - r[3])} méně</span><span class="repup-a" aria-hidden="true">→</span></a>')


def zan_price_table(ctx, slug, of):
    gbs = sorted({o["gb"] for o in of})
    ts = [t for t in ("r", "z") if any(zan_typ(o) == t for o in of)]
    rows = []
    for gb in gbs:
        here = [o for o in of if o["gb"] == gb]
        low = min(o["pc"] for o in here)
        cells = []
        for t in ts:
            ps = [o["pc"] for o in here if zan_typ(o) == t]
            cells.append(f'<td class="num{" low" if ps and min(ps) == low else ""}">{kc(min(ps))}</td>' if ps else '<td class="na">–</td>')
        nw = ctx["new_min"].get((slug, gb))
        rp = [o for o in ctx["by_model"].get(slug, []) if o["gb"] == gb and o["g"] in ("a", "b", "c")]
        r = min(rp, key=lambda o: o["pc"]) if rp else None
        rc = (f'<td class="num"><a href="/{slug}/?pamet={gb}&amp;kvalita={r["g"]}">{kc(r["pc"])}</a> <span class="muted">({GR[r["g"]]["short"]})</span></td>'
              if r else '<td class="na">–</td>')
        rows.append(f'<tr><th scope="row">{P.gb_label(gb)}</th>{"".join(cells)}{rc}<td class="num newp">{kc(nw) if nw else "–"}</td></tr>')
    head = "".join(f"<th>{ZAN_GRADES[t][0]}</th>" for t in ts)
    return (f'<div class="tscroll"><table class="ptable"><thead><tr><th>Paměť</th>{head}<th>Repasovaný</th><th>Nový</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def page_zanovni_model(out, ctx, slug):
    m, of = MODEL[slug], zan_by_model(ctx)[slug]
    path = zan_path(slug)
    lo, hi = of[0]["pc"], of[-1]["pc"]
    rep_a = low_of(ctx, slug, ("a",))
    news = [o["pc"] for o in ctx["by_model"].get(slug, []) if o["g"] == "novy"]
    nw_low = min(news) if news else None
    gbs = sorted({o["gb"] for o in of})
    cols = sorted({color_name(slug, o["col"]) for o in of})
    nr = sum(1 for o in of if zan_typ(o) == "r")
    cfg, olow = zan_cfg(ctx, m, of)
    low_href = f'?barva={olow["col"]}&amp;pamet={olow["gb"]}&amp;kvalita={zan_typ(olow)}'
    lead = (f'{"Rozbalené a zánovní" if nr else "Zánovní"} kusy bez stop používání od <a href="{low_href}" data-low><strong>{kc(lo)}</strong></a>. '
            "Vyberte barvu, paměť a stav, ukážeme nejlevnější obchod se zárukou.")
    facts = []
    facts.append(f'Zánovní {E(m["name"])} je dnes v {plural(len(gbs), "paměti", "pamětech", "pamětech")} {", ".join(P.gb_label(g) for g in gbs)} a {plural(len(cols), "barvě", "barvách", "barvách")} {E(", ".join(c.lower() for c in cols))}'
                 + (f', cena od {kc(lo)} do {kc(hi)}.' if hi > lo else "."))
    if nw_low:
        facts.append(f'Nový {E(m["name"])} stojí v obchodech v našem srovnání od {kc(nw_low)}.')
    if rep_a and rep_a < lo:
        facts.append(f'Běžný repas ve stavu A (drobné stopy) vyjde od {kc(rep_a)}, tedy o {kc(lo - rep_a)} méně než nejlevnější zánovní kus. Všechny stavy porovnáte v '
                     f'<a href="/{slug}/">konfigurátoru {E(m["name"])}</a>.')
    else:
        facts.append(f'Všechny stavy včetně levnějších repasů porovnáte v <a href="/{slug}/">konfigurátoru {E(m["name"])}</a>.')
    if not ios_ok(m):
        facts.append(f'Pozor: {E(m["name"])} už nedostává aktuální iOS, časem přijde o nové verze aplikací. <a href="/pruvodce/podpora-ios/">Podpora iOS</a>')
    nb = [n for n in neighbours(ctx, m) if n]
    vs = [(vs_link(slug, n["slug"]), n) for n in nb if vs_link(slug, n["slug"])]
    if vs:
        facts.append("Rozhodujete se mezi modely? " + ", ".join(f'<a href="{u}">{E(m["name"])} vs. {E(n["name"])}</a>' for u, n in vs[:2]) + ".")
    wars = sorted({offer_facts(o)[2] for o in of})
    faq = [(f"Kolik stojí zánovní {m['name']}?", f"Dnes od {kc(lo)}" + (f" do {kc(hi)}" if hi > lo else "") + f", podle paměti, barvy a obchodu ({nab(len(of))}). Ceny aktualizujeme každou noc."),
           (f"Vyplatí se zánovní, nebo nový {m['name']}?",
            (f"Nový stojí od {kc(nw_low)}, zánovní od {kc(lo)}. " if nw_low else "") + "Zánovní kus vypadá jako nový a má záruku od obchodu, rozdíl je hlavně v ceně a v délce záruky."),
           (f"Jakou záruku má zánovní {m['name']}?", "Podle nabídky: " + ", ".join(w.lower() for w in wars) + ". U každé nabídky ji uvádíme.")]
    others = "".join(f'<li><a href="{zan_path(s)}">{E(MODEL[s]["name"])}</a></li>' for s in sorted(ctx["zan_all"], key=lambda s: -MODEL[s]["year"]) if s != slug)
    body = f"""<div class="wrap">
<header class="mhead"><p class="eyebrow">Ceny z {date_cz(TODAY)} · {nab(len(of))}</p>
<h1>Zánovní {E(m["name"])}</h1><p class="lead">{lead}</p></header>
{configurator_html(ctx, m, cfg)}
<div class="sec">{zan_trust(of)}</div>
<section class="sec"><h2>Ceník podle paměti</h2><p class="muted">Nejnižší cena v každé paměti (všechny barvy, se slevovými kódy). „Repasovaný“ je nejlevnější kus ve stavu A, B nebo C, pokud chcete ušetřit víc, „Nový“ nejlevnější nový.</p>{zan_price_table(ctx, slug, of)}</section>
<section class="sec two"><div class="prose"><h2>Zánovní {E(m["name"])} dnes</h2><p>{" ".join(facts)}</p>
<p>Co znamená zánovní a rozbalený a proč tu nejsou kusy „Premium“, vysvětlujeme v přehledu <a href="/zanovni-iphone/">zánovní iPhony</a>.</p></div>
<aside><div class="card"><h2>Technický list</h2>{specs_html(m)}</div>{tariff_box(m)}</aside></section>
<section class="sec"><h2>Časté otázky</h2>{faq_html(faq)}</section>
{f'<section class="sec"><h2>Další zánovní iPhony</h2><ul class="chips">{others}</ul></section>' if others else ''}
</div>
<div class="buybar" data-buybar hidden><div class="wrap buybar-in"><span class="bb-t" data-bb-t></span><a class="btn" data-bb-a data-sp="bar" href="{path}" rel="sponsored nofollow noopener" target="_blank">Koupit</a></div></div>"""
    ph600 = cfg["cols"][next(i for i, c in enumerate(cfg["cols"]) if c[0] == cfg["def"][0])][3]
    preload = f'<link rel="preload" as="image" href="{ph600}" fetchpriority="high">' if ph600 else ""
    abs_img = SITE + ph600 if ph600 else ""
    ld = [product_ld(f'{m["name"]} zánovní', path, of, abs_img), faq_ld(faq)]
    idx = slug in ctx["zan_sub"]
    out.page(path, layout(ctx, path=path, title=short_title(f'{m["name"]} zánovní a rozbalený od {kc_plain(lo)} – ceny dnes'),
                          desc=(f'Zánovní a rozbalený {m["name"]} od {kc_plain(lo)}: vyberte barvu, paměť a stav, ukážeme nejlevnější obchod. Záruka a baterie u každé nabídky.').replace(" ", " "),
                          body=body, ld=ld, active="/zanovni-iphone/", index=idx, og_img=abs_img, cfg=cfg, preload=preload,
                          crumbs=[("/", "Repasované iPhony"), ("/zanovni-iphone/", "Zánovní iPhony"), (path, m["name"])]), index=idx)


def seo_bazar(ctx, rows):
    used = offers_of(ctx, lambda m, o: True, ("a", "b", "c"))
    ok = [o for o in used if ios_ok(MODEL[o["model"]])]
    M = lambda o: MODEL[o["model"]]  # noqa: E731
    cheapest = min(ok or used, key=lambda o: o["pc"])
    usbc = min((o for o in used if M(o)["port"] == "USB-C"), key=lambda o: o["pc"], default=None)
    pro120 = min((o for o in used if M(o).get("hz") == 120), key=lambda o: o["pc"], default=None)
    tips = [(cheapest, "Nejlevnější použitý iPhone s aktuálním iOS"), (usbc, "Nejlevnější s USB-C"), (pro120, "Nejlevnější se 120Hz displejem")]
    tips = [(o, r) for o, r in tips if o]
    pr = saving_pct(ctx, used)
    tr = []
    for m in [m for m in MODELS if ctx["by_model"].get(m["slug"]) and ios_ok(m)][:22]:
        bc = low_of(ctx, m["slug"], ("b", "c"))
        a_ = low_of(ctx, m["slug"], ("a",))
        nw = low_of(ctx, m["slug"], ("novy",))
        if bc or a_:
            tr.append(f'<tr><th scope="row">{link_m(m, "")}</th><td class="num">{kc(bc) if bc else "–"}</td><td class="num">{kc(a_) if a_ else "–"}</td>'
                      f'<td class="num newp">{kc(nw) if nw else "–"}</td></tr>')
    n_mp = sum(1 for o in used if o["shop"] in ("aukro", "allegro"))
    lead = (f'{nab(len(used)).capitalize()} použitých iPhonů od obchodů a firem od <strong>{kc(cheapest["pc"])}</strong>. '
            f'Na rozdíl od inzerátů mají záruku a stav na jedné stupnici A, B, C. Proti novému ušetříte typicky <strong>{pr}&nbsp;%</strong>.')
    sec = f"""<h2>iPhone z bazaru, ale se zárukou</h2>
<p>Hledání „iPhone bazar“ obvykle končí na Bazoši nebo Sbazaru: levné inzeráty, ale bez záruky, bez možnosti vrácení a s rizikem zamčeného iCloudu.
Tady najdete <strong>použité iPhony od obchodů</strong> (MobileGear, Smarty, JabkoLevně, iPhoneMarket) a od firemních prodejců na Aukru a Allegru ({nab(n_mp)}).
Každý kus má záruku nejméně 12 měsíců a při nákupu přes internet 14 dní na vrácení bez udání důvodu.</p>
<p>Stav sjednocujeme na jednu stupnici: <strong>A</strong> stopy jen zblízka, <strong>B</strong> jemné škrábance, <strong>C</strong> viditelné stopy používání.
Funkčně jsou všechny v pořádku. <a href="/pruvodce/stavy/">Co přesně jednotlivé kvality znamenají</a></p>
<h2>Kolik stojí použitý iPhone</h2><p>Nejnižší dnešní cena každého modelu s aktuálním iOS. Ceny se přepočítávají každou noc a obsahují platné slevové kódy.</p>
<div class="tscroll"><table class="ptable cmp"><thead><tr><th>Model</th><th>Kvalita B/C od</th><th>Kvalita A od</th><th>Nový od</th></tr></thead><tbody>{"".join(tr)}</tbody></table></div>
<h2>Bazoš, Aukro, nebo obchod?</h2>
<div class="tscroll"><table class="ptable cmp"><thead><tr><th></th><th>Inzerát (Bazoš, Sbazar)</th><th>Aukro, Allegro</th><th>Obchod s repasy</th></tr></thead><tbody>
<tr><th scope="row">Záruka</th><td>žádná</td><td>od firmy ano, od soukromníka ne</td><td>12–24 měsíců</td></tr>
<tr><th scope="row">Vrácení do 14 dnů</th><td>ne</td><td>od firmy ano</td><td>ano</td></tr>
<tr><th scope="row">Kontrola telefonu</th><td>sami při předání</td><td>podle prodejce</td><td>otestovaný, často nová baterie</td></tr>
<tr><th scope="row">Riziko zámku iCloudu</th><td>vysoké</td><td>nízké u firem</td><td>minimální</td></tr>
<tr><th scope="row">Cena</th><td>nejnižší</td><td>nízká</td><td>o něco vyšší</td></tr></tbody></table></div>
<p>Rozdíl mezi inzerátem a obchodem bývá jen pár set korun, za které dostanete záruku a jistotu. Pokud přece jen kupujete od soukromníka,
projděte si <a href="/pruvodce/iphone-z-bazaru/">jak koupit iPhone z bazaru bezpečně</a>.</p>
<h2>Jak koupit použitý iPhone a nenaletět</h2><ol>
<li><strong>Model s aktuálním iOS:</strong> iPhone 11 a novější nebo SE 2. generace. Starší kusy jsou levné, ale přicházejí o aplikace. <a href="/pruvodce/podpora-ios/">Podpora iOS</a></li>
<li><strong>Kondice baterie:</strong> pod 80&nbsp;% ji Apple považuje za opotřebovanou, výměna stojí stovky až tisíce korun. <a href="/pruvodce/baterie/">Jak číst kondici baterie</a></li>
<li><strong>Zámek aktivace:</strong> telefon musí být odhlášený z Apple ID a vymazaný. <a href="/pruvodce/kontrola-imei-icloud/">Kontrola IMEI a iCloudu</a></li>
<li><strong>Vyměněné díly:</strong> Nastavení → Obecné → Informace → Díly a historie servisu. <a href="/pruvodce/dily-a-historie-servisu/">Co znamená neoriginální díl</a></li>
<li><strong>Kontrola po převzetí:</strong> displej, Face ID, fotoaparáty, nabíjení. <a href="/pruvodce/kontrola/">Kontrolní seznam</a></li></ol>
<h2>Které použité iPhony se vyplatí</h2>
<p>Nejlevnější rozumný kus s aktuálním iOS je dnes {link_m(M(cheapest), "")} za {kc(cheapest["pc"])}.
{f'USB-C a modernější čip má nejlevněji {link_m(M(usbc), "")} za {kc(usbc["pc"])}. ' if usbc else ''}{f'Plynulý 120Hz displej seženete nejlevněji u {link_m(M(pro120), "")} za {kc(pro120["pc"])}.' if pro120 else ''}
Podrobně podle rozpočtu v článku <a href="/jaky-iphone-koupit/">jaký iPhone koupit</a>, podle ceny v sekci <a href="/levny-iphone/">levné iPhony</a>.</p>"""
    faq = [("Kde koupit použitý iPhone?",
            'Nejbezpečněji v obchodě s repasy nebo od firmy na Aukru či Allegru: dostanete záruku a 14 dní na vrácení. Na Bazoši je cena nejnižší, ale bez záruky. '
            '<a href="/pruvodce/kde-koupit-repasovany-iphone/">Kde koupit repasovaný iPhone</a>'),
           ("Kolik stojí použitý iPhone?", f'Nejlevnější použitý iPhone s aktuálním iOS stojí dnes {kc(cheapest["pc"])}. Ceny všech modelů jsou v tabulce výše.'),
           ("Má použitý iPhone záruku?", "Od obchodu nebo firmy ano, nejméně 12 měsíců (zákonných 24 měsíců smí prodejce u použitého zboží zkrátit na 12). Od soukromé osoby záruka není."),
           ("Jak poznat, že iPhone z bazaru není kradený nebo zamčený?",
            'Prodávající se musí před vámi odhlásit z Apple ID a telefon vymazat. Telefon, který se po resetu hlásí k cizímu účtu, nekupujte. '
            '<a href="/pruvodce/kontrola-imei-icloud/">Kontrola IMEI a iCloudu</a>'),
           ("Jaký použitý iPhone koupit?", "iPhone 11 a novější kvůli podpoře iOS, ideálně 13 nebo novější. USB-C mají modely od iPhonu 15, Apple Intelligence iPhone 15 Pro a novější.")]
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
    lead = (f'Nové, nerozbalené iPhony s plnou zárukou z obchodů ve srovnání. Nejlevnější nový iPhone je dnes '
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


CAT_SEO = {"/iphone-bazar/": ("fam", seo_bazar), "/levny-iphone/": ("price", seo_levny), "/novy-iphone/": ("cur", seo_novy)}
CAT_META = {
    "/iphone-bazar/": ("iPhone bazar – použité iPhony od {low} se zárukou",
                       "Použité a bazarové iPhony od {low} z obchodů i od firem na Aukru a Allegru, se zárukou a kvalitou A, B, C. Kolik stojí použitý iPhone a jak ho koupit bezpečně."),
    "/levny-iphone/": ("Levný iPhone – iPhone levně dnes od {low}",
                       "Nejlevnější iPhony dnes od {low}: repasované, zánovní i nové, ceny včetně slevových kódů. Který levný iPhone se vyplatí a kde koupit iPhone levně."),
    "/zanovni-iphone/": ("Zánovní iPhone a rozbalené iPhony od {low}",
                         "Zánovní a rozbalené iPhony bez stop od {low}. Kolik ušetříte proti novému, jakou mají záruku a na co si dát pozor. Ceny každý den."),
    "/novy-iphone/": ("Nový iPhone nejlevněji – ceny aktuálních iPhonů",
                      "Nový iPhone nejlevněji: ceny iPhonu 18 Pro, 17, Air, 17e i starších modelů z více obchodů. Nový, nebo zánovní? Srovnání cen každý den."),
}


def page_cats(out, ctx):
    for c in CATS:
        if c["path"] == "/zanovni-iphone/":     # own landing: page_zanovni()
            continue
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
        bud = next((b for b, u in BUDGETS if u == c["path"]), 0)
        tip_html = "".join(cat_card(ctx, MODEL[o["model"]], o, len([x for x in ctx["by_model"][o["model"]] if x["g"] == o["g"]]), E(r)) for o, r in tips)
        grid = "".join(cat_card(ctx, m, o, n) for m, o, n in rows)
        body = f"""<div class="wrap"><header class="mhead"><p class="eyebrow">Ceny z {date_cz(TODAY)} · {len(rows)} {plural(len(rows), "model", "modely", "modelů")}</p>
<h1>{E(c["h1"])}</h1><p class="lead">{lead}</p></header>
{f'<section class="sec ctips"><h2 class="sr">Naše tipy</h2><ul class="cgrid tipgrid">{tip_html}</ul></section>' if tip_html else ''}
{f'<section class="sec"><h2>Tři tipy, co dostanete za {kc(bud)}</h2><div class="bgrid one">{budget_html(ctx, bud, c["path"], more=False)}</div></section>' if bud else ''}
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
<p>Nevíte, který vybrat? <a href="/jaky-iphone-koupit/">Doporučení podle rozpočtu</a></p></section>
<section class="sec"><h2>Srovnání dvou modelů</h2><ul class="chips">{"".join(f'<li><a href="/srovnani/{a}-vs-{b}/">{E(MODEL[a]["name"])} vs. {E(MODEL[b]["name"])}</a></li>' for a, b in VS_PAIRS)}</ul></section></div>"""
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


REVIEW_SHOPS = ("jabkolevne", "mobilegear", "iphonemarket")   # specialists people search by name ("jabkolevně recenze" 1 000/month, KD 0)


def shop_review(ctx, s, of):
    """'Recenze' from data only: we have not ordered here, so we say what the offer looks like and how it compares. No invented customer reviews."""
    name = SHOP[s]["name"]
    ref = [o for o in of if o["g"] != "novy"]
    if len(ref) < 20:
        return ""
    models = len({o["model"] for o in ref})
    by_g = defaultdict(list)
    for o in ref:
        by_g[o["g"]].append(o["p"])
    cmp_rows, wins = [], 0
    for (m, gb, g), mine in ((k, [o["p"] for o in ref if (o["model"], o["gb"], o["g"]) == k]) for k in {(o["model"], o["gb"], o["g"]) for o in ref}):
        others = [x["p"] for x in ctx["offers"] if x["shop"] != s and x["g"] == g and x["model"] == m and x["gb"] == gb]
        if len(others) >= 2:
            cmp_rows.append(min(mine) <= min(others))
    share = round(sum(cmp_rows) / len(cmp_rows) * 100) if len(cmp_rows) >= 20 else None
    bat = sum(1 for o in ref if o["bat"])
    gl = ", ".join(f'{GR[g]["short"]} {len(v)}' for g, v in sorted(by_g.items(), key=lambda x: P.GRADE_ORDER[x[0]]))
    code = ctx["coupons"].get(s)
    t = [f'<p>{E(name)} má dnes ve srovnání <strong>{nab(len(ref))}</strong> použitých, repasovaných a zánovních iPhonů ({models} modelů), od {kc(min(o["p"] for o in ref))}. Rozdělení podle kvality (kusů): {gl}.</p>']
    if share is not None:
        t.append(f'<p>U stejného modelu, paměti a kvality má {E(name)} nejnižší cenu v <strong>{share}&nbsp;%</strong> z {len(cmp_rows)} srovnatelných kombinací, '
                 'u kterých nabízí aspoň dva další obchody.</p>')
    t.append((f'<p>Kondici baterie uvádí {round(bat / len(ref) * 100)}&nbsp;% nabídek. ' if bat else '<p>Kondici baterie obchod v produktovém exportu neuvádí, ptejte se na ni před nákupem. ') + (f'Platný slevový kód: <strong>{E(code[0]["code"])}</strong> ({E(code[0]["label"])}).' if code else 'Slevový kód teď nemá.') + '</p>')
    return (f'<section class="sec prose"><h2>{E(name)} recenze: co ukazují data</h2>' + "".join(t)
            + f'<p class="muted">Nákup u {E(name)} jsme nezkoušeli, hodnotíme jen nabídku a ceny z produktového exportu obchodu. Zkušenosti zákazníků hledejte na Heurece nebo Googlu. '
              f'Jak obchody srovnáváme, vysvětluje stránka <a href="/o-webu/">o webu</a>, přehled obchodů je v <a href="/obchody/">srovnání obchodů</a>.</p></section>')


def page_shops(out, ctx):
    li = "".join(f'<li><a class="shopc" href="/obchody/{s}/">{shop_logo(s, 30)}<span>{nab(ctx["shop_count"][s])}'
                 f'{" · slevový kód" if ctx["coupons"].get(s) else ""}</span></a></li>' for s in ctx["shop_ids"])
    body = (f'<div class="wrap"><header class="mhead"><h1>Obchody s repasovanými iPhony ve srovnání</h1><p class="lead">Odkud bereme nabídky, kolik jich má který obchod, '
            f'za kolik nejlevněji prodává a jaké slevové kódy platí. Data z {date_cz(TODAY)}.</p></header><ul class="shopgrid">{li}</ul>'
            f'<section class="sec"><h2>Obchody v číslech</h2>{shop_table(ctx)}</section>'
            '<section class="sec prose catseo"><h2>Jak vybrat obchod s repasovanými iPhony</h2>'
            '<p>Cena je jen polovina rozhodnutí. Před nákupem si u obchodu ověřte <strong>délku záruky</strong> (u použitého zboží smí být 12 měsíců, některé obchody dávají 24), '
            '<strong>jak popisuje stav</strong> (u nás ho převádíme na jednu stupnici A+ až C), jestli uvádí <strong>kondici baterie</strong> a jestli fotí konkrétní kus, nebo jen ilustrační obrázek.</p>'
            '<p>Specializované obchody (MobileGear, JabkoLevně, iPhoneMarket, Smarty) mají nejširší výběr repasů. Na Aukru a Allegru prodávají firmy i soukromníci: '
            'záruku a 14 dní na vrácení máte jen u firmy. iSTYLE prodává nové iPhony. '
            '<a href="/pruvodce/kde-koupit-repasovany-iphone/">Podrobný návod, kde koupit repasovaný iPhone</a>. Mezinárodní specialisty a české obchody vedle sebe ukazuje <a href="/pruvodce/srovnani-obchodu-s-repasy/">srovnání Swappie, Refurbed a JabkoLevně</a>.</p></section></div>')
    out.page("/obchody/", layout(ctx, path="/obchody/", title="Obchody s repasovanými iPhony – ceny a slevové kódy",
                                 desc="Obchody s repasovanými a použitými iPhony ve srovnání: počet nabídek, nejnižší ceny, podíl nabídek s kondicí baterie a platné slevové kódy.",
                                 body=body, crumbs=[("/", "Repasované iPhony"), ("/obchody/", "Obchody")]))
    for s in ctx["shop_ids"]:
        sh, of = SHOP[s], [o for o in ctx["offers"] if o["shop"] == s]
        info = SHOP_INFO.get(s, {})
        gc = Counter(o["g"] for o in of)
        dist = "".join(f'<li>{grade_chip(g)} {E(GR[g]["name"])} <b>{num(gc[g])}</b></li>' for g, *_r in P.GRADES if gc.get(g))
        rows = sorted(best_per_model(ctx, lambda m, o, s=s: o["shop"] == s, grades=tuple(GR)), key=lambda r: (-r[0]["year"], r[1]["pc"]))
        cps_ = ctx["coupons"].get(s, [])
        cbox = "".join(coupon_box(c, f"/go/{s}/?u=/", buttons=False) for c in cps_[:1]).replace("</code>", f'</code><button type="button" class="cpn-copy" data-copy="{E(cps_[0]["code"])}" data-shop="{s}"{href_attr(f"/go/{s}/?u=/")}>Kopírovat</button>', 1) if cps_ else ""
        c0 = cps_[0] if cps_ else None
        cta = (f'<p class="shopcta"><a class="btn big" href="/go/{s}/?u=/" rel="sponsored nofollow noopener" target="_blank" data-go="{s}" data-shop="{s}" data-sp="shop"'
               + (f' data-copy="{E(c0["code"])}">Koupit s kódem u {E(sh["name"])}' if c0 else f'>Přejít do obchodu {E(sh["name"])}')
               + '</a><small>Konkrétní iPhone vyberete níže, ceny jsou včetně platných slevových kódů.</small></p>')
        review = shop_review(ctx, s, of) if s in REVIEW_SHOPS else ""
        body = f"""<div class="wrap"><header class="mhead shophead">{shop_logo(s, 40)}<h1>{E(sh["name"])}: iPhony a ceny</h1><p class="lead">{info.get("lead", "")}</p>{cbox}{cta}</header>
<section class="sec two"><div class="prose">{info.get("text", "")}<h2>Nabídka podle kvality</h2><ul class="gdist">{dist}</ul></div>
<aside class="card"><dl class="specs"><dt>Nabídek</dt><dd>{num(len(of))}</dd><dt>Cena od</dt><dd>{kc(min(o["pc"] for o in of))}</dd><dt>Web</dt><dd>{E(sh["domain"])}</dd></dl></aside></section>
{review}<section class="sec"><h2>Nejlevnější kus každého modelu</h2>{cat_rows(ctx, rows, 30)}</section></div>"""
        out.page(f"/obchody/{s}/", layout(ctx, path=f"/obchody/{s}/", title=(f"{sh['name']} recenze: nabídka, ceny a slevový kód" if s in REVIEW_SHOPS else f"{sh['name']} – iPhony, ceny a slevové kódy"),
                                          desc=f"iPhony z {sh['name']}: {nab(len(of))} od {kc(min(o['pc'] for o in of))}, kvalita na jedné stupnici a platné slevové kódy.".replace(" ", " "),
                                          body=body, crumbs=[("/", "Repasované iPhony"), ("/obchody/", "Obchody"), (f"/obchody/{s}/", sh["name"])], index=len(of) >= 5),
                 index=len(of) >= 5)


def shop_table(ctx):
    rows = []
    for s in ctx["shop_ids"]:
        of = [o for o in ctx["offers"] if o["shop"] == s]
        if not of:
            continue
        ref = [o for o in of if o["g"] != "novy"]
        bat = sum(1 for o in of if o["bat"])
        code = ", ".join(c["code"] for c in ctx["coupons"].get(s, [])) or "–"
        rows.append(f'<tr><th scope="row"><a href="/obchody/{s}/">{E(SHOP[s]["name"])}</a></th><td class="num">{num(len(of))}</td>'
                    f'<td class="num">{kc(min(o["pc"] for o in ref)) if ref else "–"}</td><td class="num">{kc(min(o["pc"] for o in of if o["g"] == "novy")) if any(o["g"] == "novy" for o in of) else "–"}</td>'
                    f'<td class="num">{round(bat / len(of) * 100)}&nbsp;%</td><td>{E(code)}</td></tr>')
    return ('<div class="tscroll"><table class="ptable cmp"><thead><tr><th>Obchod</th><th>Nabídek</th><th>Použitý od</th><th>Nový od</th>'
            '<th>Uvádí baterii</th><th>Slevový kód</th></tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>')


def battery_stats(ctx):
    rf = [o for o in ctx["offers"] if o["g"] != "novy"]
    bats = sorted(o["bat"] for o in rf if o["bat"])
    if not bats:
        return "<p>Kondici baterie obchody v exportech teď neuvádějí.</p>"
    bands = [("95–100 %", 95, 101), ("90–94 %", 90, 95), ("85–89 %", 85, 90), ("80–84 %", 80, 85), ("pod 80 %", 0, 80)]
    tr = "".join(f'<tr><th scope="row">{lab}</th><td class="num">{num(sum(1 for b in bats if lo <= b < hi))}</td>'
                 f'<td class="num">{round(sum(1 for b in bats if lo <= b < hi) / len(bats) * 100)}&nbsp;%</td></tr>' for lab, lo, hi in bands)
    return (f'<p>Ze {num(len(rf))} repasovaných a použitých nabídek ve srovnání uvádí kondici baterie {num(len(bats))} ({round(len(bats) / len(rf) * 100)}&nbsp;%). '
            f'Typická hodnota je {bats[len(bats) // 2]}&nbsp;%. Rozložení k {date_cz(TODAY)}:</p>'
            f'<div class="tscroll"><table class="ptable cmp"><thead><tr><th>Kondice</th><th>Nabídek</th><th>Podíl</th></tr></thead><tbody>{tr}</tbody></table></div>')


def ios_table(ctx):
    tr = []
    for m in MODELS:
        lo = low_of(ctx, m["slug"])
        tr.append(f'<tr><th scope="row">{link_m(m, "") if ctx["by_model"].get(m["slug"]) else E(m["name"])}</th><td>{m["year"]}</td>'
                  f'<td>{"ano" if ios_ok(m) else "ne, poslední " + LAST_IOS.get(m["slug"], "starší")}</td><td class="num">{kc(lo) if lo else "–"}</td></tr>')
    return ('<div class="tscroll"><table class="ptable cmp"><thead><tr><th>Model</th><th>Rok</th><th>iOS 26 a 27</th><th>Z druhé ruky od</th></tr></thead><tbody>'
            + "".join(tr) + "</tbody></table></div>")


def load_guides():
    pf = APP / "content/guides/photos.json"
    photos = json.loads(pf.read_text()) if pf.exists() else {}   # featured photos (Pexels), downloaded once to static/img/guides/
    gs = []
    for f in sorted((APP / "content/guides").glob("*.html")):
        txt = f.read_text()
        m = re.match(r"<!--(.*?)-->\s*", txt, re.S)
        meta = json.loads(m.group(1))
        meta["html"], meta["slug"] = txt[m.end():], f.stem
        meta.setdefault("path", f"/pruvodce/{f.stem}/")   # a guide promoted to its own landing keeps the article template ("path" in its header)
        meta.setdefault("photo", photos.get(f.stem, {}))
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


def slugify(t):
    import unicodedata
    t = unicodedata.normalize("NFKD", t.lower())
    return re.sub(r"[^a-z0-9]+", "-", "".join(c for c in t if not unicodedata.combining(c))).strip("-")


GUIDE_ICON = {"tag": "coins", "refresh": "return", "phone": "tools", "box": "bag"}   # guide icon names -> files in static/img/ui
GUIDE_GROUPS = [("zaklady", "Než začnete"), ("vyber", "Jak vybrat"), ("kontrola", "Kontrola a bezpečnost"), ("po", "Po nákupu")]


def guide_html(ctx, g):
    rf = ctx["refurb"]
    rep_ = {"{{GRADE_TABLE}}": lambda: grade_table(ctx), "{{IOS_TABLE}}": lambda: ios_table(ctx), "{{SHOP_TABLE}}": lambda: shop_table(ctx),
            "{{BATTERY_STATS}}": lambda: battery_stats(ctx), "{{N_OFFERS}}": lambda: num(len(rf)), 
            "{{LOW_PRICE}}": lambda: kc(min(o["pc"] for o in rf)), "{{VF_URL}}": lambda: VODAFONE,
            "{{VYKUP_TABLE}}": lambda: vykup_table(ctx), "{{VYKUP_SHOPS}}": lambda: vykup_shops(ctx)}
    h = g["html"]
    for k, f in rep_.items():
        if k in h:
            h = h.replace(f"<p>{k}</p>", k).replace(k, f())
    toc, seen = [], set()

    def anchor(mo):
        txt = re.sub(r"<[^>]+>", "", mo.group(2))
        a = slugify(txt)[:48] or f"s{len(toc)}"
        while a in seen:
            a += "-2"
        seen.add(a)
        toc.append((a, txt))
        return f'<h2{mo.group(1)} id="{a}">{mo.group(2)}</h2>'
    h = re.sub(r"<h2([^>]*)>(.*?)</h2>", anchor, h)
    return h, toc


def vykup_table(ctx):
    """/vykup-iphonu/: today's cheapest refurbished piece per model (its most common storage) = the ceiling for a trade-in or private sale.
    Only our own prices; we publish no buy-back prices (they are the shops' and change daily)."""
    rows = []
    for m in MODELS:
        rf = [o for o in ctx["refurb"] if o["model"] == m["slug"]]
        if len(rf) < 3:
            continue
        gb = Counter(o["gb"] for o in rf).most_common(1)[0][0]
        cells = []
        for gs in (("aplus", "a"), ("b",), ("c",)):
            ps = [o["pc"] for o in rf if o["gb"] == gb and o["g"] in gs]
            cells.append(f"<td>{kc(min(ps))}</td>" if ps else '<td class="na">–</td>')
        rows.append(f'<tr><th><a href="/{m["slug"]}/?pamet={gb}">{E(m["name"])}</a> <span class="muted">{P.gb_label(gb)}</span></th>{"".join(cells)}</tr>')
    return ('<div class="tscroll"><table class="ptable prt vyk"><thead><tr><th>Model, nejčastější paměť</th><th>Stav A / A+</th><th>Stav B</th><th>Stav C</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div><p class="muted small">Nejnižší cena repasovaného kusu v obchodech v našem srovnání, {date_cz(TODAY)}, '
            'po započtení platného slevového kódu. Ceny se aktualizují každou noc. Výkupní ceny obchodů neuvádíme, každý výkup je určuje sám podle kontroly telefonu.</p>')


def vykup_shops(ctx):
    """Shops in the comparison that buy iPhones (terms.vykup in data/shops.json, each checked on the shop's own page)."""
    li = []
    for s in ctx["shop_ids"]:
        v = SHOP[s].get("terms", {}).get("vykup")
        if v:
            li.append(f'<li>{shop_logo(s, 20)}<p>{E(v["t"])}</p><a class="btn ghost" href="/go/{s}/?u={v["u"]}" rel="sponsored nofollow noopener" target="_blank" '
                      f'data-go="{s}" data-shop="{s}" data-sp="vykup">Výkup {E(SHOP[s]["name"])}</a></li>')
    return (f'<ul class="vshops">{"".join(li)}</ul><p class="muted small">Podle stránek obchodů k {date_cz(dt.date.fromisoformat(max(SHOP[s]["terms"]["vykup"]["checked"] for s in ctx["shop_ids"] if SHOP[s].get("terms", {}).get("vykup"))))}. '
            'Postup i podmínky se můžou změnit, platí to, co obchod uvádí při výkupu.</p>') if li else ""


GUIDE_PICK = {   # one factual sentence tying the guide to the comparison (what the visitor sees at the offers)
    "baterie": "U každé nabídky ukazujeme, co prodejce o baterii uvádí: kondici konkrétního kusu, garantované minimum, nebo že údaj chybí.",
    "stavy": "Kvalitu A+, A, B nebo C vyberete u každého modelu a hned uvidíte nejlevnější obchod.",
    "kde-koupit-repasovany-iphone": "Stejný model ve stejné kvalitě porovnáme napříč obchody, včetně platných slevových kódů.",
    "srovnani-obchodu-s-repasy": "Stejný model ve stejné kvalitě porovnáme napříč obchody, včetně platných slevových kódů.",
    "iphone-z-bazaru": "Bez rizika zamčeného iCloudu a se zárukou: použité iPhony od obchodů a firem.",
    "repas-vs-bazar": "Použité iPhony od obchodů mají záruku a 14 dní na vrácení při nákupu online.",
    "zaruka": "U nabídek ukazujeme záruku, kterou obchod uvádí, nebo že ji neuvádí.",
    "jaka-pamet": "U každého modelu vyberete paměť a uvidíte, o kolik je vyšší paměť dražší.",
    "prodej-stareho-iphonu": "Peníze z výkupu často pokryjí velkou část repasu o dvě až tři generace novějšího. Dnešní ceny:",
    "podpora-ios": "Modely s aktuálním iOS najdete v přehledu levných iPhonů i v doporučeních podle rozpočtu.",
}


def pick_models(ctx, n=6):
    pop = [m for m in sorted(MODELS, key=lambda m: -len(ctx["by_model"].get(m["slug"], []))) if ctx["by_model"].get(m["slug"]) and ios_ok(m)][:n]
    return sorted(pop, key=lambda m: -m["year"])


def pick_box(ctx, slug=""):
    """Bridge from an article to the comparison: the most offered models with today's price."""
    chips = "".join(f'<li><a href="/{m["slug"]}/">{E(m["name"])} <span>od {kc(low_of(ctx, m["slug"]))}</span></a></li>' for m in pick_models(ctx))
    ctxt = GUIDE_PICK.get(slug, 'Ceny obchodů každou noc, včetně slevových kódů.')
    return (f'<aside class="pickbox"><p class="pk-h">Hledáte iPhone?</p><p class="pk-t">{E(ctxt)}</p><ul class="pk-chips">{chips}</ul>'
            '<p class="pk-more"><a href="/levny-iphone/">Nejlevnější iPhony</a> · <a href="/#rozpocet">Podle rozpočtu</a> · <a href="/iphone-bazar/">Bazar se zárukou</a> · <a href="/#modely">Všechny modely</a></p></aside>')


def page_guides(out, ctx):
    groups = []
    for key, name in GUIDE_GROUPS:
        gs = [g for g in ctx["guides"] if g.get("group", "zaklady") == key]
        if gs:
            li = "".join(f'<li><a href="{g["path"]}"><img src="/img/ui/ic-{GUIDE_ICON.get(g.get("icon"), g.get("icon", "search"))}.webp" alt="" width="56" height="56" loading="lazy">'
                         f'<b>{E(g["h1"])}</b><span>{E(g["desc"])}</span></a></li>' for g in gs)
            groups.append(f'<section class="sec"><h2>{E(name)}</h2><ul class="glist">{li}</ul></section>')
    hub_ld = [{"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "url": SITE + g["path"], "name": g["h1"]} for i, g in enumerate(ctx["guides"])]}]
    out.page("/pruvodce/", layout(ctx, path="/pruvodce/", title="Průvodce nákupem repasovaného a použitého iPhonu",
                                  desc="Co znamená repasovaný iPhone, kvalita A, B, C, kondice baterie, podpora iOS, kontrola IMEI a iCloudu, záruka a nákup z bazaru. Návody krok za krokem.",
                                  body=f'<div class="wrap"><header class="mhead"><h1>Průvodce nákupem iPhonu z druhé ruky</h1><p class="lead">Všechno, co potřebujete vědět před nákupem '
                                       f'repasovaného, zánovního nebo bazarového iPhonu: jak vybrat model a kvalitu, co zkontrolovat při převzetí a jaká máte práva. '
                                       f'Čísla v článcích se každou noc přepočítávají z {nab(len(ctx["refurb"]))}.</p></header>{"".join(groups)}</div>',
                                  ld=hub_ld, crumbs=[("/", "Repasované iPhony"), ("/pruvodce/", "Průvodce")], active="/pruvodce/"))
    for g in ctx["guides"]:
        path = g["path"]
        html_, toc = guide_html(ctx, g)
        hs = [mo.start() for mo in re.finditer(r"<h2[ >]", html_)]
        if len(hs) >= 3:      # a short line after the second section, the full box before the FAQ
            html_ = (html_[:hs[2]] + '<p class="pickline">Hledáte konkrétní iPhone? <a href="/#modely">Vyberte model</a> nebo se podívejte na '
                     '<a href="/levny-iphone/">nejlevnější iPhony dnes</a>.</p>' + html_[hs[2]:])
        toc_html = ('<nav class="toc" aria-label="Obsah článku"><b>Obsah</b><ol>' + "".join(f'<li><a href="#{a}">{E(t)}</a></li>' for a, t in toc) + "</ol></nav>") if len(toc) >= 3 else ""
        faq = [tuple(x) for x in g.get("faq", [])]
        same = [x for x in ctx["guides"] if x is not g and x.get("group") == g.get("group")]
        rest = [x for x in ctx["guides"] if x is not g and x not in same]
        others = "".join(f'<li><a href="{x["path"]}">{E(x["short"])}</a></li>' for x in same + rest)
        photo = g.get("photo") or {}
        hero = (f'<figure class="ghero"><img src="{photo["src"]}" alt="{E(photo.get("alt", ""))}" width="1200" height="630" fetchpriority="high">'
                f'<figcaption>Foto: {E(photo.get("by", ""))}, {E(photo.get("site", "Pexels"))}</figcaption></figure>') if photo.get("src") else ""
        upd = g.get("updated", TODAY.isoformat())
        body = (f'<div class="wrap"><article class="prose art"><h1>{E(g["h1"])}</h1><p class="meta muted">Aktualizováno {date_cz(dt.date.fromisoformat(upd))} · '
                f'ceny a počty z {date_cz(TODAY)}</p>{hero}{toc_html}{html_}{pick_box(ctx, g["slug"])}'
                + (f'<h2 id="caste-otazky">Časté otázky</h2>{faq_html(faq)}' if faq else "")
                + f'</article><section class="sec"><h2>Další průvodci</h2><ul class="chips">{others}</ul></section></div>')
        art = {"@context": "https://schema.org", "@type": "Article", "headline": g["h1"], "description": g["desc"], "inLanguage": "cs",
               "datePublished": g.get("published", "2026-11-25"), "dateModified": upd, "mainEntityOfPage": SITE + path,
               "author": {"@type": "Organization", "name": BRAND, "url": SITE + "/o-webu/"},
               "publisher": {"@type": "Organization", "name": BRAND, "logo": {"@type": "ImageObject", "url": SITE + "/favicon-512.png"}}}
        if photo.get("src"):
            art["image"] = SITE + photo["src"]
        ld = [art] + ([faq_ld(faq)] if faq else [])
        out.page(path, layout(ctx, path=path, title=short_title(g["title"]), desc=g["desc"], body=body, ld=ld, active=None if g.get("landing") else "/pruvodce/",
                              og_img=SITE + photo["src"] if photo.get("src") else "",
                              crumbs=[("/", "Repasované iPhony")] + ([] if g.get("landing") else [("/pruvodce/", "Průvodce")]) + [(path, g["short"])]))


PARTNER_MAIL = "info@repasovanyiphone.cz"   # forwarded by Cloudflare Email Routing to napis@sbalit.cz


HC_IFRAME = "https://espolupracecz.go2cloud.org/aff_c?offer_id=40&aff_id=18313&file_id=46457&url_id=1275&utm_term=1275"   # eSpolupráce, Home Credit půjčka (Kenny 25. 11. 2026)
HC_ORIGINS = ("https://espolupracecz.go2cloud.org", "https://produkty.espoluprace.cz")   # go2cloud redirects the frame to produkty.espoluprace.cz
LOAN_MIN = 10000         # the form lends 10 000-250 000 Kč; below that the loan line is not shown
LOAN = "/iphone-na-splatky/"
HC_LOGO = '<img class="hc-logo" src="/img/partners/homecredit.svg" alt="Home Credit" width="{w}" height="{h}" loading="lazy" decoding="async">'


def loan_link(z, place, text="iPhone na splátky"):
    """Link to the instalments landing; z = the page the visitor comes from (passed to the partner as aff_sub2)."""
    return f'<a href="{LOAN}?z={z}" data-loan="{place}">{text}</a>'


def page_loan(out, ctx):
    """Partner terms (eSpolupráce offer 40): every page promoting Home Credit must be approved by the advertiser
    (podpora.espoluprace@srovnejto.cz), and wherever loan qualities (amount, term…) are described, the Home Credit brand
    must not be named in that sentence ("Ve spolupráci s Home Credit" / "nabízí půjčky Home Credit" are fine).
    /iphone-na-splatky/: buying the iPhone comes first (models, shops with instalments at checkout), the Home Credit loan form
    (eSpolupráce iframe, run by Elephant Orchestra / Srovnejto.cz) second. No figures about the cost of credit on our side:
    a rate, APR or instalment in an advert needs a representative example, which only the lender can give."""
    refurb = ctx["refurb"]
    picks = []
    for m in MODELS:
        rf = [o for o in refurb if o["model"] == m["slug"]]
        if rf and ios_ok(m) and LOAN_MIN <= min(o["pc"] for o in rf) <= 30000:
            picks.append((m, len(rf), min(o["pc"] for o in rf)))
    picks = sorted(sorted(picks, key=lambda x: -x[1])[:6], key=lambda x: x[2])     # the six most offered, cheapest first
    models = "".join(f'<li><a href="/{m["slug"]}/">{E(m["name"])}</a><span>od {kc(pc)}</span></li>' for m, _n, pc in picks)
    shops = [s for s in ctx["shop_ids"] if (SHOP[s].get("terms") or {}).get("splatky")]
    shop_li = "".join(
        f'<li>{shop_logo(s, 20)}<a href="/go/{s}/?u=/" rel="sponsored nofollow noopener" target="_blank" data-go="{s}" data-sp="spl">Do obchodu</a></li>' for s in shops)
    items = [("Kolik si můžu půjčit na iPhone?",
              "Formulář přijímá žádosti o půjčku od 10 000 do 250 000 Kč. Kolik vám půjčí a za jakých podmínek, uvidíte v nabídce, kterou dostanete po vyplnění žádosti."),
             ("Kdo půjčku poskytuje a kdo zpracuje žádost?",
              "Nabídka je od Home Credit. Formulář provozuje Elephant Orchestra, s.r.o. (Srovnejto.cz), registrovaný zprostředkovatel spotřebitelských úvěrů, který se vám ozve "
              "a žádost s vámi dokončí. Repasovanyiphone.cz úvěry nezprostředkovává a údaje z formuláře nevidí."),
             ("Splátky v obchodě, nebo půjčka?",
              "Splátky u obchodu se sjednávají přímo při objednávce telefonu, peníze jdou rovnou obchodu. Půjčka je volnější: peníze dostanete vy a iPhone koupíte, kde chcete. "
              "Podmínky obou možností si před podpisem porovnejte, rozhodující je celková částka, kterou zaplatíte."),
             ("Co když iPhone stojí méně než 10 000 Kč?",
              'Pak se půjčka přes tento formulář nehodí, začíná na 10 000 Kč. Repasovaný iPhone 13 nebo 14 se dá koupit i pod touto hranicí, viz <a href="/iphone-do-10000-kc/">iPhony do 10 000 Kč</a>.'),
             ("Jaké údaje formulář chce?",
              "Výši půjčky, jméno, telefon, e-mail, rodné číslo, adresu, zdroj a výši příjmu. Údaje zadáváte přímo zprostředkovateli, ten s nimi nakládá podle svých podmínek uvedených ve formuláři.")]
    ir = (APP / "scripts/vendor/iframeResizer-4.3.11.min.js").read_text()
    sandbox = "allow-same-origin allow-scripts allow-popups allow-top-navigation-by-user-activation allow-forms"
    # the form is above the fold: load it at once; the inline script right after the frame adds aff_sub2 (the page the visitor came from).
    # Height: lowestElement. bodyOffset (the default) cut the last 8 px (the mandatory information link), documentElementScroll never shrinks.
    frame = (f'<div class="hc-frame"><iframe id="hcf" title="Žádost o půjčku" data-src="{E(HC_IFRAME)}&amp;aff_sub=rp&amp;aff_sub2=" sandbox="{sandbox}" scrolling="no" width="100%"></iframe>'
             f'<noscript><iframe title="Žádost o půjčku" src="{E(HC_IFRAME)}&amp;aff_sub=rp&amp;aff_sub2=landing" sandbox="{sandbox}" width="100%" class="hc-noscript"></iframe></noscript></div>'
             f'<script>{ir}</script>'
             '<script>(function(){var f=document.getElementById("hcf"),z=new URLSearchParams(location.search).get("z")||"";if(!/^[a-z0-9-]{1,40}$/.test(z))z="landing";'
             'f.src=f.dataset.src.replace(/&amp;/g,"&")+z;if(window.iFrameResize)window.iFrameResize({checkOrigin:' + json.dumps(list(HC_ORIGINS))
             + ',heightCalculationMethod:"lowestElement",warningTimeout:0,'
             'onResized:function(d){d.iframe.style.height=(Math.ceil(+d.height)+8)+"px"}},f)})();</script>')
    body = f"""<div class="wrap loan"><div class="loan-top">
<div class="loan-main"><header class="loan-head"><p class="eyebrow">Ve spolupráci s {HC_LOGO.format(w=52, h=22)}</p><h1>iPhone na splátky</h1>
<p class="lead">Vyplňte žádost o půjčku od 10&nbsp;000 Kč, ozvou se vám a iPhone pak koupíte, kde vyjde nejlépe.</p></header>
<p class="hc-note">Formulář provozuje Elephant Orchestra, s.r.o., IČ 03272974 (Srovnejto.cz), registrovaný zprostředkovatel spotřebitelských úvěrů. Údaje zadáváte přímo jim, my je nevidíme.</p>
{frame}</div>
<aside class="loan-side">
<section><h2>Jak to proběhne</h2><ol class="lsteps"><li><b>Vyplníte žádost.</b> Výši půjčky a základní údaje, pár minut.</li>
<li><b>Ozvou se vám.</b> Zprostředkovatel s vámi žádost dokončí a ukáže podmínky.</li><li><b>Koupíte iPhone.</b> V obchodě, který vyjde nejlépe, třeba podle našeho srovnání.</li></ol></section>
{f'<section><h2>Splátky přímo v obchodě</h2><p class="muted">Tyto obchody nabízejí splátky při objednávce, podmínky uvidíte v košíku.</p><ul class="lshops">{shop_li}</ul></section>' if shop_li else ''}
<section><h2>Ještě nemáte vybráno?</h2><ul class="lmodels">{models}</ul><p class="lmore"><a href="/levny-iphone/">Všechny iPhony</a> · <a href="/jaky-iphone-koupit/">Jaký iPhone koupit</a></p></section>
</aside></div>
<section class="sec loan-faq"><h2>Časté otázky</h2>{faq_html(items)}
<p class="note">Home Credit je náš affiliate partner: když půjčku přes formulář sjednáte, můžeme dostat provizi. Vás to nic nestojí a srovnání iPhonů ani pořadí obchodů to neovlivňuje. <a href="/o-webu/">Jak web funguje</a></p></section>
</div>"""
    pre = "".join(f'<link rel="preconnect" href="{o}">' for o in HC_ORIGINS)
    out.page(LOAN, layout(ctx, path=LOAN, title="iPhone na splátky – žádost o půjčku na telefon",
                          desc="iPhone na splátky: žádost o půjčku na telefon od 10 000 Kč přímo na stránce, nebo splátky při objednávce v obchodě. Pak vyberte iPhone v našem srovnání.",
                          body=body, crumbs=[("/", "Repasované iPhony"), (LOAN, "iPhone na splátky")], ld=[faq_ld(items)], preload=pre))


def page_partners(out, ctx):
    """B2B landing for shops selling refurbished iPhones: free listing, contact by e-mail. Linked only from the footer."""
    n_off, n_shops = len(ctx["offers"]), len(ctx["shop_ids"])
    n_models = sum(1 for m in MODELS if ctx["by_model"].get(m["slug"]))
    n_pages = len(out.pages)
    mail = f'mailto:{PARTNER_MAIL}?subject=' + "Spolupr%C3%A1ce%20%E2%80%93%20n%C3%A1%C5%A1%20obchod"
    cta = (f'<p class="pp-cta"><a class="btn big" href="{mail}">Chci se přidat</a><span class="muted">nebo napište na <a href="{mail}">{PARTNER_MAIL}</a>, '
           'odpovídáme do dvou pracovních dnů</span></p>')
    why = [("ic-tap", "Zákazník, který už vybírá",
            "K vám nepřijde člověk, který „se jen dívá“. Přijde někdo, kdo si právě zvolil model, barvu, paměť i kvalitu a hledá, kde ho koupit."),
           ("ic-search", "Přesně ten kus, který máte",
            "Párujeme nabídky na úroveň konfigurace. Když máte iPhone 13 se 128 GB v modré v kvalitě B, ukážeme ho přesně lidem, kteří hledají tohle."),
           ("ic-shield", "Pořadí si nikdo nekoupí",
            "Řadíme jen podle konečné ceny. Pro vás to znamená férový souboj a pro zákazníky důvod nám věřit. A ta důvěra se přenáší na obchod, ke kterému je pošleme."),
           ("ic-coins", "Slevový kód jako trumf",
            "Platný kód rovnou odečteme z ceny a ukážeme ho u nabídky. Kód, který byste jinak schovávali do newsletteru, tu prodává.")]
    why_html = "".join(f'<li><img src="/img/ui/{i}.webp" alt="" width="56" height="56" loading="lazy"><b>{E(t)}</b><span>{E(d)}</span></li>' for i, t, d in why)
    faq = [("Je to opravdu zdarma?",
            "Ano. Za zařazení do srovnání, za zobrazení ani za prokliky neplatíte nic a nic vám nefakturujeme. Pokud máte affiliate program v síti eHub nebo CJ, rádi se přidáme, "
            "ale podmínkou spolupráce to není."),
           ("Proč to děláte zadarmo?",
            "Srovnávač je tak dobrý, kolik má obchodů. Každý další obchod znamená přesnější ceny, víc barev a pamětí skladem a víc lidí, kteří se k nám vracejí. "
            "Na části obchodů vyděláváme provizí z affiliate sítí, srovnání jako celek se tak zaplatí samo."),
           ("Můžu si připlatit za lepší pozici?",
            "Ne, a to je dobře i pro vás. Řadíme jen podle ceny po slevovém kódu. Kdo má nejlepší cenu, je první, ať je to velký e-shop, nebo malý specialista."),
           ("Nemáme XML feed. Jde to i jinak?",
            "Většinou ano. Stačí feed pro Heureku, Zboží.cz nebo Google Nákupy, který už nejspíš máte. Když nemáte ani ten, napište, domluvíme se na exportu z vašeho systému."),
           ("Jak rychle budeme ve srovnání?",
            "Obvykle do několika pracovních dnů od chvíle, kdy dostaneme feed. Ceny pak aktualizujeme automaticky každou noc."),
           ("Můžeme spolupráci kdykoli ukončit?",
            "Kdykoli, jedním e-mailem. Nabídky ze srovnání stáhneme a žádné závazky nevznikají."),
           ("Bereme i nové iPhony?",
            "Ano. Srovnáváme nové, rozbalené, zánovní, repasované i použité iPhony. Příslušenství a jiné značky zatím ne.")]
    body = f"""<div class="wrap pp"><header class="mhead"><p class="eyebrow">Pro obchody s repasovanými iPhony</p>
<h1>Vaše iPhony před lidmi, kteří je právě vybírají. Zdarma.</h1>
<p class="lead">Repasovanyiphone.cz srovnává repasované, zánovní, bazarové i nové iPhony z českých obchodů až na úroveň barvy, paměti a kvality.
Prodáváte iPhony? Přidejte svou nabídku. Neplatíte za zařazení, za kliky ani za objednávky.</p>{cta}</header>
<ul class="pp-stats"><li><b>{num(n_off)}</b><span>nabídek ve srovnání</span></li><li><b>{n_models}</b><span>modelů od iPhonu 7 po nejnovější</span></li>
<li><b>{num(n_pages)}</b><span>stránek, kde se vaše nabídka může objevit</span></li></ul>
<section class="sec why"><h2>Proč se vám to vyplatí</h2><ul>{why_html}</ul></section>
<section class="sec prose"><h2>Jak to u nás funguje</h2>
<p>Zákazník přijde z Googlu na dotaz jako „iPhone 13 bazar“ nebo „repasovaný iPhone 15“. V konfigurátoru si vybere barvu, paměť a kvalitu A+, A, B nebo C.
My mu ukážeme nejlevnější obchod a pod ním další nabídky. Klikne na „Koupit“ a ocitne se přímo na produktové stránce u vás, ne na rozcestníku.</p>
<p>Stav sjednocujeme na jednu stupnici, takže vaše „Stav A–“ nebo „Velmi dobrý+“ nikoho nezmate a srovnání je férové. Kondici baterie, pokud ji uvádíte,
ukážeme u nabídky. To je informace, kterou zákazníci hledají nejvíc a kterou obchody uvádějí nejméně.</p>
<p>Kromě konfigurátoru se vaše nabídky objeví v kategoriích (levné, zánovní, bazarové a nové iPhony), ve srovnáních modelů typu iPhone 13 vs. iPhone 14
a v průvodcích, které lidé čtou před nákupem. Každý obchod má navíc vlastní stránku s popisem, logem a přehledem nabídky.</p></section>
<section class="sec pp-two"><div class="card"><h2>Co dostanete</h2><ul class="pp-list">
<li>zařazení všech iPhonů z feedu, nových i použitých, s denní aktualizací cen</li>
<li>proklik přímo na produktovou stránku konkrétního kusu</li>
<li>vlastní stránku obchodu s logem a popisem</li>
<li>zvýrazněný slevový kód, pokud nějaký máte</li>
<li>na přání odkazy s UTM parametry, ať v Google Analytics vidíte každou objednávku od nás</li>
<li>to vše bez poplatku a bez smlouvy na dobu určitou</li></ul></div>
<div class="card"><h2>Co potřebujeme od vás</h2><ul class="pp-list">
<li>produktový feed (XML pro Heureku, Zboží.cz nebo Google Nákupy stačí)</li>
<li>v názvu nebo parametrech model, paměť, barvu a stav</li>
<li>cenu, dostupnost, odkaz na produkt a obrázek</li>
<li>bonus: kondici baterie, délku záruky a platné slevové kódy</li>
<li>pár vět o obchodě a logo</li></ul></div></section>
<section class="sec prose"><h2>Tři kroky a jste ve srovnání</h2><ol>
<li><strong>Napíšete nám</strong> na <a href="{mail}">{PARTNER_MAIL}</a>, kdo jste a kde najdeme feed.</li>
<li><strong>My feed napojíme</strong>, přiřadíme modely, barvy a kvalitu a pošleme vám náhled, jak budou vaše nabídky vypadat.</li>
<li><strong>Po vašem odsouhlasení</strong> jdete do srovnání. Ceny se od té chvíle aktualizují samy každou noc.</li></ol>
<p>Kdo za webem stojí a jak vyděláváme, popisujeme otevřeně na stránce <a href="/o-webu/">o webu</a>.
Obchody, které už ve srovnání jsou, najdete v přehledu <a href="/obchody/">obchodů</a>.</p></section>
<section class="sec"><h2>Časté otázky</h2>{faq_html(faq)}</section>
<section class="sec card pp-final"><h2>Pojďme to zkusit</h2><p>Jeden e-mail, jeden feed a o pár dní později vidí vaše iPhony lidé, kteří zrovna nakupují.
Když to nebude fungovat, ukončíte to stejně snadno, jako jste začali.</p>{cta}</section></div>"""
    out.page("/pro-obchody/", layout(ctx, path="/pro-obchody/", title="Pro obchody: inzerujte repasované iPhony zdarma",
                                     desc="Prodáváte repasované nebo použité iPhony? Zařadíme vaši nabídku do srovnání zdarma, bez poplatku za kliky. Zákazníci, kteří už vybírají model, barvu a kvalitu.",
                                     body=body, ld=[faq_ld(faq)], crumbs=[("/", "Repasované iPhony"), ("/pro-obchody/", "Pro obchody")]))


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
<h2>Slevové kódy</h2><p>Tlačítko „Kopírovat“ jen vloží kód do schránky vašeho zařízení. Kód nikam neodesíláme.</p>
<h2>Formulář půjčky</h2><p>Na stránce <a href="/iphone-na-splatky/">iPhone na splátky</a> je vložený formulář partnera (Home Credit přes eSpolupráce, provozuje Elephant Orchestra, s.r.o.,
IČ 03272974, Srovnejto.cz). Údaje do něj zadáváte přímo provozovateli formuláře, my je nevidíme ani neukládáme. Formulář používá vlastní cookies a měření podle podmínek uvedených v něm.</p>
<h2>Označení odkazů</h2><p>Do odkazu do obchodu přidáváme jen označení naší stránky a místa, odkud jste klikli (třeba „iphone-15“ a „best“). Affiliate síť ho vrátí u provize,
takže víme, které stránky lidem pomáhají vybrat. Nejde o osobní údaj a nic o vás neobsahuje.</p>
<h2>Jazykové verze</h2><p>Web je i v ukrajinštině a ruštině. Volbu jazyka si pamatuje váš prohlížeč (localStorage), nikam ji neposíláme. Překlady jsou informativní, závazné je české znění.</p></article></div>"""
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


SNAP_START = dt.date(2026, 11, 25)     # first daily snapshot


def snapshot(offers):
    """Daily price snapshot (from 25. 11. 2026), one file per day in the encrypted state (data/state/prices/YYYY-MM-DD.json, kept for good):
    "model|storage|grade" -> [cheapest price after code, median price after code, offers, shops]. Only the full nightly build writes it
    (env QUICK unset), a quick fix build reads. Feeds /ceny-iphonu/ and its CSV; these are tracked offers, not sales."""
    d = STATE / "prices"
    d.mkdir(parents=True, exist_ok=True)
    if not os.environ.get("QUICK"):
        grp = defaultdict(list)
        for o in offers:
            grp[f'{o["model"]}|{o["gb"]}|{o["g"]}'].append(o)
        day = {}
        for k, os_ in grp.items():
            ps = sorted(x["pc"] for x in os_)
            mid = ps[len(ps) // 2] if len(ps) % 2 else round((ps[len(ps) // 2 - 1] + ps[len(ps) // 2]) / 2)
            day[k] = [ps[0], mid, len(ps), len({x["shop"] for x in os_})]
        (d / f"{TODAY.isoformat()}.json").write_text(json.dumps(day, separators=(",", ":"), sort_keys=True))
    return {f.stem: json.loads(f.read_text()) for f in sorted(d.glob("*.json"))}


def spark(points, label):
    """One small-multiple line (one series, no legend: the card title names it). points = [(date, price or None)]."""
    W, H, px, py = 300, 96, 6, 14
    vals = [v for _, v in points if v]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = max(hi - lo, 1)
    n = len(points)
    xy = [(px + i * (W - 2 * px) / (n - 1), H - py - (v - lo) / span * (H - 2 * py)) for i, (_, v) in enumerate(points) if v]
    path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in xy)
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" class="hit"><title>{date_cz(d)}: {kc_plain(v)}</title></circle>'
                   for (x, y), (d, v) in zip(xy, [(d, v) for d, v in points if v]))
    (x0, y0), (x1, y1) = xy[0], xy[-1]
    return (f'<svg class="spark" viewBox="0 0 {W} {H}" role="img" aria-label="{E(label)}">'
            f'<line class="base" x1="{px}" x2="{W - px}" y1="{H - py + 6}" y2="{H - py + 6}"/><path class="ln" d="{path}"/>'
            f'<circle class="end" cx="{x0:.1f}" cy="{y0:.1f}" r="3.5"/><circle class="end" cx="{x1:.1f}" cy="{y1:.1f}" r="4"/>{dots}</svg>')


def page_prices(out, ctx):
    """/ceny-iphonu/: tracked prices over time (small multiples), today's table by quality, CSV and methodology."""
    snaps = ctx["snaps"]
    days = sorted(snaps)
    refurb = ctx["refurb"]
    cnt = Counter(o["model"] for o in refurb)
    top = [MODEL[m] for m, _ in cnt.most_common() if m in MODEL and ios_ok(MODEL[m])][:6]
    base = {m["slug"]: Counter(o["gb"] for o in refurb if o["model"] == m["slug"]).most_common(1)[0][0] for m in top}
    n_shops = len(ctx["shop_ids"])
    first = dt.date.fromisoformat(days[0]) if days else TODAY
    cards = []
    for m in top:
        k = f'{m["slug"]}|{base[m["slug"]]}|a'
        pts = [(dt.date.fromisoformat(d), (snaps[d].get(k) or [None])[0]) for d in days]
        vals = [v for _, v in pts if v]
        if not vals:
            continue
        ch = ""
        if len(vals) >= 2 and vals[0]:
            pct = (vals[-1] - vals[0]) / vals[0] * 100
            ch = f'<span class="pc-ch {"dn" if pct < 0 else "up" if pct > 0 else ""}">{"+" if pct > 0 else ""}{pct:.1f}\u00a0%'.replace(".", ",") + f' od {date_cz(first)}</span>'
        lab = f'{m["name"]} {P.gb_label(base[m["slug"]])}, stav A'
        sv = spark(pts, f"Nejnižší cena {lab} podle dne") if len(days) >= 7 else ""
        cards.append(f'<li class="pcard"><a href="/{m["slug"]}/?pamet={base[m["slug"]]}&amp;kvalita=a"><b>{E(m["name"])}</b> <span class="muted">{P.gb_label(base[m["slug"]])}, stav A</span></a>'
                     f'<p class="pc-now">{kc(vals[-1])}{ch}</p>{sv}</li>')
    wait = "" if len(days) >= 7 else (f'<p class="note">Ceny ukládáme každou noc od {date_cz(SNAP_START)}. Křivky se tu ukážou po prvním týdnu měření, '
                                      f'zatím máme {len(days)} {plural(len(days), "den", "dny", "dní")}. CSV níže je kompletní od prvního dne.</p>')
    # today's table: every current model with offers, base storage, by quality
    today = snaps.get(days[-1], {}) if days else {}
    rows = []
    for m in MODELS:
        if not ctx["by_model"].get(m["slug"]):
            continue
        rf = [o for o in refurb if o["model"] == m["slug"]]
        if not rf:
            continue
        gb = Counter(o["gb"] for o in rf).most_common(1)[0][0]
        cells = []
        for g in ("aplus", "a", "b", "c", "novy"):
            v = today.get(f'{m["slug"]}|{gb}|{g}')
            cells.append(f'<td>{kc(v[0])}<small>{v[2]}×</small></td>' if v else '<td class="na">–</td>')
        rows.append(f'<tr><th><a href="/{m["slug"]}/">{E(m["name"])}</a> <span class="muted">{P.gb_label(gb)}</span></th>{"".join(cells)}</tr>')
    table = ('<div class="tscroll"><table class="ptable prt"><thead><tr><th>Model, nejčastější paměť</th><th>A+</th><th>A</th><th>B</th><th>C</th><th>Nový</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table></div>')
    # CSV (semicolon + BOM: opens correctly in Czech Excel)
    lines = ["datum;model;pamet_gb;kvalita;nejnizsi_kc;median_kc;nabidek;obchodu"]
    for d in days:
        for k, v in sorted(snaps[d].items()):
            mo, gb, g = k.split("|")
            lines.append(f"{d};{mo};{gb};{g};{v[0]};{v[1]};{v[2]};{v[3]}")
    out.write("data/ceny-repasovanych-iphonu.csv", "\ufeff" + "\n".join(lines) + "\n")
    disclaimer = ("Jde o sledované nabídky obchodů a tržišť v našem srovnání, ne o prodeje ani o celý český trh. "
                  "Nabídka, která zmizí, mohla být prodaná, stažená nebo přeceněná, to z dat nepoznáme.")
    body = f"""<div class="wrap"><header class="mhead"><p class="eyebrow">Data · aktualizace každou noc</p><h1>Vývoj cen repasovaných iPhonů</h1>
<p class="lead">Kolik stojí nejlevnější repasovaný iPhone ve stavu A u šesti modelů s největší nabídkou a jak se cena mění den po dni. {E(disclaimer)}</p></header>
<section class="sec"><h2>Nejlevnější kus ve stavu A</h2>{wait}<ul class="pgrid">{"".join(cards)}</ul>
<p class="muted small">Cena po započtení platného slevového kódu, u každého modelu jeho nejčastější paměť. Každý graf má vlastní rozsah osy, porovnávejte vývoj, ne výšku křivek. Najetím na bod zobrazíte datum a cenu.</p></section>
<section class="sec"><h2>Dnešní ceny podle kvality</h2><p class="muted">Nejnižší cena a počet nabídek ({date_cz(TODAY)}). Stav převádíme na jednu stupnici, viz <a href="/pruvodce/stavy/">převodník stavů</a>.</p>{table}</section>
<section class="sec two"><div class="prose"><h2>Data ke stažení</h2>
<p><a class="btn ghost" href="/data/ceny-repasovanych-iphonu.csv" download>Stáhnout CSV</a></p>
<p>Jeden řádek = den, model, paměť a kvalita: nejnižší cena, medián, počet nabídek a počet obchodů. Oddělovač středník, kódování UTF-8. Data můžete volně použít s odkazem na repasovanyiphone.cz.</p>
<h2>Metodika</h2>
<ul><li><strong>Zdroj:</strong> produktové exporty obchodů v našem srovnání ({E(", ".join(SHOP[s]["name"] for s in ctx["shop_ids"]))}), stažené každou noc kolem 1. hodiny.</li>
<li><strong>Co počítáme:</strong> u každé kombinace modelu, paměti a kvality nejnižší cenu, medián a počet nabídek. Barvy slučujeme.</li>
<li><strong>Cena:</strong> po odečtení platného slevového kódu, pokud jde jednoznačně uplatnit. Doprava není započtená.</li>
<li><strong>Kvalita:</strong> označení obchodů převádíme na Nový, A+, A, B a C. Nabídky, které neumíme spolehlivě zařadit, vynecháváme.</li>
<li><strong>Měříme od {date_cz(SNAP_START)}.</strong> Starší historii nemáme a nedopočítáváme.</li></ul>
<p class="note">{E(disclaimer)}</p></div>
<aside><div class="card"><h2>Kde dál</h2><ul class="chips"><li><a href="/levny-iphone/">Levné iPhony</a></li><li><a href="/iphone-bazar/">iPhone bazar</a></li><li><a href="/jaky-iphone-koupit/">Jaký iPhone koupit</a></li><li><a href="/o-webu/">Jak web funguje</a></li></ul></div></aside></section></div>"""
    ld = [{"@context": "https://schema.org", "@type": "Dataset", "name": "Ceny repasovaných iPhonů v Česku (sledované nabídky)",
           "description": "Denní nejnižší a mediánové ceny repasovaných, použitých a nových iPhonů podle modelu, paměti a kvality z nabídek "
                          "českých obchodů a tržišť. " + disclaimer,
           "url": SITE + "/ceny-iphonu/", "isAccessibleForFree": True, "license": "https://creativecommons.org/licenses/by/4.0/",
           "creator": {"@type": "Organization", "name": BRAND, "url": SITE + "/"},
           "temporalCoverage": f"{days[0] if days else TODAY.isoformat()}/..", "spatialCoverage": "Česká republika",
           "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": SITE + "/data/ceny-repasovanych-iphonu.csv"}]}]
    out.page("/ceny-iphonu/", layout(ctx, path="/ceny-iphonu/", title="Vývoj cen repasovaných iPhonů – graf a data ke stažení",
                                     desc="Jak se mění ceny repasovaných iPhonů: nejlevnější kus ve stavu A u šesti modelů, dnešní ceny podle kvality, CSV a metodika. Sledované nabídky, ne prodeje.",
                                     body=body, crumbs=[("/", "Repasované iPhony"), ("/ceny-iphonu/", "Vývoj cen")], ld=ld))


WP_ARTICLES = {
    "/repasovany-iphone-pruvodce/": "/pruvodce/", "/co-znamena-repasovany-iphone/": "/pruvodce/co-znamena-repasovany-iphone/",
    "/stavy-repasovaneho-iphonu-a-b-c/": "/pruvodce/stavy/", "/jak-poznat-kvalitni-repasovany-iphone/": "/pruvodce/kontrola/",
    "/jak-dlouho-vydrzi-repasovany-iphone/": "/pruvodce/jak-dlouho-vydrzi-repasovany-iphone/", "/zaruka-repasovany-iphone/": "/pruvodce/zaruka/",
    "/iphone-z-bazaru-jak-nakupovat-bezpecne/": "/pruvodce/iphone-z-bazaru/", "/vyplati-se-repasovany-iphone/": "/pruvodce/vyplati-se-repasovany-iphone/",
    "/kde-koupit-repasovany-iphone/": "/pruvodce/kde-koupit-repasovany-iphone/", "/jak-koupit-iphone-levne/": "/levny-iphone/",
    "/nejlepsi-repasovany-iphone-2026/": "/jaky-iphone-koupit/", "/porovnat-produkty/": "/srovnani/",
    "/kategorie-produktu/iphone/": "/", "/kategorie-produktu/nove/": "/novy-iphone/",
}


def wp_legacy(current):
    """301 for URLs of the old WordPress shop that had Google impressions (data/wp-legacy-paths.json, from GSC).
    iPhone listings/products go to the model (x storage) page; Mac/iPad/Watch/accessories stay 404 on purpose:
    sending them to an unrelated page would only be a soft 404."""
    f = APP / "data/wp-legacy-paths.json"
    if not f.exists():
        return []
    models = sorted((p.strip("/") for p in current if re.fullmatch(r"/iphone-[a-z0-9-]+/", p)), key=len, reverse=True)
    out = []
    for p in json.loads(f.read_text()):
        if p in current:
            continue
        to = WP_ARTICLES.get(p)
        if not to:
            model, rest = None, ""
            m = re.match(r"^/kategorie-produktu/(?:iphone|nove)/([a-z0-9-]+?)(?:-iphone|-nove)?/(?:([a-z0-9-]+)/)?$", p)
            if m and m.group(1) in models:
                model, rest = m.group(1), (m.group(2) or "")[len(m.group(1)):]
            m = re.match(r"^/produkt/(iphone-[a-z0-9-]+)/$", p)
            if m:
                model = next((x for x in models if m.group(1).startswith(x + "-")), None)
                rest = m.group(1)[len(model or ""):]
            if model:
                to = f"/{model}/"
                st = re.match(r"-(\d+)-?(gb|tb)(?:-|$)", rest)
                if st and f"/{model}/{int(st.group(1)) * (1024 if st.group(2) == 'tb' else 1)}-gb/" in current:
                    to = f"/{model}/{int(st.group(1)) * (1024 if st.group(2) == 'tb' else 1)}-gb/"
        if to and to in current:
            out.append(f"{p} {to} 301")
    return out


MOVED = {"/pruvodce/prodej-stareho-iphonu/": "/vykup-iphonu/"}   # pages moved on purpose (25. 11. 2026: the trade-in guide became a landing)


def redirects(out, current):
    """301 for every path that existed in an earlier build and is gone now (Workers static assets read dist/_redirects)."""
    kp = STATE / "known-paths.json"
    known = set(json.loads(kp.read_text())) if kp.exists() else set()
    known |= set(out.old)
    known |= set(MOVED)
    lines = []
    for p in sorted(known - current):
        m = re.match(r"^/(iphone-[a-z0-9-]+)/\d+-gb/$", p)
        if MOVED.get(p) in current:
            to = MOVED[p]
        elif m and f"/{m.group(1)}/" in current:
            to = f"/{m.group(1)}/"
        elif p.startswith("/obchody/"):
            to = "/obchody/"
        elif p.startswith("/pruvodce/"):
            to = "/pruvodce/"
        elif p.startswith("/zanovni-iphone/"):
            to = "/zanovni-iphone/"
        else:
            to = "/"
        lines.append(f"{p} {to} 301")
        lines += [f"{pf}{p} {pf}{to} 301" for _, pf in LANG_ALT[1:]]
    kp.write_text(json.dumps(sorted(known | current)))
    lines = wp_legacy(current) + lines
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
           "shop_ids": [s["id"] for s in SHOPS if shop_count.get(s["id"])], "guides": load_guides(), "hist": history(refurb), "snaps": snapshot(offers),
           "photos": have, "col_rank": col_rank, "deals": deals, "cats": CATS, "coupons": coupons}
    ctx["zan"] = [o for o in offers if zan_typ(o)]
    zc = Counter(o["model"] for o in ctx["zan"])
    ctx["zan_all"] = set(zc) if len(ctx["zan"]) >= 20 else set()
    ctx["zan_sub"] = {s for s in ctx["zan_all"] if zc[s] >= ZAN_SUB_MIN}
    ctx["css"] = minify_css((APP / "static/assets/site.css").read_text())
    ctx["js"] = (APP / "static/assets/app.js").read_text().replace("</script", "<\\/script")
    out = Out(DIST)
    out.js_keys = i18n.js_keys(ctx["js"])
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
    if ctx["zan"]:
        page_zanovni(out, ctx)
        for s in sorted(ctx["zan_all"]):
            page_zanovni_model(out, ctx, s)
    page_compare(out, ctx)
    page_vs(out, ctx)
    page_buy(out, ctx)
    page_shops(out, ctx)
    page_guides(out, ctx)
    page_about(out, ctx)
    page_prices(out, ctx)
    page_loan(out, ctx)
    page_partners(out, ctx)
    page_privacy(out, ctx)
    page_404(out, ctx)
    golinks.write_go(out, go_tpl, SHOP)
    out.write("go/vodafone/index.html", golinks.go_page("vodafone", {"p": "", "s": "", "m": "r", "h": "", "d": ["ehub.cz"], "sd": [], "n": "ehub"}, "Vodafone",
                                                         golinks.GO_JS, default=VODAFONE_AFF, label="na"))
    n_redir = redirects(out, {p for p, _ in out.pages})

    idx = [p for p, i in out.pages if i]
    lidx = {(pf, p) for _, pf, p, i in out.lpages if i}
    sm = []
    for p in idx:
        imgs = "".join(f"<image:image><image:loc>{E(u)}</image:loc><image:title>{E(t)}</image:title></image:image>" for u, t in out.images.get(p, [])[:8])
        alts = "".join(f'<xhtml:link rel="alternate" hreflang="{HREFLANG[h]}" href="{SITE}{pf}{p}"/>' for h, pf in LANG_ALT if not pf or (pf, p) in lidx)
        alts += f'<xhtml:link rel="alternate" hreflang="x-default" href="{SITE}{p}"/>' if lidx else ""
        lm = out.lastmod.get(p, TODAY.isoformat())
        for h, pf in LANG_ALT:
            if not pf or (pf, p) in lidx:
                sm.append(f"<url><loc>{SITE}{pf}{p}</loc><lastmod>{lm}</lastmod>{alts}{imgs if not pf else ''}</url>")
    out.write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
                             'xmlns:xhtml="http://www.w3.org/1999/xhtml" '
                             f'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">{"".join(sm)}</urlset>')
    out.changed += [pf + p for p in list(out.changed) for _, pf in LANG_ALT[1:] if (pf, p) in lidx]
    miss = {tr.lang: {k: sorted(v)[:5] for k, v in sorted(tr.missing.items())} for tr in out.trs}
    for tr in out.trs:
        tr.js_missing(out.js_keys)
        miss[tr.lang] = {k: sorted(v)[:5] for k, v in sorted(tr.missing.items())}
    (STATE / "i18n-missing.json").write_text(json.dumps(miss, ensure_ascii=False, indent=0))
    for lang, keys in miss.items():     # public site text only: lets the monthly translation pass read the Actions log
        for k in list(keys)[:40]:
            print(f"i18n missing {lang}: {k[:160]}")
    (STATE / "i18n-share.json").write_text(json.dumps(out.share, indent=0))
    out.write("robots.txt", "User-agent: *\nDisallow: /\n" if STAGING else f"User-agent: *\nDisallow: /go/\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n")
    key = os.environ.get("INDEXNOW_KEY", "")
    if key:
        out.write(f"{key}.txt", key)
    ga = bool(GA4_ID)
    hashes = " ".join(csp_hashes(DIST))
    # Strict CSP: only our own inline scripts (by hash) run; 'strict-dynamic' lets them load GTM, which loads GA4. No eval, no plugins, no framing.
    csp = ("default-src 'self'; "
           f"script-src 'self' {hashes} 'strict-dynamic' 'inline-speculation-rules' https:; "
           "style-src 'self' 'unsafe-inline'; font-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; "
           "manifest-src 'self'; worker-src 'none'; upgrade-insecure-requests; "
           "img-src 'self' data:" + (" https://*.google-analytics.com https://*.googletagmanager.com https://*.g.doubleclick.net https://www.google.com https://www.google.cz" if ga else "") + "; "
           "connect-src 'self'" + (" https://*.google-analytics.com https://*.analytics.google.com https://*.googletagmanager.com https://*.g.doubleclick.net" if ga else "") + "; "
           "frame-src " + " ".join(HC_ORIGINS) + (" https://www.googletagmanager.com" if ga else ""))   # Home Credit form on /iphone-na-splatky/
    out.write("_headers", f"""/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: accelerometer=(), autoplay=(), bluetooth=(), browsing-topics=(), camera=(), display-capture=(), geolocation=(), gyroscope=(), hid=(), magnetometer=(), microphone=(), midi=(), payment=(), serial=(), usb=(), xr-spatial-tracking=()
  X-Frame-Options: DENY
  X-Permitted-Cross-Domain-Policies: none
  Cross-Origin-Opener-Policy: same-origin
  Cross-Origin-Resource-Policy: same-site
  Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
  Content-Security-Policy: {csp}
  Cache-Control: public, max-age=300, stale-while-revalidate=86400
/assets/*
  ! Cache-Control
  Cache-Control: public, max-age=31536000, immutable
/fonts/*
  ! Cache-Control
  Cache-Control: public, max-age=31536000, immutable
/img/*
  ! Cache-Control
  Cache-Control: public, max-age=2592000, stale-while-revalidate=86400
/go/*
  ! Cache-Control
  Cache-Control: no-store
  X-Robots-Tag: noindex, nofollow
""")
    (STATE / "page-hashes.json").write_text(json.dumps(out.new))
    (STATE / "lastmod.json").write_text(json.dumps({p: d for p, d in out.lastmod.items() if p in out.new}))
    (STATE / "changed.txt").write_text("\n".join(out.changed))
    no_photo = sorted({f'{o["model"]}|{o["col"]}' for o in offers if (o["model"], o["col"]) not in have})
    rep = {"date": TODAY.isoformat(), "shops": stats, "skipped": report, "refurb": len(refurb), "offers": len(offers), "new_ref": len(new_min),
           "models": len(by_model), "pages": len(out.pages), "indexable": len(idx), "changed": len(out.changed), "go": go_stats,
           "coupons": {s: [c["code"] for c in cl] for s, cl in coupons.items()}, "with_code": sum(1 for o in offers if o["cp"]),
           "photos": len(have), "no_photo": no_photo, "redirects": n_redir,
           "i18n": {tr.lang: {"missing": len(miss[tr.lang]), "indexable": sum(1 for lg, _, _, i in out.lpages if lg == tr.lang and i)} for tr in out.trs}}
    (STATE / "build-report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    print(json.dumps({k: rep[k] for k in ("refurb", "offers", "models", "pages", "indexable", "coupons", "with_code", "photos", "no_photo", "redirects", "i18n")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
