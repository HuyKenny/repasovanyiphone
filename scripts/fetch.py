#!/usr/bin/env python3
"""Download iPhone offers from the affiliate networks into data/raw/<shop>.json (a list of slim offer records).

    python3 scripts/fetch.py               # every enabled shop in data/shops.json
    python3 scripts/fetch.py jabkolevne    # only these shop ids

Keys come from the environment (GitHub secrets; locally from ~/ai/credentials/):
  CJ_API_KEY, CJ_CID, CJ_PID   CJ GraphQL product search
  FEEDS_JSON                   {"<feed_key>": "<url>"} for feeds whose URL carries a token (eHub panel exports)

The repository is PUBLIC and so are its Actions logs: only shop ids, counts and exception class names are printed.
Safety: a failed download keeps the previous file, and so does a feed that shrank below 50 % of the previous run.
"""
import html
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET

APP = Path(__file__).resolve().parent.parent
RAW = APP / "data/raw"
UA = "RepasIphoneFeed/1.0 (+https://repasovanyiphone.cz)"
EHUB_CLICK = "https://ehub.cz/system/scripts/click.php?a_aid=052443b7&a_bid={bid}&desturl="   # a_aid is public (in every eHub link)

sys.path.insert(0, str(APP / "scripts"))
if not os.environ.get("GITHUB_ACTIONS"):
    import localenv
    localenv.load()

# only phones: accessories and spare parts share the word "iPhone"
PHONE = re.compile(r"^\s*(apple\s+)?iphone\s*(\d|se\b|x\b|xr|xs|air)", re.I)
NOT_PHONE = re.compile(r"kryt|obal|sklo|f[óo]li|displej|lcd|bateri[ei]\b|pouzdr|kabel|nab[íi]je|\bcase\b|cover|držák|náhradní|"
                       r"deska|rámeč|čočk|magsafe battery|dock|adaptér|reprodukt|konektor|flex|šroub|tlačítk", re.I)


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def price_of(s):
    m = re.search(r"\d[\d\s.,]*", str(s or ""))
    if not m:
        return 0.0
    v = m.group(0).replace(" ", "").replace(" ", "")
    if "," in v and "." in v:
        v = v.replace(".", "").replace(",", ".")
    else:
        v = v.replace(",", ".")
    try:
        return round(float(v), 2)
    except ValueError:
        return 0.0


def clean(s, n=1500):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(s or ""))).strip()[:n]


def is_phone(title):
    return bool(PHONE.match(title or "")) and not NOT_PHONE.search(title or "")


# ---------------------------------------------------------------- CJ

def cj_gql(query):
    req = urllib.request.Request("https://ads.api.cj.com/query", data=json.dumps({"query": query}).encode(),
                                 headers={"Authorization": "Bearer " + os.environ["CJ_API_KEY"], "Content-Type": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                x = json.load(r)
            if "errors" in x:
                raise RuntimeError("CJ GraphQL error")
            return x["data"]["shoppingProducts"]
        except Exception as e:  # CJ answers 403 for a while after bursts
            if attempt == 5:
                raise
            wait = (30 if "403" in str(e) else 6) * (attempt + 1)
            log(f"  CJ retry {attempt + 1} in {wait}s: {type(e).__name__}")
            time.sleep(wait)


def cj_offers(shop):
    pid = os.environ.get("CJ_PID") or ""
    fields = ("id title description link imageLink productType condition availability "
              f'price{{ amount currency }} salePrice{{ amount }} linkCode(pid:"{pid}"){{ clickUrl }}')
    got = {}
    for kw in shop.get("keywords", ["iPhone"]):
        base = f'companyId:"{os.environ["CJ_CID"]}", partnerIds:["{shop["advertiser"]}"], keywords:["{kw}"], currency:"CZK"'
        bands = [(1500, 60000)]
        while bands:                       # split price bands until each holds <= 1000 offers (CJ's page cap)
            lo, hi = bands.pop()
            n = cj_gql('{ shoppingProducts(%s, lowPrice:%s, highPrice:%s, limit:1){ totalCount } }' % (base, lo, hi))["totalCount"]
            time.sleep(0.4)
            if n > 1000 and hi - lo > 200:
                mid = (lo + hi) // 2
                bands += [(lo, mid), (mid, hi)]
                continue
            if not n:
                continue
            x = cj_gql('{ shoppingProducts(%s, lowPrice:%s, highPrice:%s, limit:1000){ resultList{ %s } } }' % (base, lo, hi, fields))
            time.sleep(0.6)
            for p in x["resultList"]:
                if not is_phone(p["title"]) or (p.get("availability") or "in stock").lower().replace("_", " ") not in ("in stock", "instock"):
                    continue
                sale = float((p.get("salePrice") or {}).get("amount") or 0)
                reg = float(p["price"]["amount"])
                price, was = (sale, reg) if 0 < sale < reg else (reg, 0)
                go = ((p.get("linkCode") or {}).get("clickUrl")) or p["link"]
                got[p["id"]] = {"id": p["id"], "t": p["title"].strip(), "d": clean(p.get("description")), "url": p["link"], "go": go,
                                "img": p.get("imageLink") or "", "p": price, "was": was, "fcond": p.get("condition") or "",
                                "cat": " > ".join(p["productType"]) if isinstance(p.get("productType"), list) else (p.get("productType") or ""), "prm": {}}
    return list(got.values())


# ---------------------------------------------------------------- XML feeds (Heureka / Google)

def local(tag):
    return tag.rsplit("}", 1)[-1]


def xml_offers(shop, resp):
    pre = EHUB_CLICK.format(bid=shop["a_bid"]) if shop.get("network") == "ehub" else ""
    for _, el in ET.iterparse(resp, events=("end",)):
        t = local(el.tag)
        if t not in ("SHOPITEM", "item", "entry"):
            continue
        d, prm = {}, {}
        for ch in el:
            k = local(ch.tag)
            if k == "PARAM":
                prm[(ch.findtext("PARAM_NAME") or "").strip().lower()] = (ch.findtext("VAL") or "").strip()
            elif k == "product_detail":
                nv = {local(x.tag): (x.text or "").strip() for x in ch}
                if nv.get("attribute_name"):
                    prm[nv["attribute_name"].strip().lower()] = nv.get("attribute_value", "")
            else:
                d.setdefault(k, (ch.text or "").strip())
        el.clear()
        if t == "SHOPITEM":
            pid, title, url, img = d.get("ITEM_ID"), d.get("PRODUCTNAME") or d.get("PRODUCT"), d.get("URL"), d.get("IMGURL")
            price, was, cat, desc = price_of(d.get("PRICE_VAT")), 0, d.get("CATEGORYTEXT", ""), d.get("DESCRIPTION", "")
            if (d.get("STORE_STATUS") or "").strip().lower() in ("0", "false", "out of stock", "vyprodáno", "nedostupné", "not available"):
                continue
            if shop.get("in_stock_only") and str(d.get("DELIVERY_DATE", "0")).strip() not in ("0", ""):
                continue
            prm.setdefault("condition", d.get("CONDITION", ""))
        else:
            pid, title, url, img = d.get("id"), d.get("title"), d.get("link"), d.get("image_link")
            if (d.get("availability") or "in stock").lower().replace("_", " ") not in ("in stock", "instock"):
                continue
            reg, sale = price_of(d.get("price")), price_of(d.get("sale_price"))
            price, was = (sale, reg) if 0 < sale < reg else (reg, 0)
            cat, desc = d.get("product_type", ""), d.get("description", "")
            prm.setdefault("condition", d.get("condition", ""))
        if not (pid and title and url and price > 0) or not is_phone(title):
            continue
        url = url.replace("&amp;", "&")
        yield {"id": pid, "grp": d.get("ITEMGROUP_ID") or d.get("item_group_id") or "", "t": title.strip(), "d": clean(desc), "url": url, "go": pre + quote(url, safe="") if pre else url,
               "img": img or "", "p": price, "was": was, "fcond": prm.get("condition", ""), "cat": html.unescape(cat),
               "prm": {k: v[:80] for k, v in prm.items() if v and len(k) < 40}}


def feed_url(shop):
    if shop.get("feed"):
        return shop["feed"]                                  # public shop export (no token)
    u = json.loads(os.environ.get("FEEDS_JSON") or "{}").get(shop.get("feed_key", ""))
    if not u:
        raise RuntimeError("feed URL missing in FEEDS_JSON")
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::add-mask::{u}", flush=True)
    return u


def xml_shop(shop):
    import tempfile
    f = tempfile.TemporaryFile()
    req = urllib.request.Request(feed_url(shop), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:      # follows redirects (Dotidot answers 302 to a storage URL)
        while chunk := r.read(1 << 20):
            f.write(chunk)
    f.seek(0)
    if f.read(2) == b"\x1f\x8b":                               # gzip export
        import gzip
        f.seek(0)
        g = tempfile.TemporaryFile()
        with gzip.GzipFile(fileobj=f) as z:
            while chunk := z.read(1 << 20):
                g.write(chunk)
        f = g
    f.seek(0)
    return list(xml_offers(shop, f))


# ----------------------------------------------------------------

def run(shop):
    out = RAW / f"{shop['id']}.json"
    t0 = time.time()
    try:
        recs = cj_offers(shop) if shop["network"] == "cj" else xml_shop(shop)
    except Exception as e:
        log(f"{shop['id']}: FAILED ({type(e).__name__}), keeping the previous file")
        return {"ok": False, "error": type(e).__name__}
    prev = len(json.loads(out.read_text())) if out.exists() else 0
    if prev and len(recs) < prev * 0.5:
        log(f"{shop['id']}: {len(recs)} offers < 50 % of last run ({prev}), keeping the previous file")
        return {"ok": False, "error": "shrunk", "n": len(recs), "prev": prev}
    out.write_text(json.dumps(recs, ensure_ascii=False))
    log(f"{shop['id']}: {len(recs)} phone offers in {time.time() - t0:.0f}s")
    return {"ok": True, "n": len(recs)}


def coupons(shops):
    """Valid eHub voucher codes of our shops -> data/raw/coupons.json. The eHub API answers 403 without a browser User-Agent.
    Shops are matched by the campaign name without diacritics == shop domain ("Jabkolevně.cz" -> jabkolevne.cz)."""
    import datetime as dt
    import unicodedata
    nd = lambda s: unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode()  # noqa: E731
    by_dom = {s["domain"]: s["id"] for s in shops if s.get("network") == "ehub"}
    pid, key = os.environ.get("EHUB_PUBLISHER_ID"), os.environ.get("EHUB_API_KEY")
    if not (pid and key):
        log("coupons: EHUB_* missing, keeping the previous file")
        return
    got, page, today = [], 1, dt.date.today().isoformat()
    try:
        while page < 200:
            req = urllib.request.Request(f"https://api.ehub.cz/v3/publishers/{pid}/vouchers?apiKey={key}&perPage=100&page={page}",
                                         headers={"User-Agent": "Mozilla/5.0 (compatible; RepasIphone/1.0)", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                batch = json.load(r).get("vouchers") or []
            for v in batch:
                sid = by_dom.get(nd(v.get("campaignName")).strip())
                if sid and v.get("isValid") and v.get("code") and (v.get("validTill") or "9999") >= today:
                    got.append({"shop": sid, "code": v["code"].strip(), "rules": (v.get("rules") or "").strip(),
                                "from": v.get("validFrom") or "", "until": v.get("validTill") or ""})
            if len(batch) < 100:
                break
            page += 1
    except Exception as e:
        log(f"coupons: FAILED ({type(e).__name__}), keeping the previous file")
        return
    (RAW / "coupons.json").write_text(json.dumps(got, ensure_ascii=False, indent=1))
    log(f"coupons: {len(got)} valid codes for our shops")


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    shops = [s for s in json.loads((APP / "data/shops.json").read_text())["shops"] if s.get("enabled", True)]
    if "--coupons" in sys.argv:
        coupons(shops)
        return
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    if only:
        shops = [s for s in shops if s["id"] in only]
    rep = {s["id"]: run(s) for s in shops}
    rp = RAW / "fetch-report.json"
    old = json.loads(rp.read_text()) if rp.exists() else {}
    old.update(rep)
    rp.write_text(json.dumps(old, indent=1))


if __name__ == "__main__":
    main()
