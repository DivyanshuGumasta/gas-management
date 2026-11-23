// New sale / tax invoice. GST and HSN are read from Stock & Price, never typed per bill.
(function () {
  const $ = (id) => document.getElementById(id);
  const { esc, fmt } = UI;
  const state = { customer: null, cylinders: [], goods: [], suppliers: [], stockExtra: {}, states: [], business: null, special: {}, heldByType: {}, holdingsByType: {}, saving: false, loaded: false };
  const cyl = {}, good = {};
  const cents = (v) => { const n = Number(String(v ?? "").replace(/,/g, "")); return Number.isFinite(n) && n > 0 ? Math.round(n * 100) : 0; };
  const rs = (p) => fmt.money((p / 100).toFixed(2));
  const num = (v) => { const n = Number(v); return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0; };
  const showError = (m) => { $("sn-error-text").textContent = m || ""; $("sn-error").hidden = !m; if (m) window.scrollTo({ top: 0, behavior: "smooth" }); };
  const bp = (p) => p == null || p === "" ? null : Math.round(Number(p) * 100);

  function listRate(c) {
    if (state.special[c.id] != null) return state.special[c.id];
    return state.customer && state.customer.type === "wholesale" ? c.wholesale_price : c.sale_price;
  }
  function itemRate(it) { return state.customer && state.customer.type === "wholesale" && Number(it.wholesale_price) ? it.wholesale_price : it.sale_price; }
  function resetRates() {
    state.cylinders.forEach((c) => { cyl[c.id].rate = listRate(c); });
    state.goods.forEach((g) => { good[g.id].rate = itemRate(g); });
    renderAll();
  }
  function productLines() {
    const out = [];
    state.cylinders.forEach((c) => {
      const s = cyl[c.id], rate = cents(s.rate), rateBp = bp(s.gstRate);
      if (s.refill) out.push({ gross: s.refill * rate, rateBp, name: c.name, hsn: c.hsn });
      if (s.new_full) out.push({ gross: s.new_full * rate, rateBp, name: c.name, hsn: c.hsn });
    });
    state.goods.forEach((g) => {
      const s = good[g.id], q = Number(s.qty || 0);
      if (q > 0) out.push({ gross: Math.round(q * cents(s.rate)), rateBp: bp(s.gstRate), name: g.name, hsn: g.hsn });
    });
    return out;
  }
  function taxSummary() {
    const lines = productLines(), gross = lines.reduce((a, l) => a + l.gross, 0);
    const discount = Math.min(cents($("sn-discount").value), gross);
    const place = ($("sn-place-state").value || (state.customer && (state.customer.state_code || (state.customer.gstin || "").slice(0, 2))) || (state.business && state.business.state_code) || "").trim();
    const interstate = !!(state.business && place && place !== state.business.state_code);
    let taxable = 0, gst = 0, cgst = 0, sgst = 0, igst = 0;
    const shares = lines.map((line) => gross ? Math.floor(discount * line.gross / gross) : 0);
    let remainder = discount - shares.reduce((sum, value) => sum + value, 0);
    const order = lines.map((line, index) => ({ index, remainder: gross ? (discount * line.gross) % gross : 0 }))
      .sort((a, b) => b.remainder - a.remainder || a.index - b.index);
    for (let i = 0; i < remainder && i < order.length; i++) shares[order[i].index] += 1;
    lines.forEach((line, i) => {
      const base = line.gross - shares[i];
      const tax = line.rateBp == null ? 0 : Math.round(base * line.rateBp / 10000);
      taxable += base; gst += tax;
      if (interstate) igst += tax;
      else { const half = Math.ceil(tax / 2); cgst += half; sgst += tax - half; }
    });
    const depositIn = state.cylinders.reduce((a, c) => a + (cyl[c.id].new_full + cyl[c.id].new_empty) * cents(cyl[c.id].security), 0);
    const depositBack = state.cylinders.reduce((a, c) => {
      const s = cyl[c.id];
      if (!state.customer || !s.dep_back || !s.empty_in) return a;
      return a + (s.dep_each_explicit ? s.empty_in * cents(s.dep_each) : refundPreviewPaise(c.id, s.empty_in, s.return_supplier_id));
    }, 0);
    return { lines, gross, discount, taxable, gst, cgst, sgst, igst, depositIn, depositBack,
      total: taxable + gst + depositIn - depositBack, interstate, place };
  }
  function taxConfigError() {
    const lines = productLines();
    if (lines.length && (!state.business || !state.business.name || !state.business.address || !state.business.state_code)) {
      return "Complete the agency details in Sales → Invoice settings before creating an invoice.";
    }
    for (const l of lines) {
      if (!l.hsn) return "Add an HSN/SAC code for " + l.name + " in Stock & Price before creating this invoice.";
      if (l.rateBp == null) return "Set a GST rate for " + l.name + " before creating this invoice.";
      if (!Number.isFinite(l.rateBp) || l.rateBp < 0 || l.rateBp > 10000) {
        return "GST rate for " + l.name + " must be between 0 and 100 percent.";
      }
      if (l.rateBp > 0 && state.business && !state.business.gstin) {
        return "The agency GSTIN is missing. Verify registration status and tax settings in Invoice settings with the CA.";
      }
    }
    return "";
  }
  const anything = () => state.cylinders.some((c) => {
    const s = cyl[c.id]; return s.refill || s.new_full || s.new_empty || s.empty_in || s.damaged_in;
  }) || state.goods.some((g) => Number(good[g.id].qty) > 0);

  function stepper(field, id, value, minusCls, plusCls, disabled = false, max = null) {
    const maxAttr = max == null ? '' : ' max="' + max + '"';
    const minusDisabled = Number(value) <= 0 ? ' disabled' : '';
    const plusDisabled = disabled || (max != null && Number(value) >= max) ? ' disabled' : '';
    const inputDisabled = disabled ? ' disabled' : '';
    return '<div class="pn-stepper"><button type="button" class="pn-step ' + minusCls + '" data-step="-1" data-f="' + field + '" data-id="' + id + '" aria-label="Less"' + minusDisabled + '>−</button>' +
      '<input type="number" min="0"' + maxAttr + ' step="1" inputmode="numeric" value="' + value + '" data-f="' + field + '" data-id="' + id + '"' + inputDisabled + '>' +
      '<button type="button" class="pn-step ' + plusCls + '" data-step="1" data-f="' + field + '" data-id="' + id + '" aria-label="More"' + plusDisabled + '>+</button></div>';
  }
  function taxLabel(x, rate) {
    return '<div class="sn-product-tax"><span>HSN ' + (x.hsn ? esc(x.hsn) : 'not set') + '</span>' +
      '<span class="sn-gst-readonly">GST ' + (rate == null || rate === '' ? 'not set' : esc(rate) + '%') + '</span></div>';
  }
  function supplierLinks(id) {
    const item = (state.stockExtra.cylinders || {})[String(id)] || {};
    return item.suppliers || [];
  }
  function supplierOptions(id, selected, allowUnassigned) {
    const links = supplierLinks(id);
    let html = allowUnassigned ? '<option value="">Choose supplier</option>' : '<option value="">Choose supplier</option>';
    html += links.map((x) => '<option value="' + x.supplier_id + '"' + (String(selected || '') === String(x.supplier_id) ? ' selected' : '') + '>' + esc(x.name) + '</option>').join('');
    return html;
  }
  function defaultSupplier(id) {
    const links = supplierLinks(id);
    if (links.length === 1) return String(links[0].supplier_id);
    if (state.suppliers.length === 1 && links.some((x) => String(x.supplier_id) === String(state.suppliers[0].id))) return String(state.suppliers[0].id);
    return '';
  }
  function defaultReturnSupplier(id) {
    const holdings = state.holdingsByType[id] || [];
    const candidates = [...new Set(holdings.filter((h) => h.supplier_id != null && Number(h.qty) > 0).map((h) => String(h.supplier_id)))];
    if (candidates.length === 1 && supplierLinks(id).some((x) => String(x.supplier_id) === candidates[0])) return candidates[0];
    return defaultSupplier(id);
  }
  function refundPreviewPaise(id, qty, sid) {
    let remaining = Math.max(0, Number(qty) || 0), total = 0;
    const holdings = state.holdingsByType[id] || [];
    const priority = sid ? [String(sid), null] : [null];
    for (const supplier of priority) {
      const row = holdings.find((h) => (h.supplier_id == null ? null : String(h.supplier_id)) === supplier);
      if (!row || remaining <= 0) continue;
      const availableQty = Number(row.qty) || 0;
      const take = Math.min(remaining, availableQty);
      const amount = cents(row.deposit_total || 0);
      total += take === availableQty ? amount : Math.round(amount * take / availableQty);
      remaining -= take;
    }
    return total;
  }
  function defaultRefundEach(id, sid, qty) {
    const count = Math.max(1, Number(qty) || 1);
    return (refundPreviewPaise(id, count, sid) / count / 100).toFixed(2);
  }
  function stateSelectOptions(selected) {
    return '<option value="">Choose state</option>' + state.states.map((r) => '<option value="' + esc(r.code) + '"' + (String(selected || '') === String(r.code) ? ' selected' : '') + '>' + esc(r.name) + ' (' + esc(r.code) + ')</option>').join('');
  }
  function cylinderCard(c) {
    const s = cyl[c.id], used = s.refill + s.new_full, over = used > c.full;
    const held = Number(state.heldByType[c.id] || 0);
    const returnLocked = !state.customer || held <= 0;
    const emptyReturnMax = state.customer ? Math.max(0, held - s.empty_in - s.damaged_in) : 0;
    const damagedReturnMax = emptyReturnMax;
    const stockSelector = '<label class="sn-supplier-choice"><span>Supplier for cylinders supplied</span><select class="select" data-f="supplier_id" data-id="' + c.id + '">' + supplierOptions(c.id, s.supplier_id, false) + '</select></label>';
    const returnSelector = state.customer ? '<label class="sn-supplier-choice"><span>Supplier receiving returned cylinders</span><select class="select" data-f="return_supplier_id" data-id="' + c.id + '">' + supplierOptions(c.id, s.return_supplier_id, false) + '</select></label>' : '';
    return '<article class="pn-item sn-card" data-cid="' + c.id + '">' +
      '<div class="sn-head"><span class="pn-cylinder-icon">▣</span><div class="pn-item-title"><b>' + esc(c.name) + '</b>' + taxLabel(c, s.gstRate) + '<small>Full: ' + c.full + ' · Empty: ' + c.empty + '</small>' +
      (state.customer ? '<small class="sn-held-count">Customer holds: ' + held + ' · only good/damaged returns reduce this</small>' : '') + '</div>' +
      '<button type="button" class="sn-price" data-edit-price="' + c.id + '" title="Tap to change the selling price">Rs ' + esc(fmt.money(s.rate).replace(/^Rs\s?/, "")) + ' <i class="sn-pencil">✎</i></button></div>' +
      '<div class="pn-qty-line"><div><b>Refill</b><small>Full cylinder supplied; does not change customer-held quantity</small></div>' + stepper("refill", c.id, s.refill, "pn-step-minus", "pn-step-plus", false, null) + '</div>' +
      '<div class="pn-qty-line"><div><b>Good empty in</b><small>Customer returns a usable held cylinder</small></div>' +
      stepper("empty_in", c.id, s.empty_in, "pn-step-minus", "sn-step-orange", returnLocked, emptyReturnMax) + '</div>' +
      (s.empty_in && state.customer ? '<label class="sn-depback"><input type="checkbox" data-depback="' + c.id + '"' + (s.dep_back ? ' checked' : '') + '><span><b>Refund customer security deposit</b><small>Prefilled from recorded deposit, capped at the amount held</small></span>' +
        (s.dep_back ? '<span class="pn-rate sn-dep-each"><span><i>Rs</i><input type="number" min="0" step="0.01" value="' + esc(s.dep_each) + '" data-f="dep_each" data-id="' + c.id + '"></span></span>' : '') + '</label>' : '') +
      (state.customer ? '<div class="pn-qty-line"><div><b>Damaged cylinder in</b><small>Customer deposit is forfeited; cylinder moves to damaged stock</small></div>' +
        stepper("damaged_in", c.id, s.damaged_in, "pn-step-minus", "sn-step-orange", returnLocked, damagedReturnMax) + '</div>' : '') +
      (over ? '<p class="sn-warn">Only ' + c.full + ' full cylinder(s) in stock.</p>' : '') +
      '<button type="button" class="pn-bought-toggle sn-toggle' + (s.open ? ' on' : '') + '" data-toggle="' + c.id + '">Sell new cylinder or empty ' + (s.open ? '▴' : '▾') + '</button>' +
      ((s.refill || s.new_full || s.new_empty) ? stockSelector : '') +
      ((s.empty_in || s.damaged_in) ? returnSelector : '') +
      (s.open ? '<div class="sn-more"><label class="pn-rate sn-dep"><small>Refundable security deposit (per cylinder)</small><span><i>Rs</i><input type="number" min="0" step="0.01" value="' + esc(s.security) + '" data-f="security" data-id="' + c.id + '"></span></label>' +
        '<div class="pn-qty-line"><div><b>New full cylinder</b><small>Gas price plus refundable security deposit</small></div>' + stepper("new_full", c.id, s.new_full, "pn-step-minus", "pn-step-plus") + '</div>' +
        '<div class="pn-qty-line"><div><b>Empty cylinder only</b><small>Refundable security deposit only</small></div>' + stepper("new_empty", c.id, s.new_empty, "pn-step-minus", "pn-step-plus") + '</div></div>' : '') +
      '<div class="pn-item-footer"><span>Taxable product amount (deposit separate)</span><b data-amt="' + c.id + '">' + rs((s.refill + s.new_full) * cents(s.rate)) + '</b></div></article>';
  }
  function goodCard(g) {
    const s = good[g.id];
    return '<article class="sn-good" data-gid="' + g.id + '"><div class="pn-item-title"><b>' + esc(g.name) + '</b>' + taxLabel(g, s.gstRate) + '<small>In stock: ' + esc(g.qty) + ' ' + esc(g.unit) + '</small></div>' +
      '<button type="button" class="sn-price" data-edit-gprice="' + g.id + '">Rs ' + esc(fmt.money(s.rate).replace(/^Rs\s?/, "")) + ' <i class="sn-pencil">✎</i></button>' +
      '<label class="sn-qty"><small>Quantity (' + esc(g.unit) + ')</small><input type="number" min="0" step="any" inputmode="decimal" value="' + (s.qty || '') + '" placeholder="0" data-gqty="' + g.id + '"></label>' +
      '<b class="sn-gamt" data-gamt="' + g.id + '">' + rs(Math.round(Number(s.qty || 0) * cents(s.rate))) + '</b></article>';
  }
  function renderCylinders() {
    $("sn-cylinders").innerHTML = state.cylinders.length ? state.cylinders.map(cylinderCard).join("") : '<div class="pn-empty">No cylinder sizes yet. Add them in Stock &amp; Price first.</div>';
  }
  function renderGoods() {
    $("sn-items-panel").hidden = !state.goods.length;
    $("sn-goods").innerHTML = state.goods.map(goodCard).join("");
  }
  const renderAll = () => { renderCylinders(); renderGoods(); update(); };

  function update() {
    const t = taxSummary();
    state.cylinders.forEach((c) => {
      const el = document.querySelector('[data-amt="' + c.id + '"]');
      if (el) el.textContent = rs((cyl[c.id].refill + cyl[c.id].new_full) * cents(cyl[c.id].rate));
    });
    state.goods.forEach((g) => { const el = document.querySelector('[data-gamt="' + g.id + '"]'); if (el) el.textContent = rs(Math.round(Number(good[g.id].qty || 0) * cents(good[g.id].rate))); });
    $("sn-subtotal").textContent = rs(t.gross);
    $("sn-disc-row").hidden = !t.discount; $("sn-disc-show").textContent = '- ' + rs(t.discount);
    $("sn-gst-label").textContent = 'GST'; $("sn-gst-show").textContent = rs(t.gst);
    $("sn-gst-amount").value = (t.gst / 100).toFixed(2);
    $("sn-tax-split").textContent = t.interstate ? 'IGST: ' + rs(t.igst) : 'CGST: ' + rs(t.cgst) + ' · SGST: ' + rs(t.sgst);
    $("sn-deposit-in-row").hidden = !t.depositIn; $("sn-deposit-in-show").textContent = '+ ' + rs(t.depositIn);
    $("sn-back-row").hidden = !t.depositBack; $("sn-back-show").textContent = '- ' + rs(t.depositBack);
    $("sn-total-label").textContent = t.total < 0 ? 'Given back to customer' : 'Total payable';
    $("sn-total").textContent = rs(Math.abs(t.total));
    const pay = $("sn-payment");
    [...pay.options].forEach((o) => { if (o.value !== 'paid') o.disabled = !state.customer || t.total <= 0; });
    if (t.total <= 0) pay.value = 'paid';
    const mode = pay.value, paid = $("sn-paid");
    paid.disabled = mode !== 'partial';
    if (mode === 'paid') paid.value = t.total ? (Math.abs(t.total) / 100).toFixed(2) : '';
    if (mode === 'credit') paid.value = '';
    $("sn-paid-label").textContent = t.total < 0 ? 'Amount paid back now' : 'Amount received now';
    $("sn-pay-hint").textContent = state.customer ? 'Udhaar is added to ' + state.customer.name + '’s balance.' : 'Walk-in sales must be paid immediately.';
    const due = mode === 'paid' ? 0 : t.total - (mode === 'credit' ? 0 : cents(paid.value));
    $("sn-due-row").hidden = !(state.customer && due > 0); $("sn-due").textContent = rs(Math.max(0, due));
    const noCustomerForDeposit = !state.customer && state.cylinders.some((c) => cyl[c.id].new_full || cyl[c.id].new_empty || cyl[c.id].empty_in || cyl[c.id].damaged_in);
    const configError = taxConfigError();
    $("sn-tax-warning").textContent = configError || (noCustomerForDeposit ? 'Select a customer before issuing a cylinder or processing a cylinder return.' : '');
    $("sn-tax-warning").hidden = !$("sn-tax-warning").textContent;
    const over = state.cylinders.some((c) => {
      const s = cyl[c.id], held = Number(state.heldByType[c.id] || 0);
      const returnUse = s.empty_in + s.damaged_in;
      const stockNeedsSupplier = s.refill || s.new_full || s.new_empty;
      const returnNeedsSupplier = returnUse > 0;
      const stockMissing = stockNeedsSupplier && supplierLinks(c.id).length > 0 && !s.supplier_id;
      const returnMissing = returnNeedsSupplier && supplierLinks(c.id).length > 0 && !s.return_supplier_id;
      return s.refill + s.new_full > c.full || s.new_empty > c.empty ||
        (!!state.customer && returnUse > held) || stockMissing || returnMissing ||
        (!!state.suppliers.length && !!stockNeedsSupplier && !supplierLinks(c.id).length) ||
        (!!state.suppliers.length && !!returnNeedsSupplier && !supplierLinks(c.id).length);
    });
    $("sn-save").disabled = state.saving || !anything() || !!configError || noCustomerForDeposit || over;
  }

  async function setCustomer(c) {
    state.customer = c || null; state.special = {}; state.heldByType = {}; state.holdingsByType = {};
    $("sn-cust-avatar").textContent = c ? fmt.initials(c.name) : 'W';
    $("sn-cust-name").textContent = c ? c.name : 'Walk-in customer';
    $("sn-cust-meta").textContent = c ? ((c.type === 'wholesale' ? 'Wholesale' : 'Retail') + (c.phone ? ' · ' + c.phone : '')) : 'Cash sale, no udhaar';
    const b = Number(c && c.balance) || 0, tag = $("sn-cust-balance");
    tag.className = 'bal ' + (b > 0 ? 'bal-red' : b < 0 ? 'bal-green' : 'bal-clear');
    tag.textContent = !c ? '' : b > 0 ? fmt.money(b) + ' · To receive' : b < 0 ? fmt.money(-b) + ' · Paid extra' : 'Clear';
    $("sn-walkin").hidden = !c;
    $("sn-place-state").value = c ? (c.state_code || (c.gstin || '').slice(0, 2) || state.business.state_code) : state.business.state_code;
    if (c) {
      try {
        const [prices, held] = await Promise.all([
          Api.get('/api/customers/' + c.id + '/prices'),
          Api.get('/api/customers/' + c.id + '/holdings'),
        ]);
        prices.forEach((p) => { if (p.special_price != null) state.special[p.cylinder_type_id] = p.special_price; });
        (held || []).forEach((h) => {
          (state.holdingsByType[h.cylinder_type_id] ||= []).push(h);
          state.heldByType[h.cylinder_type_id] = (state.heldByType[h.cylinder_type_id] || 0) + Number(h.qty || 0);
        });
        state.cylinders.forEach((item) => {
          const row = cyl[item.id];
          row.return_supplier_id = defaultReturnSupplier(item.id);
          row.supplier_id = defaultSupplier(item.id);
          row.dep_each = defaultRefundEach(item.id, row.return_supplier_id, 1);
          row.dep_each_explicit = false;
        });
      } catch (_) {
        state.heldByType = {};
      }
    }
    resetRates();
  }
  function inlinePrice(btn, get, set) {
    const input = document.createElement('input'); input.className = 'sn-price-input'; input.type = 'number'; input.min = '0'; input.step = '0.01'; input.value = get();
    btn.replaceWith(input); input.focus(); input.select();
    const done = () => { set(input.value === '' ? get() : input.value); renderAll(); };
    input.addEventListener('blur', done);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); input.blur(); } });
  }
  document.addEventListener('click', (e) => {
    const step = e.target.closest('[data-step]');
    if (step) {
      const id = step.dataset.id, s = cyl[id], f = step.dataset.f;
      const returnAction = ['empty_in', 'damaged_in'].includes(f);
      if (state.customer && returnAction) {
        const held = Number(state.heldByType[id] || 0);
        const used = s.empty_in + s.damaged_in;
        if (Number(step.dataset.step) > 0 && used >= held) return;
      }
      const beforeGood = s.empty_in;
      s[f] = Math.max(0, s[f] + Number(step.dataset.step));
      if (f === 'empty_in' && beforeGood === 0 && s.empty_in > 0) {
        if (!s.return_supplier_id) s.return_supplier_id = defaultReturnSupplier(id);
        s.dep_each = defaultRefundEach(id, s.return_supplier_id, s.empty_in);
        s.dep_each_explicit = false;
        s.dep_back = true;
      }
      renderCylinders(); update(); return;
    }
    const toggle = e.target.closest('[data-toggle]');
    if (toggle) { cyl[toggle.dataset.toggle].open = !cyl[toggle.dataset.toggle].open; renderCylinders(); return; }
    const price = e.target.closest('[data-edit-price]');
    if (price) { const id = price.dataset.editPrice; inlinePrice(price, () => cyl[id].rate, (v) => { cyl[id].rate = v; }); return; }
    const itemPrice = e.target.closest('[data-edit-gprice]');
    if (itemPrice) { const id = itemPrice.dataset.editGprice; inlinePrice(itemPrice, () => good[id].rate, (v) => { good[id].rate = v; }); }
  });
  $("sn-cylinders").addEventListener('change', (e) => {
    const t = e.target;
    if (!t.dataset.f) return;
    const s = cyl[t.dataset.id], field = t.dataset.f;
    if (field === 'supplier_id') { s.supplier_id = t.value; update(); return; }
    if (field === 'return_supplier_id') {
      s.return_supplier_id = t.value;
      s.dep_each = defaultRefundEach(t.dataset.id, t.value, s.empty_in || 1);
      s.dep_each_explicit = false;
      renderCylinders(); update(); return;
    }
    let value = (field === 'security' || field === 'dep_each') ? t.value : num(t.value);
    if (state.customer && ['empty_in', 'damaged_in'].includes(field)) {
      const held = Number(state.heldByType[t.dataset.id] || 0);
      const alreadyUsed = s.empty_in + s.damaged_in - s[field];
      value = Math.min(value, Math.max(0, held - alreadyUsed));
    }
    if (field === 'empty_in' && Number(value) > 0 && !s.dep_back) {
      s.dep_back = true; s.dep_each = defaultRefundEach(t.dataset.id, s.return_supplier_id, value);
      s.dep_each_explicit = false;
    }
    s[field] = value;
    if (field === 'dep_each') s.dep_each_explicit = true;
    renderCylinders(); update();
  });
  $("sn-cylinders").addEventListener('change', (e) => { const id = e.target.dataset.depback; if (!id) return; cyl[id].dep_back = e.target.checked; renderCylinders(); update(); });
  $("sn-goods").addEventListener('input', (e) => {
    const id = e.target.dataset.gqty;
    if (!id) return;
    good[id].qty = e.target.value;
    update();
  });
  ['sn-discount', 'sn-paid', 'sn-payment', 'sn-place-state'].forEach((id) => { $(id).addEventListener('input', update); $(id).addEventListener('change', update); });
  $("sn-payment").addEventListener('change', update);
  $("sn-discount").addEventListener('input', (e) => Cust.cleanMoneyInput && Cust.cleanMoneyInput(e.target));
  $("sn-cust-pick").addEventListener('click', () => UI.selectCustomer(setCustomer));
  $("sn-walkin").addEventListener('click', () => setCustomer(null));
  $("sn-add-cust").addEventListener('click', () => Cust.openCustomerForm({ onSaved: (res) => setCustomer(res && res.id ? res : null) }));

  $("sn-form").addEventListener('submit', async (e) => {
    e.preventDefault(); showError('');
    if (state.saving) return;
    state.saving = true; update();
    const lines = state.cylinders.map((c) => ({ cylinder_type_id: c.id,
      refill: cyl[c.id].refill, new_full: cyl[c.id].new_full, new_empty: cyl[c.id].new_empty,
      empty_in: cyl[c.id].empty_in, damaged_in: cyl[c.id].damaged_in,
      deposit_back: !!(state.customer && cyl[c.id].dep_back && cyl[c.id].empty_in),
      ...(cyl[c.id].dep_each_explicit ? { deposit_each: String(cyl[c.id].dep_each) } : {}),
      rate: String(cyl[c.id].rate), security: String(cyl[c.id].security),
      supplier_id: cyl[c.id].supplier_id || null, return_supplier_id: cyl[c.id].return_supplier_id || null }))
      .filter((l) => l.refill || l.new_full || l.new_empty || l.empty_in || l.damaged_in);
    const items = state.goods.filter((g) => Number(good[g.id].qty) > 0)
      .map((g) => ({ item_id: g.id, qty: String(good[g.id].qty), rate: String(good[g.id].rate) }));
    try {
      const r = await Api.post('/api/sales', {
        customer_id: state.customer ? state.customer.id : null, date: $("sn-date").value,
        place_state_code: $("sn-place-state").value,
        lines, items, discount: $("sn-discount").value.trim(), payment: $("sn-payment").value,
        received_in: $("sn-received").value, paid: $("sn-paid").value.trim(),
        note: $("sn-note").value.trim(),
      });
      window.location.href = '/sales/' + r.id + '?new=1';
    } catch (ex) { state.saving = false; update(); showError(ex.message || 'Could not save the invoice.'); }
  });

  async function start() {
    if (state.loaded) { renderAll(); return; }
    state.loaded = true;
    $("sn-date").value = Cust.today(); $("sn-date").max = Cust.today();
    Cust.renderIcons(); if (window.Icons) Icons.render(document);
    try {
      const [stock, extra, business, states] = await Promise.all([
        Api.get('/api/stock'), Api.get('/api/stock/extra'), Api.get('/api/business'), Api.get('/api/states'),
      ]);
      state.cylinders = stock.cylinders; state.goods = stock.items; state.suppliers = extra.suppliers || [];
      state.stockExtra = extra; state.business = business; state.states = states || [];
      $("sn-place-state").innerHTML = stateSelectOptions(business.state_code || '');
      state.cylinders.forEach((c) => { cyl[c.id] = { refill: 0, new_full: 0, new_empty: 0, empty_in: 0, damaged_in: 0,
        rate: c.sale_price, security: c.security, gstRate: c.gst_rate == null ? '' : String(c.gst_rate),
        supplier_id: defaultSupplier(c.id), return_supplier_id: defaultSupplier(c.id),
        open: false, dep_back: false, dep_each: '0.00', dep_each_explicit: false }; });
      state.goods.forEach((g) => { good[g.id] = { qty: '', rate: g.sale_price,
        gstRate: g.gst_rate == null ? '' : String(g.gst_rate) }; });
    } catch (ex) { showError('Could not load invoice settings or stock. ' + ex.message); $("sn-save").disabled = true; return; }
    renderAll();
    const params = new URLSearchParams(location.search);
    const pre = params.get('customer');
    if (pre) { try { await setCustomer(await Api.get('/api/customers/' + pre)); } catch (_) { /* remain walk-in */ } }
    if (params.get('return') === '1') {
      state.cylinders.forEach((c) => { cyl[c.id].open = false; });
      renderAll();
    }
  }
  window.SalesNew = { open: start };
})();