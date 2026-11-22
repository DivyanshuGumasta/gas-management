# APPLY_THESE_EDITS15 — version 0.5: Sales screens (frontend only)

Paths are relative to `agni-gas/`. **A** = create 8 new files (paste the whole content). **B** = 2 small find/replace edits.
Needs v0.4.4+ (your current GitHub). Nothing here changes your database or stock.

## What you get
* **Sales** list: Today / Last 7 days / This month / All / Custom, search, 3 summary cards (Sales, Cylinders, Udhaar), one row per bill with a Paid / Part paid / Udhaar / Cancelled tag. Export button is the same placeholder as other pages.
* **New Sale** (like the design): customer card (Walk-in by default, pick a customer, or Add customer), a card per cylinder size with **tap-the-price-to-change**, **Refill**, **Empty in**, and the **"Sell with cylinder or empty"** drop-down (new full cylinder = price + security, empty cylinder only = security). Payment panel: discount, date, Paid / Part paid / Udhaar, received in cash or bank, amount paid now, GST, note, live totals. Prices start from the real Stock & Price (retail or wholesale by customer type, and a customer's own special price if set).
* **Other items** (gas pipe, stove...) can be sold on the same screen. This is not in the Figma; remove it if you do not want it.
* **Receipt** page: Print, WhatsApp (opens WhatsApp with the bill text, +91 added to 10-digit numbers), New Sale, **Cancel bill** with the confirm popup, and the red "CANCELLED" receipt.
* **Temporary fake backend** (`api/mock_sales.py`): so you can click everything now. It keeps sales **in memory only** (gone when you close the app) and never touches real stock or balances. It does check stock, GST, walk-in = cash only, etc., so the error messages show up. When we build the real backend we delete this one file and the one word in B1.

---

# A. NEW FILES

## A1. `templates/sales.html` (new file)
```html
{% extends "base.html" %}
{% block content %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/customers.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/sales.css') }}">

<div id="sl-error" class="banner banner-error" hidden><span></span><button class="btn btn-ghost btn-sm" id="sl-retry" type="button">Retry</button></div>

<div class="page-head">
  <h1 class="page-title">Sales</h1>
  <div class="head-actions">
    <div class="menu-wrap" data-scope="sales">
      <button class="btn btn-white" data-menu-toggle type="button"><i data-cicon="download"></i>Export<i data-cicon="chevronDown"></i></button>
      <div class="menu" hidden>
        <button type="button" data-export="pdf">Download PDF</button>
        <button type="button" data-export="excel">Download Excel</button>
      </div>
    </div>
    <a class="btn btn-orange" href="/sales/new"><i data-icon="plus"></i>New Sale</a>
  </div>
</div>

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
{% endblock %}
{% block scripts %}
<script src="{{ url_for('static', filename='js/customers_common.js') }}"></script>
<script src="{{ url_for('static', filename='js/sales.js') }}"></script>
{% endblock %}
```

## A2. `templates/sales_new.html` (new file)
```html
{% extends "base.html" %}
{% block content %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/customers.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/suppliers_purchases.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/sales.css') }}">

<div class="page-head sp-form-head">
  <div class="title-block"><h1 class="page-title">New Sale</h1></div>
  <a class="btn btn-white" href="/sales">Cancel</a>
</div>
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
        <label class="field"><span>Amount paid now</span><div class="pn-amount"><i>Rs</i><input class="input" id="sn-paid" inputmode="decimal" placeholder="0" disabled></div>
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
          <div class="pn-grand"><span>Total (incl. GST)</span><b id="sn-total">Rs 0</b></div>
          <div class="sn-due-row" id="sn-due-row" hidden><span>Udhaar on this bill</span><b id="sn-due">Rs 0</b></div>
        </div>
        <button class="btn btn-orange btn-block pn-save" id="sn-save" type="submit" disabled><i data-cicon="check"></i>Save sale</button>
      </div>
    </aside>
  </div>
</form>
{% endblock %}
{% block scripts %}
<script src="{{ url_for('static', filename='js/customers_common.js') }}"></script>
<script src="{{ url_for('static', filename='js/sales_new.js') }}"></script>
{% endblock %}
```

## A3. `templates/sale_detail.html` (new file)
```html
{% extends "base.html" %}
{% block content %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/customers.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/sales.css') }}">

<div id="rc-error" class="banner banner-error" hidden><span></span><button class="btn btn-ghost btn-sm" id="rc-retry" type="button">Retry</button></div>
<div id="rc-main" hidden>
  <div class="page-head">
    <div class="title-block">
      <a class="back-btn" href="/sales" aria-label="Back to sales"><i data-cicon="chevronLeft"></i></a>
      <div><h1 id="rc-title">Sale</h1><small id="rc-sub"></small></div>
    </div>
    <button class="btn btn-danger-outline" id="rc-cancel" type="button">⊘ Cancel bill</button>
  </div>

  <div class="rc-wrap">
    <div class="rc-banner rc-saved" id="rc-saved" hidden><i data-cicon="check"></i>Sale saved. Print or share the receipt.</div>
    <div class="rc-banner rc-void" id="rc-void" hidden>⊘ Bill cancelled. This receipt is no longer valid.</div>

    <article class="rc-paper" id="rc-paper">
      <div class="rc-stamp" id="rc-stamp" hidden>CANCELLED</div>
      <h2 class="rc-biz" data-biz-name>Agni Gas Agency</h2>
      <div class="rc-sep"></div>
      <div class="rc-kind">SALE RECEIPT</div>
      <div class="rc-sep"></div>
      <div class="rc-meta">
        <div><span>Receipt #</span><b id="rc-number"></b></div>
        <div><span>Date</span><b id="rc-date"></b></div>
        <div><span>Customer</span><b id="rc-customer"></b></div>
      </div>
      <div class="rc-sep"></div>
      <table class="rc-table">
        <thead><tr><th>Item</th><th class="num">Qty</th><th class="num">Rate</th><th class="num">Amount</th></tr></thead>
        <tbody id="rc-lines"></tbody>
      </table>
      <div class="rc-sep"></div>
      <div class="rc-sums" id="rc-sums"></div>
      <div class="rc-sep"></div>
      <p class="rc-thanks">Thank you!</p>
      <div class="rc-sep"></div>
      <p class="rc-credit">Developed by Divyanshu, Designed by Harsh</p>
    </article>

    <div class="rc-actions">
      <button class="btn btn-dark" id="rc-print" type="button">🖶 Print</button>
      <button class="btn btn-whatsapp" id="rc-wa" type="button">WhatsApp</button>
      <a class="btn btn-orange" href="/sales/new"><i data-icon="plus"></i>New Sale</a>
    </div>
  </div>
</div>
{% endblock %}
{% block scripts %}
<script src="{{ url_for('static', filename='js/customers_common.js') }}"></script>
<script src="{{ url_for('static', filename='js/sale_detail.js') }}"></script>
{% endblock %}
```

## A4. `static/js/sales.js` (new file)
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
        : '<div class="state"><b>No sales found</b><span>Nothing in this period yet.</span><a class="btn btn-orange" href="/sales/new">New Sale</a></div>';
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
  Cust.renderIcons(); if (window.Icons) Icons.render(document);
  load();
})();
```

## A5. `static/js/sales_new.js` (new file)
```javascript
// New sale. Reads real cylinder stock and customers; saves through POST /api/sales (see SALES_API_CONTRACT.md).
(function () {
  const $ = (id) => document.getElementById(id);
  const { esc, fmt } = UI;
  const state = { customer: null, cylinders: [], goods: [], special: {}, saving: false };
  // per size: { refill, new_full, new_empty, empty_in, rate, security, open }   per item: { qty, rate }
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
  function totals() {
    const sub = state.cylinders.reduce((a, c) => a + cylAmount(c), 0) + state.goods.reduce((a, g) => a + goodAmount(g), 0);
    const disc = Math.min(cents($("sn-discount").value), sub);
    const pct = Math.min(100, Math.max(0, Number($("sn-gst").value) || 0));
    const gst = Math.round((sub - disc) * pct / 100);
    return { sub, disc, pct, gst, total: sub - disc + gst };
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
    $("sn-total").textContent = rs(t.total);
    const mode = $("sn-payment").value, paid = $("sn-paid");
    paid.disabled = mode !== "partial";
    if (mode === "paid") paid.value = t.total ? (t.total / 100).toFixed(2) : "";
    if (mode === "credit") paid.value = "";
    const due = mode === "paid" ? 0 : t.total - (mode === "credit" ? 0 : cents(paid.value));
    $("sn-due-row").hidden = !(state.customer && due > 0); $("sn-due").textContent = rs(Math.max(0, due));
    $("sn-save").disabled = state.saving || !anything();
    document.querySelectorAll(".sn-warn").forEach(() => {});
    $("sn-save").disabled = $("sn-save").disabled || state.cylinders.some((c) => cyl[c.id].refill + cyl[c.id].new_full > c.full);
  }
  function applyCustomerRules() {
    const walkin = !state.customer, pay = $("sn-payment");
    [...pay.options].forEach((o) => { if (o.value !== "paid") o.disabled = walkin; });
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
    s[t.dataset.f] = t.dataset.f === "security" ? t.value : num(t.value);
    renderCylinders(); update();
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
      new_empty: cyl[c.id].new_empty, empty_in: cyl[c.id].empty_in, rate: String(cyl[c.id].rate), security: String(cyl[c.id].security) }))
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
      state.cylinders.forEach((c) => { cyl[c.id] = { refill: 0, new_full: 0, new_empty: 0, empty_in: 0, rate: c.sale_price, security: c.security, open: false }; });
      state.goods.forEach((g) => { good[g.id] = { qty: "", rate: g.sale_price }; });
    } catch (ex) { showError("Could not load stock. " + ex.message); $("sn-cylinders").innerHTML = ""; return; }
    applyCustomerRules(); renderAll();
    const pre = new URLSearchParams(location.search).get("customer");
    if (pre) { try { await setCustomer(await Api.get("/api/customers/" + pre)); } catch (_) { /* stay walk-in */ } }
  }
  start();
})();
```

## A6. `static/js/sale_detail.js` (new file)
```javascript
// Sale receipt: print, WhatsApp, cancel bill.
(function () {
  const $ = (id) => document.getElementById(id);
  const { esc, fmt } = UI;
  const sid = Number(location.pathname.split("/").pop());
  const justSaved = new URLSearchParams(location.search).get("new") === "1";
  let sale = null;

  const KIND = { refill: "Refill", new_full: "New cylinder + gas", new_empty: "Empty cylinder", empty_in: "Empty received", item: "" };
  const MODE = { cash: "Cash in hand", bank: "Bank / UPI" };
  const showError = (m) => { const b = $("rc-error"); b.querySelector("span").textContent = m || ""; b.hidden = !m; };

  function lineRow(l) {
    const label = l.kind === "item" ? esc(l.name) + (l.detail ? " <small>(" + esc(l.detail) + ")</small>" : "")
      : esc(l.name) + " <small>" + esc(KIND[l.kind] || "") + "</small>";
    const free = l.kind === "empty_in";
    return "<tr><td>" + label + '</td><td class="num">' + esc(l.qty) + '</td><td class="num">' + (free ? "—" : esc(fmt.money(l.rate))) +
      '</td><td class="num"><b>' + (free ? "—" : esc(fmt.money(l.amount))) + "</b></td></tr>";
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
    rows.push(sumRow("GST (" + sale.gst_percent + "%)", sale.gst), sumRow("Total (incl. GST)", sale.total, "rc-total"));
    rows.push(sumRow("Paid (" + (MODE[sale.received_in] || "Cash in hand") + ")", sale.paid));
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

## A7. `static/css/sales.css` (new file)
```css
/* Sales screens: list (sales.html), new sale (sales_new.html), receipt (sale_detail.html). */

/* ---------- list ---------- */
.sl-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 16px; }
.sl-stat { padding: 16px 20px; background: #fff; border: 1px solid #b4b3c8; border-radius: 14px; display: flex; flex-direction: column; gap: 4px; }
.sl-stat small { font-size: 12px; color: var(--muted); }
.sl-stat b { font-size: 24px; }
.sl-stat b.red { color: var(--red); }
.sl-stat span { font-size: 12px; color: var(--muted); }
.sl-custom { margin: -6px 0 14px; }
.sl-row { text-decoration: none; color: inherit; }
.sl-row .avatar { background: #ecebfa; color: var(--navy); }
.sl-amt { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }
.sl-amt b { font-size: 15px; }
.sl-due { font-size: 11px; color: var(--red); font-weight: 600; }
.badge-udhaar { background: var(--red-soft); color: var(--red); }
.sl-row.is-cancelled .row-name b, .sl-row.is-cancelled .strike { text-decoration: line-through; color: #9a9ab5; }
@media (max-width: 700px) { .sl-stats { grid-template-columns: 1fr; } }

/* ---------- new sale ---------- */
.sn-customer-row { display: flex; gap: 12px; align-items: stretch; margin-bottom: 8px; }
.sn-customer-row .pn-supplier-picker { flex: 1; min-width: 0; }
.sn-customer-row .btn { height: auto; min-height: 66px; padding: 0 18px; }
.sn-customer-row .pn-supplier-picker .avatar { background: #ecebfa; color: var(--navy); }
.sn-walkin { margin: 0 0 12px 4px; color: var(--navy); }
.sn-card .sn-head { display: grid; grid-template-columns: 31px minmax(0, 1fr) auto; gap: 8px; align-items: center; margin-bottom: 10px; }
.sn-price { display: inline-flex; align-items: center; gap: 5px; height: 30px; padding: 0 10px; border: 0; border-radius: 8px; background: #fff0e8; color: #e0601c; font-size: 12px; font-weight: 700; cursor: pointer; white-space: nowrap; }
.sn-price:hover { background: #ffe4d3; }
.sn-pencil { font-style: normal; font-size: 11px; }
.sn-price-input { width: 96px; height: 30px; border: 1px solid #e0601c; border-radius: 8px; padding: 0 8px; font: inherit; font-size: 12px; text-align: right; outline: 0; }
.sn-step-orange { background: #fff0e8; color: #dc6a24; }
.sn-toggle { display: flex; justify-content: center; gap: 6px; margin-top: 10px; background: #f1f0f8; }
.sn-more { margin-top: 8px; padding: 8px 8px 2px; border-radius: 9px; background: #f8f8fd; }
.sn-dep { margin-bottom: 8px; }
.sn-dep > span { max-width: 160px; }
.sn-warn { margin: 6px 0 0; font-size: 11px; font-weight: 600; color: var(--red); }
.sn-goods { display: grid; gap: 8px; }
.sn-good { display: grid; grid-template-columns: minmax(0, 1fr) auto 110px 92px; gap: 12px; align-items: center; padding: 10px 12px; border: 1px solid #d4d4e2; border-radius: 11px; background: #fff; }
.sn-qty { display: flex; flex-direction: column; gap: 3px; }
.sn-qty small { font-size: 9px; color: var(--muted); }
.sn-qty input { height: 30px; border: 1px solid #d0cfde; border-radius: 7px; padding: 0 8px; font: inherit; font-size: 12px; text-align: right; }
.sn-gamt { text-align: right; font-size: 12px; }
.sn-due-row b, .sn-due-row span { color: var(--red); font-weight: 700; }
@media (max-width: 900px) { .sn-good { grid-template-columns: 1fr auto; } }

/* ---------- receipt ---------- */
.btn-danger-outline { background: #fff; border: 1px solid #f0b7b7; color: var(--red); }
.btn-whatsapp { background: #2e7d32; color: #fff; }
.rc-wrap { max-width: 440px; margin: 0 auto; }
.rc-banner { display: flex; align-items: center; gap: 8px; padding: 11px 16px; border-radius: 10px; font-weight: 700; font-size: 13px; margin-bottom: 14px; }
.rc-saved { background: var(--green-soft); color: var(--green); }
.rc-void { background: var(--red-soft); color: var(--red); }
.rc-paper { position: relative; padding: 26px 24px 20px; background: #fff; border: 1px solid #c9c8dc; border-radius: 12px; overflow: hidden; }
.rc-biz { margin: 6px 0 14px; text-align: center; font-size: 17px; }
.rc-kind { text-align: center; font-size: 11px; font-weight: 700; letter-spacing: .04em; padding: 8px 0; }
.rc-sep { border-top: 1px dashed #b9b8cc; margin: 4px 0; }
.rc-meta { display: grid; gap: 9px; padding: 12px 0; font-size: 12px; }
.rc-meta div, .rc-sums div { display: flex; justify-content: space-between; gap: 12px; }
.rc-meta span, .rc-sums span { color: var(--muted); }
.rc-table { width: 100%; border-collapse: collapse; margin: 6px 0; }
.rc-table th { font-size: 11px; text-align: left; padding: 8px 0; }
.rc-table td { font-size: 12px; padding: 8px 0; vertical-align: top; }
.rc-table .num { text-align: right; white-space: nowrap; padding-left: 8px; }
.rc-table small { color: var(--muted); font-size: 10px; display: block; }
.rc-sums { display: grid; gap: 8px; padding: 12px 0; font-size: 12px; }
.rc-total span, .rc-total b { font-size: 13px; color: var(--text); font-weight: 700; }
.rc-due span, .rc-due b { color: var(--red); font-weight: 700; }
.rc-thanks { text-align: center; font-weight: 700; margin: 12px 0; }
.rc-credit { text-align: center; font-size: 10px; font-style: italic; color: var(--muted); margin: 8px 0 0; }
.rc-stamp { position: absolute; top: 42%; left: 50%; transform: translate(-50%, -50%) rotate(-18deg); font-size: 38px; font-weight: 800; letter-spacing: .08em; color: rgba(200, 40, 40, .22); border: 4px solid rgba(200, 40, 40, .22); padding: 4px 18px; border-radius: 8px; pointer-events: none; }
.rc-paper.is-void .rc-table, .rc-paper.is-void .rc-sums { opacity: .6; }
.rc-actions { display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; margin-top: 16px; }

@media print {
  body * { visibility: hidden; }
  #rc-paper, #rc-paper * { visibility: visible; }
  #rc-paper { position: absolute; left: 0; top: 0; width: 100%; border: 0; }
}

#sn-save { background: var(--orange); color: #fff; }
#sn-save:disabled { opacity: .45; }
```

## A8. `api/mock_sales.py` (new file)
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
    return " · ".join(parts) or "Empty cylinders only"


def _add(customer, lines, day, hhmm, discount, gst_pct, status_pay, paid, received_in, note):
    subtotal = sum(ln["amount_paise"] for ln in lines)
    discount = min(discount, subtotal)
    gst = int((Decimal(subtotal - discount) * Decimal(str(gst_pct)) / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    total = subtotal - discount + gst
    paid = total if status_pay == "paid" else (0 if status_pay == "credit" else paid)
    sid = _NEXT[0]
    _NEXT[0] += 1
    sale = {"id": sid, "number": f"S-{sid:05d}", "date": day, "time": hhmm, "customer": customer, "lines": lines,
            "subtotal": subtotal, "discount": discount, "gst_percent": gst_pct, "gst": gst, "total": total, "paid": paid,
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
        "subtotal": to_rupees(s["subtotal"]), "discount": to_rupees(s["discount"]), "gst_percent": s["gst_percent"],
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

---
# B. EDITS TO EXISTING FILES

## B1. `api/__init__.py` — register the temporary fake backend
**Find:**
```
from . import customers, dashboard, payments, suppliers, purchases, stock, stock_suppliers  # noqa: E402,F401
```
**Replace with:**
```
from . import customers, dashboard, payments, suppliers, purchases, stock, stock_suppliers, mock_sales  # noqa: E402,F401
```
(If your line has other names in it, just add `, mock_sales` before the `# noqa`.)

## B2. `app.py` — three lines in the `PAGES` / routes
**Find** (line ~14):
```
    "/sales": ("placeholder.html", "sales", "Sales", "Sales list, filters and export"),
    "/sales/new": ("placeholder.html", "sales", "New Sale", "Cylinder sale form, payment and GST"),
```
**Replace with:**
```
    "/sales": ("sales.html", "sales", "Sales", ""),
    "/sales/new": ("sales_new.html", "sales", "New Sale", ""),
```
**Find** (near the bottom of `create_app`):
```
                     make_view("placeholder.html", "sales", "Sale receipt", "Tax invoice, print / WhatsApp, cancel bill"))
```
**Replace with:**
```
                     make_view("sale_detail.html", "sales", "Sale receipt", ""))
```

Then restart the app and open **Sales**. The list starts with two demo bills; **New Sale** works end to end.

---
## Things I decided (tell me what to change)
* **"Sell with cylinder or empty"** I read as: a customer buying a *new cylinder with gas* (price + security) or an *empty cylinder only* (security only), with the security editable per sale. Tell me if the client means something else.
* **Empty in** = customer hands back an empty without taking a full one (no money).
* **Udhaar / Part paid** only for a chosen customer; walk-in is cash only (as in the design hint).
* **Receipt** is the simple receipt from the design, not the tax invoice (that comes with the bill later). Print uses the browser's print dialog and prints only the receipt.
* The list shows time only for Today and "date · time" for other periods.
* Full list of URLs/JSON the screens use: `SALES_API_CONTRACT.md` (sent with this).
