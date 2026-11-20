// Shared UI helpers + the modals used from every page
// (Quick Add, Select customer, Select supplier).
(function () {
  const cfg = window.APP_CONFIG || {};

  /* ---------- formatting ---------- */
  const fmt = {
    // Amounts arrive from the API as rupee strings ("1450.50"). Shown Indian style:
    // 1,15,250 - and paise only when there are any.
    money(n) {
      const v = Number(n) || 0;
      const hasPaise = Math.round(Math.abs(v) * 100) % 100 !== 0;
      const d = hasPaise ? 2 : 0;
      return (cfg.currency || "Rs") + " " + v.toLocaleString(cfg.locale || "en-IN",
        { minimumFractionDigits: d, maximumFractionDigits: d });
    },
    initials(name) {
      const parts = String(name || "?").trim().split(/\s+/).slice(0, 2);
      return parts.map((p) => p[0].toUpperCase()).join("");
    },
  };

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  /* ---------- modal ---------- */
  const root = () => document.getElementById("modal-root");
  let current = null;

  function closeModal() {
    if (!current) return;
    current.remove();
    current = null;
    document.removeEventListener("keydown", onKey);
  }
  function onKey(e) {
    if (e.key === "Escape") closeModal();
  }

  // Returns the modal body element so callers can fill it in.
  function openModal(title) {
    closeModal();
    const overlay = document.createElement("div");
    overlay.className = "overlay";
    overlay.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true">' +
      '<div class="modal-head"><h2>' + esc(title) + '</h2>' +
      '<button class="icon-btn" data-close aria-label="Close"><i data-icon="x"></i></button></div>' +
      '<div class="modal-body"></div></div>';
    overlay.addEventListener("mousedown", (e) => {
      if (e.target === overlay || e.target.closest("[data-close]")) closeModal();
    });
    root().appendChild(overlay);
    current = overlay;
    document.addEventListener("keydown", onKey);
    Icons.render(overlay);
    return overlay.querySelector(".modal-body");
  }

  /* ---------- person pickers ---------- */
  function balanceTag(kind, rawBalance) {
    const balance = Number(rawBalance) || 0;
    const owe = kind === "supplier" ? "To pay" : "To receive";
    const extra = kind === "supplier" ? "Advance" : "Paid extra";
    if (balance > 0) return '<span class="bal bal-red">' + fmt.money(balance) + " <small>" + owe + "</small></span>";
    if (balance < 0) return '<span class="bal bal-green">' + fmt.money(-balance) + " <small>" + extra + "</small></span>";
    return '<span class="bal bal-clear">Clear</span>';
  }

  function openPicker({ title, kind, endpoint, onPick }) {
    const body = openModal(title);
    body.innerHTML =
      '<label class="search search-lg"><i data-icon="search"></i>' +
      '<input type="search" placeholder="Search name, phone, address" autofocus></label>' +
      '<ul class="pick-list"></ul>';
    Icons.render(body);
    const input = body.querySelector("input");
    const list = body.querySelector(".pick-list");
    let rows = [];
    let timer;

    function draw() {
      if (!rows.length) {
        list.innerHTML = '<li class="pick-empty">Nothing found</li>';
        return;
      }
      list.innerHTML = rows.map((r, i) =>
        '<li><button class="pick-row" data-i="' + i + '">' +
        '<span class="avatar">' + esc(fmt.initials(r.name)) + "</span>" +
        '<span class="pick-name"><b>' + esc(r.name) + "</b><small>" + esc(r.type_label || "") + "</small></span>" +
        balanceTag(kind, r.balance) + "</button></li>"
      ).join("");
    }

    async function load() {
      try {
        rows = await Api.get(endpoint + "?q=" + encodeURIComponent(input.value.trim()));
        draw();
      } catch (e) {
        list.innerHTML = '<li class="pick-empty">Could not load. ' + esc(e.message) + "</li>";
      }
    }

    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(load, 200);
    });
    list.addEventListener("click", (e) => {
      const btn = e.target.closest(".pick-row");
      if (!btn) return;
      const row = rows[Number(btn.dataset.i)];
      closeModal();
      onPick(row);
    });
    load();
    input.focus();
  }

  const selectCustomer = (onPick) =>
    openPicker({ title: "Select customer", kind: "customer", endpoint: "/api/customers", onPick });
  const selectSupplier = (onPick) =>
    openPicker({ title: "Select supplier", kind: "supplier", endpoint: "/api/suppliers", onPick });

  /* ---------- Quick Add ---------- */
  // Receive / purchase flows are wired for real when those screens are built.
  function receivePayment() {
    selectCustomer((c) => { window.location.href = "/udhaar?receive=" + c.id; });
  }
  function newPurchase() {
    selectSupplier((s) => { window.location.href = "/purchases/new?supplier=" + s.id; });
  }

  function quickAdd() {
    const body = openModal("Quick Add");
    body.innerHTML =
      '<ul class="quick-list">' +
      '<li><button data-go="sale">New sale</button></li>' +
      '<li><button data-go="purchase">New purchase</button></li>' +
      '<li><button data-go="receive">Receive payment</button></li>' +
      '<li><button data-go="customer">Add customer</button></li></ul>';
    body.addEventListener("click", (e) => {
      const go = e.target.closest("[data-go]");
      if (!go) return;
      const action = go.dataset.go;
      closeModal();
      if (action === "sale") window.location.href = "/sales/new";
      if (action === "purchase") newPurchase();
      if (action === "receive") receivePayment();
      if (action === "customer") window.location.href = "/customers?add=1";
    });
  }

  window.UI = { fmt, esc, openModal, closeModal, selectCustomer, selectSupplier, receivePayment, newPurchase, quickAdd };

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-biz-name]").forEach((el) => {
      if (cfg.businessName) el.textContent = cfg.businessName;
    });
    const qa = document.getElementById("btn-quick-add");
    if (qa) qa.addEventListener("click", quickAdd);
  });
})();
