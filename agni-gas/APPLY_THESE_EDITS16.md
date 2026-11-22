# APPLY_THESE_EDITS16 — v0.5.1: Sales as two tabs + give the deposit back

Paths are relative to `agni-gas/`. Needs edits 15 applied. **A** = replace 5 whole files (select all, paste), **B** = small edits, **C** = delete 1 file.

## What changed
* **Sales page now has two tabs like Customers:** *Sales history* | *New sale*. The extra "New Sale" button in the page header is gone (the top-bar one stays). Export only shows on the history tab. The empty-list button and every old link (`/sales/new`, Quick Add, Home, customer page) now open the *New sale* tab. After saving you land on the receipt; its back arrow returns to the history tab.
* **Give back the deposit to a customer:** when you add "Empty in" for a chosen customer, a green *Give back the deposit* box appears on that cylinder card (amount per cylinder pre-filled from its security, editable). The bill shows *Deposit given back* and the total drops by that amount. If the deposit is more than they are buying, the total turns into **"You give back Rs X"** (a payout from cash or bank), and the receipt says *Given back to customer* / *Paid out*. No GST is charged on the deposit.
* The fake backend and `SALES_API_CONTRACT.md` (sent again) know about the deposit.

---

# A. REPLACE THESE WHOLE FILES

## A1. `templates/sales.html` — delete everything in the file and paste this
```html
{% extends "base.html" %}
{% block content %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/customers.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/suppliers_purchases.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/sales.css') }}">

<div id="sl-error" class="banner banner-error" hidden><span></span><button class="btn btn-ghost btn-sm" id="sl-retry" type="button">Retry</button></div>

<div class="page-head">
  <h1 class="page-title">Sales</h1>
  <div class="head-actions" id="sl-head-actions">
    <div class="menu-wrap" data-scope="sales">
      <button class="btn btn-white" data-menu-toggle type="button"><i data-cicon="download"></i>Export<i data-cicon="chevronDown"></i></button>
      <div class="menu" hidden>
        <button type="button" data-export="pdf">Download PDF</button>
        <button type="button" data-export="excel">Download Excel</button>
      </div>
    </div>
  </div>
</div>

<div class="tabs" role="tablist">
  <button class="tab on" id="sl-tab-history" role="tab" type="button">Sales history</button>
  <button class="tab" id="sl-tab-new" role="tab" type="button">New sale</button>
</div>

<!-- ============ Sales history ============ -->
<section id="sl-view-history">
<div class="toolbar">
  <div class="chips" id="sl-chips">
    <button class="chip on" data-range="today" type="button">Today</button>
    <button class="chip" data-range="7d" type="button">Last 7 days</button>
    <button class="chip" data-range="month" type="button">This month</button>
    <button class="chip" data-range="all" type="button">All</button>
    <button class="chip" data-range="custom" type="button">Custom</button>
  </div>
  <label class="search"><i data-icon="search"></i>
    <input type="search" id="sl-search" placeholder="Search customer or bill no." autocomplete="off"></label>
</div>
<div class="date-filter sl-custom" id="sl-custom" hidden>
  <span>From</span><input type="date" id="sl-from"><span>To</span><input type="date" id="sl-to">
</div>

<div class="sl-stats">
  <div class="sl-stat"><small>Sales</small><b id="sl-total">Rs 0</b><span id="sl-bills">0 bills</span></div>
  <div class="sl-stat"><small>Cylinders</small><b id="sl-cyl">0</b><span>full sold</span></div>
  <div class="sl-stat"><small>Udhaar</small><b class="red" id="sl-udhaar">Rs 0</b><span>on these bills</span></div>
</div>

<div class="list-card" id="sl-list"></div>
</section>

<!-- ============ New sale ============ -->
<section id="sl-view-new" hidden>
<div id="sn-error" class="banner banner-error" hidden><span id="sn-error-text"></span></div>

<form id="sn-form" novalidate>
  <div class="pn-layout">
    <section class="pn-left">
      <div class="sn-customer-row">
        <button class="cust-pick pn-supplier-picker" id="sn-cust-pick" type="button">
          <span class="avatar" id="sn-cust-avatar">W</span>
          <span class="cp-main"><small>Customer</small><b id="sn-cust-name">Walk-in customer</b><small id="sn-cust-meta">Cash sale, no udhaar</small></span>
          <span id="sn-cust-balance" class="bal bal-clear"></span>
          <span class="pn-picker-chevron"><i data-cicon="chevronsUpDown"></i></span>
        </button>
        <button class="btn btn-white" id="sn-add-cust" type="button"><i data-icon="userPlus"></i>Add customer</button>
      </div>
      <button class="link-btn sn-walkin" id="sn-walkin" type="button" hidden>Use walk-in customer instead</button>

      <div class="pn-section-head"><h2>What are you selling?</h2><small>Tap price to change</small></div>
      <div class="pn-items" id="sn-cylinders"><div class="pn-empty">Loading cylinders…</div></div>

      <section class="pn-other-panel" id="sn-items-panel" hidden>
        <div class="pn-section-head"><h2>Other items</h2><small>Tap price to change</small></div>
        <div class="sn-goods" id="sn-goods"></div>
      </section>
    </section>

    <aside class="pn-right">
      <div class="pn-section-head"><h2>Payment</h2></div>
      <div class="pn-panel pn-payment-panel">
        <div class="two">
          <label class="field"><span>Discount (optional)</span><div class="pn-amount"><i>Rs</i><input class="input" id="sn-discount" inputmode="decimal" placeholder="0"></div></label>
          <label class="field"><span>Date</span><input class="input" id="sn-date" type="date"></label>
        </div>
        <div class="two">
          <label class="field"><span>Payment</span>
            <select class="select" id="sn-payment"><option value="paid">Paid</option><option value="partial">Part paid</option><option value="credit">Udhaar (pay later)</option></select></label>
          <label class="field"><span>Received in</span>
            <select class="select" id="sn-received"><option value="cash">Cash in hand</option><option value="bank">Bank / UPI</option></select></label>
        </div>
        <label class="field"><span id="sn-paid-label">Amount paid now</span><div class="pn-amount"><i>Rs</i><input class="input" id="sn-paid" inputmode="decimal" placeholder="0" disabled></div>
          <small class="hint" id="sn-pay-hint">Walk-in sales are cash only. Select a customer to give udhaar.</small></label>
        <div class="two">
          <label class="field"><span>GST rate (%)</span><div class="pn-suffix-input"><input class="input" id="sn-gst" type="number" min="0" max="100" step="0.01" value="0"><i>%</i></div></label>
          <label class="field"><span>GST amount</span><div class="pn-amount pn-readonly"><i>Rs</i><input class="input" id="sn-gst-amount" value="0.00" readonly></div></label>
        </div>
        <label class="field"><span>Note (optional)</span><textarea class="textarea" id="sn-note" maxlength="500"></textarea></label>
        <div class="pn-totals">
          <div><span>Subtotal</span><b id="sn-subtotal">Rs 0</b></div>
          <div class="sn-disc-row" id="sn-disc-row" hidden><span>Discount</span><b id="sn-disc-show">- Rs 0</b></div>
          <div><span>GST (<i id="sn-gst-label">0</i>%)</span><b id="sn-gst-show">Rs 0</b></div>
          <div class="sn-back-row" id="sn-back-row" hidden><span>Deposit given back</span><b id="sn-back-show">- Rs 0</b></div>
          <div class="pn-grand"><span id="sn-total-label">Total (incl. GST)</span><b id="sn-total">Rs 0</b></div>
          <div class="sn-due-row" id="sn-due-row" hidden><span>Udhaar on this bill</span><b id="sn-due">Rs 0</b></div>
        </div>
        <button class="btn btn-orange btn-block pn-save" id="sn-save" type="submit" disabled><i data-cicon="check"></i>Save sale</button>
      </div>
    </aside>
  </div>
</form>
</section>
{% endblock %}
{% block scripts %}
<script src="{{ url_for('static', filename='js/customers_common.js') }}"></script>
<script src="{{ url_for('static', filename='js/sales_new.js') }}"></script>
<script src="{{ url_for('static', filename='js/sales.js') }}"></script>
{% endblock %}
```

## A2. `static/js/sales.js` — delete everything in the file and paste this
```javascript
// Sales list: period chips, search, three summary cards and one row per bill.
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
      '<span class="sl-amt"><b class="strike">' + esc(fmt.money(s.total)) + "</b>" + due + '<span class="badge ' + cls + '">' + text + "</span></span></a>";
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
    if (remember) history.replaceState(null, "", isNew ? "/sales?tab=new" : "/sales");
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
```

## A3. `static/js/sales_new.js` — delete everything in the file and paste this
```javascript
// New sale. Reads real cylinder stock and customers; saves through POST /api/sales (see SALES_API_CONTRACT.md).
(function () {
  const $ = (id) => document.getElementById(id);
  const { esc, fmt } = UI;
  const state = { customer: null, cylinders: [], goods: [], special: {}, saving: false };
  // per size: { refill, new_full, new_empty, empty_in, rate, security, open, dep_back, dep_each }   per item: { qty, rate }
  const cyl = {}, good = {};

  const cents = (v) => { const n = Number(String(v).replace(/,/g, "")); return Number.isFinite(n) && n > 0 ? Math.round(n * 100) : 0; };
  const rs = (c) => fmt.money((c / 100).toFixed(2));
  const num = (v) => { const n = Number(v); return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0; };
  const showError = (m) => { $("sn-error-text").textContent = m || ""; $("sn-error").hidden = !m; if (m) window.scrollTo({ top: 0, behavior: "smooth" }); };

  /* ---------- prices ---------- */
  function listRate(c) {          // what this customer pays for a full cylinder refill
    if (state.special[c.id] != null) return state.special[c.id];
    return state.customer && state.customer.type === "wholesale" ? c.wholesale_price : c.sale_price;
  }
  function itemRate(it) { return state.customer && state.customer.type === "wholesale" && Number(it.wholesale_price) ? it.wholesale_price : it.sale_price; }
  function resetRates() {
    state.cylinders.forEach((c) => { cyl[c.id].rate = listRate(c); });
    state.goods.forEach((g) => { good[g.id].rate = itemRate(g); });
    renderAll();
  }

  /* ---------- amounts ---------- */
  function cylAmount(c) {
    const s = cyl[c.id], rate = cents(s.rate), dep = cents(s.security);
    return s.refill * rate + s.new_full * (rate + dep) + s.new_empty * dep;
  }
  const goodAmount = (g) => Math.round(Number(good[g.id].qty || 0) * cents(good[g.id].rate));
  // security deposit handed back to the customer for the empties they return (only with a chosen customer)
  const depBack = (c) => { const s = cyl[c.id]; return state.customer && s.dep_back && s.empty_in ? s.empty_in * cents(s.dep_each) : 0; };
  function totals() {
    const sub = state.cylinders.reduce((a, c) => a + cylAmount(c), 0) + state.goods.reduce((a, g) => a + goodAmount(g), 0);
    const disc = Math.min(cents($("sn-discount").value), sub);
    const pct = Math.min(100, Math.max(0, Number($("sn-gst").value) || 0));
    const gst = Math.round((sub - disc) * pct / 100);
    const back = state.cylinders.reduce((a, c) => a + depBack(c), 0);
    return { sub, disc, pct, gst, back, total: sub - disc + gst - back };
  }
  const anything = () => state.cylinders.some((c) => { const s = cyl[c.id]; return s.refill || s.new_full || s.new_empty || s.empty_in; }) || state.goods.some((g) => Number(good[g.id].qty) > 0);

  /* ---------- cylinder cards ---------- */
  function stepper(field, id, value, minusCls, plusCls) {
    return '<div class="pn-stepper"><button type="button" class="pn-step ' + minusCls + '" data-step="-1" data-f="' + field + '" data-id="' + id + '" aria-label="Less">−</button>' +
      '<input type="number" min="0" step="1" inputmode="numeric" value="' + value + '" data-f="' + field + '" data-id="' + id + '">' +
      '<button type="button" class="pn-step ' + plusCls + '" data-step="1" data-f="' + field + '" data-id="' + id + '" aria-label="More">+</button></div>';
  }
  function cylinderCard(c) {
    const s = cyl[c.id];
    const used = s.refill + s.new_full;
    const over = used > c.full;
    return '<article class="pn-item sn-card" data-cid="' + c.id + '">' +
      '<div class="sn-head"><span class="pn-cylinder-icon">▣</span><div class="pn-item-title"><b>' + esc(c.name) + "</b><small>Full: " + c.full + " · Empty: " + c.empty + "</small></div>" +
      '<button type="button" class="sn-price" data-edit-price="' + c.id + '" title="Tap to change the price">Rs ' + esc(fmt.money(s.rate).replace(/^Rs\s?/, "")) + ' <i class="sn-pencil">✎</i></button></div>' +
      '<div class="pn-qty-line"><div><b>Refill</b><small>Full cylinder, the empty comes back</small></div>' + stepper("refill", c.id, s.refill, "pn-step-minus", "pn-step-plus") + "</div>" +
      '<div class="pn-qty-line"><div><b>Empty in</b><small>Customer returns an empty</small></div>' + stepper("empty_in", c.id, s.empty_in, "pn-step-minus", "sn-step-orange") + "</div>" +
      (s.empty_in && state.customer ? '<label class="sn-depback"><input type="checkbox" data-depback="' + c.id + '"' + (s.dep_back ? " checked" : "") + '><span><b>Give back the deposit</b><small>Customer gets the security back for the ' + s.empty_in + " empty cylinder(s)</small></span>" +
        (s.dep_back ? '<span class="pn-rate sn-dep-each"><span><i>Rs</i><input type="number" min="0" step="0.01" value="' + esc(s.dep_each) + '" data-f="dep_each" data-id="' + c.id + '"></span></span>' : "") + "</label>" : "") +
      (over ? '<p class="sn-warn">Only ' + c.full + " full cylinder(s) in stock.</p>" : "") +
      '<button type="button" class="pn-bought-toggle sn-toggle' + (s.open ? " on" : "") + '" data-toggle="' + c.id + '">Sell with cylinder or empty ' + (s.open ? "▴" : "▾") + "</button>" +
      (s.open ?
        '<div class="sn-more"><label class="pn-rate sn-dep"><small>Security (per cylinder)</small><span><i>Rs</i><input type="number" min="0" step="0.01" value="' + esc(s.security) + '" data-f="security" data-id="' + c.id + '"></span></label>' +
        '<div class="pn-qty-line"><div><b>New full cylinder</b><small>Gas + cylinder: price + security</small></div>' + stepper("new_full", c.id, s.new_full, "pn-step-minus", "pn-step-plus") + "</div>" +
        '<div class="pn-qty-line"><div><b>Empty cylinder only</b><small>No gas: security only</small></div>' + stepper("new_empty", c.id, s.new_empty, "pn-step-minus", "pn-step-plus") + "</div></div>" : "") +
      '<div class="pn-item-footer"><span>Amount</span><b data-amt="' + c.id + '">' + rs(cylAmount(c)) + "</b></div></article>";
  }
  function goodCard(g) {
    const s = good[g.id];
    return '<article class="sn-good" data-gid="' + g.id + '"><div class="pn-item-title"><b>' + esc(g.name) + "</b><small>In stock: " + esc(g.qty) + " " + esc(g.unit) + "</small></div>" +
      '<button type="button" class="sn-price" data-edit-gprice="' + g.id + '">Rs ' + esc(fmt.money(s.rate).replace(/^Rs\s?/, "")) + ' <i class="sn-pencil">✎</i></button>' +
      '<label class="sn-qty"><small>Quantity (' + esc(g.unit) + ')</small><input type="number" min="0" step="any" inputmode="decimal" value="' + (s.qty || "") + '" placeholder="0" data-gqty="' + g.id + '"></label>' +
      '<b class="sn-gamt" data-gamt="' + g.id + '">' + rs(goodAmount(g)) + "</b></article>";
  }
  function renderCylinders() {
    $("sn-cylinders").innerHTML = state.cylinders.length ? state.cylinders.map(cylinderCard).join("")
      : '<div class="pn-empty">No cylinder sizes yet. Add them in Stock &amp; Price first.</div>';
  }
  function renderGoods() {
    $("sn-items-panel").hidden = !state.goods.length;
    $("sn-goods").innerHTML = state.goods.map(goodCard).join("");
  }
  const renderAll = () => { renderCylinders(); renderGoods(); update(); };

  /* ---------- payment panel ---------- */
  function update() {
    const t = totals();
    state.cylinders.forEach((c) => { const el = document.querySelector('[data-amt="' + c.id + '"]'); if (el) el.textContent = rs(cylAmount(c)); });
    state.goods.forEach((g) => { const el = document.querySelector('[data-gamt="' + g.id + '"]'); if (el) el.textContent = rs(goodAmount(g)); });
    $("sn-subtotal").textContent = rs(t.sub);
    $("sn-disc-row").hidden = !t.disc; $("sn-disc-show").textContent = "- " + rs(t.disc);
    $("sn-gst-label").textContent = t.pct; $("sn-gst-show").textContent = rs(t.gst); $("sn-gst-amount").value = (t.gst / 100).toFixed(2);
    $("sn-back-row").hidden = !t.back; $("sn-back-show").textContent = "- " + rs(t.back);
    $("sn-total-label").textContent = t.total < 0 ? "You give back" : "Total (incl. GST)";
    $("sn-total").textContent = rs(Math.abs(t.total));
    const pay = $("sn-payment");
    [...pay.options].forEach((o) => { if (o.value !== "paid") o.disabled = !state.customer || t.total <= 0; });
    if (t.total <= 0) pay.value = "paid";                     // nothing to owe when you are giving money back
    const mode = pay.value, paid = $("sn-paid");
    paid.disabled = mode !== "partial";
    if (mode === "paid") paid.value = t.total ? (Math.abs(t.total) / 100).toFixed(2) : "";
    if (mode === "credit") paid.value = "";
    $("sn-paid-label").textContent = t.total < 0 ? "Amount given back now" : "Amount paid now";
    if (state.customer && t.total < 0) $("sn-pay-hint").textContent = state.customer.name + " gets " + rs(-t.total) + " back.";
    else applyCustomerRules();
    const due = mode === "paid" ? 0 : t.total - (mode === "credit" ? 0 : cents(paid.value));
    $("sn-due-row").hidden = !(state.customer && due > 0); $("sn-due").textContent = rs(Math.max(0, due));
    $("sn-save").disabled = state.saving || !anything();
    document.querySelectorAll(".sn-warn").forEach(() => {});
    $("sn-save").disabled = $("sn-save").disabled || state.cylinders.some((c) => cyl[c.id].refill + cyl[c.id].new_full > c.full);
  }
  function applyCustomerRules() {
    const walkin = !state.customer, pay = $("sn-payment");
    if (walkin) pay.value = "paid";
    $("sn-pay-hint").textContent = walkin ? "Walk-in sales are cash only. Select a customer to give udhaar."
      : "Udhaar is added to " + state.customer.name + "'s balance.";
  }

  /* ---------- customer ---------- */
  async function setCustomer(c) {
    state.customer = c || null; state.special = {};
    $("sn-cust-avatar").textContent = c ? fmt.initials(c.name) : "W";
    $("sn-cust-name").textContent = c ? c.name : "Walk-in customer";
    $("sn-cust-meta").textContent = c ? ((c.type === "wholesale" ? "Wholesale" : "Retail") + (c.phone ? " · " + c.phone : "")) : "Cash sale, no udhaar";
    const b = Number(c && c.balance) || 0, tag = $("sn-cust-balance");
    tag.className = "bal " + (b > 0 ? "bal-red" : b < 0 ? "bal-green" : "bal-clear");
    tag.textContent = !c ? "" : b > 0 ? fmt.money(b) + " · To receive" : b < 0 ? fmt.money(-b) + " · Paid extra" : "Clear";
    $("sn-walkin").hidden = !c;
    applyCustomerRules();
    if (c) {
      try {
        (await Api.get("/api/customers/" + c.id + "/prices")).forEach((p) => { if (p.special_price != null) state.special[p.cylinder_type_id] = p.special_price; });
      } catch (_) { /* default prices are fine */ }
    }
    resetRates();
  }

  /* ---------- events ---------- */
  function inlinePrice(btn, get, set) {
    const input = document.createElement("input");
    input.className = "sn-price-input"; input.type = "number"; input.min = "0"; input.step = "0.01"; input.value = get();
    btn.replaceWith(input); input.focus(); input.select();
    const done = () => { set(input.value === "" ? get() : input.value); renderAll(); };
    input.addEventListener("blur", done);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); input.blur(); } });
  }
  document.addEventListener("click", (e) => {
    const step = e.target.closest("[data-step]");
    if (step) {
      const s = cyl[step.dataset.id], f = step.dataset.f;
      s[f] = Math.max(0, s[f] + Number(step.dataset.step));
      renderCylinders(); update(); return;
    }
    const tg = e.target.closest("[data-toggle]");
    if (tg) { cyl[tg.dataset.toggle].open = !cyl[tg.dataset.toggle].open; renderCylinders(); return; }
    const pr = e.target.closest("[data-edit-price]");
    if (pr) { const id = pr.dataset.editPrice; inlinePrice(pr, () => cyl[id].rate, (v) => { cyl[id].rate = v; }); return; }
    const gp = e.target.closest("[data-edit-gprice]");
    if (gp) { const id = gp.dataset.editGprice; inlinePrice(gp, () => good[id].rate, (v) => { good[id].rate = v; }); }
  });
  $("sn-cylinders").addEventListener("change", (e) => {
    const t = e.target; if (!t.dataset.f) return;
    const s = cyl[t.dataset.id];
    s[t.dataset.f] = (t.dataset.f === "security" || t.dataset.f === "dep_each") ? t.value : num(t.value);
    renderCylinders(); update();
  });
  $("sn-cylinders").addEventListener("change", (e) => {
    const id = e.target.dataset.depback; if (!id) return;
    cyl[id].dep_back = e.target.checked; renderCylinders(); update();
  });
  $("sn-goods").addEventListener("input", (e) => {
    const id = e.target.dataset.gqty; if (!id) return;
    good[id].qty = e.target.value; update();
  });
  ["sn-discount", "sn-gst", "sn-paid", "sn-payment"].forEach((id) => $(id).addEventListener("input", update));
  $("sn-payment").addEventListener("change", update);
  $("sn-discount").addEventListener("input", (e) => Cust.cleanMoneyInput && Cust.cleanMoneyInput(e.target));
  $("sn-cust-pick").addEventListener("click", () => UI.selectCustomer(setCustomer));
  $("sn-walkin").addEventListener("click", () => setCustomer(null));
  $("sn-add-cust").addEventListener("click", () => Cust.openCustomerForm({ onSaved: (res) => setCustomer(res && res.id ? res : null) }));

  $("sn-form").addEventListener("submit", async (e) => {
    e.preventDefault(); showError("");
    if (state.saving) return;
    state.saving = true; update();
    const lines = state.cylinders.map((c) => ({ cylinder_type_id: c.id, refill: cyl[c.id].refill, new_full: cyl[c.id].new_full,
      new_empty: cyl[c.id].new_empty, empty_in: cyl[c.id].empty_in, deposit_back: !!(state.customer && cyl[c.id].dep_back && cyl[c.id].empty_in), deposit_each: String(cyl[c.id].dep_each), rate: String(cyl[c.id].rate), security: String(cyl[c.id].security) }))
      .filter((l) => l.refill || l.new_full || l.new_empty || l.empty_in);
    const items = state.goods.filter((g) => Number(good[g.id].qty) > 0).map((g) => ({ item_id: g.id, qty: String(good[g.id].qty), rate: String(good[g.id].rate) }));
    try {
      const r = await Api.post("/api/sales", {
        customer_id: state.customer ? state.customer.id : null, date: $("sn-date").value, lines, items,
        discount: $("sn-discount").value.trim(), gst_percent: $("sn-gst").value, payment: $("sn-payment").value,
        received_in: $("sn-received").value, paid: $("sn-paid").value.trim(), note: $("sn-note").value.trim() });
      window.location.href = "/sales/" + r.id + "?new=1";
    } catch (ex) {
      state.saving = false; update(); showError(ex.message || "Could not save the sale.");
    }
  });

  /* ---------- start ---------- */
  async function start() {
    $("sn-date").value = Cust.today(); $("sn-date").max = Cust.today();
    Cust.renderIcons(); if (window.Icons) Icons.render(document);
    try {
      const stock = await Api.get("/api/stock");
      state.cylinders = stock.cylinders; state.goods = stock.items;
      state.cylinders.forEach((c) => { cyl[c.id] = { refill: 0, new_full: 0, new_empty: 0, empty_in: 0, rate: c.sale_price, security: c.security, open: false, dep_back: false, dep_each: c.security }; });
      state.goods.forEach((g) => { good[g.id] = { qty: "", rate: g.sale_price }; });
    } catch (ex) { showError("Could not load stock. " + ex.message); $("sn-cylinders").innerHTML = ""; return; }
    applyCustomerRules(); renderAll();
    const pre = new URLSearchParams(location.search).get("customer");
    if (pre) { try { await setCustomer(await Api.get("/api/customers/" + pre)); } catch (_) { /* stay walk-in */ } }
  }
  window.SalesNew = { open: start };    // sales.js calls this the first time the New sale tab is opened
})();
```

## A4. `static/js/sale_detail.js` — delete everything in the file and paste this
```javascript
// Sale receipt: print, WhatsApp, cancel bill.
(function () {
  const $ = (id) => document.getElementById(id);
  const { esc, fmt } = UI;
  const sid = Number(location.pathname.split("/").pop());
  const justSaved = new URLSearchParams(location.search).get("new") === "1";
  let sale = null;

  const KIND = { deposit_back: "Deposit given back", refill: "Refill", new_full: "New cylinder + gas", new_empty: "Empty cylinder", empty_in: "Empty received", item: "" };
  const MODE = { cash: "Cash in hand", bank: "Bank / UPI" };
  const showError = (m) => { const b = $("rc-error"); b.querySelector("span").textContent = m || ""; b.hidden = !m; };

  function lineRow(l) {
    const label = l.kind === "item" ? esc(l.name) + (l.detail ? " <small>(" + esc(l.detail) + ")</small>" : "")
      : esc(l.name) + " <small>" + esc(KIND[l.kind] || "") + "</small>";
    const free = l.kind === "empty_in", back = l.kind === "deposit_back";
    return "<tr><td>" + label + '</td><td class="num">' + esc(l.qty) + '</td><td class="num">' + (free ? "—" : esc(fmt.money(l.rate))) +
      '</td><td class="num"><b>' + (free ? "—" : (back ? "- " : "") + esc(fmt.money(l.amount))) + "</b></td></tr>";
  }
  function sumRow(label, value, cls) { return '<div class="' + (cls || "") + '"><span>' + label + "</span><b>" + esc(fmt.money(value)) + "</b></div>"; }

  function render() {
    const cancelled = sale.status === "cancelled";
    $("rc-main").hidden = false;
    $("rc-title").textContent = "Sale " + sale.number;
    $("rc-sub").textContent = Cust.date(sale.date) + " · " + sale.time;
    $("rc-number").textContent = sale.number;
    $("rc-date").textContent = Cust.date(sale.date) + ", " + sale.time;
    $("rc-customer").textContent = sale.customer ? sale.customer.name : "Walk-in customer";
    $("rc-lines").innerHTML = sale.lines.map(lineRow).join("");
    const rows = [sumRow("Subtotal", sale.subtotal)];
    if (Number(sale.discount)) rows.push("<div><span>Discount</span><b>- " + esc(fmt.money(sale.discount)) + "</b></div>");
    rows.push(sumRow("GST (" + sale.gst_percent + "%)", sale.gst));
    if (Number(sale.deposit_back)) rows.push("<div><span>Deposit given back</span><b>- " + esc(fmt.money(sale.deposit_back)) + "</b></div>");
    const out = Number(sale.total) < 0;                      // more deposit handed back than the customer bought
    rows.push(sumRow(out ? "Given back to customer" : "Total (incl. GST)", out ? String(-Number(sale.total)) : sale.total, "rc-total"));
    rows.push(sumRow((out ? "Paid out (" : "Paid (") + (MODE[sale.received_in] || "Cash in hand") + ")", out ? String(-Number(sale.paid)) : sale.paid));
    if (Number(sale.due) > 0 && !cancelled) rows.push(sumRow("Udhaar (to pay)", sale.due, "rc-due"));
    $("rc-sums").innerHTML = rows.join("");
    $("rc-saved").hidden = !(justSaved && !cancelled);
    $("rc-void").hidden = !cancelled;
    $("rc-stamp").hidden = !cancelled;
    $("rc-cancel").hidden = cancelled;
    $("rc-paper").classList.toggle("is-void", cancelled);
    Cust.renderIcons(); if (window.Icons) Icons.render(document);
  }

  async function load() {
    showError("");
    try { sale = await Api.get("/api/sales/" + sid); render(); }
    catch (e) { $("rc-main").hidden = true; showError("Could not load this sale. " + e.message); }
  }

  function whatsappText() {
    const lines = sale.lines.filter((l) => l.kind !== "empty_in").map((l) => "• " + l.qty + " x " + l.name + (l.kind === "item" ? "" : " (" + (KIND[l.kind] || "").toLowerCase() + ")") + " = " + fmt.money(l.amount));
    return ["*" + ($("rc-main").querySelector("[data-biz-name]").textContent || "Agni Gas Agency") + "*", "Receipt " + sale.number + " · " + Cust.date(sale.date), ""]
      .concat(lines, ["", "Total: " + fmt.money(sale.total), "Paid: " + fmt.money(sale.paid)],
        Number(sale.due) > 0 ? ["To pay: " + fmt.money(sale.due)] : [], ["", "Thank you!"]).join("\n");
  }
  $("rc-wa").addEventListener("click", () => {
    const digits = ((sale.customer && sale.customer.phone) || "").replace(/\D/g, "");
    const phone = digits.length === 10 ? "91" + digits : digits;     // 10-digit Indian numbers get +91
    window.open("https://wa.me/" + phone + "?text=" + encodeURIComponent(whatsappText()), "_blank", "noopener");
  });
  $("rc-print").addEventListener("click", () => window.print());
  $("rc-retry").addEventListener("click", load);
  $("rc-cancel").addEventListener("click", () => Cust.openConfirm({
    title: "Cancel this bill?", danger: true, confirmLabel: "Yes, cancel bill", cancelLabel: "Keep bill",
    message: "Stock goes back on the shelf and any udhaar on this bill is removed. The receipt stays on record, marked cancelled. This cannot be undone.",
    onConfirm: async () => { await Api.post("/api/sales/" + sid + "/cancel", {}); Cust.toast("Bill cancelled"); await load(); },
  }));
  load();
})();
```

## A5. `api/mock_sales.py` — delete everything in the file and paste this
```python
"""TEMPORARY fake Sales API so the Sales screens can be reviewed before the real backend exists.

Keeps sales in memory only (gone when the app closes) and NEVER changes stock or customer balances.
It reads the real customers and cylinder sizes. Delete this file (and `mock_sales` in api/__init__.py)
when the real Sales backend is added. Same URLs and JSON as SALES_API_CONTRACT.md.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

from db import get_db
from money import to_paise, to_rupees
from . import api_bp
from .util import ApiError, body

_SALES = []
_NEXT = [1]


def _p(v):
    return to_paise(v) if v not in (None, "") else 0


def _label(lines):
    parts = []
    for ln in lines:
        n = ln["qty"]
        if ln["kind"] in ("refill", "new_full"):
            parts.append(f"{n} x {ln['name']}")
        elif ln["kind"] == "item":
            parts.append(f"{n} {ln['name']}")
    if not parts:
        return "Empty returned, deposit given back" if any(ln["kind"] == "deposit_back" for ln in lines) else "Empty cylinders only"
    return " · ".join(parts)


def _add(customer, lines, day, hhmm, discount, gst_pct, status_pay, paid, received_in, note):
    back = sum(-ln["amount_paise"] for ln in lines if ln["kind"] == "deposit_back")      # deposit handed back (stored negative)
    subtotal = sum(ln["amount_paise"] for ln in lines if ln["kind"] != "deposit_back")
    discount = min(discount, subtotal)
    gst = int((Decimal(subtotal - discount) * Decimal(str(gst_pct)) / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    total = subtotal - discount + gst - back
    paid = total if (status_pay == "paid" or total <= 0) else (0 if status_pay == "credit" else paid)
    sid = _NEXT[0]
    _NEXT[0] += 1
    sale = {"id": sid, "number": f"S-{sid:05d}", "date": day, "time": hhmm, "customer": customer, "lines": lines,
            "subtotal": subtotal, "deposit_back": back, "discount": discount, "gst_percent": gst_pct, "gst": gst, "total": total, "paid": paid,
            "received_in": received_in, "note": note, "cancelled": False}
    _SALES.append(sale)
    return sale


def _status(s):
    if s["cancelled"]:
        return "cancelled"
    if s["paid"] >= s["total"]:
        return "paid"
    return "udhaar" if s["paid"] == 0 else "partial"


def _row(s):
    cyl = sum(ln["qty"] for ln in s["lines"] if ln["kind"] in ("refill", "new_full"))
    return {"id": s["id"], "number": s["number"], "date": s["date"], "time": s["time"],
            "customer": s["customer"]["name"] if s["customer"] else "Walk-in customer",
            "customer_id": s["customer"]["id"] if s["customer"] else None,
            "label": _label(s["lines"]), "cylinders": cyl, "total": to_rupees(s["total"]),
            "due": to_rupees(max(0, s["total"] - s["paid"])), "status": _status(s)}


def _seed():
    if _SALES:
        return
    db = get_db()
    ct = db.execute("SELECT id, name, sale_price_paise FROM cylinder_types WHERE active=1 ORDER BY sort_order LIMIT 3").fetchall()
    cust = db.execute("SELECT id, name, phone FROM customers WHERE active=1 ORDER BY id LIMIT 2").fetchall()
    today, y = date.today().isoformat(), (date.today() - timedelta(days=2)).isoformat()
    if ct:
        c = ct[-1]
        _add(None, [{"kind": "refill", "name": c["name"], "qty": 1, "rate_paise": c["sale_price_paise"], "amount_paise": c["sale_price_paise"]}],
             today, "10:23 AM", 0, 0, "paid", 0, "cash", None)
    if ct and cust:
        c = ct[0]
        amt = 2 * c["sale_price_paise"]
        _add({"id": cust[0]["id"], "name": cust[0]["name"], "phone": cust[0]["phone"]},
             [{"kind": "refill", "name": c["name"], "qty": 2, "rate_paise": c["sale_price_paise"], "amount_paise": amt}],
             y, "04:05 PM", 0, 0, "credit", 0, "cash", "Will pay on Friday")


@api_bp.get("/sales")
def sales_list():
    _seed()
    f, t = request.args.get("from"), request.args.get("to")
    q = (request.args.get("q") or "").strip().lower()
    out = [s for s in _SALES if (not f or s["date"] >= f) and (not t or s["date"] <= t)]
    if q:
        out = [s for s in out if q in s["number"].lower() or q in (s["customer"]["name"].lower() if s["customer"] else "walk-in customer")]
    out.sort(key=lambda s: (s["date"], s["id"]), reverse=True)
    live = [s for s in out if not s["cancelled"]]
    return jsonify({
        "summary": {"total": to_rupees(sum(s["total"] for s in live)), "bills": len(live),
                    "cylinders": sum(sum(ln["qty"] for ln in s["lines"] if ln["kind"] in ("refill", "new_full")) for s in live),
                    "udhaar": to_rupees(sum(max(0, s["total"] - s["paid"]) for s in live))},
        "sales": [_row(s) for s in out]})


def _find(sid):
    _seed()
    for s in _SALES:
        if s["id"] == sid:
            return s
    raise ApiError("Sale not found.", 404)


@api_bp.get("/sales/<int:sid>")
def sale_get(sid):
    s = _find(sid)
    return jsonify({
        "id": s["id"], "number": s["number"], "date": s["date"], "time": s["time"], "status": _status(s),
        "customer": s["customer"], "note": s["note"],
        "lines": [{"kind": ln["kind"], "name": ln["name"], "qty": ln["qty"], "rate": to_rupees(ln["rate_paise"]),
                   "amount": to_rupees(ln["amount_paise"]), "detail": ln.get("detail")} for ln in s["lines"]],
        "subtotal": to_rupees(s["subtotal"]), "deposit_back": to_rupees(s["deposit_back"]), "discount": to_rupees(s["discount"]), "gst_percent": s["gst_percent"],
        "gst": to_rupees(s["gst"]), "total": to_rupees(s["total"]), "paid": to_rupees(s["paid"]),
        "due": to_rupees(max(0, s["total"] - s["paid"])), "received_in": s["received_in"]})


@api_bp.post("/sales/<int:sid>/cancel")
def sale_cancel(sid):
    s = _find(sid)
    if s["cancelled"]:
        raise ApiError("This bill is already cancelled.", 409)
    s["cancelled"] = True
    return jsonify({"ok": True})


@api_bp.post("/sales")
def sale_create():
    _seed()
    data = body()
    db = get_db()
    customer = None
    if data.get("customer_id") not in (None, ""):
        c = db.execute("SELECT id, name, phone FROM customers WHERE id=? AND active=1", (data["customer_id"],)).fetchone()
        if not c:
            raise ApiError("Customer not found.", 404)
        customer = {"id": c["id"], "name": c["name"], "phone": c["phone"]}
    lines = []
    for ln in data.get("lines") or []:
        c = db.execute("SELECT * FROM cylinder_types WHERE id=? AND active=1", (ln.get("cylinder_type_id"),)).fetchone()
        if not c:
            raise ApiError("Unknown cylinder size.", 404)
        n = {k: int(ln.get(k) or 0) for k in ("refill", "new_full", "new_empty", "empty_in")}
        rate, dep = _p(ln.get("rate")), _p(ln.get("security"))
        if n["refill"] + n["new_full"] > c["full_qty"]:
            raise ApiError(f"{c['name']}: only {c['full_qty']} full cylinder(s) in stock.", 409)
        if n["refill"]:
            lines.append({"kind": "refill", "name": c["name"], "qty": n["refill"], "rate_paise": rate, "amount_paise": n["refill"] * rate, "detail": "Refill"})
        if n["new_full"]:
            lines.append({"kind": "new_full", "name": c["name"], "qty": n["new_full"], "rate_paise": rate + dep,
                          "amount_paise": n["new_full"] * (rate + dep), "detail": "New full cylinder (gas + deposit)"})
        if n["new_empty"]:
            lines.append({"kind": "new_empty", "name": c["name"], "qty": n["new_empty"], "rate_paise": dep,
                          "amount_paise": n["new_empty"] * dep, "detail": "Empty cylinder (deposit only)"})
        if n["empty_in"]:
            lines.append({"kind": "empty_in", "name": c["name"], "qty": n["empty_in"], "rate_paise": 0, "amount_paise": 0, "detail": "Empty received"})
            if ln.get("deposit_back"):
                if not customer:
                    raise ApiError("Select a customer to give the deposit back.", field="deposit_back")
                each = _p(ln.get("deposit_each"))
                lines.append({"kind": "deposit_back", "name": c["name"], "qty": n["empty_in"], "rate_paise": each,
                              "amount_paise": -n["empty_in"] * each, "detail": "Deposit given back"})
    for it in data.get("items") or []:
        row = db.execute("SELECT * FROM catalog_items WHERE id=? AND active=1", (it.get("item_id"),)).fetchone()
        if not row:
            raise ApiError("Unknown item.", 404)
        qty = Decimal(str(it.get("qty") or 0))
        rate = _p(it.get("rate"))
        if qty * 1000 > row["stock_qty_milli"]:
            raise ApiError(f"{row['name']}: not enough in stock.", 409)
        lines.append({"kind": "item", "name": row["name"], "qty": float(qty) if qty % 1 else int(qty), "rate_paise": rate,
                      "amount_paise": int((qty * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)), "detail": row["unit"]})
    if not any(ln["amount_paise"] or ln["kind"] == "empty_in" for ln in lines):
        raise ApiError("Add at least one cylinder or item.")
    mode = data.get("payment") or "paid"
    if mode not in ("paid", "partial", "credit"):
        raise ApiError("Choose how it was paid.", field="payment")
    if mode != "paid" and not customer:
        raise ApiError("Walk-in sales are cash only. Select a customer to give udhaar.", field="payment")
    received = data.get("received_in") or "cash"
    if received not in ("cash", "bank"):
        raise ApiError("Choose where the money was received.", field="received_in")
    discount = _p(data.get("discount"))
    gst_pct = float(data.get("gst_percent") or 0)
    if not 0 <= gst_pct <= 100:
        raise ApiError("GST must be between 0 and 100.", field="gst_percent")
    now = datetime.now()
    s = _add(customer, lines, data.get("date") or date.today().isoformat(), now.strftime("%I:%M %p"), discount, gst_pct,
             mode, _p(data.get("paid")), received, (data.get("note") or "").strip() or None)
    if mode == "partial" and not 0 < s["paid"] < s["total"]:
        _SALES.remove(s)
        raise ApiError("Amount paid now must be more than 0 and less than the total.", field="paid")
    return jsonify({"id": s["id"], "number": s["number"]}), 201
```

## A6. `static/css/sales.css` — paste at the very END of the file
```css
/* ---------- v0.5.1: give the deposit back ---------- */
.sn-depback { display: flex; align-items: center; gap: 9px; margin: 8px 0 2px; padding: 9px 10px; border-radius: 9px; background: #eff7f0; flex-wrap: wrap; }
.sn-depback input[type=checkbox] { accent-color: #2f8742; }
.sn-depback span:not(.pn-rate):not(.sn-dep-each) { flex: 1; min-width: 150px; }
.sn-depback b, .sn-depback small { display: block; }
.sn-depback b { font-size: 11px; }
.sn-depback small { font-size: 9px; color: var(--muted); margin-top: 2px; }
.sn-dep-each { width: 110px; }
.sn-back-row b, .sn-back-row span { color: var(--green); font-weight: 700; }
```

---

# B. SMALL EDITS

## B1. `templates/sale_detail.html` — "New Sale" button goes to the tab
**Find:**
```
<a class="btn btn-orange" href="/sales/new"><i data-icon="plus"></i>New Sale</a>
```
**Replace with:**
```
<a class="btn btn-orange" href="/sales?tab=new"><i data-icon="plus"></i>New Sale</a>
```

## B2. `app.py` — import `request`
**Find:**
```
from flask import Flask, redirect, render_template
```
**Replace with:**
```
from flask import Flask, redirect, render_template, request
```

## B3. `app.py` — remove the New Sale page line (it is a tab now)
**Find (delete this whole line):**
```
    "/sales/new": ("sales_new.html", "sales", "New Sale", ""),
```
**Replace with:** nothing.

## B4. `app.py` — old links to /sales/new still work (they open the tab)
**Find:**
```
    app.add_url_rule("/udhaar", "page_udhaar", lambda: redirect("/customers"))
```
**Replace with:**
```
    app.add_url_rule("/udhaar", "page_udhaar", lambda: redirect("/customers"))
    # "New sale" is the second tab on the Sales page; old links to /sales/new still work.
    app.add_url_rule("/sales/new", "page_sales_new", lambda: redirect(
        "/sales?tab=new" + ("&" + request.query_string.decode() if request.query_string else "")))
```

## B5. `tests/test_api.py` — `test_pages` (there is a live copy and a commented-out `#` copy; edit the one NOT starting with `#`)
**Find:**
```
        for url in ["/", "/sales", "/sales/new", "/sales/5", "/customers", "/customers/1",
```
**Replace with:**
```
        for url in ["/", "/sales", "/sales/5", "/customers", "/customers/1",
```
Then, a few lines below in the same test, **after** the line `self.assertEqual(self.client.get("/udhaar").status_code, 302)` add:
```
        self.assertEqual(self.client.get("/sales/new?customer=2").headers["Location"], "/sales?tab=new&customer=2")   # New sale is a tab now
```

---

# C. DELETE
`templates/sales_new.html` (its form now lives inside `templates/sales.html`).

---
## Things I decided
* The deposit box only appears for a **chosen customer** (a walk-in cannot hold a deposit). The amount is per cylinder and multiplies by the *Empty in* count.
* Udhaar / Part paid are switched off when the bill is a payout.
* Opening `/sales?tab=new` while you are on history keeps nothing of a half-filled form; switching tabs back and forth does keep it.
* Suite: still 40 tests, all passing; I also clicked through both tabs and a deposit-only return in a browser.
