"""Shop links as /go/<shop>/?u=/product-path instead of the raw affiliate deeplink (Kenny 12.-13. 11. 2026).

The SAME file lives in apps/vian, apps/hrackarium and apps/auty (scripts/golinks.py): change it in one place, copy it to the others.

Each shop has one template, prefix + product URL (+ suffix), read off its own links. /go/<shop>/ is a tiny static page whose script
rebuilds the deeplink and redirects (no Worker code = 0 $). An offer whose link does not follow the shop's template keeps its exact link
as ?g=. The page redirects only to hosts that the shop's own links use, so /go/ is no open redirect.

Safety net: after rewriting, every offer is rebuilt the way the browser script does it and compared with the original link (CJ's optional
SKU and the CJ click-host rotation are the only intended differences). A mismatch keeps the original absolute link. Counts are logged."""
import hashlib
import html
import json
import re
from collections import Counter, defaultdict
from urllib.parse import quote, unquote

E = html.escape
CJ_HOSTS = re.compile(r"^https://www\.(kqzyfj|tkqlhce|jdoqocy|dpbolvw|anrdoezrs)\.(com|net)/")
CJ_SKU = re.compile(r"&cjsku=[^&]*$")

GO_JS = r"""(function(){var b=document.body.dataset,q=new URLSearchParams(location.search),u=q.get("u")||"",g=q.get("g")||"",to="",d=[],sd=[];
try{d=JSON.parse(b.d);sd=JSON.parse(b.sd||"[]")}catch(e){}
function inn(h,l){return l.some(function(n){return h===n||h.slice(-n.length-1)==="."+n})}
function ok(x){try{var p=new URL(x);return p.protocol==="https:"&&inn(p.hostname,d)}catch(e){return false}}
function nested(x){var m=decodeURIComponent(x).match(/https?:\/\/[^&?#"' ]+/g)||[];return m.slice(1).every(function(y){try{return inn(new URL(y).hostname,sd.length?sd:d)}catch(e){return false}})}
if(g){if(ok(g)&&nested(g))to=g}else if(u){var t=/^https?:\/\//.test(u)?u:b.h+u;if(ok(t))to=b.p+(b.m==="e"?encodeURIComponent(t):t)+b.s}
var a=document.getElementById("go");if(to){a.href=to;location.replace(to)}})();
"""


def _enc(s):
    """encodeURIComponent: leaves A-Z a-z 0-9 - _ . ! ~ * ' ( )"""
    return quote(s, safe="!*'()")


def _host_ok(url, doms):
    m = re.match(r"https?://([^/?#:]+)", url or "")
    if not m:
        return False
    h = m.group(1).lower()
    return any(h == n or h.endswith("." + n) for n in doms)


def _split(o):
    go, url = o.get("go") or "", o.get("url") or ""
    if not go.startswith("http") or not url.startswith("http"):
        return None
    for mode, needle in (("e", quote(url, safe="")), ("r", url)):
        i = go.find(needle)
        if i >= 0:
            suf = go[i + len(needle):]
            if re.fullmatch(r"&cjsku=[^&]*", suf):      # CJ's optional SKU (reporting only): one template for the shop
                suf = ""
            return CJ_HOSTS.sub("https://www.anrdoezrs.net/", go[:i]), suf, mode   # CJ rotates five equivalent click hosts
    return None


def _rebuild(path, t):
    """What the browser script produces for this /go/ path (None = it would not redirect)."""
    q = path.split("?", 1)[1]
    k, v = q.split("=", 1)
    v = unquote(v)
    if k == "g":
        nested = re.findall(r"https?://[^&?#\"' ]+", unquote(v))[1:]      # a network click link must point into the shop itself
        ok = v.startswith("https://") and _host_ok(v, t["d"]) and all(_host_ok(x, t.get("sd") or t["d"]) for x in nested)
        return v if ok else None
    full = v if re.match(r"https?://", v) else t["h"] + v
    if not _host_ok(full, t["d"]):
        return None
    return t["p"] + (_enc(full) if t["m"] == "e" else full) + t["s"]


_UNRESERVED = {"%21": "!", "%27": "'", "%28": "(", "%29": ")", "%2A": "*"}


def _same(a, b):
    """Equal, except that ! ' ( ) * may be percent-encoded or not (the same value for any server; encodeURIComponent leaves them bare)."""
    f = lambda x: re.sub(r"%(21|27|28|29|2A)", lambda m: _UNRESERVED["%" + m.group(1)], x, flags=re.I)
    return a == b or f(a) == f(b)


def _norm(go):
    return CJ_SKU.sub("", CJ_HOSTS.sub("https://www.anrdoezrs.net/", go))


def local_go(products):
    """Rewrites o["go"] of every offer in place (products and their variants); returns ({shop: template}, stats)."""
    offers = [o for p in products for o in p["offers"]] + [o for p in products for v in p.get("variants") or [] for o in v.get("offers") or []]
    keys, hosts, doms = defaultdict(Counter), defaultdict(Counter), defaultdict(set)
    for o in offers:
        k = _split(o)
        if k:
            keys[o["shop"]][k] += 1
        if (o.get("url") or "").startswith("http"):
            hosts[o["shop"]][re.match(r"https?://[^/?#]+", o["url"]).group(0)] += 1
        for u in (o.get("go"), o.get("url")):
            m = re.match(r"https?://([^/?#:]+)", u or "")
            if m:
                doms[o["shop"]].add(m.group(1).lower())
    tpl = {}
    for sid in set(keys) | set(hosts) | set(doms):
        k = keys[sid].most_common(1)[0][0] if keys[sid] else ("", "", "r")
        tpl[sid] = {"p": k[0], "s": k[1], "m": k[2], "h": hosts[sid].most_common(1)[0][0] if hosts[sid] else "", "d": sorted(doms[sid]),
                    "sd": sorted({re.sub(r"^https?://", "", h) for h in hosts[sid]})}   # the shop's own hosts: where a ?g= link may finally land
    st = Counter()
    for o in offers:
        t, sid, orig = tpl.get(o["shop"]), o["shop"], o.get("go") or ""
        if not orig.startswith("http"):
            st["already-local"] += 1
            continue
        k = _split(o)
        new = None
        if t and k == (t["p"], t["s"], t["m"]):
            u = o["url"][len(t["h"]):] if t["h"] and o["url"].startswith(t["h"] + "/") else o["url"]
            new = f"/go/{sid}/?u=" + quote(u, safe="/-_.~")
            kind = "u"
        elif t:
            new = f"/go/{sid}/?g=" + quote(orig, safe="")
            kind = "g"
        if new and _same(_rebuild(new, t) or "", orig if kind == "g" else _norm(orig)):
            o["go"] = new
            st[kind] += 1
        else:
            st["kept-original"] += 1          # the safety net: never ship a link that does not reproduce the original
    total = sum(st.values()) or 1
    print(f"go links: {dict(st)}  ({len(tpl)} shops)")
    if (st["g"] + st["kept-original"]) / total > 0.05:
        print(f"::warning::go links: {100 * (st['g'] + st['kept-original']) / total:.1f} % of offers do not follow their shop's link template - check the feeds")
    return tpl, dict(st)


def go_page(sid, t, name, js_name):
    dom = t["d"]
    home = t["h"] or (f"https://{dom[0]}" if dom else "/")
    return ('<!doctype html><html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex,nofollow"><title>Přesměrování do obchodu ' + E(name) + '</title>'
            '<style>body{font:16px/1.5 system-ui,sans-serif;margin:0;display:grid;place-items:center;min-height:90vh;background:#f6f6f8;color:#1b1b24}'
            'a{color:#b5301f;font-weight:700}</style></head>'
            f'<body data-p="{E(t["p"])}" data-s="{E(t["s"])}" data-m="{t["m"]}" data-h="{E(t["h"])}" data-d="{E(json.dumps(dom))}" data-sd="{E(json.dumps(t.get("sd", [])))}">'
            f'<p>Přesměrováváme vás do obchodu <b>{E(name)}</b>… <a id="go" href="{E(home)}" rel="sponsored nofollow">Pokračovat</a></p>'
            f'<script>{js_name}</script></body></html>')


def write_go(out, tpl, shop_meta):
    """Writes go/<shop>/index.html for every shop, the redirect script inline (allowed by its CSP hash).
    repasovanyiphone: inline script + ?g= nested-URL check (25. 11. 2026); the vian/hrackarium/auty copies still use the old external file."""
    for sid, t in tpl.items():
        out.write(f"go/{sid}/index.html", go_page(sid, t, shop_meta.get(sid, {}).get("name", sid), GO_JS))
