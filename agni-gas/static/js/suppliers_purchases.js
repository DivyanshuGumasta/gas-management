// Combined Suppliers & Purchases page. This only combines navigation/presentation:
// supplier data still comes from /api/suppliers; no purchase API is introduced.
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = UI.esc;
  const fmt = UI.fmt;
  const tabs = {
    suppliers: { button: $("sp-tab-suppliers"), view: $("sp-view-suppliers") },
    purchases: { button: $("sp-tab-purchases"), view: $("sp-view-purchases") },
  };
  let rows = [];
  let timer = null;

  function setTab(name, updateUrl = true) {
    const selected = name === "purchases" ? "purchases" : "suppliers";
    Object.entries(tabs).forEach(([key, item]) => {
      const active = key === selected;
      item.button.setAttribute("aria-selected", active ? "true" : "false");
      item.button.tabIndex = active ? 0 : -1;
      item.view.hidden = !active;
    });
    if (updateUrl) {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", selected);
      window.history.replaceState({}, "", url);
    }
  }

  function balanceMarkup(raw) {
    const value = Number(raw) || 0;
    if (value > 0) {
      return '<span class="sp-payable">' + esc(fmt.money(value)) + ' · To pay</span>';
    }
    if (value < 0) {
      return '<span class="sp-advance">' + esc(fmt.money(Math.abs(value))) + ' · Advance</span>';
    }
    return '<span class="sp-clear">Clear</span>';
  }

  function drawSuppliers(data) {
    const list = $("sp-supplier-list");
    $("sp-supplier-count").textContent = data.length + (data.length === 1 ? " supplier" : " suppliers");
    if (!data.length) {
      list.innerHTML = '<div class="sp-state">No suppliers found.</div>';
      return;
    }
    list.innerHTML = data.map((supplier) => {
      const contact = [supplier.gstin ? "GSTIN: " + supplier.gstin : "", supplier.phone || "", supplier.address || ""]
        .filter(Boolean).join(" · ");
      return '<article class="sp-supplier-row">' +
        '<span class="sp-supplier-avatar">' + esc(fmt.initials(supplier.name)) + '</span>' +
        '<span class="sp-supplier-main"><b>' + esc(supplier.name) + '</b>' +
        '<small>' + esc(contact || "No contact details") + '</small></span>' +
        '<span class="sp-supplier-balance"><small>Opening balance</small><b>' + balanceMarkup(supplier.balance) + '</b></span>' +
        '</article>';
    }).join("");
  }

  async function loadSuppliers() {
    const error = $("sp-supplier-error");
    const list = $("sp-supplier-list");
    const query = $("sp-supplier-search").value.trim();
    error.hidden = true;
    list.innerHTML = '<div class="sp-state">Loading suppliers…</div>';
    try {
      rows = await Api.get("/api/suppliers?q=" + encodeURIComponent(query));
      drawSuppliers(rows);
    } catch (err) {
      list.innerHTML = '<div class="sp-state">Supplier list could not be loaded.</div>';
      $("sp-supplier-error-text").textContent = "Could not load suppliers. " + (err.message || "Please try again.");
      error.hidden = false;
      $("sp-supplier-count").textContent = "";
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const params = new URLSearchParams(window.location.search);
    setTab(params.get("tab"), false);

    Object.entries(tabs).forEach(([name, item]) => {
      item.button.addEventListener("click", () => setTab(name));
      item.button.addEventListener("keydown", (event) => {
        if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
          event.preventDefault();
          const next = name === "suppliers" ? "purchases" : "suppliers";
          tabs[next].button.focus();
          setTab(next);
        }
      });
    });

    $("sp-supplier-search").addEventListener("input", () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(loadSuppliers, 220);
    });
    $("sp-supplier-retry").addEventListener("click", loadSuppliers);
    loadSuppliers();
  });
})();
