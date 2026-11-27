/* repasovanyiphone.cz: voucher copy buttons (every page) + configurator colour -> storage -> quality -> cheapest shop (model pages).
   Configurator data: <script id="cfg" type="application/json"> from scripts/build.py.
   Rows: [colour, storage, grade, shop price, shop, go, battery, eSIM, price after voucher code, facts index into C.f], sorted by price after code.
   The markup mirrors configurator_html()/result_html() in build.py, so the page reads the same without JS. Quality = our scale only.
   Texts: T(czech text with {0}, x) and pl(n, one/few/many forms) look up the page's #l10n JSON (Ukrainian / Russian pages, scripts/i18n.py). */
var rpI = (function () {
  var d = document.documentElement, lang = d.lang || "cs", L = {};
  try { var el = document.getElementById("l10n"); if (el) L = JSON.parse(el.textContent); } catch (e) { /* ignore */ }
  var T = function (s) {
    var a = arguments;
    return (L[s] || s).replace(/\{(\d)\}/g, function (_, i) { return a[+i + 1]; });
  };
  var pl = function (n, forms) {
    var f = T(forms).split("|"), i;
    if (lang === "cs") i = n === 1 ? 0 : n >= 2 && n <= 4 ? 1 : 2;
    else { var a = n % 10, b = n % 100; i = a === 1 && b !== 11 ? 0 : a >= 2 && a <= 4 && (b < 12 || b > 14) ? 1 : 2; }
    return n + "\u00a0" + (f[i] || f[f.length - 1]);
  };
  /* the language switcher remembers the choice: no automatic switch after that */
  document.addEventListener("click", function (e) {
    var a = e.target.closest("a[data-lang]");
    if (a) { try { localStorage.setItem("ri-lang", a.dataset.lang); } catch (x) { /* ignore */ } }
  });
  return { T: T, pl: pl, lp: lang === "uk" ? "/ua" : lang === "ru" ? "/ru" : "" };
})();

(function () {
  var T = rpI.T;
  /* copy a voucher code: buttons show "copied", links (buy with code / to the shop) copy and then open the shop as usual */
  function copy(code) {
    try { if (navigator.clipboard) return navigator.clipboard.writeText(code); } catch (e) { /* ignore */ }
    var t = document.createElement("textarea"); t.value = code; t.style.position = "fixed"; t.style.opacity = "0";
    document.body.appendChild(t); t.select(); try { document.execCommand("copy"); } catch (e) { /* ignore */ } t.remove();
  }
  function done(el) {
    var old = el.innerHTML; el.textContent = T("Zkopírováno ✓"); el.classList.add("done");
    setTimeout(function () { el.innerHTML = old; el.classList.remove("done"); }, 2200);
  }
  document.addEventListener("click", function (e) {
    var el = e.target.closest("[data-copy]");
    if (!el) return;
    var code = el.dataset.copy, shop = el.dataset.shop || el.dataset.go || "", p = copy(code);
    window.dataLayer = window.dataLayer || [];
    window.dataLayer.push({ event: "coupon_copy", coupon: code, shop: shop, from_path: location.pathname });
    if (el.tagName !== "BUTTON" && !el.dataset.pop) return;
    /* coupon-site pattern: this page (with the code) opens in a new tab, the current tab goes to the shop through /go/,
       so a copied code still counts as our affiliate click. Ctrl/Cmd/Shift/middle click = copy only. */
    var href = el.dataset.href || (el.dataset.pop ? el.getAttribute("href") : "");
    if (href && !(e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button)) {
      var tab = window.open(location.pathname + location.search + "#kod=" + encodeURIComponent(code) + (shop ? "&s=" + encodeURIComponent(shop) : ""), "_blank");
      if (tab) {
        e.preventDefault();      /* a link marked data-pop behaves like the copy button (not used on the site at the moment) */
        try { tab.opener = null; } catch (x) { /* ignore */ }
        window.dataLayer.push({ event: "click_shop", shop: shop, with_code: "yes", via: "copy", from_path: location.pathname, transport_type: "beacon" });
        var gone = 0, leave = function () { if (!gone) { gone = 1; location.href = href; } };
        if (p && p.then) p.then(leave, leave);
        setTimeout(leave, 400);
        return;
      }
      if (el.tagName !== "BUTTON") return;      /* popup blocked: the link simply opens the shop */
      if (!el.parentNode.querySelector(".cpn-open")) {
        var a = document.createElement("a");
        a.className = "cpn-open"; a.href = href; a.target = "_blank"; a.rel = "sponsored nofollow noopener";
        a.dataset.go = shop; a.dataset.copy = code; a.textContent = T("Otevřít obchod s kódem");
        el.insertAdjacentElement("afterend", a);
      }
    }
    done(el);
  });

  /* the new tab from a copied code: say the code is in the clipboard, point at it, then clean the address */
  var km = /^#kod=([^&]+)(?:&s=([a-z0-9-]+))?$/.exec(location.hash);
  if (km) {
    var kc0 = decodeURIComponent(km[1]);
    history.replaceState(null, "", location.pathname + location.search);
    window.dataLayer = window.dataLayer || [];
    window.dataLayer.push({ event: "coupon_reveal", coupon: kc0, shop: km[2] || "", from_path: location.pathname });
    var reveal = function () {
      var bar = document.createElement("div");
      bar.className = "kodbar"; bar.setAttribute("role", "status");
      bar.innerHTML = "<p>" + T("Kód {0} máte zkopírovaný. Obchod se otevřel v původní kartě, kód vložte v košíku.", "<code></code>") + "</p>" +
        '<button type="button" class="cpn-copy">' + T("Kopírovat znovu") + '</button><button type="button" class="kodbar-x" aria-label="' + T("Zavřít") + '">×</button>';
      bar.querySelector("code").textContent = kc0;
      bar.querySelector(".cpn-copy").dataset.copy = kc0;
      bar.querySelector(".kodbar-x").addEventListener("click", function () { bar.remove(); });
      var k1 = kc0.replace(/["\\]/g, ""), t = document.querySelector('[data-kod="' + k1 + '"], [data-copy="' + k1 + '"]:not(a)');
      document.body.appendChild(bar);
      var box = t && (t.closest(".cpn, .ccard, .alts li, .cphint") || t);
      if (box) {
        /* sections below the fold use content-visibility (estimated 640 px heights): render everything first,
           otherwise the scroll target is computed from the estimates and the page lands in the footer */
        document.documentElement.classList.add("cv-off");
        box.classList.add("kod-here");
        requestAnimationFrame(function () { box.scrollIntoView({ block: "center" }); });
      }
    };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", reveal); else setTimeout(reveal, 0);
  }

  /* clicks to shops for GTM (click_shop) */
  document.addEventListener("click", function (e) {
    var a = e.target.closest("a[data-go]");
    if (!a || e.defaultPrevented) return;
    window.dataLayer = window.dataLayer || [];
    window.dataLayer.push({ event: "click_shop", shop: a.dataset.go, with_code: a.dataset.copy ? "yes" : "no", price: +(a.dataset.price || 0) || undefined,
      from_path: location.pathname, transport_type: "beacon" });
  });

  /* subID for commission per page: every /go/ link gets ?si=<page>&sp=<place>; the /go/ page turns them into
     eHub data1/data2 or CJ sid (prefix rp-). Kept in the browser so guides, categories and the configurator all share it. */
  var SI = (location.pathname.replace(/^\/+|\/+$/g, "").replace(/[^a-z0-9]+/g, "-") || "home").slice(0, 40);
  var tagged = function (h, sp) {
    if (!h || h.indexOf("/go/") !== 0 || /[?&]si=/.test(h)) return h;
    return h + (h.indexOf("?") < 0 ? "?" : "&") + "si=" + SI + "&sp=" + sp;
  };
  window.rpTag = function (root) {
    (root || document).querySelectorAll('a[href^="/go/"], [data-href^="/go/"]').forEach(function (a) {
      var sp = /^[a-z]{1,10}$/.test(a.dataset.sp || "") ? a.dataset.sp : a.dataset.go === "vodafone" ? "vf" : "l";
      if (a.tagName === "A") a.setAttribute("href", tagged(a.getAttribute("href"), sp));
      if (a.dataset.href) a.dataset.href = tagged(a.dataset.href, sp);
    });
  };
  window.rpTag();

  /* instalments landing (Home Credit): an intermediate step, the key event stays click_shop */
  document.addEventListener("click", function (e) {
    var a = e.target.closest("a[data-loan]");
    if (!a) return;
    window.dataLayer = window.dataLayer || [];
    window.dataLayer.push({ event: "loan_click", via: a.dataset.loan, from_path: location.pathname, transport_type: "beacon" });
  });

  /* in-page anchors (#rozpocet, #modely…): sections lower on the page use content-visibility with estimated heights,
     so a plain jump lands far off; render everything first, then scroll (same fix as the coupon reveal) */
  var jump = function (id, smooth) {
    var t = id && document.getElementById(id);
    if (!t) return false;
    document.documentElement.classList.add("cv-off");
    requestAnimationFrame(function () { t.scrollIntoView({ block: "start", behavior: smooth ? "smooth" : "auto" }); });
    return true;
  };
  document.addEventListener("click", function (e) {
    var a = e.target.closest('a[href*="#"]');
    if (!a || a.hash.length < 2 || a.pathname !== location.pathname || a.origin !== location.origin || e.ctrlKey || e.metaKey || e.shiftKey || e.button) return;
    if (jump(a.hash.slice(1), true)) { e.preventDefault(); history.replaceState(null, "", a.hash); }
  });
  if (/^#[a-z][a-z0-9-]*$/.test(location.hash)) {
    var go0 = function () { jump(location.hash.slice(1), false); };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", go0); else go0();
  }

  /* consent bar: Consent Mode v2 update (the default "denied" is set in the page head before GTM loads) */
  var bar = document.querySelector("[data-consentbar]");
  if (bar) {
    var store = function (v) { try { if (v === undefined) return localStorage.getItem("ri-consent"); localStorage.setItem("ri-consent", v); } catch (e) { return null; } };
    if (!store()) bar.hidden = false;
    bar.addEventListener("click", function (e) {
      var b = e.target.closest("[data-consent]");
      if (!b) return;
      store(b.dataset.consent);
      bar.hidden = true;
      if (window.gtag) window.gtag("consent", "update", { analytics_storage: b.dataset.consent === "yes" ? "granted" : "denied" });
    });
    document.addEventListener("click", function (e) {
      if (e.target.closest("[data-consent-open]")) { e.preventDefault(); bar.hidden = false; }
    });
  }
})();

(function () {
  var el = document.getElementById("cfg");
  var root = document.querySelector("[data-cfg]");
  if (!el || !root) return;
  var C = JSON.parse(el.textContent), T = rpI.T, pl = rpI.pl;
  var ORDER = C.order || ["novy", "aplus", "a", "b", "c"];
  var rows = C.o;
  var q = function (s) { return root.querySelector(s); };
  var kc = function (v) { return String(Math.round(v)).replace(/\B(?=(\d{3})+(?!\d))/g, " ") + " Kč"; };
  var esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };
  var gbl = function (v) { return v >= 1024 ? (v / 1024) + " TB" : v + " GB"; };
  var nab = function (n) { return pl(n, "nabídka|nabídky|nabídek"); };
  var colIdx = function (k) { for (var i = 0; i < C.cols.length; i++) if (C.cols[i][0] === k) return i; return -1; };
  var go = function (r) { return r[5].charAt(0) === "~" ? "/go/" + r[4] + "/?u=" + r[5].slice(1) : r[5]; };
  var min = function (list) { var m = null; list.forEach(function (r) { if (m === null || r[8] < m) m = r[8]; }); return m; };
  var where = function (ci, gi, g) { return rows.filter(function (r) { return (ci < 0 || r[0] === ci) && (gi < 0 || r[1] === gi) && (!g || r[2] === g); }); };
  var code = function (r) { return r[8] < r[3] && C.cp[r[4]] ? C.cp[r[4]] : null; };

  var S = { c: colIdx(C.def[0]), gi: C.gbs.indexOf(C.def[1]), g: C.def[2] };
  var p = new URLSearchParams(location.search);
  if (p.get("barva") && colIdx(p.get("barva")) >= 0) S.c = colIdx(p.get("barva"));
  if (p.get("pamet") && C.gbs.indexOf(+p.get("pamet")) >= 0) S.gi = C.gbs.indexOf(+p.get("pamet"));
  if (p.get("kvalita") && ORDER.indexOf(p.get("kvalita")) >= 0) S.g = p.get("kvalita");

  function settle(keep) {
    /* never leave the visitor on an empty combination: keep what they just chose, move the rest to the nearest available */
    if (!where(S.c, S.gi).length) {
      if (keep === "gb") {
        var cs = C.cols.map(function (_, i) { return i; }).filter(function (i) { return where(i, S.gi).length; });
        if (cs.length) S.c = cs.sort(function (a, b) { return min(where(a, S.gi)) - min(where(b, S.gi)); })[0];
      } else {
        var gs = C.gbs.map(function (_, i) { return i; }).filter(function (i) { return where(S.c, i).length; });
        if (gs.length) S.gi = gs.sort(function (a, b) { return Math.abs(a - S.gi) - Math.abs(b - S.gi); })[0];
      }
    }
    if (!where(S.c, S.gi, S.g).length) {
      var have = ORDER.filter(function (g) { return where(S.c, S.gi, g).length; });
      if (have.length) {
        var at = ORDER.indexOf(S.g);
        S.g = have.sort(function (a, b) { return Math.abs(ORDER.indexOf(a) - at) - Math.abs(ORDER.indexOf(b) - at); })[0];
      }
    }
  }

  function shopMini(sid, h) {
    var s = C.shops[sid];
    var hk = Math.round((h || 22) * (s[4] || 1));
    return s[1] ? '<img class="slogo" src="' + s[1] + '" alt="' + esc(s[0]) + '" width="' + Math.round(s[3] * hk) + '" height="' + hk + '" style="--k:' + (s[4] || 1) + '" decoding="async">'
      : '<span class="slogo stext" style="--c:' + s[2] + '">' + esc(s[0]) + "</span>";
  }

  function facts(f) {
    var li = (f[0] ? '<li class="of of-b ' + f[1] + '">' + esc(f[0]) + "</li>" : "") + '<li class="of of-w ' + f[3] + '">' + esc(f[2]) + '</li><li class="of of-t">' + esc(f[4]) + "</li>" +
      (f[5] ? '<li class="of of-d">' + esc(f[5].charAt(0).toUpperCase() + f[5].slice(1)) + "</li>" : "");
    return '<ul class="ofacts">' + li + "</ul>";
  }

  function repup(best) {
    /* zánovní configurator only: the same phone as an ordinary refurb (A, else B/C), if it is clearly cheaper */
    var r = C.rep && C.rep[S.c + "," + S.gi];
    if (!r || r[3] > best[8] - 300) return "";
    var gb = C.gbs[S.gi];
    var u = rpI.lp + "/" + C.m + "/?barva=" + r[0] + "&amp;pamet=" + gb + "&amp;kvalita=" + r[2];
    return '<a class="repup" href="' + u + '"><span>' + T("<b>Chcete ušetřit víc?</b> Repasovaný {0} {1}, {2} ve stavu {3} od <b>{4}</b> · o {5} méně",
      esc(C.name), gbl(gb), esc(r[1].toLowerCase()), esc(C.rgr[r[2]]), kc(r[3]), kc(best[8] - r[3])) + '</span><span class="repup-a" aria-hidden="true">→</span></a>';
  }

  function result() {
    var res = where(S.c, S.gi, S.g);
    if (!res.length) return '<p class="empty">' + T("Tahle kombinace teď není skladem. Zkuste jinou barvu nebo kvalitu.") + "</p>";
    var best = res[0], gb = C.gbs[S.gi], newp = C.newp[String(gb)], cp = code(best), F = C.f;
    var save = newp && newp > best[8] && best[2] !== "novy" ? '<span class="save hand">' + T("o {0} levněji než nový", kc(newp - best[8])) + "</span>" : "";
    var was = best[8] < best[3] ? '<span class="was">' + T("{0} v obchodě", kc(best[3])) + "</span>" : "";
    var lowl = "", L = C.low;
    if (L && best[8] > L[3]) {
      var lc = C.cols[colIdx(L[0])];
      lowl = '<a class="lowlink" href="?barva=' + L[0] + "&amp;pamet=" + L[1] + "&amp;kvalita=" + L[2] + '" data-low>' + T("Nejlevnější {0} za <b>{1}</b> · stav {2}, {3}, {4}", esc(C.name), kc(L[3]),
        esc(C.grades[L[2]][0]), gbl(L[1]), esc(lc ? lc[1].toLowerCase() : "")) + "</a>";
    }
    var seen = {}, others = [];
    res.forEach(function (r) { if (!seen[r[4]]) { seen[r[4]] = 1; if (r !== best) others.push(r); } });
    var pr = F[best[9]][6] ? null : res.filter(function (r) { return F[r[9]][6]; })[0], proven = "";
    if (pr) {
      var pc = code(pr);
      proven = '<div class="proven"><p class="pv-k">' + T("Nejlevnější s doloženou baterií a zárukou") + '</p><div class="pv-row">' + shopMini(pr[4]) +
        '<span class="pv-p"><b>' + kc(pr[8]) + "</b><small>" + T("o {0} víc", kc(pr[8] - best[8])) + "</small></span>" +
        '<a class="btn sm" href="' + esc(go(pr)) + '" rel="sponsored nofollow noopener" target="_blank" data-go="' + pr[4] + '" data-price="' + pr[8] + '" data-sp="proven"' +
        (pc ? ' data-copy="' + esc(pc[0]) + '"' : "") + ">" + T("Do obchodu") + "</a></div>" + facts(F[pr[9]]) + "</div>";
    }
    var html = '<div class="best"><div class="best-top"><span class="best-k">' + T("Nejlevněji") + "</span>" + shopMini(best[4], 26) + "</div>" +
      '<p class="best-p"><span class="price">' + kc(best[8]) + "</span>" + was + save + "</p>" + lowl + facts(F[best[9]]) +
      (best[7] ? '<p class="best-f">' + T("jen eSIM") + "</p>" : "") +
      (cp ? '<div class="cpn"><span class="cpn-k">' + T("Slevový kód") + "</span><code>" + esc(cp[0]) + '</code><button type="button" class="cpn-copy" data-copy="' + esc(cp[0]) + '" data-shop="' + best[4] + '" data-href="' + esc(go(best)) + '">' + T("Kopírovat") + "</button>" +
        "<small>" + esc(cp[1]) + " · " + esc(cp[2]) + " · " + T("zadejte v košíku") + "</small></div>" : "") +
      '<a class="btn big" href="' + esc(go(best)) + '" rel="sponsored nofollow noopener" target="_blank" data-go="' + best[4] + '" data-price="' + best[8] + '" data-sp="best"' +
      (cp ? ' data-copy="' + esc(cp[0]) + '"' : "") + ">" +
      (cp ? T("Koupit s kódem u {0}", esc(C.shops[best[4]][0])) : T("Koupit u {0}", esc(C.shops[best[4]][0]))) + "</a>" +
      '<p class="best-n">' + T("{0} v této konfiguraci", nab(res.length)) + "</p>" +
      (best[8] >= 10000 ? '<a class="loanrow" href="' + rpI.lp + "/iphone-na-splatky/?z=" + C.m + '" data-loan="card"><img class="hc-logo" src="/img/partners/homecredit.svg" alt="Home Credit" width="40" height="17" loading="lazy" decoding="async">' +
        "<span>" + T("Chcete platit postupně? <b>iPhone na splátky</b>") + "</span></a>" : "") + "</div>" + repup(best) + proven;
    var ICON = '<svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2.5" fill="none" stroke="currentColor" stroke-width="2"/>' +
      '<path d="M5 15V6a2 2 0 0 1 2-2h9" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
    var chip = function (r) {
      var c = code(r);
      return c ? '<button type="button" class="cchip" data-copy="' + esc(c[0]) + '" data-shop="' + r[4] + '" data-sp="chip" data-href="' + esc(go(r)) + '" aria-label="' + T("Kopírovat slevový kód {0}", esc(c[0])) + '"><span>' + esc(c[0]) + "</span>" + ICON + "</button>" : "";
    };
    if (!cp) {
      var near = others.filter(function (r) { return code(r) && r[8] <= best[8] * 1.03; })[0];
      if (near) html += '<p class="cphint">' + T('<span class="hand">Radši se slevovým kódem?</span> {0} s kódem {1} za {2}', esc(C.shops[near[4]][0]), chip(near), kc(near[8])) +
        (near[8] > best[8] ? T(" (jen o {0} víc)", kc(near[8] - best[8])) : "") + "</p>";
    }
    if (others.length) {
      html += '<div class="alts"><h3>' + T("Další obchody") + "</h3><ul>" + others.map(function (r) {
        var c = code(r);
        return '<li><span class="o-shop">' + shopMini(r[4]) + '<span class="o-f">' + esc(F[r[9]][7]) + '</span></span><span class="o-cp">' + chip(r) + '</span><span class="o-p"><b>' + kc(r[8]) + "</b>" + (c ? "<s>" + kc(r[3]) + "</s>" : "") +
          '</span><a class="btn sm ghost" href="' + esc(go(r)) + '" rel="sponsored nofollow noopener" target="_blank" data-go="' + r[4] + '" data-price="' + r[8] + '" data-sp="alt"' + (c ? ' data-copy="' + esc(c[0]) + '"' : "") + ">" + T("Do obchodu") + "</a></li>";
      }).join("") + "</ul></div>";
    }
    /* cheaper nearby: another colour (same storage + quality) or one step lower quality (same colour + storage) */
    var tips = [];
    var oc = where(-1, S.gi, S.g).filter(function (r) { return r[0] !== S.c && r[8] < best[8] - 200; })[0];
    if (oc) tips.push('<button type="button" class="tip" data-set-col="' + C.cols[oc[0]][0] + '"><span class="dot xs" style="--h:' + C.cols[oc[0]][2] + '"></span>' + T("v barvě {0} za {1}", esc(C.cols[oc[0]][1]), kc(oc[8])) + "</button>");
    var lower = ORDER.slice(ORDER.indexOf(S.g) + 1);
    for (var i = 0; i < lower.length; i++) {
      var lg = where(S.c, S.gi, lower[i])[0];
      if (lg && lg[8] < best[8] - 200) { tips.push('<button type="button" class="tip" data-set-g="' + lower[i] + '">' + (C.glab ? T("jako {0} za {1}", C.grades[lower[i]][0], kc(lg[8])) : T("v kvalitě {0} za {1}", C.grades[lower[i]][0], kc(lg[8]))) + "</button>"); break; }
    }
    if (tips.length) html += '<div class="tips"><span class="hand">' + T("Levněji:") + "</span>" + tips.join("") + "</div>";
    return html;
  }

  function render() {
    var col = C.cols[S.c];
    var ph = q("[data-photo]");
    if (col[3] && ph.getAttribute("src") !== col[3]) { ph.src = col[3]; ph.alt = T("{0} v barvě {1}", C.name, col[1]); }
    q("[data-v-col]").textContent = col[1];
    q("[data-cols]").innerHTML = C.cols.map(function (c, i) {
      var here = where(i, S.gi), any = where(i, -1);
      var t = c[1] + (here.length ? T(", od {0}", kc(min(here))) : any.length ? T(", v jiné paměti") : "");
      return '<button type="button" class="sw' + (i === S.c ? " on" : "") + (here.length ? "" : " dim") + '" data-col="' + c[0] + '" aria-pressed="' + (i === S.c) +
        '" aria-label="' + esc(t) + '" title="' + esc(t) + '"><span class="dot" style="--h:' + c[2] + '"></span></button>';
    }).join("");
    q("[data-gbs]").innerHTML = C.gbs.map(function (g, i) {
      var here = where(S.c, i);
      return '<button type="button" class="pill' + (i === S.gi ? " on" : "") + (here.length ? "" : " dim") + '" data-gb="' + g + '" aria-pressed="' + (i === S.gi) + '">' +
        gbl(g) + "<small>" + (here.length ? T("od {0}", kc(min(here))) : T("jiná barva")) + "</small></button>";
    }).join("");
    q("[data-grades]").innerHTML = ORDER.map(function (g) {
      var here = where(S.c, S.gi, g), m = min(here);
      return '<button type="button" class="gcard' + (g === S.g ? " on" : "") + (here.length ? "" : " off") + '" data-g="' + g + '" aria-pressed="' + (g === S.g) + '"' + (here.length ? "" : " disabled") + ">" +
        '<span class="gl g-' + g + '">' + C.grades[g][0] + '</span><span class="gn">' + C.grades[g][1] + '</span><span class="gp">' + (here.length ? T("od {0}", kc(m)) : T("není skladem")) + "</span></button>";
    }).join("");
    var hint = C.grades[S.g][2];
    q("[data-ghint]").textContent = hint.charAt(0).toUpperCase() + hint.slice(1) + ".";
    var gim = q("[data-gimg]");
    if (gim) { var ok = (C.gimg || []).indexOf(S.g) >= 0; gim.hidden = !ok; if (ok) gim.src = "/img/ui/grade-" + S.g + ".webp"; }
    q("[data-result]").innerHTML = result();
    if (window.rpTag) window.rpTag(q("[data-result]"));
    var best = where(S.c, S.gi, S.g)[0], bb = document.querySelector("[data-buybar]");
    if (bb && best) {
      var cp = code(best);
      bb.querySelector("[data-bb-t]").innerHTML = "<b>" + kc(best[8]) + "</b> " + esc(C.name) + " " + gbl(C.gbs[S.gi]) + ", " + (S.g === "novy" ? T("nový") : C.order ? C.grades[S.g][0].toLowerCase() : T("stav {0}", C.grades[S.g][0])) + (cp ? T(", s kódem") : "");
      var a = bb.querySelector("[data-bb-a]");
      a.href = go(best);
      a.textContent = T("Koupit u {0}", C.shops[best[4]][0]);
      if (cp) a.dataset.copy = cp[0]; else delete a.dataset.copy;
      if (window.rpTag) window.rpTag(bb);
    }
    if (!S.touched && !location.search) return;          /* clean URL until the visitor chooses something */
    var u = new URLSearchParams(location.search);
    u.set("barva", col[0]); u.set("pamet", C.gbs[S.gi]); u.set("kvalita", S.g);
    history.replaceState(null, "", location.pathname + "?" + u.toString());
  }

  document.addEventListener("click", function (e) {
    var l = e.target.closest("a[data-low]");
    if (!l || !C.low || e.ctrlKey || e.metaKey || e.shiftKey || e.button) return;
    e.preventDefault();
    S.c = colIdx(C.low[0]); S.gi = C.gbs.indexOf(C.low[1]); S.g = C.low[2]; S.touched = true;
    settle("g"); render();
    if (l.closest(".mhead")) root.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  root.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (!b || b.disabled || b.dataset.copy) return;
    if (b.dataset.col || b.dataset.setCol) { S.c = colIdx(b.dataset.col || b.dataset.setCol); settle("col"); }
    else if (b.dataset.gb) { S.gi = C.gbs.indexOf(+b.dataset.gb); settle("gb"); }
    else if (b.dataset.g || b.dataset.setG) { S.g = b.dataset.g || b.dataset.setG; settle("g"); }
    else return;
    S.touched = true;
    render();
  });

  /* sticky buy bar on phones once the big button scrolls away */
  var bar = document.querySelector("[data-buybar]");
  if (bar && "IntersectionObserver" in window) {
    /* visible from the first screen (the price is two screens down on phones), hidden only while the big button is in view
       or while the consent bar is open (both sit at the bottom) */
    var seen = false, cbar = document.querySelector("[data-consentbar]");
    var upd = function () { bar.hidden = seen || !!(cbar && !cbar.hidden); };
    var io = new IntersectionObserver(function (en) { seen = en[0].isIntersecting; upd(); });
    if (cbar) cbar.addEventListener("click", function () { setTimeout(upd, 0); });
    var watch = function () { var b = root.querySelector(".best .btn"); if (b) { io.disconnect(); io.observe(b); } };
    new MutationObserver(watch).observe(q("[data-result]"), { childList: true });
    watch();
  }
  settle("col");
  render();
})();

/* category pages: filter chips over the card grid (price band, series, current line-up); several groups combine (AND).
   data-typ may list several values ("z r"); on the zánovní landing a type filter also hides the offer rows of the other type. */
(function () {
  var fs = Array.prototype.slice.call(document.querySelectorAll("[data-cfilter]")), grid = document.querySelector("[data-cgrid]");
  if (!fs.length || !grid) return;
  var cards = Array.prototype.slice.call(grid.children), out = document.querySelector("[data-cf-n]"), sel = {};
  var nabWord = grid.dataset.word === "nab", T = rpI.T, pl = rpI.pl;
  var word = function (n) { return nabWord ? pl(n, "nabídka|nabídky|nabídek") : pl(n, "model|modely|modelů"); };
  function has(list, v) { return (" " + (list || "") + " ").indexOf(" " + v + " ") >= 0; }
  function apply() {
    var n = 0;
    cards.forEach(function (c) {
      var ok = true;
      Object.keys(sel).forEach(function (a) {
        var v = sel[a];
        if (!v || !ok) return;
        if (a === "p") { var r = v.split("-"), p = +c.dataset.p; ok = p > +r[0] && p <= +r[1]; }
        else ok = has(c.dataset[a], v);
      });
      c.hidden = !ok; if (ok) n++;
      c.querySelectorAll(".zrow[data-typ]").forEach(function (r) { r.hidden = !!sel.typ && r.dataset.typ !== sel.typ; });
    });
    if (out) out.textContent = word(n) + (n ? "" : T(" · zkuste jiný filtr"));
  }
  fs.forEach(function (f) {
    sel[f.dataset.cfilter] = "";
    f.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-v]");
      if (!b) return;
      f.querySelectorAll("button").forEach(function (x) { x.classList.toggle("on", x === b); x.setAttribute("aria-pressed", x === b); });
      sel[f.dataset.cfilter] = b.dataset.v;
      apply();
    });
  });
  apply();
})();

/* mobile: keep the current menu item in view inside the scrolling menu */
(function () {
  var a = document.querySelector(".nav a[aria-current]"), n = a && a.parentElement;
  if (n && n.scrollWidth > n.clientWidth) n.scrollLeft = Math.max(0, a.offsetLeft - 16);
})();
