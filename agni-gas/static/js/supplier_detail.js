(function () {
  const $ = (id) => document.getElementById(id);
  const sid = Number(window.SUPPLIER_ID);
  const esc = UI.esc, fmt = UI.fmt;
  let supplier = null, activeTab = "ledger", itemsCache = [], catalogItemsCache = [], ledgerRows = [], purchaseRows = [];



  function showError(message) {
    $("sd-error-text").textContent = message || "";
    $("sd-error").hidden = !message;
  }
  function balanceClass(value) { return value > 0 ? "payable" : value < 0 ? "advance" : "clear"; }
  function balanceText(value) { return value > 0 ? "To pay" : value < 0 ? "Advance available" : "Settled"; }

  async function loadSupplier() {
    showError("");
    try {
      supplier = await Api.get("/api/suppliers/" + sid);
      $("sd-main").hidden = false; $("sd-missing").hidden = true;
      $("sd-name").textContent = supplier.name;
      $("sd-name2").textContent = supplier.name;
      $("sd-gstin").textContent = "GSTIN: " + supplier.gstin;
      $("sd-avatar").textContent = fmt.initials(supplier.name);
      const bal = Number(supplier.balance) || 0;
      $("sd-balance").textContent = fmt.money(Math.abs(bal));
      $("sd-balance-label").textContent = balanceText(bal);
      $("sd-balance").parentElement.classList.toggle("is-advance", bal < 0);
      $("sd-purchase-count").textContent = supplier.purchase_count;
      $("sd-total-purchases").textContent = fmt.money(supplier.total_purchases);
      $("sd-total-paid").textContent = fmt.money(supplier.total_paid);
      $("sd-last-purchase").textContent = supplier.last_purchase || "—";
      $("sd-meta").innerHTML = [supplier.phone, supplier.address, supplier.note].filter(Boolean).map((v) => '<span>' + esc(v) + '</span>').join("") || "No additional contact details";
    } catch (err) {
      $("sd-main").hidden = true; $("sd-missing").hidden = false;
      showError("Could not load supplier. " + err.message);
    }
  }

  function setTab(tab) {
    activeTab = tab;
    document.querySelectorAll(".sp-detail-tabs [data-tab]").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
    if (tab === "ledger") loadLedger();
    if (tab === "purchases") loadPurchases();
    if (tab === "items") loadItems();
  }

  async function loadLedger() {
    const panel = $("sd-panel"); panel.innerHTML = '<div class="sp-state">Loading supplier ledger…</div>';
    try {
      const data = await Api.get("/api/suppliers/" + sid + "/ledger");
      ledgerRows = data.rows;
      panel.innerHTML = '<div class="sd-panel-pad"><div class="sd-panel-head"><h2>Account ledger</h2><b>Closing balance: ' + esc(fmt.money(data.closing_balance)) + '</b></div>' +
        '<p class="sd-note">Positive balances mean payable to the supplier. Negative balances are supplier advances.</p>' +
        '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Date</th><th>Detail</th><th class="num">Purchase</th><th class="num">Paid</th><th class="num">Balance</th><th></th></tr></thead><tbody>' +
        data.rows.map((r) => '<tr>' +
          '<td>' + esc(r.date || "—") + '</td><td><b>' + esc(r.detail) + '</b>' + (r.sub ? '<small class="sub">' + esc(r.sub) + '</small>' : '') + (r.status === "cancelled" ? '<small class="sub">Cancelled payment</small>' : '') + '</td>' +
          '<td class="num">' + (r.purchase ? esc(fmt.money(r.purchase)) : "—") + '</td><td class="num">' + (r.paid ? esc(fmt.money(r.paid)) : "—") + '</td>' +
          '<td class="num">' + esc(fmt.money(r.balance)) + '</td><td>' + (r.kind === "payment" && r.status === "active" ? '<button class="link-btn" type="button" data-cancel-payment="' + r.id + '">Cancel</button>' : "") + '</td></tr>'
        ).join("") + '</tbody></table></div></div>';
    } catch (err) { panel.innerHTML = '<div class="sp-state">Could not load ledger. ' + esc(err.message) + '</div>'; }
  }

  async function loadPurchases() {
    const panel = $("sd-panel"); panel.innerHTML = '<div class="sp-state">Loading purchases…</div>';
    try {
      const rows = await Api.get("/api/purchases?supplier_id=" + sid);
      purchaseRows = rows;
      panel.innerHTML = '<div class="sd-panel-pad"><div class="sd-panel-head"><h2>Purchases</h2><button class="btn btn-dark btn-sm" id="sd-add-purchase" type="button">New purchase</button></div>' +
        (rows.length ? '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Purchase</th><th>Date</th><th class="num">Total</th><th class="num">Paid</th><th>Status</th></tr></thead><tbody>' + rows.map((p) => '<tr><td><a href="/purchases/' + p.id + '">' + esc(p.number) + '</a><small class="sub">' + esc(p.items_summary) + '</small></td><td>' + esc(p.date) + '</td><td class="num">' + esc(fmt.money(p.total)) + '</td><td class="num">' + esc(fmt.money(p.paid)) + '</td><td><span class="sp-status sp-status-' + esc(p.status) + '">' + esc(p.status) + '</span></td></tr>').join("") + '</tbody></table></div>' : '<div class="sp-state">No purchases recorded for this supplier yet.</div>') + '</div>';
      const add = $("sd-add-purchase"); if (add) add.addEventListener("click", () => { location.href = "/purchases/new?supplier=" + sid; });
    } catch (err) { panel.innerHTML = '<div class="sp-state">Could not load purchases. ' + esc(err.message) + '</div>'; }
  }

  async function loadItems() {
    const panel = $("sd-panel"); panel.innerHTML = '<div class="sp-state">Loading supplier items…</div>';
    try {
      const [cylinders, otherItems] = await Promise.all([
        Api.get("/api/suppliers/" + sid + "/items"),
        Api.get("/api/suppliers/" + sid + "/catalog-items"),
      ]);
      itemsCache = cylinders;
      catalogItemsCache = otherItems;
      panel.innerHTML =
        '<div class="sd-panel-pad">' +
          '<section class="sd-item-section">' +
            '<div class="sd-panel-head"><div><h2>Cylinder sizes supplied</h2><small class="sd-note">Add the exact cylinder weights this supplier provides. Different suppliers may provide different weights.</small></div>' +
            '<button class="btn btn-dark btn-sm" id="sd-add-cylinder" type="button">＋ Add cylinder</button></div>' +
            (itemsCache.length ? '<div class="sd-cylinder-list">' + itemsCache.map((it) =>
              '<div class="sd-cylinder-row" data-cylinder-row="' + it.cylinder_type_id + '">' +
                '<span class="sd-cylinder-icon">▣</span>' +
                '<span class="sd-catalog-main"><b>' + esc(it.name) + '</b><small>Deposit: ' + esc(fmt.money(it.security_price)) + ' · Selling price: ' + esc(fmt.money(it.sale_price)) + '</small></span>' +
                '<span class="sd-catalog-price"><small>Supplier purchase rate</small><b>' + esc(fmt.money(it.purchase_price)) + '</b></span>' +
                '<span class="sd-catalog-actions"><button class="btn btn-white btn-sm" type="button" data-edit-cylinder="' + it.cylinder_type_id + '">Edit</button>' +
                '<button class="link-btn" type="button" data-remove-cylinder="' + it.cylinder_type_id + '">Remove</button></span>' +
              '</div>'
            ).join("") + '</div>' : '<div class="sp-state sd-catalog-empty">No cylinder weights added yet. Add the weights this supplier provides.</div>') +
            '<p class="sd-note">Enter the actual weight in kg for each supplier. Removing a supplier entry does not change stock or old purchases.</p>' +
          '</section>' +
          '<section class="sd-item-section sd-catalog-section">' +
            '<div class="sd-panel-head"><div><h2>Other items supplied</h2><small class="sd-note">Add the goods this supplier sells, with its purchase price and your sale price.</small></div><button class="btn btn-dark btn-sm" id="sd-add-catalog-item" type="button">＋ Add item</button></div>' +
            (catalogItemsCache.length ? '<div class="sd-catalog-list">' + catalogItemsCache.map((it) =>
              '<div class="sd-catalog-row" data-catalog-row="' + it.id + '">' +
                '<span class="sd-catalog-main"><b>' + esc(it.name) + '</b><small>' + esc(it.unit) + ' · In stock: ' + esc(it.stock) + '</small></span>' +
                '<span class="sd-catalog-price"><small>Supplier rate</small><b>' + esc(fmt.money(it.purchase_price)) + '</b></span>' +
                '<span class="sd-catalog-price"><small>Sale price</small><b>' + esc(fmt.money(it.sale_price)) + '</b></span>' +
                '<span class="sd-catalog-actions"><button class="btn btn-white btn-sm" type="button" data-edit-catalog="' + it.id + '">Edit</button><button class="link-btn" type="button" data-remove-catalog="' + it.id + '">Remove</button></span>' +
              '</div>'
            ).join("") + '</div>' : '<div class="sp-state sd-catalog-empty">No items added yet. Add the goods this supplier provides.</div>') +
          '</section>' +
        '</div>';

      $("sd-add-cylinder").addEventListener("click", () => SupplierUI.openCylinderItemForm({
        supplierId: sid, onSaved: loadItems,
      }));
      $("sd-add-catalog-item").addEventListener("click", () => SupplierUI.openCatalogItemForm({
        supplierId: sid, onSaved: loadItems,
      }));
    } catch (err) {
      panel.innerHTML = '<div class="sp-state">Could not load supplier items. ' + esc(err.message) + '</div>';
    }
  }

  $("sd-edit").addEventListener("click", () => SupplierUI.openSupplierForm({ supplier, onSaved: async () => { await loadSupplier(); setTab(activeTab); } }));
  $("sd-archive").addEventListener("click", () => SupplierUI.openConfirm({
    title: "Archive " + supplier.name + "?",
    message: "This supplier will be hidden from active lists. Its purchase and payment history will remain available. Any outstanding payable or advance must be settled first.",
    confirmLabel: "Archive supplier", danger: true,
    onConfirm: async () => { await Api.del("/api/suppliers/" + sid); SupplierUI.toast("Supplier archived"); location.href = "/suppliers-purchases?tab=suppliers"; },
  }));
  $("sd-new-purchase").addEventListener("click", () => { location.href = "/purchases/new?supplier=" + sid; });
  $("sd-pay").addEventListener("click", () => SupplierUI.openPaymentForm({ supplier, onSaved: async () => { await loadSupplier(); setTab(activeTab); } }));
  $("sd-statement").addEventListener("click", () => window.print());

  $("sd-retry").addEventListener("click", async () => { await loadSupplier(); setTab(activeTab); });
  document.querySelectorAll(".sp-detail-tabs [data-tab]").forEach((button) => button.addEventListener("click", () => setTab(button.dataset.tab)));
  $("sd-panel").addEventListener("click", (event) => {
    const editCylinder = event.target.closest("[data-edit-cylinder]");
    if (editCylinder) {
      const item = itemsCache.find((row) => row.cylinder_type_id === Number(editCylinder.dataset.editCylinder));
      if (item) SupplierUI.openCylinderItemForm({ supplierId: sid, item, onSaved: loadItems });
      return;
    }
    const removeCylinder = event.target.closest("[data-remove-cylinder]");
    if (removeCylinder) {
      const item = itemsCache.find((row) => row.cylinder_type_id === Number(removeCylinder.dataset.removeCylinder));
      if (!item) return;
      SupplierUI.openConfirm({
        title: "Remove " + item.name + " from this supplier?",
        message: "This cylinder size will no longer be available when recording purchases from this supplier. Stock and past purchase records will remain unchanged.",
        confirmLabel: "Remove cylinder", danger: true,
        onConfirm: async () => {
          await Api.del("/api/suppliers/" + sid + "/items/" + item.cylinder_type_id);
          SupplierUI.toast("Cylinder removed from supplier");
          await loadItems();
        },
      });
      return;
    }
    const editItem = event.target.closest("[data-edit-catalog]");
    if (editItem) {
      const item = catalogItemsCache.find((row) => row.id === Number(editItem.dataset.editCatalog));
      if (item) SupplierUI.openCatalogItemForm({ supplierId: sid, item, onSaved: loadItems });
      return;
    }
    const removeItem = event.target.closest("[data-remove-catalog]");
    if (removeItem) {
      const item = catalogItemsCache.find((row) => row.id === Number(removeItem.dataset.removeCatalog));
      if (!item) return;
      SupplierUI.openConfirm({
        title: "Remove " + item.name + " from this supplier?",
        message: "The item will no longer be available for new purchases from this supplier. The catalogue item, stock and old purchase history will be retained.",
        confirmLabel: "Remove item", danger: true,
        onConfirm: async () => { await Api.del("/api/suppliers/" + sid + "/catalog-items/" + item.id); SupplierUI.toast("Item removed from supplier"); await loadItems(); },
      });
      return;
    }
    const button = event.target.closest("[data-cancel-payment]");
    if (!button) return;
    SupplierUI.openConfirm({
      title: "Cancel supplier payment?",
      message: "The payment will be marked cancelled and added back to this supplier's outstanding balance. The record remains in the ledger.",
      confirmLabel: "Cancel payment", danger: true,
      onConfirm: async () => { await Api.post("/api/supplier-payments/" + button.dataset.cancelPayment + "/cancel"); SupplierUI.toast("Payment cancelled"); await loadSupplier(); loadLedger(); },
    });
  });

  (async () => {
    await loadSupplier();
    if (supplier) setTab(location.hash === "#items" ? "items" : "ledger");
  })();
})();
