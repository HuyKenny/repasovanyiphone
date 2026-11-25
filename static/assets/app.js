/* Offer filter on model pages: storage, condition, shop, sort. Pure DOM, no dependencies. */
(function () {
  var list = document.querySelector("[data-offers]");
  if (!list) return;
  var form = document.querySelector("[data-filters]");
  var tags = Array.prototype.slice.call(list.querySelectorAll(".tag"));
  var count = form.querySelector("[data-count]");
  var moreBtn = document.querySelector("[data-more]");
  var PAGE = 24, shown = PAGE;
  var order = { "novy": 0, "jako-novy": 1, "vyborny": 2, "velmi-dobry": 3, "dobry": 4 };
  function val(n) { var el = form.querySelector('[name="' + n + '"]'); return el ? el.value : ""; }
  function apply(reset) {
    if (reset) shown = PAGE;
    var gb = val("gb"), g = val("g"), shop = val("shop"), sort = val("sort");
    var hit = tags.filter(function (t) {
      var d = t.dataset;
      return (!gb || d.gb === gb) && (!g || order[d.g] <= order[g]) && (!shop || d.shop === shop);
    });
    hit.sort(function (a, b) {
      var A = a.dataset, B = b.dataset;
      if (sort === "bat") return (+B.bat || 0) - (+A.bat || 0) || A.p - B.p;
      if (sort === "g") return order[A.g] - order[B.g] || A.p - B.p;
      if (sort === "pd") return B.p - A.p;
      return A.p - B.p;
    });
    tags.forEach(function (t) { t.hidden = true; });
    hit.forEach(function (t, i) { list.appendChild(t); t.hidden = i >= shown; });
    count.textContent = hit.length + " " + (hit.length === 1 ? "nabídka" : hit.length < 5 && hit.length > 0 ? "nabídky" : "nabídek");
    if (moreBtn) moreBtn.hidden = hit.length <= shown;
    var q = new URLSearchParams();
    ["gb", "g", "shop", "sort"].forEach(function (n) { var v = val(n); if (v && !(n === "sort" && v === "p")) q.set(n, v); });
    history.replaceState(null, "", location.pathname + (q.toString() ? "?" + q : "") + location.hash);
  }
  var p = new URLSearchParams(location.search);
  ["gb", "g", "shop", "sort"].forEach(function (n) {
    var el = form.querySelector('[name="' + n + '"]');
    if (el && p.get(n) && el.querySelector('option[value="' + CSS.escape(p.get(n)) + '"]')) el.value = p.get(n);
  });
  form.addEventListener("change", function () { apply(true); });
  if (moreBtn) moreBtn.addEventListener("click", function () { shown += PAGE; apply(false); });
  apply(true);
})();
