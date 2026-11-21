// Combined Suppliers & Purchases workspace. Presentation is shared; APIs remain separate.
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = UI.esc, fmt = UI.fmt;
  const tabs = {
    suppliers: { button: $("sp-tab-suppliers"), view: $("sp-view-suppliers") },
    purchases: { button: $("sp-tab-purchases"), view: $("sp-view-purchases") },
  };
  let supplierTimer = null;
  let period = "month";

  function showError(message) {
    $("sp-error-text").textContent = message || "";
    $("sp-error").hidden = !message;
  }
  function balanceMarkup(raw) {
    const value = Number(raw) || 0;
    if (value > 0) return '<span class="bal bal-red">' + esc(fmt.money(value)) + ' <small>To pay</small></span>';
    if (value < 0) return '<span class="bal bal-green">' + esc(fmt.money(-value)) + ' <small>Advance</small></span>';
    return '<span class="bal bal-clear">Clear</span>';
  }
  function iso(d) {
    const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 10);
  }
  function dateRange() {
    const now = new Date();
    if (period === "today") return { from: iso(now), to: iso(now) };
    if (period === "7d") { const start = new Date(now); start.setDate(start.getDate() - 6); return { from: iso(start), to: iso(now) }; }
    if (period === "month") return { from: iso(new Date(now.getFullYear(), now.getMonth(), 1)), to: iso(now) };
    if (period === "custom") return { from: $("sp-from").value, to: $("sp-to").value };
    return {};
  }
  function setTab(name, updateUrl = true) {
    const selected = name === "purchases" ? "purchases" : "suppliers";
    Object.entries(tabs).forEach(([key, tab]) => {
      const active = key === selected;
      tab.button.classList.toggle("on", active);
      tab.button.setAttribute("aria-selected", active ? "true" : "false");
      tab.button.tabIndex = active ? 0 : -1;
      tab.view.hidden = !active;
    });
    $("sp-page-title").textContent = selected === "purchases" ? "Purchases" : "Suppliers";
    if (updateUrl) {
      const url = new URL(location.href);
      url.searchParams.set("tab", selected);
      history.replaceState({}, "", url);
    }
    if (selected === "purchases") { loadPurchaseSummary(); loadPurchases(); }
    else loadSuppliers();
  }

  async function loadSuppliers() {
    showError("");
    const list = $("sp-supplier-list");
    list.innerHTML = '<div class="state">Loading suppliers…</div>';
    try {
      const rows = await Api.get("/api/suppliers?q=" + encodeURIComponent($("sp-supplier-search").value.trim()));
      if (!rows.length) {
        list.innerHTML = '<div class="state"><b>No suppliers yet</b>Add your first supplier to get started.<button class="btn btn-dark" type="button" data-add-first>Add supplier</button></div>';
        return;
      }
      list.innerHTML = rows.map((supplier) =>
        '<a class="row" href="/suppliers-purchases/supplier/' + supplier.id + '">' +
          '<span class="avatar">' + esc(fmt.initials(supplier.name)) + '</span>' +
          '<span class="row-name"><b>' + esc(supplier.name) + '</b><small>Supplier' +
          (supplier.phone ? ' · ' + esc(supplier.phone) : '') + '</small></span>' +
          balanceMarkup(supplier.balance) +
        '</a>'
      ).join("");
    } catch (err) {
      list.innerHTML = '<div class="state"><b>Could not load suppliers</b>' + esc(err.message) + '</div>';
      showError("Could not load suppliers. " + err.message);
    }
  }

  async function loadPurchaseSummary() {
    const params = new URLSearchParams(dateRange());
    try {
      const summary = await Api.get("/api/purchases/summary?" + params);
      $("sp-purchase-total").textContent = fmt.money(summary.total);
      $("sp-purchase-count").textContent = summary.purchase_count + (summary.purchase_count === 1 ? " bill" : " bills");
      $("sp-purchase-payable").textContent = fmt.money(summary.payable);
    } catch (err) { showError("Could not load purchase summary. " + err.message); }
  }

  async function loadPurchases() {
    showError("");
    const params = new URLSearchParams(dateRange());
    const list = $("sp-purchase-list");
    list.innerHTML = '<div class="state">Loading purchases…</div>';
    try {
      const rows = await Api.get("/api/purchases?" + params);
      if (!rows.length) {
        list.innerHTML = '<div class="state"><b>No purchases found</b>Purchase records for this period will appear here.<a class="btn btn-dark" href="/purchases/new">New purchase</a></div>';
        return;
      }
      list.innerHTML = rows.map((purchase) => {
        const status = purchase.status === "paid" ? "badge-paid" : "badge-pending";
        return '<a class="row sp-purchase-row" href="/purchases/' + purchase.id + '">' +
          '<span class="avatar">' + esc(fmt.initials(purchase.supplier)) + '</span>' +
          '<span class="row-name"><b>' + esc(purchase.supplier) + '</b><small>' +
            esc(purchase.number) + ' · ' + esc(purchase.date) + ' · ' + esc(purchase.items_summary) + '</small></span>' +
          '<span class="sp-purchase-amount"><b>' + esc(fmt.money(purchase.total)) + '</b>' +
            '<small class="' + (Number(purchase.due) > 0 ? 'text-red' : 'text-green') + '">' +
              (Number(purchase.due) > 0 ? 'Due ' + esc(fmt.money(purchase.due)) : 'Paid') + '</small></span>' +
          '<span class="badge ' + status + '">' + esc(purchase.status) + '</span>' +
        '</a>';
      }).join("");
    } catch (err) {
      list.innerHTML = '<div class="state"><b>Could not load purchases</b>' + esc(err.message) + '</div>';
      showError("Could not load purchases. " + err.message);
    }
  }

  function addSupplier() {
    SupplierUI.openSupplierForm({ onSaved: loadSuppliers });
  }
  Object.entries(tabs).forEach(([name, tab]) => {
    tab.button.addEventListener("click", () => setTab(name));
    tab.button.addEventListener("keydown", (event) => {
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault();
        const next = name === "suppliers" ? "purchases" : "suppliers";
        tabs[next].button.focus();
        setTab(next);
      }
    });
  });
  $("sp-add-supplier").addEventListener("click", addSupplier);
  $("sp-supplier-list").addEventListener("click", (event) => {
    if (event.target.closest("[data-add-first]")) addSupplier();
  });
  $("sp-supplier-search").addEventListener("input", () => {
    clearTimeout(supplierTimer);
    supplierTimer = setTimeout(loadSuppliers, 220);
  });
  $("sp-retry").addEventListener("click", () => {
    if (tabs.purchases.view.hidden) loadSuppliers();
    else { loadPurchaseSummary(); loadPurchases(); }
  });
  $("sp-periods").addEventListener("click", (event) => {
    const button = event.target.closest("[data-period]");
    if (!button) return;
    period = button.dataset.period;
    $("sp-periods").querySelectorAll(".chip").forEach((chip) => chip.classList.toggle("on", chip === button));
    $("sp-custom-dates").hidden = period !== "custom";
    loadPurchaseSummary(); loadPurchases();
  });
  ["sp-from", "sp-to"].forEach((id) => $(id).addEventListener("change", () => {
    if (period === "custom") { loadPurchaseSummary(); loadPurchases(); }
  }));

  const initialTab = new URLSearchParams(location.search).get("tab") || "suppliers";
  setTab(initialTab, false);
})();
