// Shared pieces for the customer screens: toast, dates, balance tags, the export
// menu, and the popups (Add/Edit customer, opening cylinders, Receive payment, Confirm).
// Loaded by customers.html and customer_detail.html AFTER ui.js and api.js.
window.Cust = (function () {
  const { fmt, esc } = UI;
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const pad = (n) => String(n).padStart(2, "0");

  /* ---------- icons not in icons.js (use <i data-cicon="name">) ---------- */
  const ICONS = {
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    chevronLeft: '<path d="m15 18-6-6 6-6"/>',
    chevronDown: '<path d="m6 9 6 6 6-6"/>',
    chevronsUpDown: '<path d="m7 15 5 5 5-5"/><path d="m7 9 5-5 5 5"/>',
  };
  function renderIcons(root) {
    (root || document).querySelectorAll("[data-cicon]").forEach((el) => {
      if (el.firstChild) return;
      el.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICONS[el.dataset.cicon] || "") + "</svg>";
    });
  }

  /* ---------- small helpers ---------- */
  function today() {
    const d = new Date();
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }
  function date(iso) {                       // 2026-11-13 -> 13 Nov 2026
    if (!iso) return "";
    const [y, m, d] = String(iso).slice(0, 10).split("-");
    return pad(+d) + " " + MONTHS[+m - 1] + " " + y;
  }
  function balanceTag(raw) {                 // customer balance: + owes us, - paid extra
    const b = Number(raw) || 0;
    if (b > 0) return '<span class="bal bal-red">' + esc(fmt.money(b)) + " <small>To receive</small></span>";
    if (b < 0) return '<span class="bal bal-green">' + esc(fmt.money(-b)) + " <small>Paid extra</small></span>";
    return '<span class="bal bal-clear">Clear</span>';
  }
  function cleanMoneyInput(input) {          // digits and one dot, max 2 decimals
    let v = input.value.replace(/[^0-9.]/g, "");
    const i = v.indexOf(".");
    if (i !== -1) v = v.slice(0, i + 1) + v.slice(i + 1).replace(/\./g, "").slice(0, 2);
    if (v !== input.value) input.value = v;
  }
  function toast(msg, kind) {
    const el = document.createElement("div");
    el.className = "toast" + (kind === "error" ? " error" : "");
    el.setAttribute("role", "status");
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3200);
  }
  // Show a message on the NEXT page (e.g. after deleting and going back to the list).
  function flash(msg) { try { sessionStorage.setItem("agni_flash", msg); } catch (_) { /* ignore */ } }
  function showFlash() {
    try {
      const m = sessionStorage.getItem("agni_flash");
      if (m) { sessionStorage.removeItem("agni_flash"); toast(m); }
    } catch (_) { /* ignore */ }
  }
  function showError(root, err) {            // field error under the field, else the red box
    const field = err && err.data && err.data.field;
    const slot = field && root.querySelector('[data-err="' + field + '"]');
    if (slot) {
      slot.textContent = err.message;
      const inp = root.querySelector('[name="' + field + '"]');
      if (inp) { inp.classList.add("invalid"); inp.focus(); }
    } else {
      const box = root.querySelector(".form-error");
      if (box) box.textContent = err.message || "Something went wrong.";
    }
  }
  function clearErrors(root) {
    root.querySelectorAll(".err").forEach((e) => (e.textContent = ""));
    root.querySelectorAll(".invalid").forEach((e) => e.classList.remove("invalid"));
    const box = root.querySelector(".form-error");
    if (box) box.textContent = "";
  }

  /* ---------- export menu (PDF / Excel) ---------- */
  function localIso(d) {
    const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 10);
  }
  function rangeParams(kind, mode, fromId, toId) {
    const p = new URLSearchParams();
    const now = new Date();
    let from = "", to = "";
    if (mode === "today") from = to = localIso(now);
    else if (mode === "7d") { const start = new Date(now); start.setDate(start.getDate() - 6); from = localIso(start); to = localIso(now); }
    else if (mode === "month") { from = localIso(new Date(now.getFullYear(), now.getMonth(), 1)); to = localIso(now); }
    else if (mode === "custom") { from = document.getElementById(fromId)?.value || ""; to = document.getElementById(toId)?.value || ""; }
    if (from) p.set("from", from);
    if (to) p.set("to", to);
    return p;
  }
  function exportParams(scope) {
    const p = new URLSearchParams();
    const value = (id) => document.getElementById(id)?.value?.trim() || "";
    if (scope === "sales") {
      const mode = document.querySelector("#sl-chips .chip.on")?.dataset.range || "today";
      const dates = rangeParams("sales", mode, "sl-from", "sl-to");
      dates.forEach((v, k) => p.set(k, v));
      if (value("sl-search")) p.set("q", value("sl-search"));
    } else if (scope === "customers") {
      const mode = document.querySelector("#chips .chip.on")?.dataset.type || "all";
      if (value("search")) p.set("q", value("search"));
      if (mode === "retail" || mode === "wholesale") p.set("type", mode);
      if (mode === "udhaar") p.set("owing", "1");
    } else if (scope === "payments") {
      if (value("pay-search")) p.set("q", value("pay-search"));
      if (value("pay-from")) p.set("from", value("pay-from"));
      if (value("pay-to")) p.set("to", value("pay-to"));
    } else if (scope === "suppliers") {
      if (value("sp-supplier-search")) p.set("q", value("sp-supplier-search"));
    } else if (scope === "purchases") {
      const mode = document.querySelector("#sp-periods .chip.on")?.dataset.period || "month";
      const dates = rangeParams("purchases", mode, "sp-from", "sp-to");
      dates.forEach((v, k) => p.set(k, v));
    } else if (scope === "stock-history") {
      const holder = document.querySelector('[data-scope="stock-history"]');
      if (holder?.dataset.cylinderTypeId) p.set("cylinder_type_id", holder.dataset.cylinderTypeId);
    }
    return p;
  }
  function exportData(kind, scope) {
    if (!scope) { toast("Could not identify which section to export.", "error"); return; }
    const format = kind === "pdf" ? "pdf" : "xlsx";
    const params = exportParams(scope);
    params.set("format", format);
    const base = (window.APP_CONFIG && window.APP_CONFIG.apiBase) || "";
    const url = base + "/api/exports/" + encodeURIComponent(scope) + "?" + params.toString();
    const link = document.createElement("a");
    link.href = url;
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }
  document.addEventListener("click", (e) => {
    const toggle = e.target.closest("[data-menu-toggle]");
    document.querySelectorAll(".menu-wrap .menu").forEach((m) => {
      if (toggle && m.parentElement === toggle.parentElement) m.hidden = !m.hidden;
      else m.hidden = true;
    });
    const ex = e.target.closest("[data-export]");
    if (ex) {
      const scoped = ex.closest("[data-scope]") || ex;
      exportData(ex.dataset.export, scoped.dataset?.scope);
      const menu = ex.closest(".menu");
      if (menu) menu.hidden = true;
    }
  });

  /* ---------- reference options and opening customer cylinders ---------- */
  let cachedStates = null;
  async function stateOptions() {
    if (!cachedStates) cachedStates = await Api.get("/api/states");
    return cachedStates;
  }
  async function stockHoldOptions() {
    const [stock, extra] = await Promise.all([Api.get("/api/stock"), Api.get("/api/stock/extra")]);
    return { cylinders: stock.cylinders || [], extra };
  }
  function addOpeningRow(container, options) {
    const cylinders = options.cylinders || [];
    const row = document.createElement("div");
    row.className = "cust-opening-row";
    row.setAttribute("data-opening-row", "");
    row.innerHTML =
      '<label class="field"><span>Cylinder size</span><select class="select" data-opening-cylinder>' +
      cylinders.map((c) => '<option value="' + c.id + '">' + esc(c.name) + '</option>').join("") + '</select></label>' +
      '<label class="field"><span>Supplier</span><select class="select" data-opening-supplier></select></label>' +
      '<label class="field"><span>Qty</span><input class="input" data-opening-qty inputmode="numeric" min="1" value="1"></label>' +
      '<label class="field"><span>Deposit / cylinder</span><div class="amt"><i>Rs</i><input data-opening-deposit inputmode="decimal"></div></label>' +
      '<button class="icon-btn" type="button" data-opening-remove aria-label="Remove opening cylinder row">×</button>';
    const type = row.querySelector("[data-opening-cylinder]");
    const supplier = row.querySelector("[data-opening-supplier]");
    const deposit = row.querySelector("[data-opening-deposit]");
    function refresh() {
      const c = cylinders.find((x) => String(x.id) === type.value);
      const typeExtra = ((options.extra.cylinders || {})[String(type.value)] || {});
      const links = typeExtra.suppliers || [];
      supplier.innerHTML = '<option value="">Unassigned / not sure</option>' + links.map((x) =>
          '<option value="' + x.supplier_id + '">' + esc(x.name) + '</option>').join("");
      if (links.length === 1) supplier.value = String(links[0].supplier_id);
      deposit.value = c ? String((links.find((x) => String(x.supplier_id) === supplier.value) || {}).security || c.security || "0") : "0";
    }
    type.addEventListener("change", refresh);
    supplier.addEventListener("change", () => {
      const links = (((options.extra.cylinders || {})[String(type.value)] || {}).suppliers || []);
      const selected = links.find((x) => String(x.supplier_id) === supplier.value);
      const c = cylinders.find((x) => String(x.id) === type.value);
      deposit.value = selected ? String(selected.security || c.security || "0") : String(c ? c.security || "0" : "0");
    });
    row.querySelector("[data-opening-remove]").addEventListener("click", () => row.remove());
    refresh();
    container.appendChild(row);
    return row;
  }
  function openingPayload(container) {
    return [...container.querySelectorAll("[data-opening-row]")].map((row) => ({
      cylinder_type_id: Number(row.querySelector("[data-opening-cylinder]").value),
      supplier_id: row.querySelector("[data-opening-supplier]").value || null,
      qty: Number(row.querySelector("[data-opening-qty]").value) || 0,
      deposit_each: row.querySelector("[data-opening-deposit]").value.trim(),
    })).filter((x) => x.qty > 0);
  }
  async function populateStateSelect(select, selected) {
    try {
      const rows = await stateOptions();
      select.innerHTML = '<option value="">Choose state</option>' + rows.map((r) =>
        '<option value="' + esc(r.code) + '">' + esc(r.name) + ' (' + esc(r.code) + ')</option>').join("");
      select.value = selected || "";
    } catch (_) {
      select.innerHTML = '<option value="">Could not load states</option>';
      select.value = selected || "";
    }
  }

  /* ---------- Add / Edit customer ---------- */
  function openCustomerForm({ customer = null, onSaved }) {
    const edit = !!customer;
    const opening = customer ? Number(customer.opening_balance) : 0;
    const f = { type: customer ? customer.type : "retail", otype: opening < 0 ? "advance" : "udhaar" };
    const body = UI.openModal(edit ? "Edit customer" : "Add customer");
    body.innerHTML =
      '<form novalidate>' +
      '<label class="field"><span>Customer / shop name</span><input class="input" name="name" maxlength="80" autocomplete="off">' +
      '<em class="err" data-err="name"></em></label>' +
      '<div class="two"><label class="field"><span>Phone (optional)</span>' +
      '<input class="input" name="phone" inputmode="tel" maxlength="30" placeholder="xxx-xxx-xxxx" autocomplete="off">' +
      '<em class="err" data-err="phone"></em></label>' +
      '<div class="field"><span>Customer type</span><div class="seg" data-seg="type">' +
      '<button type="button" class="seg-btn" data-val="retail">Retail</button>' +
      '<button type="button" class="seg-btn" data-val="wholesale">Wholesale</button></div></div></div>' +
      '<label class="field"><span>Address (optional)</span><input class="input" name="address" maxlength="200" autocomplete="off"></label>' +
      '<label class="field"><span>Billing address (optional)</span><input class="input" name="billing_address" maxlength="250" autocomplete="off"></label>' +
      '<div class="two"><label class="field"><span>GSTIN (optional)</span><input class="input" name="gstin" maxlength="15" autocapitalize="characters" autocomplete="off"></label>' +
      '<label class="field"><span>State</span><select class="select" name="state_code"><option value="">Choose state</option></select></label></div>' +
      '<div class="field"><span>Previous balance (optional)</span><div class="balance-row">' +
      '<div class="seg" data-seg="otype"><button type="button" class="seg-btn" data-val="udhaar">Udhaar</button>' +
      '<button type="button" class="seg-btn" data-val="advance">Advance</button></div>' +
      '<div class="amt"><i>Rs</i><input name="opening_amount" inputmode="decimal" placeholder="0" autocomplete="off"></div></div>' +
      '<em class="err" data-err="opening_amount"></em><small class="hint" data-hint></small></div>' +
      (!edit ? '<section class="cust-opening-section"><div class="cust-opening-heading"><div><b>Opening cylinders with customer</b><small>Record cylinders already held before the first sale</small></div><button class="btn btn-white" type="button" data-opening-add>Add row</button></div><div data-opening-rows></div></section>' : '') +
      '<label class="field"><span>Note (optional)</span><textarea class="textarea" name="note" maxlength="500"></textarea></label>' +
      '<div class="form-error" role="alert"></div>' +
      '<div class="modal-foot"><button type="button" class="btn btn-white" data-close>Cancel</button>' +
      '<button type="submit" class="btn btn-dark"><i data-cicon="check"></i>Save</button></div></form>';
    renderIcons(body);

    const form = body.querySelector("form");
    const q = (n) => form.elements[n];
    populateStateSelect(q("state_code"), customer ? customer.state_code : "");
    if (!edit) {
      const rows = form.querySelector("[data-opening-rows]");
      let options = null;
      const add = form.querySelector("[data-opening-add]");
      async function addRow() {
        if (!options) options = await stockHoldOptions();
        if (!options.cylinders.length) { form.querySelector(".form-error").textContent = "Add cylinder sizes in Stock & Price before recording opening cylinders."; return; }
        addOpeningRow(rows, options);
      }
      add.addEventListener("click", () => {
        addRow().catch((err) => { form.querySelector(".form-error").textContent = err.message; });
      });
    }
    if (customer) {
      q("name").value = customer.name || "";
      q("phone").value = customer.phone || "";
      q("address").value = customer.address || "";
      q("billing_address").value = customer.billing_address || "";
      q("gstin").value = customer.gstin || "";
      q("state_code").value = customer.state_code || "";
      q("note").value = customer.note || "";
      q("opening_amount").value = opening ? String(Math.abs(opening)) : "";
    }
    function paint() {
      form.querySelectorAll(".seg-btn").forEach((b) => {
        b.classList.toggle("on", f[b.closest("[data-seg]").dataset.seg] === b.dataset.val);
      });
      form.querySelector("[data-hint]").textContent = f.otype === "udhaar"
        ? "Amount the customer already owes you." : "Amount the customer has already paid you in advance.";
    }
    paint();
    form.addEventListener("click", (e) => {
      const b = e.target.closest(".seg-btn");
      if (!b) return;
      f[b.closest("[data-seg]").dataset.seg] = b.dataset.val;
      paint();
    });
    q("opening_amount").addEventListener("input", (e) => cleanMoneyInput(e.target));

    let saving = false;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (saving) return;
      clearErrors(form);
      const name = q("name").value.trim();
      if (!name) { showError(form, { message: "Customer name is required.", data: { field: "name" } }); return; }
      saving = true;
      const saveBtn = form.querySelector('[type="submit"]');
      saveBtn.disabled = true;
      const payload = {
        name, type: f.type, phone: q("phone").value.trim(), address: q("address").value.trim(),
        billing_address: q("billing_address").value.trim(), gstin: q("gstin").value.trim().toUpperCase(),
        state_code: q("state_code").value.trim(),
        opening_type: f.otype, opening_amount: q("opening_amount").value.trim(), note: q("note").value.trim(),
      };
      if (!edit) payload.held = openingPayload(form.querySelector("[data-opening-rows]"));
      try {
        const res = edit ? await Api.put("/api/customers/" + customer.id, payload) : await Api.post("/api/customers", payload);
        UI.closeModal();
        toast(edit ? "Customer updated" : "Customer added");
        if (onSaved) onSaved(res);
      } catch (err) {
        showError(form, err);
      } finally {
        saving = false;
        saveBtn.disabled = false;
      }
    });
    q("name").focus();
  }

  /* ---------- Receive payment ---------- */
  function openReceive(opts) {
    const { customer, onSaved } = opts;
    const body = UI.openModal("Receive payment");
    const owed = Number(customer.balance) || 0;
    body.innerHTML =
      '<form novalidate>' +
      '<button type="button" class="cust-pick" data-pick><span class="avatar">' + esc(fmt.initials(customer.name)) + "</span>" +
      '<span class="cp-main"><small>Customer</small><b>' + esc(customer.name) + "</b></span>" + balanceTag(customer.balance) +
      '<i data-cicon="chevronsUpDown"></i></button>' +
      '<div class="field"><span>Amount received</span><div class="amt-row">' +
      '<div class="amt"><i>Rs</i><input name="amount" inputmode="decimal" placeholder="0" autocomplete="off"></div>' +
      (owed > 0 ? '<button type="button" class="btn btn-soft" data-full>Full</button>' : "") + "</div>" +
      '<em class="err" data-err="amount"></em><small class="hint" data-hint></small>' +
      '<small class="hint">Clears any opening balance first, then applies to the oldest outstanding invoice. Extra remains as customer advance.</small></div>' +
      '<div class="two"><label class="field"><span>Received in</span><select class="select" name="received_in">' +
      '<option value="cash">Cash in hand</option><option value="bank">Bank / UPI</option></select></label>' +
      '<label class="field"><span>Date</span><input class="input" type="date" name="date" max="' + today() + '"></label></div>' +
      '<label class="field"><span>Note (optional)</span><textarea class="textarea" name="note" maxlength="200"></textarea></label>' +
      '<div class="form-error" role="alert"></div>' +
      '<div class="modal-foot"><button type="button" class="btn btn-white" data-close>Cancel</button>' +
      '<button type="submit" class="btn btn-green" disabled><i data-cicon="check"></i>Save payment</button></div></form>';
    renderIcons(body);

    const form = body.querySelector("form");
    const q = (n) => form.elements[n];
    q("amount").value = opts.amount || "";
    q("received_in").value = opts.mode || "cash";
    q("date").value = opts.date || today();
    q("note").value = opts.note || "";
    const saveBtn = form.querySelector('[type="submit"]');
    const hint = form.querySelector("[data-hint]");

    function refresh() {
      const amt = Number(q("amount").value) || 0;
      saveBtn.disabled = !(amt > 0);
      hint.textContent = owed > 0 && amt > owed
        ? fmt.money(amt - owed) + " more than owed. The extra will stay as advance." : "";
    }
    refresh();
    q("amount").addEventListener("input", (e) => { cleanMoneyInput(e.target); refresh(); });
    const full = form.querySelector("[data-full]");
    if (full) full.addEventListener("click", () => { q("amount").value = String(owed); refresh(); q("amount").focus(); });

    form.querySelector("[data-pick]").addEventListener("click", () => {
      const keep = { amount: q("amount").value, mode: q("received_in").value, date: q("date").value, note: q("note").value, onSaved };
      UI.selectCustomer((c) => openReceive({ ...keep, customer: c }));
    });

    let saving = false;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (saving) return;
      clearErrors(form);
      saving = true;
      saveBtn.disabled = true;
      try {
        const res = await Api.post("/api/payments", {
          customer_id: customer.id, amount: q("amount").value, received_in: q("received_in").value,
          date: q("date").value || today(), note: q("note").value.trim(),
        });
        UI.closeModal();
        toast("Payment " + res.number + " saved");
        if (onSaved) onSaved(res);
      } catch (err) {
        showError(form, err);
        saving = false;
        refresh();
      }
    });
    q("amount").focus();
  }

  /* ---------- Opening cylinders on an existing customer ---------- */
  async function openOpeningCylinders({ customerId, customerName, onSaved }) {
    const body = UI.openModal("Add opening cylinders" + (customerName ? " · " + customerName : ""));
    body.innerHTML = '<form novalidate><p class="hint">Record cylinders that were already with this customer before the new tracking workflow.</p>' +
      '<div data-opening-rows></div><button class="btn btn-white" type="button" data-opening-add>Add another cylinder</button>' +
      '<div class="form-error" role="alert"></div><div class="modal-foot"><button type="button" class="btn btn-white" data-close>Cancel</button>' +
      '<button type="submit" class="btn btn-dark">Save opening cylinders</button></div></form>';
    const form = body.querySelector("form"), rows = form.querySelector("[data-opening-rows]");
    let options;
    try { options = await stockHoldOptions(); }
    catch (err) { form.querySelector(".form-error").textContent = "Could not load stock and suppliers. " + err.message; return; }
    if (!options.cylinders.length) { form.querySelector(".form-error").textContent = "Add cylinder sizes in Stock & Price first."; return; }
    addOpeningRow(rows, options);
    form.querySelector("[data-opening-add]").addEventListener("click", () => addOpeningRow(rows, options));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const held = openingPayload(rows);
      if (!held.length) { form.querySelector(".form-error").textContent = "Add at least one cylinder quantity."; return; }
      const btn = form.querySelector('[type="submit"]'); btn.disabled = true;
      try {
        await Api.post("/api/customers/" + customerId + "/opening-cylinders", { held });
        UI.closeModal(); toast("Opening cylinders recorded"); if (onSaved) onSaved();
      } catch (err) { form.querySelector(".form-error").textContent = err.message; btn.disabled = false; }
    });
  }

  /* ---------- Confirm ---------- */
  // onConfirm must return a promise; if it rejects, the message is shown and the popup stays.
  function openConfirm({ title, message, confirmLabel = "Yes", danger = false, cancelLabel = "Keep it", onConfirm }) {
    const body = UI.openModal(title);
    body.innerHTML =
      '<p class="confirm-text">' + esc(message) + "</p>" +
      '<div class="form-error" role="alert"></div>' +
      '<div class="modal-foot"><button type="button" class="btn btn-white" data-close>' + esc(cancelLabel) + "</button>" +
      '<button type="button" class="btn ' + (danger ? "btn-danger" : "btn-dark") + '" data-ok>' + esc(confirmLabel) + "</button></div>";
    const ok = body.querySelector("[data-ok]");
    let busy = false;
    ok.addEventListener("click", async () => {
      if (busy) return;
      busy = true;
      ok.disabled = true;
      body.querySelector(".form-error").textContent = "";
      try {
        await onConfirm();
        UI.closeModal();
      } catch (err) {
        body.querySelector(".form-error").textContent = err.message || "Something went wrong.";
        busy = false;
        ok.disabled = false;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => { renderIcons(); showFlash(); });

  return { date, today, balanceTag, toast, flash, renderIcons, exportData,
           openCustomerForm, openReceive, openOpeningCylinders, openConfirm };
})();
