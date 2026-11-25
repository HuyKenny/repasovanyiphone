/* repasovanyiphone.cz configurator: colour -> storage -> quality -> cheapest shop + other shops.
   Data: <script id="cfg" type="application/json"> written by scripts/build.py (rows: [colour, storage, grade, price, shop, go, shop wording, battery, eSIM]).
   The markup mirrors configurator_html()/result_html() in build.py, so the page reads the same without JS. */
(function () {
  var el = document.getElementById("cfg");
  var root = document.querySelector("[data-cfg]");
  if (!el || !root) return;
  var C = JSON.parse(el.textContent);
  var ORDER = ["novy", "aplus", "a", "b", "c"];
  var rows = C.o;
  var q = function (s) { return root.querySelector(s); };
  var kc = function (v) { return String(Math.round(v)).replace(/\B(?=(\d{3})+(?!\d))/g, " ") + " Kč"; };
  var esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };
  var gbl = function (v) { return v >= 1024 ? (v / 1024) + " TB" : v + " GB"; };
  var nab = function (n) { return n + " " + (n === 1 ? "nabídka" : n >= 2 && n <= 4 ? "nabídky" : "nabídek"); };
  var colIdx = function (k) { for (var i = 0; i < C.cols.length; i++) if (C.cols[i][0] === k) return i; return -1; };
  var go = function (r) { return /^(https?:|\/)/.test(r[5]) ? r[5] : "/go/" + r[4] + "/?u=" + r[5]; };
  var min = function (list) { var m = null; list.forEach(function (r) { if (m === null || r[3] < m) m = r[3]; }); return m; };
  var where = function (ci, gi, g) { return rows.filter(function (r) { return (ci < 0 || r[0] === ci) && (gi < 0 || r[1] === gi) && (!g || r[2] === g); }); };

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
    return s[1] ? '<img class="slogo" src="' + s[1] + '" alt="' + esc(s[0]) + '" height="' + (h || 22) + '" decoding="async">'
      : '<span class="slogo stext" style="--c:' + s[2] + '">' + esc(s[0]) + "</span>";
  }

  function result() {
    var res = where(S.c, S.gi, S.g);
    if (!res.length) return '<p class="empty">Tahle kombinace teď není skladem. Zkuste jinou barvu nebo kvalitu.</p>';
    var best = res[0], gb = C.gbs[S.gi], newp = C.newp[String(gb)];
    var save = newp && newp > best[3] && best[2] !== "novy" ? '<span class="save hand">o ' + kc(newp - best[3]) + " levněji než nový</span>" : "";
    var facts = [];
    if (best[6]) facts.push("u obchodu: " + esc(best[6]));
    if (best[7]) facts.push("baterie " + best[7] + " %");
    if (best[8]) facts.push("jen eSIM");
    var seen = {}, others = [];
    res.forEach(function (r) { if (!seen[r[4]]) { seen[r[4]] = 1; if (r !== best) others.push(r); } });
    var html = '<div class="best"><div class="best-top"><span class="best-k">Nejlevněji</span>' + shopMini(best[4], 26) + "</div>" +
      '<p class="best-p"><span class="price">' + kc(best[3]) + "</span>" + save + "</p>" +
      '<p class="best-f">' + facts.join(" · ") + "</p>" +
      '<a class="btn big" href="' + esc(go(best)) + '" rel="sponsored nofollow noopener" target="_blank" data-go="' + best[4] + '">Koupit u ' + esc(C.shops[best[4]][0]) + "</a>" +
      '<p class="best-n">' + nab(res.length) + " v této konfiguraci</p></div>";
    if (others.length) {
      html += '<div class="alts"><h3>Další obchody</h3><ul>' + others.map(function (r) {
        return '<li><span class="o-shop">' + shopMini(r[4]) + '</span><span class="o-sg">' + esc(r[6]) + '</span><span class="o-p">' + kc(r[3]) +
          '</span><a class="btn sm ghost" href="' + esc(go(r)) + '" rel="sponsored nofollow noopener" target="_blank" data-go="' + r[4] + '">Do obchodu</a></li>';
      }).join("") + "</ul></div>";
    }
    /* cheaper nearby: another colour (same storage + quality) or one step lower quality (same colour + storage) */
    var tips = [];
    var oc = where(-1, S.gi, S.g).filter(function (r) { return r[0] !== S.c && r[3] < best[3] - 200; })[0];
    if (oc) tips.push('<button type="button" class="tip" data-set-col="' + C.cols[oc[0]][0] + '"><span class="dot xs" style="--h:' + C.cols[oc[0]][2] + '"></span>v barvě ' + esc(C.cols[oc[0]][1]) + " za " + kc(oc[3]) + "</button>");
    var lower = ORDER.slice(ORDER.indexOf(S.g) + 1);
    for (var i = 0; i < lower.length; i++) {
      var lg = where(S.c, S.gi, lower[i])[0];
      if (lg && lg[3] < best[3] - 200) { tips.push('<button type="button" class="tip" data-set-g="' + lower[i] + '">v kvalitě ' + C.grades[lower[i]][0] + " za " + kc(lg[3]) + "</button>"); break; }
    }
    if (tips.length) html += '<div class="tips"><span class="hand">Levněji:</span>' + tips.join("") + "</div>";
    return html;
  }

  function render() {
    var col = C.cols[S.c];
    var ph = q("[data-photo]");
    if (col[3] && ph.getAttribute("src") !== col[3]) { ph.src = col[3]; ph.alt = C.name + ", " + col[1]; }
    q("[data-v-col]").textContent = col[1];
    q("[data-cols]").innerHTML = C.cols.map(function (c, i) {
      var here = where(i, S.gi), any = where(i, -1);
      var t = c[1] + (here.length ? ", od " + kc(min(here)) : any.length ? ", v jiné paměti" : "");
      return '<button type="button" class="sw' + (i === S.c ? " on" : "") + (here.length ? "" : " dim") + '" data-col="' + c[0] + '" aria-pressed="' + (i === S.c) +
        '" aria-label="' + esc(t) + '" title="' + esc(t) + '"><span class="dot" style="--h:' + c[2] + '"></span></button>';
    }).join("");
    q("[data-gbs]").innerHTML = C.gbs.map(function (g, i) {
      var here = where(S.c, i);
      return '<button type="button" class="pill' + (i === S.gi ? " on" : "") + (here.length ? "" : " dim") + '" data-gb="' + g + '" aria-pressed="' + (i === S.gi) + '">' +
        gbl(g) + '<small>' + (here.length ? "od " + kc(min(here)) : "jiná barva") + "</small></button>";
    }).join("");
    q("[data-grades]").innerHTML = ORDER.map(function (g) {
      var here = where(S.c, S.gi, g), m = min(here);
      return '<button type="button" class="gcard' + (g === S.g ? " on" : "") + (here.length ? "" : " off") + '" data-g="' + g + '" aria-pressed="' + (g === S.g) + '"' + (here.length ? "" : " disabled") + ">" +
        '<span class="gl g-' + g + '">' + C.grades[g][0] + '</span><span class="gn">' + C.grades[g][1] + '</span><span class="gp">' + (here.length ? "od " + kc(m) : "není skladem") + "</span></button>";
    }).join("");
    var hint = C.grades[S.g][2];
    q("[data-ghint]").textContent = hint.charAt(0).toUpperCase() + hint.slice(1) + ".";
    var gi = q("[data-gimg]");
    if (gi) { var ok = (C.gimg || []).indexOf(S.g) >= 0; gi.hidden = !ok; if (ok) gi.src = "/img/ui/grade-" + S.g + ".webp"; }
    q("[data-result]").innerHTML = result();
    var best = where(S.c, S.gi, S.g)[0], bb = document.querySelector("[data-buybar]");
    if (bb && best) {
      bb.querySelector("[data-bb-t]").innerHTML = "<b>" + kc(best[3]) + "</b> " + esc(C.name) + " " + gbl(C.gbs[S.gi]) + ", " + C.grades[S.g][0];
      var a = bb.querySelector("[data-bb-a]");
      a.href = go(best);
      a.textContent = "Koupit u " + C.shops[best[4]][0];
    }
    if (!S.touched && !location.search) return;          /* clean URL until the visitor chooses something */
    var u = new URLSearchParams(location.search);
    u.set("barva", col[0]); u.set("pamet", C.gbs[S.gi]); u.set("kvalita", S.g);
    history.replaceState(null, "", location.pathname + "?" + u.toString());
  }

  root.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (!b || b.disabled) return;
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
    var io = new IntersectionObserver(function (en) { bar.hidden = en[0].isIntersecting || en[0].boundingClientRect.top > 0; });
    var watch = function () { var b = root.querySelector(".best .btn"); if (b) { io.disconnect(); io.observe(b); } };
    new MutationObserver(watch).observe(q("[data-result]"), { childList: true });
    watch();
  }
  settle("col");
  render();
})();
