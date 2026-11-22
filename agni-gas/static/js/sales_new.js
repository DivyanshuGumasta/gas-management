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