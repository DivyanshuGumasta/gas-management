// // New purchase form. Item availability is supplier-specific; creation happens in Stock & Price.
// (function () {
//   const $ = (id) => document.getElementById(id);
//   const esc = UI.esc, fmt = UI.fmt;
//   const state = { supplier: null, cylinders: [], catalog: [] };

//   function today() { return SupplierUI.today(); }
//   function cents(value) {
//     const n = Number(value);
//     return Number.isFinite(n) ? Math.round(n * 100) : 0;
//   }
//   function moneyFromCents(value) { return fmt.money((value || 0) / 100); }
//   function showError(message) {
//     $("pn-error-text").textContent = message || "";
//     $("pn-error").hidden = !message;
//   }
//   function value(input) {
//     const n = Number(input && input.value);
//     return Number.isFinite(n) && n > 0 ? n : 0;
//   }
//   function setSupplier(supplier) {
//     state.supplier = supplier;
//     state.cylinders = [];
//     state.catalog = [];
//     $("pn-items").innerHTML = '<div class="pn-empty">' + (supplier ? 'Loading linked cylinders…' : 'Select a supplier to load its linked cylinders.') + '</div>';
//     $("pn-catalog-lines").innerHTML = '<div class="pn-empty">' + (supplier ? 'Loading linked items…' : 'Select a supplier to load its linked items.') + '</div>';
//     $("pn-add-catalog-row").disabled = true;
//     $("pn-supplier-id").value = supplier ? String(supplier.id) : "";
//     $("pn-supplier-avatar").textContent = supplier ? fmt.initials(supplier.name) : "?";
//     $("pn-supplier-name").textContent = supplier ? supplier.name : "Select supplier";
//     $("pn-supplier-meta").textContent = supplier
//       ? (supplier.gstin ? "GSTIN: " + supplier.gstin : (supplier.phone || "Supplier selected"))
//       : "Choose who supplied these items";
//     const bal = Number(supplier && supplier.balance) || 0;
//     const balance = $("pn-supplier-balance");
//     balance.className = "bal " + (bal > 0 ? "bal-red" : bal < 0 ? "bal-green" : "bal-clear");
//     balance.textContent = supplier ? (bal > 0 ? fmt.money(bal) + " · To pay" : bal < 0 ? fmt.money(-bal) + " · Advance" : "Clear") : "Not selected";
//     $("pn-save").disabled = true;
//   }

//   function stepper(field, current, max = null) {
//     return '<div class="pn-stepper" data-stepper="' + field + '">' +
//       '<button type="button" class="pn-step pn-step-minus" data-step="-1" data-field="' + field + '" aria-label="Decrease">−</button>' +
//       '<input type="number" min="0" step="1" value="0" inputmode="numeric" data-' + field + ' ' +
//         (max === null ? '' : 'max="' + max + '"') + '>' +
//       '<button type="button" class="pn-step pn-step-plus" data-step="1" data-field="' + field + '" aria-label="Increase">+</button>' +
//       '</div>';
//   }

//   function cylinderCard(item) {
//     return '<article class="pn-item" data-item="' + item.id + '">' +
//       '<div class="pn-item-head"><span class="pn-cylinder-icon">▣</span><div class="pn-item-title"><b>' + esc(item.name) + '</b>' +
//         '<small>Full: ' + item.full_stock + ' · Empty: ' + item.empty_stock + '</small></div>' +
//         '<label class="pn-rate"><small>Rate</small><span><i>Rs</i><input type="number" min="0" step="0.01" value="' + esc(item.rate) + '" data-rate></span></label></div>' +
//       '<div class="pn-qty-line"><b>Full in</b>' + stepper('full', 0) + '</div>' +
//       '<div class="pn-qty-line"><b>Empty out</b>' + stepper('empty', 0, item.empty_stock) + '</div>' +
//       '<button class="pn-bought-toggle" type="button" data-toggle-new-empty>＋ Bought new empty cylinders?</button>' +
//       '<div class="pn-new-empty" data-new-empty-wrap hidden><div><b>New empty</b><small>Security: ' + esc(fmt.money(item.security_rate)) + '</small></div>' + stepper('new-empty', 0) + '</div>' +
//       '<div class="pn-item-footer"><span>Amount</span><b data-line-total>Rs 0</b></div></article>';
//   }

//   async function loadCylinderOptions() {
//     const box = $("pn-items");
//     if (!state.supplier) {
//       state.cylinders = [];
//       box.innerHTML = '<div class="pn-empty">Select a supplier to load its linked cylinders.</div>';
//       return;
//     }
//     box.innerHTML = '<div class="pn-empty">Loading linked cylinders…</div>';
//     try {
//       state.cylinders = await Api.get("/api/purchases/options?supplier_id=" + state.supplier.id);
//       box.innerHTML = state.cylinders.length
//         ? state.cylinders.map(cylinderCard).join("")
//         : '<div class="pn-empty">This supplier has no linked cylinders. Link them on the supplier page.</div>';
//       calculate();
//     } catch (err) {
//       state.cylinders = [];
//       box.innerHTML = '<div class="pn-empty">Could not load cylinders: ' + esc(err.message) + '</div>';
//     }
//   }

//   function catalogRow() {
//     return '<div class="pn-catalog-row" data-catalog-row="">' +
//       '<label class="pn-catalog-name"><span>Item</span><select class="select" data-catalog-select>' +
//         '<option value="">Choose an item</option>' +
//       '</select><small data-catalog-stock></small></label>' +
//       '<label><span>Quantity</span><input class="input" type="number" min="0" step="0.001" value="0" placeholder="0" data-catalog-qty></label>' +
//       '<label><span>Rate / unit</span><input class="input" type="number" min="0.01" step="0.01" value="" data-catalog-rate></label>' +
//       '<div class="pn-catalog-total"><small>Amount</small><b data-catalog-total>Rs 0</b>' +
//         '<button class="link-btn" type="button" data-remove-catalog>Remove</button></div>' +
//     '</div>';
//   }

//   function refreshCatalogSelects() {
//     const rows = Array.from($("pn-catalog-lines").querySelectorAll("[data-catalog-row]"));
//     const selectedIds = rows.map((row) => Number(row.dataset.catalogRow)).filter(Boolean);
//     rows.forEach((row) => {
//       const select = row.querySelector("[data-catalog-select]");
//       const current = Number(row.dataset.catalogRow) || 0;
//       const available = state.catalog.filter((item) => !selectedIds.includes(item.id) || item.id === current);
//       select.innerHTML = '<option value="">Choose an item</option>' + available.map((item) =>
//         '<option value="' + item.id + '" ' + (item.id === current ? 'selected' : '') + '>' +
//         esc(item.name) + ' (' + esc(item.unit) + ')</option>'
//       ).join("");
//       select.value = current ? String(current) : "";
//     });
//   }

//   async function loadCatalogOptions() {
//     const box = $("pn-catalog-lines");
//     const add = $("pn-add-catalog-row");
//     if (!state.supplier) {
//       state.catalog = [];
//       add.disabled = true;
//       box.innerHTML = '<div class="pn-empty">Select a supplier to load its linked items.</div>';
//       return;
//     }
//     box.innerHTML = '<div class="pn-empty">Loading linked items…</div>';
//     try {
//       state.catalog = await Api.get("/api/purchases/catalog-options?supplier_id=" + state.supplier.id);
//       add.disabled = state.catalog.length === 0;
//       box.innerHTML = state.catalog.length
//         ? '<div class="pn-catalog-hint">Choose only from items linked to this supplier.</div>'
//         : '<div class="pn-empty">This supplier has no linked items. Link items on the supplier page.</div>';
//     } catch (err) {
//       state.catalog = [];
//       add.disabled = true;
//       box.innerHTML = '<div class="pn-empty">Could not load items: ' + esc(err.message) + '</div>';
//     }
//   }

//   async function loadOptions() {
//     await Promise.all([loadCylinderOptions(), loadCatalogOptions()]);
//     calculate();
//   }

//   function addCatalogRow() {
//     if (!state.catalog.length) {
//       SupplierUI.toast("This supplier has no linked items. Link items on the supplier page.", true);
//       return;
//     }
//     const box = $("pn-catalog-lines");
//     const used = new Set(Array.from(box.querySelectorAll("[data-catalog-row]"))
//       .map((row) => Number(row.dataset.catalogRow)).filter(Boolean));
//     if (used.size >= state.catalog.length) {
//       SupplierUI.toast("All linked items are already on this purchase.", true);
//       return;
//     }
//     const hint = box.querySelector(".pn-catalog-hint");
//     if (hint) hint.remove();
//     box.insertAdjacentHTML("beforeend", catalogRow());
//     const row = box.lastElementChild;
//     row.querySelector("[data-catalog-select]").addEventListener("change", (event) => {
//       const id = Number(event.target.value) || 0;
//       const item = state.catalog.find((candidate) => candidate.id === id);
//       row.dataset.catalogRow = item ? String(item.id) : "";
//       row.querySelector("[data-catalog-stock]").textContent = item
//         ? "In stock: " + item.stock + " " + item.unit : "";
//       row.querySelector("[data-catalog-rate]").value = item ? item.rate : "";
//       const quantityInput = row.querySelector("[data-catalog-qty]");
//       quantityInput.value = item ? "1" : "0";
//       const wholeUnits = item && ["pcs", "packet", "box", "set", "pair"].includes(item.unit);
//       quantityInput.step = wholeUnits ? "1" : "0.001";
//       quantityInput.min = item ? (wholeUnits ? "1" : "0.001") : "0";
//       refreshCatalogSelects();
//       calculate();
//     });
//     refreshCatalogSelects();
//     calculate();
//   }

//   function calculate() {
//     let subtotalCents = 0;
//     $("pn-items").querySelectorAll("[data-item]").forEach((card) => {
//       const item = state.cylinders.find((row) => row.id === Number(card.dataset.item));
//       if (!item) return;
//       const rateCents = cents(card.querySelector("[data-rate]").value);
//       const full = value(card.querySelector("[data-full]"));
//       const empty = value(card.querySelector("[data-empty]"));
//       const newEmpty = value(card.querySelector("[data-new-empty]"));
//       const securityCents = cents(item.security_rate);
//       const lineCents = full * rateCents + newEmpty * securityCents;
//       subtotalCents += lineCents;
//       card.querySelector("[data-line-total]").textContent = moneyFromCents(lineCents);
//       const emptyInput = card.querySelector("[data-empty]");
//       emptyInput.max = item.empty_stock;
//       emptyInput.classList.toggle("invalid", empty > item.empty_stock);
//     });
//     $("pn-catalog-lines").querySelectorAll("[data-catalog-row]").forEach((row) => {
//       const itemId = Number(row.dataset.catalogRow) || 0;
//       const quantity = Number(row.querySelector("[data-catalog-qty]").value) || 0;
//       const rateCents = cents(row.querySelector("[data-catalog-rate]").value);
//       const lineCents = itemId > 0 && quantity > 0 ? Math.round(quantity * rateCents) : 0;
//       subtotalCents += lineCents;
//       row.querySelector("[data-catalog-total]").textContent = moneyFromCents(lineCents);
//     });
//     $("pn-items").querySelectorAll("[data-stepper]").forEach((stepper) => {
//       const input = stepper.querySelector("input");
//       const current = Number(input.value) || 0;
//       const max = input.max ? Number(input.max) : Infinity;
//       const minus = stepper.querySelector('[data-step="-1"]');
//       const plus = stepper.querySelector('[data-step="1"]');
//       minus.disabled = current <= 0;
//       plus.disabled = current >= max;
//     });
//     const gstRate = Math.max(0, Math.min(100, Number($("pn-gst").value) || 0));
//     const gstCents = Math.round(subtotalCents * gstRate / 100);
//     const totalCents = subtotalCents + gstCents;
//     const status = $("pn-payment-status").value;
//     const paidInput = $("pn-paid");
//     if (status === "paid") paidInput.value = (totalCents / 100).toFixed(2);
//     if (status === "credit") paidInput.value = "0.00";
//     paidInput.disabled = status !== "partial";
//     $("pn-paid-from").disabled = status === "credit";
//     $("pn-paid-hint").textContent = status === "paid"
//       ? "The full purchase amount will be recorded as paid."
//       : status === "partial" ? "Enter the amount paid now. The remaining balance stays payable." : "No payment is recorded now. The full amount stays payable.";
//     $("pn-subtotal").textContent = moneyFromCents(subtotalCents);
//     $("pn-gst-label").textContent = String(gstRate);
//     $("pn-gst-amount").value = (gstCents / 100).toFixed(2);
//     $("pn-gst-display").textContent = moneyFromCents(gstCents);
//     $("pn-total").textContent = moneyFromCents(totalCents);
//     if (status === "partial" && cents(paidInput.value) > totalCents) paidInput.value = (totalCents / 100).toFixed(2);
//     const hasLines = subtotalCents > 0;
//     $("pn-save").disabled = !state.supplier || !hasLines;
//   }

//   function collectCylinderItems() {
//     const result = [];
//     $("pn-items").querySelectorAll("[data-item]").forEach((card) => {
//       const item = state.cylinders.find((row) => row.id === Number(card.dataset.item));
//       if (!item) return;
//       const full = Math.floor(value(card.querySelector("[data-full]")));
//       const empty = Math.floor(value(card.querySelector("[data-empty]")));
//       const newEmpty = Math.floor(value(card.querySelector("[data-new-empty]")));
//       if (!full && !empty && !newEmpty) return;
//       result.push({ cylinder_type_id: item.id, full_in: full, empty_out: empty, new_empty: newEmpty,
//         rate: card.querySelector("[data-rate]").value.trim() || "0" });
//     });
//     return result;
//   }

//   function collectCatalogItems() {
//     const items = [];
//     const seen = new Set();
//     for (const row of $("pn-catalog-lines").querySelectorAll("[data-catalog-row]")) {
//       const id = Number(row.dataset.catalogRow) || 0;
//       const quantity = row.querySelector("[data-catalog-qty]").value.trim();
//       const rate = row.querySelector("[data-catalog-rate]").value.trim();
//       if (!(Number(quantity) > 0)) continue;
//       if (!id) throw new Error("Choose an item from this supplier's linked items.");
//       if (seen.has(id)) throw new Error("An item can only appear once in a purchase.");
//       seen.add(id);
//       const item = state.catalog.find((candidate) => candidate.id === id);
//       if (item && ["pcs", "packet", "box", "set", "pair"].includes(item.unit) && !Number.isInteger(Number(quantity))) {
//         throw new Error(item.name + " is counted in whole " + item.unit + "; enter a whole quantity.");
//       }
//       if (!(Number(rate) > 0)) throw new Error("Enter a valid rate for every other item.");
//       items.push({ item_id: id, quantity, rate });
//     }
//     return items;
//   }

//   $("pn-supplier-pick").addEventListener("click", () => {
//     UI.selectSupplier(async (supplier) => {
//       setSupplier(supplier);
//       showError("");
//       await loadOptions();
//     });
//   });
//   $("pn-items").addEventListener("click", (event) => {
//     const toggle = event.target.closest("[data-toggle-new-empty]");
//     if (toggle) {
//       const card = toggle.closest("[data-item]");
//       const wrap = card.querySelector("[data-new-empty-wrap]");
//       wrap.hidden = !wrap.hidden;
//       toggle.classList.toggle("on", !wrap.hidden);
//       return;
//     }
//     const step = event.target.closest("[data-step]");
//     if (!step) return;
//     const card = step.closest("[data-item]");
//     const field = step.dataset.field;
//     const input = card.querySelector("[data-" + field + "]");
//     const max = input.max ? Number(input.max) : Infinity;
//     input.value = String(Math.max(0, Math.min(max, (Number(input.value) || 0) + Number(step.dataset.step))));
//     calculate();
//   });
//   $("pn-items").addEventListener("input", (event) => { if (event.target.matches("input")) calculate(); });
//   $("pn-catalog-lines").addEventListener("input", (event) => { if (event.target.matches("input")) calculate(); });
//   $("pn-catalog-lines").addEventListener("click", (event) => {
//     const button = event.target.closest("[data-remove-catalog]");
//     if (!button) return;
//     button.closest("[data-catalog-row]").remove();
//     refreshCatalogSelects();
//     calculate();
//   });
//   $("pn-add-catalog-row").addEventListener("click", addCatalogRow);
//   $("pn-payment-status").addEventListener("change", calculate);
//   $("pn-gst").addEventListener("input", calculate);
//   $("pn-paid").addEventListener("input", calculate);

//   $("pn-form").addEventListener("submit", async (event) => {
//     event.preventDefault();
//     showError("");
//     if (!state.supplier) { showError("Select a supplier before saving the purchase."); return; }
//     const items = collectCylinderItems();
//     let catalogItems;
//     try { catalogItems = collectCatalogItems(); }
//     catch (err) { showError(err.message); return; }
//     if (!items.length && !catalogItems.length) { showError("Enter at least one quantity before saving."); return; }
//     const status = $("pn-payment-status").value;
//     let paidAmount = status === "paid" ? $("pn-total").textContent.replace(/[^0-9.]/g, "") :
//       status === "credit" ? "0" : $("pn-paid").value.trim();
//     if (status === "partial" && !(Number(paidAmount) > 0)) {
//       showError("Enter the amount paid now, or choose Credit."); return;
//     }
//     if (status === "partial" && Number(paidAmount) >= Number($("pn-total").textContent.replace(/[^0-9.]/g, ""))) {
//       showError("The partial payment must be less than the total. Choose Paid if the full amount was paid."); return;
//     }
//     const date = $("pn-date").value || today();
//     const payload = {
//       supplier_id: state.supplier.id,
//       date,
//       items,
//       catalog_items: catalogItems,
//       gst_percent: $("pn-gst").value || "0",
//       paid_amount: paidAmount || "0",
//       paid_from: $("pn-paid-from").value,
//       update_prices: $("pn-update-prices").checked,
//       note: $("pn-note").value.trim(),
//     };
//     const attachment = $("pn-bill").files[0];
//     if (attachment && attachment.size > 5 * 1024 * 1024) { showError("Supplier bill attachment must be 5 MB or smaller."); return; }
//     const formData = new FormData();
//     formData.append("payload", JSON.stringify(payload));
//     if (attachment) formData.append("supplier_bill", attachment, attachment.name);
//     const button = $("pn-save");
//     button.disabled = true; button.textContent = "Saving…";
//     try {
//       const result = await Api.postForm("/api/purchases", formData);
//       SupplierUI.toast("Purchase " + result.number + " saved");
//       location.href = "/purchases/" + result.id;
//     } catch (err) {
//       showError(err.message || "Could not save purchase.");
//       button.textContent = "✓ Save purchase";
//       calculate();
//     }
//   });

//   $("pn-date").value = today();
//   $("pn-date").max = today();
//   setSupplier(null);
//   const preferred = new URLSearchParams(location.search).get("supplier");
//   if (preferred) {
//     Api.get("/api/suppliers/" + encodeURIComponent(preferred))
//       .then(async (supplier) => { setSupplier(supplier); await loadOptions(); })
//       .catch((err) => showError("Could not load the selected supplier. " + err.message));
//   }
//   calculate();
// })();
// New purchase form. Item availability is supplier-specific; creation happens in Stock & Price.
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = UI.esc, fmt = UI.fmt;
  const state = { supplier: null, cylinders: [], catalog: [] };

  function today() { return SupplierUI.today(); }
  function cents(value) {
    const n = Number(value);
    return Number.isFinite(n) ? Math.round(n * 100) : 0;
  }
  function moneyFromCents(value) { return fmt.money((value || 0) / 100); }
  function showError(message) {
    $("pn-error-text").textContent = message || "";
    $("pn-error").hidden = !message;
  }
  function value(input) {
    const n = Number(input && input.value);
    return Number.isFinite(n) && n > 0 ? n : 0;
  }
  function setSupplier(supplier) {
    state.supplier = supplier;
    state.cylinders = [];
    state.catalog = [];
    $("pn-items").innerHTML = '<div class="pn-empty">' + (supplier ? 'Loading linked cylinders…' : 'Select a supplier to load its linked cylinders.') + '</div>';
    $("pn-catalog-lines").innerHTML = '<div class="pn-empty">' + (supplier ? 'Loading linked items…' : 'Select a supplier to load its linked items.') + '</div>';
    $("pn-add-catalog-row").disabled = true;
    $("pn-supplier-id").value = supplier ? String(supplier.id) : "";
    $("pn-supplier-avatar").textContent = supplier ? fmt.initials(supplier.name) : "?";
    $("pn-supplier-name").textContent = supplier ? supplier.name : "Select supplier";
    $("pn-supplier-meta").textContent = supplier
      ? (supplier.gstin ? "GSTIN: " + supplier.gstin : (supplier.phone || "Supplier selected"))
      : "Choose who supplied these items";
    const bal = Number(supplier && supplier.balance) || 0;
    const balance = $("pn-supplier-balance");
    balance.className = "bal " + (bal > 0 ? "bal-red" : bal < 0 ? "bal-green" : "bal-clear");
    balance.textContent = supplier ? (bal > 0 ? fmt.money(bal) + " · To pay" : bal < 0 ? fmt.money(-bal) + " · Advance" : "Clear") : "Not selected";
    $("pn-save").disabled = true;
  }

  function stepper(field, current, max = null) {
    return '<div class="pn-stepper" data-stepper="' + field + '">' +
      '<button type="button" class="pn-step pn-step-minus" data-step="-1" data-field="' + field + '" aria-label="Decrease">−</button>' +
      '<input type="number" min="0" step="1" value="0" inputmode="numeric" data-' + field + ' ' +
        (max === null ? '' : 'max="' + max + '"') + '>' +
      '<button type="button" class="pn-step pn-step-plus" data-step="1" data-field="' + field + '" aria-label="Increase">+</button>' +
      '</div>';
  }

  function cylinderCard(item) {
    return '<article class="pn-item" data-item="' + item.id + '">' +
      '<div class="pn-item-head"><span class="pn-cylinder-icon">▣</span><div class="pn-item-title"><b>' + esc(item.name) + '</b>' +
        '<small>Full: ' + item.full_stock + ' · Empty: ' + item.empty_stock + '</small></div>' +
        '<label class="pn-rate"><small>Rate</small><span><i>Rs</i><input type="number" min="0" step="0.01" value="' + esc(item.rate) + '" data-rate></span></label></div>' +
      '<div class="pn-qty-line"><b>Full in</b>' + stepper('full', 0) + '</div>' +
      '<div class="pn-qty-line"><b>Empty out</b>' + stepper('empty', 0, item.empty_stock) + '</div>' +
      '<button class="pn-bought-toggle" type="button" data-toggle-new-empty>＋ Bought new empty cylinders?</button>' +
      '<div class="pn-new-empty" data-new-empty-wrap hidden><div><b>New empty</b><small>Security: ' + esc(fmt.money(item.security_rate)) + '</small></div>' + stepper('new-empty', 0) + '</div>' +
      '<div class="pn-item-footer"><span>Amount</span><b data-line-total>Rs 0</b></div></article>';
  }

  async function loadCylinderOptions() {
    const box = $("pn-items");
    if (!state.supplier) {
      state.cylinders = [];
      box.innerHTML = '<div class="pn-empty">Select a supplier to load its linked cylinders.</div>';
      return;
    }
    box.innerHTML = '<div class="pn-empty">Loading linked cylinders…</div>';
    try {
      state.cylinders = await Api.get("/api/purchases/options?supplier_id=" + state.supplier.id);
      box.innerHTML = state.cylinders.length
        ? state.cylinders.map(cylinderCard).join("")
        : '<div class="pn-empty">This supplier has no cylinder weights yet. Add them in the supplier’s Items supplied tab.</div>';
      calculate();
    } catch (err) {
      state.cylinders = [];
      box.innerHTML = '<div class="pn-empty">Could not load cylinders: ' + esc(err.message) + '</div>';
    }
  }

  function catalogRow() {
    return '<div class="pn-catalog-row" data-catalog-row="">' +
      '<label class="pn-catalog-name"><span>Item</span><select class="select" data-catalog-select>' +
        '<option value="">Choose an item</option>' +
      '</select><small data-catalog-stock></small></label>' +
      '<label><span>Quantity</span><input class="input" type="number" min="0" step="0.001" value="0" placeholder="0" data-catalog-qty></label>' +
      '<label><span>Rate / unit</span><input class="input" type="number" min="0.01" step="0.01" value="" data-catalog-rate></label>' +
      '<div class="pn-catalog-total"><small>Amount</small><b data-catalog-total>Rs 0</b>' +
        '<button class="link-btn" type="button" data-remove-catalog>Remove</button></div>' +
    '</div>';
  }

  function refreshCatalogSelects() {
    const rows = Array.from($("pn-catalog-lines").querySelectorAll("[data-catalog-row]"));
    const selectedIds = rows.map((row) => Number(row.dataset.catalogRow)).filter(Boolean);
    rows.forEach((row) => {
      const select = row.querySelector("[data-catalog-select]");
      const current = Number(row.dataset.catalogRow) || 0;
      const available = state.catalog.filter((item) => !selectedIds.includes(item.id) || item.id === current);
      select.innerHTML = '<option value="">Choose an item</option>' + available.map((item) =>
        '<option value="' + item.id + '" ' + (item.id === current ? 'selected' : '') + '>' +
        esc(item.name) + ' (' + esc(item.unit) + ')</option>'
      ).join("");
      select.value = current ? String(current) : "";
    });
  }

  async function loadCatalogOptions() {
    const box = $("pn-catalog-lines");
    const add = $("pn-add-catalog-row");
    if (!state.supplier) {
      state.catalog = [];
      add.disabled = true;
      box.innerHTML = '<div class="pn-empty">Select a supplier to load its linked items.</div>';
      return;
    }
    box.innerHTML = '<div class="pn-empty">Loading linked items…</div>';
    try {
      state.catalog = await Api.get("/api/purchases/catalog-options?supplier_id=" + state.supplier.id);
      add.disabled = state.catalog.length === 0;
      box.innerHTML = state.catalog.length
        ? '<div class="pn-catalog-hint">Choose only from items linked to this supplier.</div>'
        : '<div class="pn-empty">This supplier has no items yet. Add them in the supplier’s Items supplied tab.</div>';
    } catch (err) {
      state.catalog = [];
      add.disabled = true;
      box.innerHTML = '<div class="pn-empty">Could not load items: ' + esc(err.message) + '</div>';
    }
  }

  async function loadOptions() {
    await Promise.all([loadCylinderOptions(), loadCatalogOptions()]);
    calculate();
  }

  function addCatalogRow() {
    if (!state.catalog.length) {
      SupplierUI.toast("This supplier has no items yet. Add them in the supplier’s Items supplied tab.", true);
      return;
    }
    const box = $("pn-catalog-lines");
    const used = new Set(Array.from(box.querySelectorAll("[data-catalog-row]"))
      .map((row) => Number(row.dataset.catalogRow)).filter(Boolean));
    if (used.size >= state.catalog.length) {
      SupplierUI.toast("All linked items are already on this purchase.", true);
      return;
    }
    const hint = box.querySelector(".pn-catalog-hint");
    if (hint) hint.remove();
    box.insertAdjacentHTML("beforeend", catalogRow());
    const row = box.lastElementChild;
    row.querySelector("[data-catalog-select]").addEventListener("change", (event) => {
      const id = Number(event.target.value) || 0;
      const item = state.catalog.find((candidate) => candidate.id === id);
      row.dataset.catalogRow = item ? String(item.id) : "";
      row.querySelector("[data-catalog-stock]").textContent = item
        ? "In stock: " + item.stock + " " + item.unit : "";
      row.querySelector("[data-catalog-rate]").value = item ? item.rate : "";
      const quantityInput = row.querySelector("[data-catalog-qty]");
      quantityInput.value = item ? "1" : "0";
      const wholeUnits = item && ["pcs", "packet", "box", "set", "pair"].includes(item.unit);
      quantityInput.step = wholeUnits ? "1" : "0.001";
      quantityInput.min = item ? (wholeUnits ? "1" : "0.001") : "0";
      refreshCatalogSelects();
      calculate();
    });
    refreshCatalogSelects();
    calculate();
  }

  function calculate() {
    let subtotalCents = 0;
    $("pn-items").querySelectorAll("[data-item]").forEach((card) => {
      const item = state.cylinders.find((row) => row.id === Number(card.dataset.item));
      if (!item) return;
      const rateCents = cents(card.querySelector("[data-rate]").value);
      const full = value(card.querySelector("[data-full]"));
      const empty = value(card.querySelector("[data-empty]"));
      const newEmpty = value(card.querySelector("[data-new-empty]"));
      const securityCents = cents(item.security_rate);
      const lineCents = full * rateCents + newEmpty * securityCents;
      subtotalCents += lineCents;
      card.querySelector("[data-line-total]").textContent = moneyFromCents(lineCents);
      const emptyInput = card.querySelector("[data-empty]");
      emptyInput.max = item.empty_stock;
      emptyInput.classList.toggle("invalid", empty > item.empty_stock);
    });
    $("pn-catalog-lines").querySelectorAll("[data-catalog-row]").forEach((row) => {
      const itemId = Number(row.dataset.catalogRow) || 0;
      const quantity = Number(row.querySelector("[data-catalog-qty]").value) || 0;
      const rateCents = cents(row.querySelector("[data-catalog-rate]").value);
      const lineCents = itemId > 0 && quantity > 0 ? Math.round(quantity * rateCents) : 0;
      subtotalCents += lineCents;
      row.querySelector("[data-catalog-total]").textContent = moneyFromCents(lineCents);
    });
    $("pn-items").querySelectorAll("[data-stepper]").forEach((stepper) => {
      const input = stepper.querySelector("input");
      const current = Number(input.value) || 0;
      const max = input.max ? Number(input.max) : Infinity;
      const minus = stepper.querySelector('[data-step="-1"]');
      const plus = stepper.querySelector('[data-step="1"]');
      minus.disabled = current <= 0;
      plus.disabled = current >= max;
    });
    const gstRate = Math.max(0, Math.min(100, Number($("pn-gst").value) || 0));
    const gstCents = Math.round(subtotalCents * gstRate / 100);
    const totalCents = subtotalCents + gstCents;
    const status = $("pn-payment-status").value;
    const paidInput = $("pn-paid");
    if (status === "paid") paidInput.value = (totalCents / 100).toFixed(2);
    if (status === "credit") paidInput.value = "0.00";
    paidInput.disabled = status !== "partial";
    $("pn-paid-from").disabled = status === "credit";
    $("pn-paid-hint").textContent = status === "paid"
      ? "The full purchase amount will be recorded as paid."
      : status === "partial" ? "Enter the amount paid now. The remaining balance stays payable." : "No payment is recorded now. The full amount stays payable.";
    $("pn-subtotal").textContent = moneyFromCents(subtotalCents);
    $("pn-gst-label").textContent = String(gstRate);
    $("pn-gst-amount").value = (gstCents / 100).toFixed(2);
    $("pn-gst-display").textContent = moneyFromCents(gstCents);
    $("pn-total").textContent = moneyFromCents(totalCents);
    if (status === "partial" && cents(paidInput.value) > totalCents) paidInput.value = (totalCents / 100).toFixed(2);
    const hasLines = subtotalCents > 0;
    $("pn-save").disabled = !state.supplier || !hasLines;
  }

  function collectCylinderItems() {
    const result = [];
    $("pn-items").querySelectorAll("[data-item]").forEach((card) => {
      const item = state.cylinders.find((row) => row.id === Number(card.dataset.item));
      if (!item) return;
      const full = Math.floor(value(card.querySelector("[data-full]")));
      const empty = Math.floor(value(card.querySelector("[data-empty]")));
      const newEmpty = Math.floor(value(card.querySelector("[data-new-empty]")));
      if (!full && !empty && !newEmpty) return;
      result.push({ cylinder_type_id: item.id, full_in: full, empty_out: empty, new_empty: newEmpty,
        rate: card.querySelector("[data-rate]").value.trim() || "0" });
    });
    return result;
  }

  function collectCatalogItems() {
    const items = [];
    const seen = new Set();
    for (const row of $("pn-catalog-lines").querySelectorAll("[data-catalog-row]")) {
      const id = Number(row.dataset.catalogRow) || 0;
      const quantity = row.querySelector("[data-catalog-qty]").value.trim();
      const rate = row.querySelector("[data-catalog-rate]").value.trim();
      if (!(Number(quantity) > 0)) continue;
      if (!id) throw new Error("Choose an item from this supplier's linked items.");
      if (seen.has(id)) throw new Error("An item can only appear once in a purchase.");
      seen.add(id);
      const item = state.catalog.find((candidate) => candidate.id === id);
      if (item && ["pcs", "packet", "box", "set", "pair"].includes(item.unit) && !Number.isInteger(Number(quantity))) {
        throw new Error(item.name + " is counted in whole " + item.unit + "; enter a whole quantity.");
      }
      if (!(Number(rate) > 0)) throw new Error("Enter a valid rate for every other item.");
      items.push({ item_id: id, quantity, rate });
    }
    return items;
  }

  $("pn-supplier-pick").addEventListener("click", () => {
    UI.selectSupplier(async (supplier) => {
      setSupplier(supplier);
      showError("");
      await loadOptions();
    });
  });
  $("pn-items").addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-toggle-new-empty]");
    if (toggle) {
      const card = toggle.closest("[data-item]");
      const wrap = card.querySelector("[data-new-empty-wrap]");
      wrap.hidden = !wrap.hidden;
      toggle.classList.toggle("on", !wrap.hidden);
      return;
    }
    const step = event.target.closest("[data-step]");
    if (!step) return;
    const card = step.closest("[data-item]");
    const field = step.dataset.field;
    const input = card.querySelector("[data-" + field + "]");
    const max = input.max ? Number(input.max) : Infinity;
    input.value = String(Math.max(0, Math.min(max, (Number(input.value) || 0) + Number(step.dataset.step))));
    calculate();
  });
  $("pn-items").addEventListener("input", (event) => { if (event.target.matches("input")) calculate(); });
  $("pn-catalog-lines").addEventListener("input", (event) => { if (event.target.matches("input")) calculate(); });
  $("pn-catalog-lines").addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-catalog]");
    if (!button) return;
    button.closest("[data-catalog-row]").remove();
    refreshCatalogSelects();
    calculate();
  });
  $("pn-add-catalog-row").addEventListener("click", addCatalogRow);
  $("pn-payment-status").addEventListener("change", calculate);
  $("pn-gst").addEventListener("input", calculate);
  $("pn-paid").addEventListener("input", calculate);

  $("pn-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    if (!state.supplier) { showError("Select a supplier before saving the purchase."); return; }
    const items = collectCylinderItems();
    let catalogItems;
    try { catalogItems = collectCatalogItems(); }
    catch (err) { showError(err.message); return; }
    if (!items.length && !catalogItems.length) { showError("Enter at least one quantity before saving."); return; }
    const status = $("pn-payment-status").value;
    let paidAmount = status === "paid" ? $("pn-total").textContent.replace(/[^0-9.]/g, "") :
      status === "credit" ? "0" : $("pn-paid").value.trim();
    if (status === "partial" && !(Number(paidAmount) > 0)) {
      showError("Enter the amount paid now, or choose Credit."); return;
    }
    if (status === "partial" && Number(paidAmount) >= Number($("pn-total").textContent.replace(/[^0-9.]/g, ""))) {
      showError("The partial payment must be less than the total. Choose Paid if the full amount was paid."); return;
    }
    const date = $("pn-date").value || today();
    const payload = {
      supplier_id: state.supplier.id,
      date,
      items,
      catalog_items: catalogItems,
      gst_percent: $("pn-gst").value || "0",
      paid_amount: paidAmount || "0",
      paid_from: $("pn-paid-from").value,
      update_prices: $("pn-update-prices").checked,
      note: $("pn-note").value.trim(),
    };
    const attachment = $("pn-bill").files[0];
    if (attachment && attachment.size > 5 * 1024 * 1024) { showError("Supplier bill attachment must be 5 MB or smaller."); return; }
    const formData = new FormData();
    formData.append("payload", JSON.stringify(payload));
    if (attachment) formData.append("supplier_bill", attachment, attachment.name);
    const button = $("pn-save");
    button.disabled = true; button.textContent = "Saving…";
    try {
      const result = await Api.postForm("/api/purchases", formData);
      SupplierUI.toast("Purchase " + result.number + " saved");
      location.href = "/purchases/" + result.id;
    } catch (err) {
      showError(err.message || "Could not save purchase.");
      button.textContent = "✓ Save purchase";
      calculate();
    }
  });

  $("pn-date").value = today();
  $("pn-date").max = today();
  setSupplier(null);
  const preferred = new URLSearchParams(location.search).get("supplier");
  if (preferred) {
    Api.get("/api/suppliers/" + encodeURIComponent(preferred))
      .then(async (supplier) => { setSupplier(supplier); await loadOptions(); })
      .catch((err) => showError("Could not load the selected supplier. " + err.message));
  }
  calculate();
})();
