// Shared supplier forms and payment dialogs for the supplier/purchase workspace.
(function () {
  const esc = UI.esc;
  const fmt = UI.fmt;

  function today() {
    const d = new Date();
    const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 10);
  }

  function toast(message, error = false) {
    let el = document.querySelector(".toast");
    if (!el) { el = document.createElement("div"); el.className = "toast"; document.body.appendChild(el); }
    el.textContent = message;
    el.classList.toggle("error", !!error);
    el.hidden = false;
    window.clearTimeout(el._hideTimer);
    el._hideTimer = window.setTimeout(() => { el.remove(); }, 2600);
  }

  function openSupplierForm({ supplier = null, onSaved } = {}) {
    const edit = !!supplier;
    const opening = Number(supplier && supplier.opening_balance) || 0;
    const body = UI.openModal(edit ? "Edit supplier" : "Add supplier");
    body.innerHTML =
      '<form novalidate>' +
      '<label class="field"><span>Supplier name *</span><input class="input" name="name" maxlength="100" required></label>' +
      '<label class="field"><span>GST number *</span><input class="input" name="gstin" maxlength="15" autocomplete="off" required><em class="err" data-err="gstin"></em><small class="hint">Enter the supplier’s 15-character GSTIN.</small></label>' +
      '<div class="two"><label class="field"><span>Phone (optional)</span><input class="input" name="phone" maxlength="30"></label><label class="field"><span>Address (optional)</span><input class="input" name="address" maxlength="250"></label></div>' +
      '<div class="field"><span>Previous balance (optional)</span><div class="balance-row"><div class="seg" data-seg="opening"><button class="seg-btn" data-val="payable" type="button">Payable</button><button class="seg-btn" data-val="advance" type="button">Advance</button></div><div class="amt"><i>Rs</i><input name="opening_amount" inputmode="decimal" placeholder="0"></div></div><small class="hint" data-opening-hint></small></div>' +
      '<label class="field"><span>Note (optional)</span><textarea class="textarea" name="note" maxlength="500"></textarea></label>' +
      '<div class="form-error" role="alert"></div>' +
      '<div class="modal-foot"><button class="btn btn-white" type="button" data-close>Cancel</button><button class="btn btn-dark" type="submit">Save supplier</button></div></form>';
    const form = body.querySelector("form");
    const q = (name) => form.elements[name];
    const state = { opening: opening < 0 ? "advance" : "payable" };
    if (supplier) {
      q("name").value = supplier.name || "";
      q("gstin").value = supplier.gstin || "";
      q("phone").value = supplier.phone || "";
      q("address").value = supplier.address || "";
      q("opening_amount").value = opening ? String(Math.abs(opening).toFixed(2)) : "";
      q("note").value = supplier.note || "";
    }
    function paint() {
      form.querySelectorAll(".seg-btn").forEach((b) => b.classList.toggle("on", b.dataset.val === state.opening));
      form.querySelector("[data-opening-hint]").textContent = state.opening === "payable"
        ? "Amount you already owe this supplier." : "Amount you have already paid in advance.";
    }
    paint();
    form.addEventListener("click", (e) => {
      const button = e.target.closest(".seg-btn");
      if (button) { state.opening = button.dataset.val; paint(); }
    });
    let saving = false;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (saving) return;
      const error = form.querySelector(".form-error");
      error.textContent = "";
      form.querySelectorAll("[data-err]").forEach((el) => { el.textContent = ""; });
      const payload = {
        name: q("name").value.trim(), gstin: q("gstin").value.trim().toUpperCase(),
        phone: q("phone").value.trim(), address: q("address").value.trim(), note: q("note").value.trim(),
        opening_type: state.opening, opening_amount: q("opening_amount").value.trim(),
      };
      if (!payload.name) { error.textContent = "Supplier name is required."; q("name").focus(); return; }
      if (!payload.gstin) { error.textContent = "GST number is required."; q("gstin").focus(); return; }
      saving = true;
      const button = form.querySelector('[type="submit"]'); button.disabled = true;
      try {
        const saved = edit ? await Api.put("/api/suppliers/" + supplier.id, payload) : await Api.post("/api/suppliers", payload);
        UI.closeModal();
        toast(edit ? "Supplier updated" : "Supplier added");
        if (onSaved) onSaved(saved);
      } catch (err) {
        if (err.data && err.data.field) {
          const target = form.querySelector('[data-err="' + err.data.field + '"]');
          if (target) target.textContent = err.message;
          else error.textContent = err.message;
        } else error.textContent = err.message || "Could not save supplier.";
      } finally { saving = false; button.disabled = false; }
    });
    q("name").focus();
  }

  async function openCatalogItemForm({ supplierId, item = null, onSaved } = {}) {
    if (!supplierId) { toast("Select a supplier first.", true); return; }
    const editing = !!item;
    const body = UI.openModal(editing ? "Edit supplier purchase price" : "Link item to supplier");
    body.innerHTML =
      '<form novalidate>' +
      (editing
        ? '<p class="hint-text">Supplier purchase rate for <b>' + esc(item.name) + '</b>.</p>'
        : '<label class="field"><span>Choose an item from Stock &amp; Price</span>' +
          '<select class="select" name="existing_item"><option value="">Loading items…</option></select>' +
          '<small class="hint" data-item-hint></small></label>') +
      '<label class="field"><span>Purchase price from this supplier *</span><div class="amt"><i>Rs</i>' +
        '<input name="purchase_price" inputmode="decimal" autocomplete="off" placeholder="0"></div>' +
        '<em class="err" data-err="purchase_price"></em></label>' +
      '<div class="form-error" role="alert"></div>' +
      '<div class="modal-foot"><button class="btn btn-white" type="button" data-close>Cancel</button>' +
      '<button class="btn btn-dark" type="submit">' + (editing ? 'Save price' : 'Link item') + '</button></div></form>';
    const form = body.querySelector("form");
    const q = (name) => form.elements[name];
    if (editing) {
      q("purchase_price").value = item.purchase_price || "";
    } else {
      const select = q("existing_item");
      try {
        const [allItems, linkedItems] = await Promise.all([
          Api.get("/api/items"),
          Api.get("/api/suppliers/" + supplierId + "/catalog-items"),
        ]);
        const linked = new Set(linkedItems.map((row) => Number(row.id)));
        const available = allItems.filter((row) => !linked.has(Number(row.id)));
        select.innerHTML = '<option value="">Choose an item</option>' + available.map((row) =>
          '<option value="' + row.id + '" data-rate="' + esc(row.purchase_price) + '">' +
          esc(row.name) + ' (' + esc(row.unit) + ' · stock ' + esc(row.stock) + ')</option>'
        ).join("");
        if (!allItems.length) {
          select.innerHTML = '<option value="">No items available</option>';
          select.disabled = true;
          form.querySelector("[data-item-hint]").textContent = "No items yet. Create items in Stock & Price first.";
        } else if (!available.length) {
          select.innerHTML = '<option value="">All items are already linked</option>';
          select.disabled = true;
          form.querySelector("[data-item-hint]").textContent = "All active catalogue items are already linked to this supplier.";
        } else {
          form.querySelector("[data-item-hint]").textContent = "Items are created and maintained in Stock & Price. This only links an existing item.";
        }
      } catch (err) {
        select.innerHTML = '<option value="">Could not load items</option>';
        select.disabled = true;
        form.querySelector("[data-item-hint]").textContent = err.message || "Could not load catalogue items.";
      }
      select.addEventListener("change", () => {
        const selected = select.selectedOptions[0];
        if (selected && selected.dataset.rate) q("purchase_price").value = selected.dataset.rate;
      });
    }

    let saving = false;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (saving) return;
      const error = form.querySelector(".form-error");
      error.textContent = "";
      const purchasePrice = q("purchase_price").value.trim();
      if (!(Number(purchasePrice) > 0)) {
        error.textContent = "Enter a purchase price greater than zero.";
        q("purchase_price").focus();
        return;
      }
      let url, payload;
      if (editing) {
        url = "/api/suppliers/" + supplierId + "/catalog-items/" + item.id;
        payload = { purchase_price: purchasePrice };
      } else {
        const itemId = Number(q("existing_item").value) || 0;
        if (!itemId) {
          error.textContent = "Choose an item from Stock & Price first.";
          q("existing_item").focus();
          return;
        }
        url = "/api/suppliers/" + supplierId + "/catalog-items";
        payload = { item_id: itemId, purchase_price: purchasePrice };
      }
      saving = true;
      const button = form.querySelector('[type="submit"]');
      button.disabled = true;
      try {
        const saved = editing ? await Api.put(url, payload) : await Api.post(url, payload);
        UI.closeModal();
        toast(editing ? "Supplier purchase price updated" : "Item linked to supplier");
        if (onSaved) onSaved(saved);
      } catch (err) {
        error.textContent = err.message || "Could not save supplier item.";
      } finally {
        saving = false;
        button.disabled = false;
      }
    });
    if (editing) q("purchase_price").focus();
  }

  function openPaymentForm({ supplier, onSaved }) {
    const body = UI.openModal("Pay supplier · " + supplier.name);
    const currentBalance = Number(supplier.balance) || 0;
    const balanceLabel = currentBalance > 0 ? "To pay" : currentBalance < 0 ? "Advance available" : "Settled";
    const balanceClass = currentBalance < 0 ? "bal-green" : currentBalance > 0 ? "bal-red" : "bal-clear";
    body.innerHTML =
      '<form novalidate>' +
      '<div class="cust-pick"><span class="avatar">' + esc(fmt.initials(supplier.name)) + '</span><span class="cp-main"><small>Supplier</small><b>' + esc(supplier.name) + '</b></span><span class="bal ' + balanceClass + '">' + esc(fmt.money(Math.abs(currentBalance))) + ' <small>' + balanceLabel + '</small></span></div>' +
      '<label class="field"><span>Amount paid *</span><div class="amt"><i>Rs</i><input name="amount" inputmode="decimal" autocomplete="off" placeholder="0"></div></label>' +
      '<div class="two"><label class="field"><span>Paid from</span><select class="select" name="paid_from"><option value="cash">Cash in hand</option><option value="bank">Bank / UPI</option></select></label><label class="field"><span>Date</span><input class="input" type="date" name="date" max="' + today() + '"></label></div>' +
      '<label class="field"><span>Apply to purchase (optional)</span><select class="select" name="purchase_id"><option value="">General supplier payment</option></select></label>' +
      '<label class="field"><span>Note (optional)</span><textarea class="textarea" name="note" maxlength="200"></textarea></label>' +
      '<div class="form-error" role="alert"></div>' +
      '<div class="modal-foot"><button type="button" class="btn btn-white" data-close>Cancel</button><button type="submit" class="btn btn-green">Save payment</button></div></form>';
    const form = body.querySelector("form");
    form.elements.date.value = today();
    Api.get("/api/purchases?supplier_id=" + supplier.id).then((rows) => {
      const select = form.elements.purchase_id;
      rows.filter((p) => Number(p.due) > 0).forEach((p) => {
        const option = document.createElement("option"); option.value = p.id;
        option.textContent = p.number + " · due " + fmt.money(p.due); select.appendChild(option);
      });
    }).catch(() => { /* General supplier payment remains available. */ });
    let saving = false;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (saving) return;
      const amount = form.elements.amount.value.trim();
      if (!(Number(amount) > 0)) { form.querySelector(".form-error").textContent = "Enter an amount greater than zero."; return; }
      saving = true;
      const button = form.querySelector('[type="submit"]'); button.disabled = true;
      try {
        await Api.post("/api/suppliers/" + supplier.id + "/payments", {
          amount, paid_from: form.elements.paid_from.value, date: form.elements.date.value,
          note: form.elements.note.value.trim(),
          purchase_id: form.elements.purchase_id.value || null,
        });
        UI.closeModal(); toast("Supplier payment recorded");
        if (onSaved) onSaved();
      } catch (err) {
        form.querySelector(".form-error").textContent = err.message || "Could not record payment.";
      } finally { saving = false; button.disabled = false; }
    });
    form.elements.amount.focus();
  }

  function openConfirm({ title, message, confirmLabel = "Confirm", danger = false, onConfirm }) {
    const body = UI.openModal(title);
    body.innerHTML = '<p class="confirm-text">' + esc(message) + '</p><div class="form-error" role="alert"></div>' +
      '<div class="modal-foot"><button type="button" class="btn btn-white" data-close>Cancel</button>' +
      '<button type="button" class="btn ' + (danger ? "btn-danger" : "btn-dark") + '" data-confirm>' + esc(confirmLabel) + '</button></div>';
    const button = body.querySelector("[data-confirm]");
    button.addEventListener("click", async () => {
      button.disabled = true;
      try { await onConfirm(); UI.closeModal(); }
      catch (err) { body.querySelector(".form-error").textContent = err.message || "Action failed."; button.disabled = false; }
    });
  }

  window.SupplierUI = { toast, today, openSupplierForm, openCatalogItemForm, openPaymentForm, openConfirm };
})();
