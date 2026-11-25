"""Turn raw shop offers into normalised iPhone offers: model, storage, official colour, quality grade, battery, eSIM-only.

Grades follow what people know from the shops: Nový · A+ (jako nový) · A · B · C. Every shop writes them differently
(MobileGear "třídy Velmi dobrý+", JabkoLevně "(Stav A-)", Smarty "(Kategorie B)", Aukro "Stav zařízení: Téměř výborný"),
so each shop has its own mapping below; the shop's own wording is kept as `sg`. Unknown wording -> the offer is skipped
and counted in the report (never guessed).
Colours: data/colors.json lists Apple's official colours per model; shop text is matched by regexes without diacritics.
"""
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
MODELS = json.loads((APP / "data/models.json").read_text())["models"]
BY_SLUG = {m["slug"]: m for m in MODELS}
_C = json.loads((APP / "data/colors.json").read_text())
COLORS = {slug: _C["sets"][k] for slug, k in _C["models"].items()}

GRADES = [  # key, short label, name, what you see
    ("novy", "Nový", "Nerozbalený", "nový kus s plnou zárukou 24 měsíců"),
    ("aplus", "A+", "Jako nový", "bez viditelných stop, často rozbalený nebo krátce používaný"),
    ("a", "A", "Výborný", "drobné stopy, které uvidíte jen zblízka"),
    ("b", "B", "Velmi dobrý", "jemné škrábance na rámu nebo zádech"),
    ("c", "C", "Dobrý", "viditelné známky používání, plně funkční"),
]
GRADE = {k: {"short": s, "name": n, "ex": e} for k, s, n, e in GRADES}
GRADE_ORDER = {k: i for i, (k, *_r) in enumerate(GRADES)}

PHONE = re.compile(r"^\s*(apple\s+)?iphone\s*(\d|se\b|x\b|xr|xs|air)", re.I)
NOT_PHONE = re.compile(r"kryt|obal|sklo|f[óo]li|displej|lcd|bateri[ei]\b|pouzdr|kabel|nab[íi]je|\bcase\b|cover|držák|náhradní|housing|"
                       r"deska|rámeč|čočk|magsafe battery|dock|adaptér|reprodukt|konektor|flex|šroub|tlačítk|avacom|sluchátk|motor", re.I)


def nd(s):
    return unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode()


def _model_rx(m):
    if m["slug"] == "iphone-se-2022":
        return r"se\s*(\(?\s*2022\s*\)?|3\.?\s*(gen|generace)|\(?3rd|3\b)"
    if m["slug"] == "iphone-se-2020":
        return r"se\s*(\(?\s*2020\s*\)?|2\.?\s*(gen|generace)|\(?2nd|2\b)"
    rx = r"\s*".join(re.escape(p) for p in m["name"].replace("iPhone ", "").lower().split())
    return rx + r"(?![\w+])"


_RX = [(m["slug"], re.compile(r"iphone\s*" + _model_rx(m), re.I)) for m in sorted(MODELS, key=lambda m: -len(m["name"]))]


def model_of(text):
    t = re.sub(r"\s+", " ", text or "")
    for slug, rx in _RX:
        if rx.search(t):
            return slug
    return None


def storage_of(text, model=None):
    """Capacity in GB; the first value the model was sold with (titles also carry RAM: "8GB 128GB")."""
    for n, unit in re.findall(r"(\d{1,4})\s?(gb|tb)\b", text or "", re.I):
        v = int(n) * (1024 if unit.lower() == "tb" else 1)
        if not model or v in BY_SLUG[model]["storage"]:
            return v
    return None


def color_of(model, *texts):
    """Official colour key for the model, or None. The shop's colour field comes first; the longest regex match wins."""
    for t in texts:
        t = nd(t)
        if not t.strip():
            continue
        best, blen = None, 0
        for c in COLORS.get(model, []):
            for rx in c["rx"]:
                m = re.search(rx, t)
                if m and len(m.group(0)) > blen:
                    best, blen = c["key"], len(m.group(0))
        if best:
            return best
    return None


def color(model, key):
    return next((c for c in COLORS.get(model, []) if c["key"] == key), None)


def battery_of(text):
    for rx in (r"(?:kondic\w*|kapacit\w*|zdrav\w*|stav)\s+bateri\w*[^0-9%]{0,20}(\d{2,3})\s?%",
               r"(\d{2,3})\s?%\s*(?:kondic\w*|kapacit\w*|zdraví)\s*(?:bateri\w*)?",
               r"bateri\w*\s*(?:na\s*)?(\d{2,3})\s?%"):
        m = re.search(rx, text or "", re.I)
        if m and 70 <= int(m.group(1)) <= 100:
            return int(m.group(1))
    return None


MG = {"premium": "aplus", "zánovní": "aplus", "výborný": "a", "velmi dobrý+": "b", "velmi dobrý": "b", "dobrý": "c", "nový": "novy"}
JL = {"stav a": "a", "stav a-": "a", "stav a/b": "b", "stav b": "c", "stav b/c": "c", "stav c": "c", "zánovní": "aplus", "rozbaleno": "aplus",
      "rozbalený": "aplus", "nový": "novy", "nerozbaleno": "novy", "nerozbalený": "novy"}
IM = {"premium": "aplus", "zánovní": "aplus", "rozbaleno": "aplus", "výborný": "a", "velmi dobrý": "b", "dobrý": "c", "nerozbaleno": "novy", "nový": "novy"}
AU = {"premium": "aplus", "zánovní": "aplus", "výborný": "a", "téměř výborný": "a", "velmi dobrý": "b", "dobrý": "c", "uspokojivý": "c"}


def grade_of(shop, r):
    """-> (grade key | None = unknown wording, shop's own wording)."""
    t, d, prm = r["t"], r.get("d", ""), r.get("prm") or {}
    sid = shop["id"]
    if shop.get("role") == "new":
        if re.search(r"repasovan|obnoven|použit|rozbalen|refurb|zánovní", t, re.I):
            return None, ""
        return "novy", "nový"
    if sid == "mobilegear":
        m = re.search(r"třídy\s+(.+?)\s*$", t)
        s = m.group(1) if m else ""
        return MG.get(s.lower()), s
    if sid == "jabkolevne":
        m = re.search(r"\((Stav [^)]+|Zánovní|Nový|Rozbaleno|Rozbalený|Nerozbaleno|Nerozbalený)\)", t)
        s = m.group(1) if m else ""
        return JL.get(s.lower()), s
    if sid == "smarty":
        st = (prm.get("stav zboží") or "").lower()
        m = re.search(r"\(Kategorie ([ABC])\)", t)
        if m:
            return m.group(1).lower(), f"Kategorie {m.group(1)}"
        if "(Další)" in t:
            return None, "Další"
        if st == "nový":
            return "novy", "nový"
        if st == "rozbalený":
            return "aplus", "rozbalený"
        return None, st
    if sid == "iphonemarket":
        s = prm.get("stav produktu") or (re.search(r"Stav produktu:\s*(\S+)", t) or [None, ""])[1]
        return IM.get(s.lower()), s
    if sid == "aukro":
        if r.get("fcond") not in shop.get("fcond", []):
            return "skip", ""
        m = re.search(r"stav zařízení:\s*(Premium|Zánovní|Výborný|Téměř výborný|Velmi dobrý|Dobrý|Uspokojivý)", d, re.I)
        if m:
            return AU[m.group(1).lower()], m.group(1)
        m = re.search(r"(?:třída|stav)\s*([ABC])\b", t + " " + d)
        return ({"A": "a", "B": "b", "C": "c"}.get(m.group(1)) if m else None), (f"třída {m.group(1)}" if m else "")
    return None, ""


def normalise(shop, r, report=None):
    """One raw record -> normalised offer dict, or None."""
    t = r["t"]
    prm = r.get("prm") or {}
    if NOT_PHONE.search(t):
        return None
    model = (model_of(prm.get("model zařízení", "")) or model_of(prm.get("model", "")) or model_of(t))
    if not model:
        if report is not None:
            report["no_model"][shop["id"]] += 1
        return None
    storage = (storage_of(prm.get("vnitřní paměť", ""), model) or storage_of(prm.get("velikost úložiště", ""), model)
               or storage_of(prm.get("kapacita paměti", ""), model) or storage_of(t, model))
    if not storage:
        if report is not None:
            report["no_storage"][shop["id"]] += 1
        return None
    g, sg = grade_of(shop, r)
    if g == "skip":
        return None
    if not g:
        if report is not None:
            report["unknown_grade"][f'{shop["id"]}: {sg or "?"}'] += 1
        return None
    title_col = re.sub(r"(?i)^.*?\d+\s?(gb|tb)\b", "", t)          # colour words come after the capacity in titles
    col = color_of(model, prm.get("barevný odstín", ""), prm.get("barva", ""), prm.get("color", ""), title_col)
    if not col:
        if report is not None:
            report["unknown_color"][f"{model}: {prm.get('barva') or prm.get('barevný odstín') or title_col.strip()[:30]}"] += 1
        return None
    esim = bool(re.search(r"\besim\b", t, re.I)) and not re.search(r"dual|nano|\+\s*e-?sim|sim\s*\+", t, re.I)
    if BY_SLUG[model].get("esim_only"):
        esim = True
    return {"shop": shop["id"], "id": str(r["id"]), "model": model, "gb": storage, "g": g, "sg": sg, "col": col,
            "bat": battery_of(t + " " + r.get("d", "")), "esim": esim, "p": int(round(r["p"])), "was": int(round(r.get("was") or 0)),
            "url": r["url"], "go": r["go"], "img": r.get("img") or "", "t": t}


def load_all(raw_dir, shops):
    offers, stats = [], {}
    report = {"no_model": Counter(), "no_storage": Counter(), "unknown_grade": Counter(), "unknown_color": Counter()}
    for s in shops:
        f = raw_dir / f"{s['id']}.json"
        if not f.exists():
            continue
        n = kept = 0
        for r in json.loads(f.read_text()):
            n += 1
            o = normalise(s, r, report)
            if o:
                offers.append(o)
                kept += 1
        stats[s["id"]] = {"raw": n, "kept": kept}
    return offers, stats, {k: dict(v.most_common(40)) for k, v in report.items()}


COUPON_LIMITS = re.compile(r"mimo|pouze|jen na|vybran|příslušenstv|sluchát|kryt|obal|reprodukt|nov[éeý] telefon|registrac|první nákup|aplikac|newsletter", re.I)


def coupon_effect(rules):
    """What a voucher does, read from eHub's free-text rules. -> {"amount": Kč or 0, "pct": % or 0, "min": Kč, "auto": bool}.
    auto = the discount can be counted into the price (a plain fixed or percentage discount, optionally over a minimum order);
    anything with exclusions or conditions we cannot check ("mimo", "jen na", "první nákup"...) is only shown, never counted."""
    t = (rules or "").replace("\u00a0", " ")
    amount = pct = minimum = 0
    m = re.search(r"sleva\s*(\d[\d\s]*?)\s*(kč|,-)", t, re.I) or re.search(r"(\d[\d\s]*?)\s*kč\s*sleva", t, re.I)
    if m:
        amount = int(re.sub(r"\s", "", m.group(1)))
    m = re.search(r"(\d{1,2})\s*%", t)
    if m and not amount:
        pct = int(m.group(1))
    m = re.search(r"(?:nad|od|min(?:imáln\w*)?\.?\s*(?:nákup|objednávk)\w*\s*)\s*(\d[\d\s]*?)\s*kč", t, re.I)
    if m:
        minimum = int(re.sub(r"\s", "", m.group(1)))
    auto = bool(amount or pct) and not COUPON_LIMITS.search(t)
    return {"amount": amount, "pct": pct, "min": minimum, "auto": auto}


def gb_label(v):
    return f"{v // 1024} TB" if v >= 1024 else f"{v} GB"
