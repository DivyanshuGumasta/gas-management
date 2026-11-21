// Main Suppliers & Purchases workspace.
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = UI.esc, fmt = UI.fmt;
  const tabs = {
    suppliers: { button: $("sp-tab-suppliers"), view: $("sp-view-suppliers") },
    purchases: { button: $("sp-tab-purchases"), view: $("sp-view-purchases") },
  };
  let supplierTimer, purchaseTimer;
  let period = "month";
  let supplierRows = [], purchaseRows = [];

  function exportCsv(filename, headers, rows) {
    const quote = (value) => '"' + String(value ?? "").replace(/"/g, '""') + '"';
    const csv = [headers, ...rows].map((row) => row.map(quote).join(",")).join("\r\n");
    const blob = new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
  }

  function setTab(name, writeUrl = true) {
    const selected = name === "purchases" ? "purchases" : "suppliers";
    Object.entries(tabs).forEach(([key, item]) => {
      const active = key === selected;
      item.button.setAttribute("aria-selected", active ? "true" : "false");
      item.button.tabIndex = active ? 0 : -1;
      item.view.hidden = !active;
    });
    if (writeUrl) {
      const url = new URL(location.href); url.searchParams.set("tab", selected);
      history.replaceState({}, "", url);
    }
    if (selected === "purchases") { loadPurchaseSummary(); loadPurchases(); }
    else { loadSupplierSummary(); loadSuppliers(); }
  }

  function showError(message) {
    $("sp-error-text").textContent = message || "";
    $("sp-error").hidden = !message;
  }

  function balanceMarkup(raw) {
    const value = Number(raw) || 0;
    if (value > 0) return '<span class="sp-payable">' + esc(fmt.money(value)) + ' · To pay</span>';
    if (value < 0) return '<span class="sp-advance">' + esc(fmt.money(-value)) + ' · Advance</span>';
    return '<span class="sp-clear">Clear</span>';
  }

  async function loadSupplierSummary() {
    try {
      const data = await Api.get("/api/suppliers/summary");
      $("sp-supplier-total").textContent = data.supplier_count;
      $("sp-supplier-payable").textContent = fmt.money(data.payable);
      $("sp-supplier-advance").textContent = fmt.money(data.advance);
    } catch (err) { showError("Could not load supplier totals. " + err.message); }
  }

  async function loadSuppliers() {
    showError("");
    const list = $("sp-supplier-list");
    list.innerHTML = '<div class="sp-state">Loading suppliers…</div>';
    try {
      const rows = await Api.get("/api/suppliers?q=" + encodeURIComponent($("sp-supplier-search").value.trim()));
      supplierRows = rows;
      $("sp-supplier-count").textContent = rows.length + (rows.length === 1 ? " supplier" : " suppliers");
      if (!rows.length) {
        list.innerHTML = '<div class="sp-state">No suppliers found. Use “Add supplier” to create one.</div>';
        return;
      }
      list.innerHTML = rows.map((s) => {
        const contact = [s.gstin ? "GSTIN: " + s.gstin : "", s.phone || "", s.address || ""].filter(Boolean).join(" · ");
        return '<a class="sp-supplier-row" href="/suppliers-purchases/supplier/' + s.id + '">' +
          '<span class="sp-supplier-avatar">' + esc(fmt.initials(s.name)) + '</span>' +
          '<span class="sp-supplier-main"><b>' + esc(s.name) + '</b><small>' + esc(contact || "No contact details") + '</small>' +
          '<small>' + s.purchase_count + ' purchases · Total ' + esc(fmt.money(s.total_purchases)) + '</small></span>' +
          '<span class="sp-supplier-balance"><small>Current balance</small><b>' + balanceMarkup(s.balance) + '</b></span></a>';
      }).join("");
    } catch (err) {
      list.innerHTML = '<div class="sp-state">Supplier list could not be loaded.</div>';
      $("sp-supplier-count").textContent = "";
      showError("Could not load suppliers. " + err.message);
    }
  }

  function getDateRange() {
    const now = new Date();
    const iso = (d) => {
      const x = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
      return x.toISOString().slice(0, 10);
    };
    if (period === "today") return { from: iso(now), to: iso(now) };
    if (period === "7d") { const d = new Date(now); d.setDate(d.getDate() - 6); return { from: iso(d), to: iso(now) }; }
    if (period === "month") return { from: iso(new Date(now.getFullYear(), now.getMonth(), 1)), to: iso(now) };
    if (period === "custom") return { from: $("sp-from").value, to: $("sp-to").value };
    return {};
  }

  async function loadPurchaseSummary() {
    const params = new URLSearchParams(getDateRange());
    try {
      const data = await Api.get("/api/purchases/summary?" + params);
      $("sp-purchase-total").textContent = fmt.money(data.total);
      $("sp-purchase-count").textContent = data.purchase_count + (data.purchase_count === 1 ? " record" : " records");
      $("sp-purchase-payable").textContent = fmt.money(data.payable);
    } catch (err) { showError("Could not load purchase totals. " + err.message); }
  }

  async function loadPurchases() {
    showError("");
    const params = new URLSearchParams(getDateRange());
    const q = $("sp-purchase-search").value.trim();
    if (q) params.set("q", q);
    const list = $("sp-purchase-list");
    list.innerHTML = '<div class="sp-state">Loading purchase history…</div>';
    try {
      const rows = await Api.get("/api/purchases?" + params);
      purchaseRows = rows;
      if (!rows.length) { list.innerHTML = '<div class="sp-state">No purchases found for this period.</div>'; return; }
      list.innerHTML = rows.map((p) =>
        '<a class="sp-purchase-row" href="/purchases/' + p.id + '">' +
        '<span class="sp-purchase-main"><b>' + esc(p.supplier) + '</b><small>' + esc(p.number) + ' · ' + esc(p.items_summary) + '</small></span>' +
        '<span class="sp-purchase-meta"><b>' + esc(p.date) + '</b><small>' + (p.has_attachment ? 'Supplier bill attached' : 'No attachment') + '</small></span>' +
        '<span class="sp-purchase-amount"><b>' + esc(fmt.money(p.total)) + '</b><small>Paid ' + esc(fmt.money(p.paid)) + '</small></span>' +
        '<span class="sp-status sp-status-' + esc(p.status) + '">' + esc(p.status) + '</span></a>'
      ).join("");
    } catch (err) {
      list.innerHTML = '<div class="sp-state">Purchase history could not be loaded.</div>';
      showError("Could not load purchase history. " + err.message);
    }
  }

  function addSupplier() {
    SupplierUI.openSupplierForm({ onSaved: () => { loadSupplierSummary(); loadSuppliers(); } });
  }

  Object.entries(tabs).forEach(([name, item]) => {
    item.button.addEventListener("click", () => setTab(name));
    item.button.addEventListener("keydown", (event) => {
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault(); const next = name === "suppliers" ? "purchases" : "suppliers";
        tabs[next].button.focus(); setTab(next);
      }
    });
  });
  $("sp-add-supplier").addEventListener("click", addSupplier);
  $("sp-export-suppliers").addEventListener("click", () => exportCsv("agni-suppliers.csv", ["Name", "GSTIN", "Phone", "Address", "Current balance", "Total purchases", "Total paid"], supplierRows.map((s) => [s.name,s.gstin,s.phone,s.address,s.balance,s.total_purchases,s.total_paid])));
  $("sp-export-purchases").addEventListener("click", () => exportCsv("agni-purchases.csv", ["Purchase number", "Date", "Supplier", "Items", "Subtotal", "GST", "Total", "Paid", "Due", "Status"], purchaseRows.map((p) => [p.number,p.date,p.supplier,p.items_summary,p.subtotal,p.gst,p.total,p.paid,p.due,p.status])));
  $("sp-new-purchase").addEventListener("click", () => { location.href = "/purchases/new"; });
  $("sp-supplier-search").addEventListener("input", () => { clearTimeout(supplierTimer); supplierTimer = setTimeout(loadSuppliers, 220); });
  $("sp-purchase-search").addEventListener("input", () => { clearTimeout(purchaseTimer); purchaseTimer = setTimeout(loadPurchases, 220); });
  $("sp-retry").addEventListener("click", () => { loadSupplierSummary(); loadSuppliers(); if (period) { loadPurchaseSummary(); loadPurchases(); } });
  document.querySelectorAll("[data-period]").forEach((button) => button.addEventListener("click", () => {
    period = button.dataset.period;
    document.querySelectorAll("[data-period]").forEach((b) => b.classList.toggle("on", b === button));
    $("sp-custom-dates").hidden = period !== "custom";
    loadPurchaseSummary(); loadPurchases();
  }));
  ["sp-from", "sp-to"].forEach((id) => $(id).addEventListener("change", () => { if (period === "custom") { loadPurchaseSummary(); loadPurchases(); } }));

  const startTab = new URLSearchParams(location.search).get("tab") || "suppliers";
  setTab(startTab, false);
})();
