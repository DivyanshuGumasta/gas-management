(function () {
  const $ = (id) => document.getElementById(id);
  const esc = UI.esc, fmt = UI.fmt;
  let cylinderItems = [];
  let catalogItems = [];
  let suppliers = [];

  function today() { return SupplierUI.today(); }
  function money(value) { return fmt.money((Number(value) || 0).toFixed(2)); }
  function showError(message) {
    $("pn-error-text").textContent = message || "";
    $("pn-error").hidden = !message;
  }
  function selectedSupplier() { return Number($("pn-supplier").value) || 0; }

  async function loadSuppliers(preferredId) {
    suppliers = await Api.get("/api/suppliers");
    const select = $("pn-supplier");
    select.innerHTML = '<option value="">Select supplier</option>' + suppliers.map((s) =>
      '<option value="' + s.id + '">' + esc(s.name) + ' · ' + esc(s.gstin) + '</option>'
    ).join("");
    if (preferredId && suppliers.some((s) => s.id === Number(preferredId))) select.value = String(preferredId);
    if (select.value) await loadItems();
    else {
      $("pn-create-catalog").disabled = true;
      $("pn-add-catalog-row").disabled = true;
    }
  }

  function cylinderCard(item) {
    return '<article class="pn-item" data-item="' + item.id + '">' +
      '<div class="pn-item-head"><b>' + esc(item.name) + '</b><span class="pn-stock">Full: ' + item.full_stock + ' · Empty: ' + item.empty_stock + '</span></div>' +
      '<label class="pn-item-rate"><span>Rate per full cylinder</span><input type="number" min="0" step="0.01" value="' + esc(item.rate) + '" data-rate></label>' +
      '<div class="pn-qty-grid">' +
      '<label>Full in<input type="number" min="0" max="100000" step="1" value="0" data-full></label>' +
      '<label>Empty out<input type="number" min="0" max="' + item.empty_stock + '" step="1" value="0" data-empty></label>' +
      '<label>New empty<input type="number" min="0" max="100000" step="1" value="0" data-new-empty></label>' +
      '</div><div class="pn-item-footer"><span>New empty security rate: ' + esc(fmt.money(item.security_rate)) + '</span><b data-line-total>Rs 0</b></div></article>';
  }

  async function loadCatalogOptions() {
    const sid = selectedSupplier();
    const box = $("pn-catalog-lines");
    if (!sid) {
      catalogItems = [];
      box.innerHTML = '<div class="sp-state">Select a supplier to load its other items.</div>';
      $("pn-create-catalog").disabled = true;
      $("pn-add-catalog-row").disabled = true;
      return;
    }
    try {
      catalogItems = await Api.get("/api/purchases/catalog-options?supplier_id=" + encodeURIComponent(sid));
      box.innerHTML = catalogItems.length
        ? '<div class="pn-catalog-empty">No other item lines added to this purchase yet.</div>'
        : '<div class="pn-catalog-empty">This supplier has no other items yet. Create one to use it in this or future purchases.</div>';
      $("pn-create-catalog").disabled = false;
      $("pn-add-catalog-row").disabled = !catalogItems.length;
      calculate();
    } catch (err) {
      catalogItems = [];
      box.innerHTML = '<div class="pn-catalog-empty">Could not load supplier items: ' + esc(err.message) + '</div>';
      $("pn-create-catalog").disabled = false;
      $("pn-add-catalog-row").disabled = true;
    }
  }

  async function loadItems() {
    const sid = selectedSupplier();
    $("pn-items").innerHTML = '<div class="sp-state">Loading cylinder types…</div>';
    try {
      const url = "/api/purchases/options" + (sid ? "?supplier_id=" + encodeURIComponent(sid) : "");
      cylinderItems = await Api.get(url);
      $("pn-items").innerHTML = cylinderItems.length
        ? cylinderItems.map(cylinderCard).join("")
        : '<div class="sp-state">No active cylinder types. Add them in Stock &amp; Price first.</div>';
      $("pn-items").querySelectorAll("input").forEach((input) => input.addEventListener("input", calculate));
    } catch (err) {
      cylinderItems = [];
      $("pn-items").innerHTML = '<div class="sp-state">Could not load cylinder types: ' + esc(err.message) + '</div>';
    }
    await loadCatalogOptions();
    calculate();
  }

  function num(input) {
    const n = Number(input && input.value);
    return Number.isFinite(n) && n > 0 ? n : 0;
  }

  function addCatalogRow(preselectedId) {
    if (!catalogItems.length) {
      SupplierUI.toast("Add an item to this supplier first.", true);
      return;
    }
    const box = $("pn-catalog-lines");
    const emptyState = box.querySelector(".pn-catalog-empty");
    if (emptyState) emptyState.remove();
    const used = new Set(Array.from(box.querySelectorAll("[data-catalog-select]"))
      .map((select) => Number(select.value)).filter(Boolean));
    if (preselectedId && used.has(Number(preselectedId))) {
      SupplierUI.toast("That item is already on this purchase.", true);
      return;
    }
    const available = catalogItems.filter((item) => !used.has(item.id));
    const chosen = Number(preselectedId) || (available[0] && available[0].id);
    if (!chosen) {
      SupplierUI.toast("Each item can only be added once per purchase.", true);
      return;
    }
    const item = catalogItems.find((row) => row.id === chosen);
    const row = document.createElement("div");
    row.className = "pn-catalog-row";
    row.innerHTML =
      '<label class="pn-catalog-name"><span>Item</span><select class="select" data-catalog-select>' +
        '<option value="">Select item</option>' + catalogItems.map((it) =>
          '<option value="' + it.id + '" ' + (it.id === chosen ? 'selected' : '') + '>' + esc(it.name) + ' (' + esc(it.unit) + ')</option>'
        ).join("") +
      '</select><small data-catalog-stock></small></label>' +
      '<label class="pn-catalog-qty"><span>Quantity</span><input class="input" type="number" min="0" step="0.001" value="1" data-catalog-qty></label>' +
      '<label class="pn-catalog-rate"><span>Rate / unit</span><input class="input" type="number" min="0.01" step="0.01" value="' + esc(item.rate) + '" data-catalog-rate></label>' +
      '<div class="pn-catalog-total"><small>Amount</small><b data-catalog-total>' + money(Number(item.rate)) + '</b><button type="button" class="link-btn" data-remove-catalog-row>Remove</button></div>';
    box.appendChild(row);
    const select = row.querySelector("[data-catalog-select]");
    select.addEventListener("change", () => {
      const selected = catalogItems.find((it) => it.id === Number(select.value));
      if (selected) {
        row.querySelector("[data-catalog-rate]").value = selected.rate;
        row.querySelector("[data-catalog-stock]").textContent = "In stock: " + selected.stock + " " + selected.unit;
      } else row.querySelector("[data-catalog-stock]").textContent = "";
      calculate();
    });
    row.querySelector("[data-catalog-stock]").textContent = "In stock: " + item.stock + " " + item.unit;
    row.querySelectorAll("input").forEach((input) => input.addEventListener("input", calculate));
    row.querySelector("[data-remove-catalog-row]").addEventListener("click", () => {
      row.remove();
      if (!box.querySelector("[data-catalog-row]")) {
        // No sentinel is needed when options exist; render a helpful empty state.
        if (!box.querySelector(".pn-catalog-row")) box.innerHTML = '<div class="pn-catalog-empty">No other item lines added to this purchase yet.</div>';
      }
      calculate();
    });
    row.dataset.catalogRow = "1";
    calculate();
  }

  function calculate() {
    let subtotal = 0;
    $("pn-items").querySelectorAll("[data-item]").forEach((card) => {
      const item = cylinderItems.find((x) => x.id === Number(card.dataset.item));
      if (!item) return;
      const rate = num(card.querySelector("[data-rate]"));
      const full = num(card.querySelector("[data-full]"));
      const empty = num(card.querySelector("[data-empty]"));
      const newEmpty = num(card.querySelector("[data-new-empty]"));
      const line = full * rate + newEmpty * Number(item.security_rate);
      subtotal += line;
      card.querySelector("[data-line-total]").textContent = money(line);
      const emptyInput = card.querySelector("[data-empty]");
      emptyInput.max = item.empty_stock;
      emptyInput.classList.toggle("invalid", empty > item.empty_stock);
    });
    $("pn-catalog-lines").querySelectorAll(".pn-catalog-row").forEach((row) => {
      const quantity = num(row.querySelector("[data-catalog-qty]"));
      const rate = num(row.querySelector("[data-catalog-rate]"));
      const line = quantity * rate;
      subtotal += line;
      row.querySelector("[data-catalog-total]").textContent = money(line);
    });
    const gstRate = Math.max(0, Math.min(100, Number($("pn-gst").value) || 0));
    const gst = Math.round(subtotal * gstRate) / 100;
    const total = subtotal + gst;
    const paid = num($("pn-paid"));
    $("pn-subtotal").textContent = money(subtotal);
    $("pn-gst-label").textContent = String(gstRate);
    $("pn-gst-amount").textContent = money(gst);
    $("pn-total").textContent = money(total);
    $("pn-balance").textContent = money(Math.max(0, total - paid));
    $("pn-paid").max = total.toFixed(2);
  }

  function collectItems() {
    const items = [];
    $("pn-items").querySelectorAll("[data-item]").forEach((card) => {
      const id = Number(card.dataset.item);
      const full = num(card.querySelector("[data-full]"));
      const empty = num(card.querySelector("[data-empty]"));
      const newEmpty = num(card.querySelector("[data-new-empty]"));
      if (full + empty + newEmpty > 0) {
        items.push({
          cylinder_type_id: id, full_in: full, empty_out: empty, new_empty: newEmpty,
          rate: card.querySelector("[data-rate]").value.trim() || "0",
        });
      }
    });
    return items;
  }

  function collectCatalogItems() {
    const items = [], seen = new Set();
    for (const row of $("pn-catalog-lines").querySelectorAll(".pn-catalog-row")) {
      const itemId = Number(row.querySelector("[data-catalog-select]").value);
      const quantity = row.querySelector("[data-catalog-qty]").value.trim();
      const rate = row.querySelector("[data-catalog-rate]").value.trim();
      if (!(Number(quantity) > 0)) continue;
      if (!itemId) throw new Error("Choose an item for each other-goods line.");
      if (seen.has(itemId)) throw new Error("An item can only appear once in a purchase.");
      seen.add(itemId);
      if (!(Number(rate) > 0)) throw new Error("Enter a valid rate for every other-goods item.");
      items.push({ item_id: itemId, quantity, rate });
    }
    return items;
  }

  $("pn-supplier").addEventListener("change", loadItems);
  $("pn-gst").addEventListener("input", calculate);
  $("pn-paid").addEventListener("input", calculate);
  $("pn-add-catalog-row").addEventListener("click", () => addCatalogRow());
  $("pn-create-catalog").addEventListener("click", () => {
    const sid = selectedSupplier();
    if (!sid) { showError("Select a supplier before adding an item."); return; }
    SupplierUI.openCatalogItemForm({ supplierId: sid, onSaved: (item) => {
      const option = { id: item.id, name: item.name, unit: item.unit, stock: item.stock, rate: item.purchase_price };
      const index = catalogItems.findIndex((row) => row.id === option.id);
      if (index >= 0) catalogItems[index] = option;
      else catalogItems.push(option);
      $("pn-add-catalog-row").disabled = false;
      addCatalogRow(item.id);
      showError("");
    } });
  });
  $("pn-add-supplier").addEventListener("click", () => SupplierUI.openSupplierForm({ onSaved: async (supplier) => {
    await loadSuppliers(supplier.id); showError("");
  } }));

  $("pn-form").addEventListener("submit", async (event) => {
    event.preventDefault(); showError("");
    const supplierId = selectedSupplier();
    if (!supplierId) { showError("Select a supplier before saving."); $("pn-supplier").focus(); return; }
    const items = collectItems();
    let catalogPayload;
    try { catalogPayload = collectCatalogItems(); }
    catch (err) { showError(err.message); return; }
    if (!items.length && !catalogPayload.length) { showError("Enter at least one item quantity in the purchase."); return; }
    const date = $("pn-date").value || today();
    const payload = {
      supplier_id: supplierId, date, items, catalog_items: catalogPayload,
      gst_percent: $("pn-gst").value || "0",
      paid_amount: $("pn-paid").value || "0",
      paid_from: $("pn-paid-from").value,
      update_prices: $("pn-update-prices").checked,
      note: $("pn-note").value.trim(),
    };
    const attachment = $("pn-bill").files[0];
    if (attachment && attachment.size > 5 * 1024 * 1024) { showError("Supplier bill attachment must be 5 MB or smaller."); return; }
    const formData = new FormData();
    formData.append("payload", JSON.stringify(payload));
    if (attachment) formData.append("supplier_bill", attachment, attachment.name);
    const button = $("pn-save"); button.disabled = true; button.textContent = "Saving…";
    try {
      const result = await Api.postForm("/api/purchases", formData);
      SupplierUI.toast("Purchase " + result.number + " saved");
      location.href = "/purchases/" + result.id;
    } catch (err) {
      showError(err.message || "Could not save purchase.");
      button.disabled = false; button.textContent = "Save purchase";
    }
  });

  $("pn-date").value = today();
  const preferred = new URLSearchParams(location.search).get("supplier");
  loadSuppliers(preferred).catch((err) => showError("Could not load suppliers. " + err.message));
})();
