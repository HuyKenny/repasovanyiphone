#!/usr/bin/env python3
"""Ukrainian and Russian versions of the built Czech pages (translation memory over finished HTML).

The Czech page is the source. Every page is cut into segments at block-level tags; inline tags inside a segment become
placeholders <1>…</1> / <2/>, numbers become {0}, {1}… so the nightly prices never change a segment. A segment is looked up in
content/i18n/<lang>.json (key = Czech segment, value = translation with the same placeholders); a missing one stays Czech
and is reported in data/state/i18n-missing.json. JSON-LD and the configurator JSON (#cfg) are translated value by value.

    python3 scripts/i18n.py missing [lang]     # untranslated segments of the last build (data/state/i18n-missing.json)
    python3 scripts/i18n.py check              # placeholders of every translation match its key
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
        vodafone ehub cj home credit repasovanyiphone www https http cookies x xr xs cs ua ru""".split()}
# "{n} word" alone (card counts): the form follows the number in the target language, not the Czech form
PLURALS = ["nabídka|nabídky|nabídek", "model|modely|modelů", "rok|roky|let", "měsíc|měsíce|měsíců", "den|dny|dní", "kus|kusy|kusů",
           "obchod|obchody|obchodů", "barva|barvy|barev"]
PLURAL_OF = {w: f for f in PLURALS for w in f.split("|")}
SKIP_KEYS = {"@context", "@type", "@id", "url", "item", "image", "logo", "sku", "gtin", "gtin13", "mpn", "priceCurrency",
             "availability", "itemCondition", "sameAs", "contentUrl", "thumbnailUrl", "inLanguage", "encodingFormat", "brand"}


MONTHS = {"cs": "ledna února března dubna května června července srpna září října listopadu prosince".split(),
          "uk": "січня лютого березня квітня травня червня липня серпня вересня жовтня листопада грудня".split(),
          "ru": "января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split()}


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


class Tr:
    """One language: translates whole pages, collects what is missing."""

    def __init__(self, lang):
        self.lang, self.pfx = lang, "/" + LANGS[lang]
        self.d = load(lang)
        self.missing = defaultdict(set)           # key -> pages
        self.page = ""
        self.words_all = self.words_miss = 0

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
        t = self.d.get(key)
        if t is None:
            self.missing[key].add(self.page)
            if count:
                self.words_miss += n
            return s
        try:
            return lead + re.sub(r"\{(\d+)\}", lambda m: nums[int(m.group(1))], t) + trail
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
        t = self.d.get(k)
        ok = t is not None and set(re.findall(r"</?\d+/?>", t)) == set(tags)
        if not ok:
            self.missing[k].add(self.page)
            self.words_miss += words
            return "".join(x[1] for x in head) + "".join(x[1] for x in toks) + "".join(x[1] for x in tail)
        parts = re.split(r"(</?\d+/?>|\{\d+\})", t)
        outp = []
        for p in parts:
            if p in tags:
                outp.append(tags[p])
            elif re.fullmatch(r"\{\d+\}", p or ""):
                i = int(p[1:-1])
                outp.append(H.escape(nums[i], quote=False) if i < len(nums) else "")
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
        url = site + self.pfx + path
        out = out.replace('<html lang="cs"', f'<html lang="{self.lang}"', 1)
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
            if re.search(r"[ěščřžůťďň]", v, re.I) and not re.search(r"jabkolevn|[A-Z][a-z]*ě", v):
                print(f"{lang}: Czech letters left\n  {v}")
    print("bad", bad)
    return bad


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "missing"
    if cmd == "check":
        sys.exit(1 if check() else 0)
    if cmd == "missing":
        m = json.loads((APP / "data/state/i18n-missing.json").read_text())
        for lang, keys in m.items():
            if len(sys.argv) > 2 and lang != sys.argv[2]:
                continue
            print(lang, len(keys))
