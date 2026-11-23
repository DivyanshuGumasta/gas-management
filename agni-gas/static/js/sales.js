// Sales list: period chips, search, four summary cards and invoice rows.
(function () {
  const $ = (id) => document.getElementById(id);
  const { esc, fmt } = UI;
  let range = "today", timer = 0, seq = 0;

  const iso = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  function dates() {
    const now = new Date();
    if (range === "today") return { from: iso(now), to: iso(now) };
    if (range === "7d") { const s = new Date(now); s.setDate(s.getDate() - 6); return { from: iso(s), to: iso(now) }; }
    if (range === "month") return { from: iso(new Date(now.getFullYear(), now.getMonth(), 1)), to: iso(now) };
    if (range === "custom") return { from: $("sl-from").value, to: $("sl-to").value };
    return {};
  }
  const BADGE = { paid: ["Paid", "badge-paid"], partial: ["Part paid", "badge-pending"], udhaar: ["Udhaar", "badge-udhaar"], cancelled: ["Cancelled", "badge-cancelled"] };

  function row(s) {
    const [text, cls] = BADGE[s.status] || ["", ""];
    const when = (range === "today" ? "" : Cust.date(s.date) + " · ") + s.time;
    const due = s.status === "partial" ? '<small class="sl-due">Due ' + esc(fmt.money(s.due)) + "</small>" : "";
    return '<a class="row sl-row' + (s.status === "cancelled" ? " is-cancelled" : "") + '" href="/sales/' + s.id + '">' +
      '<span class="avatar">' + esc(fmt.initials(s.customer)) + "</span>" +
      '<span class="row-name"><b>' + esc(s.customer) + "</b><small>" + esc(s.number) + " · " + esc(when) + " · " + esc(s.label) + "</small></span>" +
      '<span class="sl-amt"><b>' + esc(fmt.money(s.sales_value == null ? s.total : s.sales_value)) + "</b>" +
      (Number(s.deposit_received || 0) || Number(s.deposit_refunded || 0) ? '<small class="sl-deposit-note">Deposit net ' + esc(fmt.money(Number(s.deposit_received || 0) - Number(s.deposit_refunded || 0))) + '</small>' : '') +
      due + '<span class="badge ' + cls + '">' + text + "</span></span></a>";
  }

  async function load() {
    const my = ++seq, d = dates();
    const p = new URLSearchParams({ q: $("sl-search").value.trim() });
    if (d.from) p.set("from", d.from);
    if (d.to) p.set("to", d.to);
    try {
      const r = await Api.get("/api/sales?" + p);
      if (my !== seq) return;
      document.querySelector("#sl-error").hidden = true;
      $("sl-total").textContent = fmt.money(r.summary.total);
      $("sl-bills").textContent = r.summary.bills + (r.summary.bills === 1 ? " bill" : " bills");
      $("sl-cyl").textContent = r.summary.cylinders;
      $("sl-udhaar").textContent = fmt.money(r.summary.udhaar);
      $("sl-deposits").textContent = fmt.money(r.summary.deposits_held_change == null ? 0 : r.summary.deposits_held_change);
      $("sl-list").innerHTML = r.sales.length ? r.sales.map(row).join("")
        : '<div class="state"><b>No sales found</b><span>Nothing in this period yet.</span><button class="btn btn-orange" type="button" data-go-new>New sale</button></div>';
    } catch (e) {
      if (my !== seq) return;
      const box = $("sl-error"); box.querySelector("span").textContent = "Could not load sales. " + e.message; box.hidden = false;
    }
  }

  $("sl-chips").addEventListener("click", (e) => {
    const b = e.target.closest(".chip"); if (!b) return;
    range = b.dataset.range;
    document.querySelectorAll("#sl-chips .chip").forEach((c) => c.classList.toggle("on", c === b));
    $("sl-custom").hidden = range !== "custom";
    if (range !== "custom" || ($("sl-from").value && $("sl-to").value)) load();
  });
  ["sl-from", "sl-to"].forEach((id) => $(id).addEventListener("change", load));
  $("sl-search").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(load, 250); });
  $("sl-retry").addEventListener("click", load);

  /* ---------- the two tabs: Sales history | New sale ---------- */
  let newOpened = false;
  function setTab(name, remember = true) {
    const isNew = name === "new";
    $("sl-tab-history").classList.toggle("on", !isNew);
    $("sl-tab-new").classList.toggle("on", isNew);
    $("sl-view-history").hidden = isNew;
    $("sl-view-new").hidden = !isNew;
    $("sl-head-actions").hidden = isNew;                 // Export belongs to the history tab
    if (remember) {
      const params = new URLSearchParams(location.search);
      if (isNew) params.set("tab", "new"); else params.delete("tab");
      const query = params.toString();
      history.replaceState(null, "", "/sales" + (query ? "?" + query : ""));
    }
    if (isNew && !newOpened) { newOpened = true; window.SalesNew.open(); }
    if (!isNew) load();
  }
  $("sl-tab-history").addEventListener("click", () => setTab("history"));
  $("sl-tab-new").addEventListener("click", () => setTab("new"));
  document.addEventListener("click", (e) => { if (e.target.closest("[data-go-new]")) setTab("new"); });
  window.SalesTabs = { show: setTab };
  Cust.renderIcons(); if (window.Icons) Icons.render(document);
  if (new URLSearchParams(location.search).get("tab") === "new") setTab("new", false); else load();
})();