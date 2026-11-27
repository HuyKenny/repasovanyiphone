#!/usr/bin/env python3
"""Ukrainian and Russian versions of the built Czech pages (translation memory over finished HTML).

The Czech page is the source. Every page is cut into segments at block-level tags; inline tags inside a segment become
placeholders <1>…</1> / <2/>, numbers become {0}, {1}… so the nightly prices never change a segment. A segment is looked up in
content/i18n/<lang>.json (key = Czech segment, value = translation with the same placeholders); a missing one stays Czech
and is reported in data/state/i18n-missing.json. JSON-LD and the configurator JSON (#cfg) are translated value by value.

    python3 scripts/i18n.py missing [lang]     # untranslated segments of the last build (data/state/i18n-missing.json)
    python3 scripts/i18n.py check              # placeholders of every translation match its key
    python3 scripts/i18n.py merge out-*.json   # add translated batches to content/i18n/<lang>.json
"""
import html as H
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
I18N = APP / "content/i18n"
LANGS = {"uk": "ua", "ru": "ru"}                  # html lang / hreflang -> URL prefix
# a language goes live only once its dictionary is in the repo (no half-Czech /ua/ pages from the nightly build)
ACTIVE = [lang for lang in LANGS if (Path(__file__).resolve().parent.parent / f"content/i18n/{lang}.json").exists()]
LOCALE = {"uk": "uk_UA", "ru": "ru_RU"}
TITLE_TAG = {"uk": "порівняння і ціни", "ru": "сравнение и цены"}
NOINDEX_SHARE = 0.10                              # a translated page with more untranslated text than this stays noindex

INLINE = {"a", "b", "strong", "i", "em", "span", "small", "s", "sup", "sub", "abbr", "mark", "time", "u", "img", "br", "wbr",
          "button", "label", "q", "del", "ins", "input", "bdi"}
VOID = {"img", "br", "wbr", "input"}
OPAQUE = ("script", "style", "svg", "code", "textarea", "noscript")
NUM = re.compile(r"\d+(?:[   .,]\d+)*")
WORD = re.compile(r"[^\W\d_]{2,}")
# words that stay as they are in every language: a segment made only of these is not translated
KEEP = {w.lower() for w in """iphone pro max plus mini se air gb tb kč ios esim apple usb lightning mm mah face id touch a b c
        ok cz eu dph bionic jabkolevně jabkolevne mobilegear smarty iphonemarket aukro allegro istyle swappie refurbed
        vodafone ehub cj home credit repasovanyiphone www https http cookies x xr xs cs ua ru vs""".split()}
# "{n} word" alone (card counts): the form follows the number in the target language, not the Czech form
PLURALS = ["nabídka|nabídky|nabídek", "model|modely|modelů", "rok|roky|let", "měsíc|měsíce|měsíců", "den|dny|dní", "kus|kusy|kusů",
           "obchod|obchody|obchodů", "barva|barvy|barev"]
PLURAL_OF = {w: f for f in PLURALS for w in f.split("|")}
SKIP_KEYS = {"@context", "@type", "@id", "url", "item", "image", "logo", "sku", "gtin", "gtin13", "mpn", "priceCurrency",
             "availability", "itemCondition", "sameAs", "contentUrl", "thumbnailUrl", "inLanguage", "encodingFormat", "brand"}


MONTHS = {"cs": "ledna února března dubna května června července srpna září října listopadu prosince".split(),
          "uk": "січня лютого березня квітня травня червня липня серпня вересня жовтня листопада грудня".split(),
          "ru": "января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split()}


# lists that change with the nightly data ("v barvách modrá, zelená a černá", "z obchodů JabkoLevně, MobileGear…") become [0], [1]…
# in the key; the items are translated one by one (colour names from the dictionary, shop names stay)
_COL = json.loads((APP / "data/colors.json").read_text())
_SHOPS = [s["name"] for s in json.loads((APP / "data/shops.json").read_text())["shops"]]
ITEMS = sorted({c["name"] for v in _COL["sets"].values() for c in (v.values() if isinstance(v, dict) else v)} | set(_SHOPS) | {"(product)red"},
               key=len, reverse=True)
_IT = "|".join(re.escape(x[0].upper() + x[1:]) + "|" + re.escape(x[0].lower() + x[1:]) for x in ITEMS)
_GB = r"\{\d+\} [GT]B"
_MODEL = r"iPhone (?:SE \(\{\d+\}\)|\{\d+\}e?|SE|Air|XR|XS|X)(?: Pro Max| Pro| Plus| mini| Max)?(?![\w(])"
_QUAL = r"kvalita (?:A\+|A|B|C|Nový) od \{\d+\} Kč"
_J = "(?:, | a | nebo )"
LIST = re.compile(rf"(?<![\w-])(?:{_IT})(?:{_J}(?:{_IT}))*(?![\w-])|{_GB}(?:{_J}{_GB})*|{_QUAL}(?:{_J}{_QUAL})*|{_MODEL}")
QUAL_T = {"uk": ("стан", "від", "новий"), "ru": ("состояние", "от", "новый")}
# Czech forms that only follow the numbers/lists ("1 nabídka", "v paměti 128 GB a barvě"): one key for all of them; the translation
# agrees through {n|one|few|many}
CANON = [(r"(\{\d+\}(?:</\d+>)?) nabíd(?:ka|ky|ek)\b", r"\1 nabídek"), (r"\bv paměti\b", "v pamětech"), (r"\ba barvě\b", "a barvách"),
         (r"\bz obchodu (\[\d+\])", r"z obchodů \1"), (r"(\{\d+\}) (?:den|dny|dní)\b", r"\1 dní"), (r"(\{\d+\}) (?:rok|roky|let)\b", r"\1 let")]
JOIN = {"uk": {" a ": " і ", " nebo ": " або "}, "ru": {" a ": " и ", " nebo ": " или "}}


def load(lang):
    """The dictionary, plus every dated sentence for the other eleven months (dates are in the text as "27. listopadu")."""
    f = I18N / f"{lang}.json"
    d = json.loads(f.read_text()) if f.exists() else {}
    for k, v in list(d.items()):
        for i, mc in enumerate(MONTHS["cs"]):
            if re.search(rf"\b{mc}\b", k) and MONTHS[lang][i] in v:
                for j, mc2 in enumerate(MONTHS["cs"]):
                    d.setdefault(re.sub(rf"\b{mc}\b", mc2, k), v.replace(MONTHS[lang][i], MONTHS[lang][j]))
                break
    return d


def needs(text):
    """Anything worth translating: a word of 2+ letters that is not a model/brand/unit token."""
    return any(w.lower() not in KEEP for w in WORD.findall(text))


def fill(t, nums):
    """{n} -> the number; {n|one|few|many} -> the number with the form that agrees with it (uk/ru rules)."""
    def one(m):
        i = int(m.group(1))
        v = nums[i] if i < len(nums) else ""
        if not m.group(2):
            return v
        forms = m.group(2).split("|")
        x = int(re.sub(r"\D", "", v) or 0)
        a, b = x % 10, x % 100
        k = 0 if a == 1 and b != 11 else 1 if 2 <= a <= 4 and not 12 <= b <= 14 else 2
        return v + "\u00a0" + forms[min(k, len(forms) - 1)]
    return re.sub(r"\{(\d+)(?:\|([^{}]*))?\}", one, t)


class Tr:
    """One language: translates whole pages, collects what is missing."""

    def __init__(self, lang):
        self.lang, self.pfx = lang, "/" + LANGS[lang]
        self.d = load(lang)
        self.missing = defaultdict(set)           # key -> pages
        self.page = ""
        self.words_all = self.words_miss = 0

    # ------------------------------------------------------------ lists
    def lists(self, key):
        """key -> (key with [n] for every colour/shop/storage list and {n} renumbered, the lists, new {n} -> old {n})"""
        found = []
        nk = LIST.sub(lambda m: (found.append(m.group(0)), "[%d]" % (len(found) - 1))[1], key)
        for a, b in CANON:
            nk = re.sub(a, b, nk)
        old = list(dict.fromkeys(int(x) for x in re.findall(r"\{(\d+)\}", nk)))
        nk = re.sub(r"\{(\d+)\}", lambda m: "{%d}" % old.index(int(m.group(1))), nk)
        tg = list(dict.fromkeys(int(x) for x in re.findall(r"<(\d+)/?>", nk)))    # tags in order of first appearance, from 1
        self._tg = tg
        nk = re.sub(r"<(/?)(\d+)(/?)>", lambda m: "<%s%d%s>" % (m.group(1), tg.index(int(m.group(2))) + 1, m.group(3)) if int(m.group(2)) in tg else m.group(0), nk)
        return nk, found, old

    def render_list(self, src):
        out = []
        if src.startswith("iPhone "):
            return src
        for part in re.split(r"(, | a | nebo )", src):
            if part in JOIN[self.lang] or part == ", ":
                out.append(JOIN[self.lang].get(part, part))
                continue
            q = re.fullmatch(r"kvalita (\S+) od (\{\d+\}) Kč", part)
            if q:
                st, od, new = QUAL_T[self.lang]
                out.append(f"{st} {new if q.group(1) == 'Nový' else q.group(1)} {od} {q.group(2)} Kč")
                continue
            t = self.d.get(part) or self.d.get(part[0].lower() + part[1:])
            if t is None:
                t = part
            elif part[0].isupper():
                t = t[0].upper() + t[1:]
            out.append(t)
        return "".join(out)

    def lookup(self, key):
        """Exact key first, then the key with its colour/shop lists as [n]. -> (translation with lists filled in, key to report)"""
        t = self.d.get(key)
        if t is not None:
            return t, key
        nk, found, old = self.lists(key)
        if found or nk != key:
            t = self.d.get(nk)
            if t is not None and set(re.findall(r"\[\d+\]", t)) <= {f"[{i}]" for i in range(len(found))}:
                t = re.sub(r"\{(\d+)((?:\|[^{}]*)?)\}", lambda m: "{%d%s}" % (old[int(m.group(1))], m.group(2)) if int(m.group(1)) < len(old) else m.group(0), t)
                tg = self._tg
                t = re.sub(r"<(/?)(\d+)(/?)>", lambda m: "<%s%d%s>" % (m.group(1), tg[int(m.group(2)) - 1], m.group(3)) if int(m.group(2)) <= len(tg) else m.group(0), t)
                return re.sub(r"\[(\d+)\]", lambda m: self.render_list(found[int(m.group(1))]), t), nk
        # a paragraph assembled from optional sentences (depends on the data): sentence by sentence, each with its own key
        parts = re.split(r"(?<=[.?!])\s+(?=[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ<\[{])", key)
        if len(parts) > 1 and all(self._balanced(x) for x in parts):
            outs = []
            for x in parts:
                if not needs(re.sub(r"</?\d+/?>|\{\d+\}", " ", x)):
                    outs.append(x)
                    continue
                tx = self.d.get(x)
                if tx is None:
                    sk, sf, so = self.lists(x)
                    tx = self.d.get(sk)
                    if tx is None:
                        return None, nk
                    tg = self._tg
                    tx = re.sub(r"\{(\d+)((?:\|[^{}]*)?)\}", lambda m: "{%d%s}" % (so[int(m.group(1))], m.group(2)) if int(m.group(1)) < len(so) else m.group(0), tx)
                    tx = re.sub(r"<(/?)(\d+)(/?)>", lambda m: "<%s%d%s>" % (m.group(1), tg[int(m.group(2)) - 1], m.group(3)) if int(m.group(2)) <= len(tg) else m.group(0), tx)
                    tx = re.sub(r"\[(\d+)\]", lambda m: self.render_list(sf[int(m.group(1))]), tx)
                outs.append(tx)
            return " ".join(outs), nk
        return None, nk

    @staticmethod
    def _balanced(x):
        return sorted(re.findall(r"<(\d+)>", x)) == sorted(re.findall(r"</(\d+)>", x))

    # ------------------------------------------------------------ text / segments
    def text(self, s, count=True):
        """Plain text (attribute, JSON value): numbers -> {n}."""
        if not s or not needs(s):
            return s
        lead, core, trail = re.match(r"(\s*)(.*?)(\s*)$", s, re.S).groups()
        nums = []
        key = NUM.sub(lambda m: (nums.append(m.group(0)), "{%d}" % (len(nums) - 1))[1], re.sub(r"\s+", " ", core))
        n = len(key.split())
        if count:
            self.words_all += n
        pm = re.fullmatch(r"\{0\} ([^\W\d]+)", key)
        if pm and pm.group(1) in PLURAL_OF and PLURAL_OF[pm.group(1)] in self.d:
            forms = self.d[PLURAL_OF[pm.group(1)]].split("|")
            v = int(re.sub(r"\D", "", nums[0]) or 0)
            a, b = v % 10, v % 100
            i = 0 if a == 1 and b != 11 else 1 if 2 <= a <= 4 and not 12 <= b <= 14 else 2
            return lead + nums[0] + "\u00a0" + forms[min(i, len(forms) - 1)] + trail
        t, mk = self.lookup(key)
        if t is None:
            self.missing[mk].add(self.page)
            if count:
                self.words_miss += n
            return s
        try:
            return lead + fill(t, nums) + trail
        except IndexError:
            self.missing[key].add(self.page)
            return s

    def run(self, toks):
        """A run of text and inline tags between two block boundaries -> translated HTML."""
        if not any(k == "t" and needs(v) for k, v, *_ in toks):
            return "".join(t[1] if t[0] == "t" else t[1] for t in toks)
        # peel tags that wrap the whole run (<a>…</a>) and void tags at the edges: fewer placeholders
        head, tail = [], []
        while toks and toks[0][0] == "g" and (toks[0][3] == "void" or toks[0][3] == "close"):
            head.append(toks.pop(0))
        while toks and toks[-1][0] == "g" and (toks[-1][3] == "void" or toks[-1][3] == "open"):
            tail.insert(0, toks.pop())
        while len(toks) >= 2 and toks[0][0] == "g" and toks[0][3] == "open" and toks[-1][0] == "g" and toks[-1][3] == "close" \
                and toks[0][2] == toks[-1][2] and self._pairs(toks):
            head.append(toks.pop(0))
            tail.insert(0, toks.pop())
        lead = re.match(r"\s*", toks[0][1]).group(0) if toks and toks[0][0] == "t" else ""
        trail = re.search(r"\s*$", toks[-1][1]).group(0) if toks and toks[-1][0] == "t" else ""
        key, nums, tags, stack, n = [], [], {}, [], 0
        for i, (k, v, *rest) in enumerate(toks):
            if k == "t":
                v = H.unescape(v)
                if i == 0:
                    v = v.lstrip()
                if i == len(toks) - 1:
                    v = v.rstrip()
                key.append(NUM.sub(lambda m: (nums.append(m.group(0)), "{%d}" % (len(nums) - 1))[1], v))
            else:
                name, kind = rest
                if kind == "open":
                    n += 1
                    stack.append((name, n))
                    tags[f"<{n}>"] = v
                    key.append(f"<{n}>")
                elif kind == "close":
                    j = next((x for nm, x in reversed(stack) if nm == name), None)
                    if j is None:                  # stray closing tag: keep it as a void placeholder
                        n += 1
                        tags[f"<{n}/>"] = v
                        key.append(f"<{n}/>")
                    else:
                        stack.remove((name, j))
                        tags[f"</{j}>"] = v
                        key.append(f"</{j}>")
                else:
                    n += 1
                    tags[f"<{n}/>"] = v
                    key.append(f"<{n}/>")
        k = re.sub(r"\s+", " ", "".join(key)).strip()
        plain = re.sub(r"</?\d+/?>", " ", k)
        words = len(plain.split())
        pieces = [x[1] for x in toks if x[0] == "t" and needs(x[1])]
        if n > 6 or (n >= 3 and words / max(1, len(pieces)) < 3.5):
            # a card made of many short labels (model · colour · grade · price): every text on its own, so that combinations
            # of models, colours and prices do not each need a translation
            return "".join(self.text_node(x[1]) if x[0] == "t" else x[1] for x in head + toks + tail)
        self.words_all += words
        t, mk = self.lookup(k)
        ok = t is not None and set(re.findall(r"</?\d+/?>", t)) == set(tags)
        if not ok:
            self.missing[mk].add(self.page)
            self.words_miss += words
            return "".join(x[1] for x in head) + "".join(x[1] for x in toks) + "".join(x[1] for x in tail)
        parts = re.split(r"(</?\d+/?>|\{\d+(?:\|[^{}]*)?\})", t)
        outp = []
        for p in parts:
            if p in tags:
                outp.append(tags[p])
            elif re.fullmatch(r"\{\d+(?:\|[^{}]*)?\}", p or ""):
                outp.append(H.escape(fill(p, nums), quote=False))
            else:
                outp.append(H.escape(p, quote=False))
        return "".join(x[1] for x in head) + lead + "".join(outp) + trail + "".join(x[1] for x in tail)

    def text_node(self, raw):
        if not needs(raw):
            return raw
        return H.escape(self.text(H.unescape(raw)), quote=False)

    @staticmethod
    def _pairs(toks):
        """The first open tag closes only at the very end."""
        name, depth = toks[0][2], 0
        for i, t in enumerate(toks):
            if t[0] == "g" and t[2] == name:
                depth += 1 if t[3] == "open" else -1 if t[3] == "close" else 0
                if depth == 0 and i != len(toks) - 1:
                    return False
        return True

    # ------------------------------------------------------------ tags
    def tag(self, tok):
        """Translate the visible attributes, point internal links at the language version."""
        if tok.startswith("</") or tok.startswith("<!"):
            return tok

        def attr(m):
            return f'{m.group(1)}="{H.escape(self.text(H.unescape(m.group(2)), count=False), quote=True)}"'
        tok = re.sub(r'\b(alt|title|aria-label|placeholder)="([^"]*)"', attr, tok)
        if tok.startswith("<meta") and re.search(r'(name="description"|property="og:(title|description|image:alt)"|name="twitter:(title|description)")', tok):
            tok = re.sub(r'\b(content)="([^"]*)"', attr, tok)
        if "data-lang" not in tok:
            tok = re.sub(r'\b(href|action)="(/(?!go/|img/|assets/|fonts/|data/|favicon|site\.webmanifest)[^"]*)"',
                         lambda m: m.group(0) if re.search(r"\.[a-z0-9]{2,5}(?:[?#]|$)", m.group(2)) else f'{m.group(1)}="{self.pfx}{m.group(2)}"', tok)
        return tok

    # ------------------------------------------------------------ JSON
    def json_val(self, v, key=None):
        if isinstance(v, dict):
            return {k: (x if k in SKIP_KEYS else self.json_val(x, k)) for k, x in v.items()}
        if isinstance(v, list):
            return [self.json_val(x, key) for x in v]
        if isinstance(v, str) and not v.startswith(("/", "http", "~", "#")) and (" " in v or re.search(r"[^\x00-\x7f]", v)):
            if "<" in v and ">" in v:              # FAQ answers in JSON-LD may carry markup
                return self.html_fragment(v)
            return self.text(v, count=False)
        return v

    def html_fragment(self, s):
        return self.translate_body(s)

    # ------------------------------------------------------------ page
    def translate_body(self, src):
        stash = []

        def keep(m):
            stash.append(m.group(0))
            return f"\x00{len(stash) - 1}\x00"
        src = re.sub(r"<(script|style|svg|textarea|noscript)\b.*?</\1>", lambda m: self._script(m.group(0), stash), src, flags=re.S | re.I)
        src = re.sub(r"<code\b[^>]*>.*?</code>", keep, src, flags=re.S)
        out, run = [], []
        for tok in re.split(r"(<!--.*?-->|<[^>]+>|\x00\d+\x00)", src, flags=re.S):
            if not tok:
                continue
            if tok.startswith("\x00"):
                body = stash[int(tok[1:-1])]
                if body.startswith("<code"):
                    run.append(("g", body, "code", "void"))
                else:
                    out.append(self.run(run)) if run else None
                    run = []
                    out.append(body)
            elif tok.startswith("<!--"):
                run.append(("g", tok, "!", "void"))
            elif tok.startswith("<"):
                m = re.match(r"</?\s*([a-zA-Z0-9]+)", tok)
                name = m.group(1).lower() if m else ""
                tok = self.tag(tok)
                if name in INLINE:
                    kind = "void" if name in VOID or tok.endswith("/>") else "close" if tok.startswith("</") else "open"
                    run.append(("g", tok, name, kind))
                else:
                    if run:
                        out.append(self.run(run))
                    run = []
                    out.append(tok)
            else:
                run.append(("t", tok))
        if run:
            out.append(self.run(run))
        return "".join(out)

    def _script(self, s, stash):
        """Scripts stay as they are except data: JSON-LD and the configurator JSON get translated values."""
        m = re.match(r'(<script type="application/(?:ld\+)?json"[^>]*>)(.*?)(</script>)$', s, re.S)
        if m and 'id="l10n"' not in m.group(1):
            try:
                data = json.loads(m.group(2))
                s = m.group(1) + json.dumps(self.json_val(data), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") + m.group(3)
            except ValueError:
                pass
        stash.append(s)
        return f"\x00{len(stash) - 1}\x00"

    def translate(self, html, path, site, index, js_keys):
        """Whole page -> (html of the language version, indexable?)."""
        self.page, self.words_all, self.words_miss = path, 0, 0
        out = self.translate_body(html)
        # a title with nothing to translate ("iPhone SE (2020) vs iPhone SE (2022)") would repeat the Czech one
        tc = re.search(r"<title>(.*?)</title>", html, re.S)
        if tc and tc.group(0) in out:
            out = out.replace(tc.group(0), f"<title>{tc.group(1)} – {TITLE_TAG[self.lang]}</title>", 1)
        url = site + self.pfx + path
        out = out.replace('<html lang="cs"', f'<html lang="{self.lang}"', 1)
        out = out.replace('"inLanguage":"cs"', f'"inLanguage":"{self.lang}"')
        out = out.replace('<meta property="og:locale" content="cs_CZ">', f'<meta property="og:locale" content="{LOCALE[self.lang]}">', 1)
        out = re.sub(r'<link rel="canonical" href="[^"]*">', f'<link rel="canonical" href="{url}">', out, count=1)
        out = re.sub(r'<meta property="og:url" content="[^"]*">', f'<meta property="og:url" content="{url}">', out, count=1)
        l10n = {k: self.d[k] for k in js_keys if k in self.d}
        out = out.replace('<script type="application/json" id="l10n">{}</script>',
                          '<script type="application/json" id="l10n">' + json.dumps(l10n, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") + "</script>", 1)
        share = self.words_miss / self.words_all if self.words_all else 0
        idx = index and share <= NOINDEX_SHARE
        if index and not idx:
            out = out.replace('content="index,follow,max-image-preview:large"', 'content="noindex,follow"', 1)
        return out, idx, share

    def js_missing(self, js_keys):
        for k in js_keys:
            if k not in self.d:
                self.missing[k].add("app.js")


def js_keys(js):
    """Strings app.js translates: T("…") and pl(n, "a|b|c")."""
    keys = [json.loads(f'"{k}"') for k in re.findall(r'\bT\(\s*"((?:[^"\\]|\\.)*)"', js) + re.findall(r'\bpl\([^,]+,\s*"((?:[^"\\]|\\.)*)"', js)]
    keys += [k.replace("\\'", "'") for k in re.findall(r"\bT\(\s*'((?:[^'\\]|\\.)*)'", js)]
    return sorted(set(keys))


def placeholders(s):
    return sorted(re.findall(r"</?\d+/?>|\{\d+\}", s))


def check():
    bad = 0
    for lang in LANGS:
        for k, v in load(lang).items():
            pk, pv = set(re.findall(r"</?\d+/?>", k)), set(re.findall(r"</?\d+/?>", v))
            nk, nv = set(re.findall(r"\{\d+\}", k)), set(re.findall(r"\{\d+\}", v))
            if pk != pv or not nv <= nk:
                bad += 1
                print(f"{lang}: placeholders differ\n  {k}\n  {v}")
            if re.search(r"[ěščřžůťďň]", v.replace("Kč", ""), re.I) and not re.search(r"jabkolevn|[A-Z][a-z]*ě|Slevový kód", v):
                print(f"{lang}: Czech letters left\n  {v}")
    print("bad", bad)
    return bad


def merge(files):
    """Add translated batches ({"uk": {...}, "ru": {...}}) to content/i18n/<lang>.json; placeholder mismatches are skipped."""
    for lang in LANGS:
        f = I18N / f"{lang}.json"
        d = json.loads(f.read_text()) if f.exists() else {}
        n = bad = 0
        for b in files:
            for k, v in json.loads(Path(b).read_text()).get(lang, {}).items():
                if set(re.findall(r"</?\d+/?>", k)) != set(re.findall(r"</?\d+/?>", v)) or not set(re.findall(r"\{\d+\}", v)) <= set(re.findall(r"\{\d+\}", k)):
                    bad += 1
                    continue
                d[k] = v
                n += 1
        f.write_text(json.dumps(dict(sorted(d.items())), ensure_ascii=False, indent=0) + "\n")
        print(lang, "added", n, "skipped", bad, "total", len(d))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "missing"
    if cmd == "merge":
        merge(sys.argv[2:])
        sys.exit(0)
    if cmd == "check":
        sys.exit(1 if check() else 0)
    if cmd == "missing":
        m = json.loads((APP / "data/state/i18n-missing.json").read_text())
        for lang, keys in m.items():
            if len(sys.argv) > 2 and lang != sys.argv[2]:
                continue
            print(lang, len(keys))
