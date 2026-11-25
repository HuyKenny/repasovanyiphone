"""Turn raw shop offers into normalised iPhone offers: model, storage, condition grade, colour, battery, eSIM-only.

Every shop writes condition differently (JabkoLevně "(Stav A-)", Aukro "Stav zařízení: Téměř výborný", MALL "- rozbaleno").
They all map onto one scale of five grades so the visitor can compare across shops; the shop's own wording is kept as `sg`.
"""
import json
import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
MODELS = json.loads((APP / "data/models.json").read_text())["models"]
BY_SLUG = {m["slug"]: m for m in MODELS}

# grade scale (key, label, short explanation) - best first
GRADES = [
    ("novy", "Nový", "nerozbalený kus, plná záruka"),
    ("jako-novy", "Jako nový", "bez viditelných stop, často rozbalený nebo krátce používaný"),
    ("vyborny", "Výborný", "drobné stopy viditelné jen zblízka"),
    ("velmi-dobry", "Velmi dobrý", "jemné škrábance na rámu nebo zádech"),
    ("dobry", "Dobrý", "viditelné známky používání, plně funkční"),
]
GRADE = {k: (lab, ex) for k, lab, ex in GRADES}
GRADE_ORDER = {k: i for i, (k, _, _) in enumerate(GRADES)}


def _model_rx(m):
    n = m["name"].replace("iPhone ", "")
    if m["slug"] == "iphone-se-2022":
        return r"se\s*(\(?\s*2022\s*\)?|3\.?\s*(gen|generace)|\(?3rd|3\b)"
    if m["slug"] == "iphone-se-2020":
        return r"se\s*(\(?\s*2020\s*\)?|2\.?\s*(gen|generace)|\(?2nd|2\b)"
    parts = n.lower().split()
    rx = r"\s*".join(re.escape(p) for p in parts)
    return rx + r"(?![\w+])" if not rx.endswith("e") else rx + r"(?![\w])"


# longest names first so "15 Pro Max" wins over "15 Pro" and "15"
_ORDER = sorted(MODELS, key=lambda m: -len(m["name"]))
_RX = [(m["slug"], re.compile(r"iphone\s*" + _model_rx(m), re.I)) for m in _ORDER]

COLORS = [  # (regex, Czech label) - specific titanium names first
    (r"přírodní titan|natural titan", "přírodní titan"),
    (r"pouštní titan|desert titan", "pouštní titan"),
    (r"bílý titan|white titan", "bílý titan"),
    (r"černý titan|black titan", "černý titan"),
    (r"modrý titan|blue titan", "modrý titan"),
    (r"vesmírně čern|space black|kosmick\w* čern|černá|černý|black|midnight|temně inkoust|grafitov|graphite|space gr[ae]y|vesmírně šed", "černá"),
    (r"bíl[áý]|white|starlight|hvězdně bíl|cloud white", "bílá"),
    (r"oranž|orange", "oranžová"),
    (r"ultramarín|ultramarine", "ultramarínová"),
    (r"modrozelen|teal", "modrozelená"),
    (r"blankytn|sky blue|světle modr|mist blue|mlhově modr|sierra blue|pacific blue|tichomořsk", "světle modrá"),
    (r"modr|blue", "modrá"),
    (r"zelen|green|alpine|sage", "zelená"),
    (r"fial|purple|lavender|levandul|deep purple", "fialová"),
    (r"růžov|pink|blush", "růžová"),
    (r"červen|red|\(product\)", "červená"),
    (r"žlut|yellow", "žlutá"),
    (r"zlat|gold", "zlatá"),
    (r"stříbr|silver", "stříbrná"),
]
COLORS = [(re.compile(rx, re.I), lab) for rx, lab in COLORS]


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


def color_of(title, prm):
    for src in (prm.get("barva") or "", title or ""):
        for rx, lab in COLORS:
            if rx.search(src):
                return lab
    return ""


def battery_of(text):
    for rx in (r"(?:kondic\w*|kapacit\w*|zdrav\w*|stav)\s+bateri\w*[^0-9%]{0,20}(\d{2,3})\s?%",
               r"(\d{2,3})\s?%\s*(?:kondic\w*|kapacit\w*|zdraví)\s*(?:bateri\w*)?",
               r"bateri\w*\s*(?:na\s*)?(\d{2,3})\s?%"):
        m = re.search(rx, text or "", re.I)
        if m and 70 <= int(m.group(1)) <= 100:
            return int(m.group(1))
    return None


def grade_of(shop, r):
    """-> (grade key or None = not refurbished, shop wording). None means a NEW phone (reference price only)."""
    t, d = r["t"], r.get("d", "")
    if shop["id"] == "jabkolevne":
        m = re.search(r"\((Stav [^)]+|Zánovní|Nový|Rozbaleno|Nerozbaleno)\)", t)
        s = m.group(1) if m else ""
        k = {"Stav A": "vyborny", "Stav A-": "vyborny", "Stav A/B": "velmi-dobry", "Stav B": "dobry", "Stav B/C": "dobry", "Stav C": "dobry",
             "Zánovní": "jako-novy", "Rozbaleno": "jako-novy", "Nový": None, "Nerozbaleno": None}.get(s, "velmi-dobry" if s else None)
        return k, s
    if shop["id"] == "aukro":
        if r.get("fcond") not in shop.get("fcond", []):
            return "skip", ""
        m = re.search(r"stav zařízení:\s*(Premium|Zánovní|Výborný|Téměř výborný|Velmi dobrý|Dobrý|Uspokojivý)", d, re.I)
        s = m.group(1) if m else ""
        k = {"premium": "jako-novy", "zánovní": "jako-novy", "výborný": "vyborny", "téměř výborný": "vyborny",
             "velmi dobrý": "velmi-dobry", "dobrý": "dobry", "uspokojivý": "dobry"}.get(s.lower())
        if not k:
            m = re.search(r"(?:třída|stav)\s*([ABC])\b", t + " " + d)
            k = {"A": "vyborny", "B": "velmi-dobry", "C": "dobry"}.get(m.group(1) if m else "", "velmi-dobry")
            s = f"třída {m.group(1)}" if m else "repasovaný"
        return k, s
    # MALL, Allegro: a suffix or word in the title; everything else is a new phone
    m = re.search(r"\b(rozbalen[oéý]|zánovní|použit[éýá]|repasovan[ýé]|obnoven[ýé]|refurbished)\b", t, re.I)
    if not m:
        return None, ""
    w = m.group(1).lower()
    k = "jako-novy" if w.startswith(("rozbal", "zánov")) else "velmi-dobry"
    return k, w


def normalise(shop, r):
    """One raw record -> normalised offer dict, or None (not an identifiable phone)."""
    t = r["t"]
    prm = r.get("prm") or {}
    model = model_of(prm.get("model", "")) or model_of(t)
    if not model:
        return None
    storage = storage_of(prm.get("vnitřní paměť", ""), model) or storage_of(t, model)
    if not storage:
        return None
    g, sg = grade_of(shop, r)
    if g == "skip":
        return None
    text = t + " " + r.get("d", "")
    esim = bool(re.search(r"\besim\b", t, re.I)) and not re.search(r"dual|nano|\+\s*e-?sim|sim\s*\+", t, re.I)
    if BY_SLUG[model].get("esim_only"):
        esim = True
    return {"shop": shop["id"], "id": str(r["id"]), "model": model, "gb": storage, "g": g or "novy", "new": g is None, "sg": sg,
            "col": color_of(t, prm), "bat": battery_of(text), "esim": esim, "p": int(round(r["p"])), "was": int(round(r.get("was") or 0)),
            "url": r["url"], "go": r["go"], "img": r.get("img") or "", "t": t}


def load_all(raw_dir, shops):
    offers, stats = [], {}
    for s in shops:
        f = raw_dir / f"{s['id']}.json"
        if not f.exists():
            continue
        n = kept = 0
        for r in json.loads(f.read_text()):
            n += 1
            o = normalise(s, r)
            if o:
                offers.append(o)
                kept += 1
        stats[s["id"]] = {"raw": n, "kept": kept}
    return offers, stats


def gb_label(v):
    return f"{v // 1024} TB" if v >= 1024 else f"{v} GB"
