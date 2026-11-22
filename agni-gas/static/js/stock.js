// Stock & Price page: numbers, damaged cylinders, cylinder cards, other items, stock history.
// Talks to the Stock API described in STOCK_API_CONTRACT.md (the backend is the next step).
(function () {
  const { fmt, esc } = UI;
  const $ = (id) => document.getElementById(id);
  const PAGE = 30;
  const state = { cylinders: [], items: [], histSize: "", histLimit: PAGE, histSeq: 0 };

  /* ---------- small helpers ---------- */
  const money = (v) => fmt.money(v);
  const qty = (v) => String(Math.round(Number(v) * 1000) / 1000);          // 2 -> "2", 1.5 -> "1.5"
  const num = (v) => Number(v) || 0;
  const toast = (m, err) => Cust.toast(m, err);
  function showError(msg) {
    const box = $("st-error");
    box.hidden = !msg;
    if (msg) box.querySelector("span").textContent = msg;
  }
  function when(at) {                                                        // "2026-11-14 10:23:00" -> "14 Nov, 10:23 AM"
    const d = new Date(String(at).replace(" ", "T"));
    if (isNaN(d)) return esc(at);
    const day = d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
    const time = d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true }).toUpperCase();
    return day + ", " + time;
  }
  const suppliersLine = (list) => list && list.length
    ? "Supplied by <b>" + list.map(esc).join(", ") + "</b>"
    : "No supplier linked yet";

  /* ---------- numbers ---------- */
  function renderSummary(s) {
    $("st-ready").textContent = s.ready;
    $("st-refill").textContent = s.to_refill;
    $("st-with").textContent = s.with_customers;
    $("st-total").textContent = s.total_owned;
    $("st-other").textContent = s.other_items;
    $("st-cost").textContent = money(s.stock_cost);
    $("st-value").textContent = money(s.stock_value);
    const badge = $("st-damaged-badge");
    badge.textContent = s.damaged_total + " damaged";
    badge.classList.toggle("has", s.damaged_total > 0);
  }

  function renderDamaged() {}

  /* ---------- cards ---------- */
  function actions(kind, id) {
    return '<div class="st-actions" data-kind="' + kind + '" data-id="' + id + '">' +
      '<button class="btn btn-soft" data-act="adjust" type="button">Adjust stock</button>' +
      '<button class="btn btn-dark" data-act="price" type="button">Update price</button>' +
      '<button class="btn btn-white" data-act="edit" type="button">Edit</button>' +
      '<button class="btn btn-del" data-act="delete" type="button">Delete</button></div>';
  }
  function margin(m, unit) {
    const v = num(m);
    return '<p class="st-margin' + (v < 0 ? " neg" : "") + '">Margin ' + money(m) + " / " + unit + "</p>";
  }
  function cylinderCard(c) {
    return '<article class="st-card" id="cyl-' + c.id + '">' +
      '<div class="st-card-head"><span class="st-card-icon"><i data-icon="cylinder"></i></span>' +
      '<span class="st-card-name">' + esc(c.name) + "</span>" + (c.low ? '<span class="st-low">LOW</span>' : "") + "</div>" +
      '<div class="st-boxes">' +
        '<div class="st-box sale"><small>Sale price</small><b>' + money(c.sale_price) + "</b></div>" +
        '<div class="st-box"><small>Wholesale</small><b>' + money(c.wholesale_price) + "</b></div>" +
        '<div class="st-box"><small>Purchase price</small><b>' + money(c.purchase_price) + "</b></div></div>" +
      '<div class="st-boxes">' +
        '<div class="st-box"><b>' + c.full + "</b><small>Full</small></div>" +
        '<div class="st-box amber"><b>' + c.empty + "</b><small>Empty</small></div>" +
        '<div class="st-box purple"><b>' + c.with_customers + "</b><small>With customers</small></div></div>" +
      '<p class="st-meta">Security ' + money(c.security) + " · Stock value " + money(c.stock_value) + "</p>" +
      margin(c.margin, "cyl") +
      '<p class="st-supplier">' + suppliersLine(c.suppliers) + "</p>" +
      actions("cylinder", c.id) + "</article>";
  }
  function itemCard(it) {
    return '<article class="st-card" id="item-' + it.id + '">' +
      '<div class="st-card-head"><span class="st-card-icon item"><i data-icon="cart"></i></span>' +
      '<span><span class="st-card-name">' + esc(it.name) + '</span><br><span class="st-card-unit">Sold per ' + esc(it.unit) + "</span></span>" +
      (it.low ? '<span class="st-low">LOW</span>' : "") + "</div>" +
      '<div class="st-boxes">' +
        '<div class="st-box sale"><small>Sale price</small><b>' + money(it.sale_price) + "</b></div>" +
        '<div class="st-box"><small>Wholesale</small><b>' + money(it.wholesale_price) + "</b></div>" +
        '<div class="st-box"><small>Purchase price</small><b>' + money(it.purchase_price) + "</b></div></div>" +
        '<div class="st-boxes one"><div class="st-box amber"><small>In stock</small><b>' + qty(it.qty) + " " + esc(it.unit) + "</b></div></div>" +
      '<p class="st-meta">Stock value ' + money(it.stock_value) + "</p>" +
      margin(it.margin, esc(it.unit)) +
      '<p class="st-supplier">' + suppliersLine(it.suppliers) + "</p>" +
      actions("item", it.id) + "</article>";
  }
  function render(d) {
    state.cylinders = d.cylinders;
    state.items = d.items;
    renderSummary(d.summary);
    renderDamaged();
    $("st-cylinders").innerHTML = d.cylinders.length ? d.cylinders.map(cylinderCard).join("")
      : '<div class="st-empty"><b>No cylinders yet</b>Add your first cylinder size to start tracking stock.</div>';
    $("st-items").innerHTML = d.items.length ? d.items.map(itemCard).join("")
      : '<div class="st-empty"><b>No other items yet</b>Add things you sell besides gas, like gas pipes, regulators and stoves.</div>';
    $("st-chips").innerHTML = '<button class="chip' + (state.histSize ? "" : " on") + '" data-size="" type="button">All</button>' +
      d.cylinders.map((c) => '<button class="chip' + (String(c.id) === state.histSize ? " on" : "") + '" data-size="' + c.id + '" type="button">' + esc(c.name) + "</button>").join("");
    Cust.renderIcons(document);
    if (window.Icons && Icons.render) Icons.render(document);
    document.dispatchEvent(new CustomEvent("stock:rendered"));
  }

  /* ---------- history ---------- */
  function historyRow(r) {
    const changes = (r.changes || []).map((c) =>
      '<span class="' + (c.n > 0 ? "pos" : "neg") + '">' + (c.n > 0 ? "+" : "−") + qty(Math.abs(c.n)) + " " + esc(c.label) + "</span>").join("");
    return '<div class="row"><span class="row-name"><b>' + esc(r.title) + "</b><small>" + when(r.at) + (r.ref ? " · " + esc(r.ref) : "") + "</small></span>" +
      '<span class="st-changes">' + changes + "</span></div>";
  }
  async function loadHistory() {
    const seq = ++state.histSeq;
    const p = new URLSearchParams({ limit: state.histLimit + 1 });
    if (state.histSize) p.set("cylinder_type_id", state.histSize);
    try {
      const rows = await Api.get("/api/stock/history?" + p);
      if (seq !== state.histSeq) return;
      const more = rows.length > state.histLimit;
      const shown = rows.slice(0, state.histLimit);
      $("st-history").innerHTML = shown.length ? shown.map(historyRow).join("")
        : '<div class="state"><b>No stock movements yet</b>Purchases, sales and adjustments will show up here.</div>';
      $("st-more").hidden = !more;
    } catch (e) {
      if (seq === state.histSeq) $("st-history").innerHTML = '<div class="state"><b>Could not load history</b>' + esc(e.message) + "</div>";
    }
  }

  async function load() {
    try {
      const d = await Api.get("/api/stock");
      showError("");
      render(d);
    } catch (e) { showError("Could not load stock. " + e.message); }
    loadHistory();
  }

  /* ---------- popups (one small form builder for all of them) ---------- */
  // fields: { name, label, kind: "money" | "int" | "qty" | "text" | "unit", value, required, suffix, hint }
  function fieldHtml(f) {
    const v = f.value == null ? "" : esc(f.value);
    let control;
    if (f.kind === "money") control = '<div class="amt"><i>Rs</i><input name="' + f.name + '" inputmode="decimal" autocomplete="off" placeholder="0" value="' + v + '"></div>';
    else if (f.kind === "int") control = '<div class="amt"><input name="' + f.name + '" type="number" min="0" step="1" inputmode="numeric" value="' + v + '"><i>' + esc(f.suffix || "cyl") + "</i></div>";
    else if (f.kind === "qty") control = '<div class="amt"><input name="' + f.name + '" inputmode="decimal" autocomplete="off" value="' + v + '">' + (f.suffix ? "<i>" + esc(f.suffix) + "</i>" : "") + "</div>";
    else if (f.kind === "unit") control = '<select name="' + f.name + '" class="amt">' + ["pcs", "metre", "kg", "litre", "set", "box"].map((u) =>
      '<option' + (u === (f.value || "pcs") ? " selected" : "") + ">" + u + "</option>").join("") + "</select>";
    else control = '<div class="amt"><input name="' + f.name + '" autocomplete="off" value="' + v + '"' + (f.placeholder ? ' placeholder="' + esc(f.placeholder) + '"' : "") + "></div>";
    return '<label class="field"><span>' + esc(f.label) + (f.required ? " *" : "") + "</span>" + control +
      (f.hint ? '<small class="hint">' + esc(f.hint) + "</small>" : "") + "</label>";
  }
  function formModal({ title, intro, fields, submit = "Save", success, run }) {
    const body = UI.openModal(title);
    let html = '<form novalidate autocomplete="off">' + (intro ? '<p class="st-intro hint">' + esc(intro) + "</p>" : "");
    for (let i = 0; i < fields.length; i++) {
      if (fields[i].pair) { html += '<div class="two">' + fieldHtml(fields[i]) + fieldHtml(fields[++i]) + "</div>"; }
      else html += fieldHtml(fields[i]);
    }
    html += '<div class="form-error" role="alert"></div><div class="modal-foot"><button type="button" class="btn btn-white" data-close>Cancel</button>' +
      '<button type="submit" class="btn btn-dark">' + esc(submit) + "</button></div></form>";
    body.innerHTML = html;
    const form = body.querySelector("form"), err = body.querySelector(".form-error");
    const first = form.querySelector("input,select"); if (first) first.focus();
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      err.textContent = "";
      const v = {};
      fields.forEach((f) => { v[f.name] = (form.elements[f.name].value || "").trim(); });
      const missing = fields.find((f) => f.required && !v[f.name]);
      if (missing) { err.textContent = missing.label + " is required."; form.elements[missing.name].focus(); return; }
      const btn = form.querySelector("[type=submit]"); btn.disabled = true;
      try { await run(v); UI.closeModal(); toast(success); load(); }
      catch (ex) {
        err.textContent = ex.message || "Could not save.";
        const bad = ex.field && form.elements[ex.field]; if (bad) bad.focus();
        btn.disabled = false;
      }
    });
  }

  const priceFields = (c) => [
    { name: "sale_price", label: "Sale price", kind: "money", value: c ? c.sale_price : "", pair: true },
    { name: "wholesale_price", label: "Wholesale price", kind: "money", value: c ? c.wholesale_price : "" },
  ];

  function addCylinder() {
    formModal({
      title: "Add cylinder", submit: "Add cylinder", success: "Cylinder added",
      intro: "Add a cylinder size you sell. Link it to a supplier from the supplier's page so it appears in purchases.",
      fields: [
        { name: "weight_kg", label: "Cylinder weight (kg)", kind: "qty", required: true, suffix: "kg", hint: "Decimal weights such as 5.4 are fine." },
        ...priceFields(null),
        { name: "purchase_price", label: "Purchase price", kind: "money", pair: true },
        { name: "security", label: "Security (deposit)", kind: "money" },
        { name: "full", label: "Full cylinders you have now", kind: "int", value: "0", pair: true },
        { name: "empty", label: "Empty cylinders you have now", kind: "int", value: "0" },
      ],
      run: (v) => Api.post("/api/cylinders", v),
    });
  }
  function addItem() {
    formModal({
      title: "Add item", submit: "Add item", success: "Item added",
      intro: "Anything you sell besides gas: gas pipes, regulators, stoves and so on.",
      fields: [
        { name: "name", label: "Item name", kind: "text", required: true, placeholder: "e.g. Gas pipe" },
        { name: "unit", label: "Sold per", kind: "unit", pair: true },
        { name: "qty", label: "In stock now", kind: "qty", value: "0" },
        { name: "sale_price", label: "Sale price", kind: "money", pair: true },
        { name: "wholesale_price", label: "Wholesale price", kind: "money" },
        { name: "purchase_price", label: "Purchase price", kind: "money" },
      ],
      run: (v) => Api.post("/api/items", v),
    });
  }
  function adjust(kind, id) {
    if (kind === "cylinder") {
      const c = state.cylinders.find((x) => x.id === id);
      formModal({
        title: "Adjust stock · " + c.name, submit: "Save stock", success: "Stock updated",
        intro: "Type what you actually count on the shelf now. The difference is saved in Stock history.",
        fields: [
          { name: "full", label: "Full cylinders", kind: "int", value: c.full, required: true, pair: true },
          { name: "empty", label: "Empty cylinders", kind: "int", value: c.empty, required: true },
          { name: "note", label: "Reason (optional)", kind: "text", placeholder: "e.g. counted again, found 1 extra" },
        ],
        run: (v) => Api.post("/api/cylinders/" + id + "/adjust", v),
      });
    } else {
      const it = state.items.find((x) => x.id === id);
      formModal({
        title: "Adjust stock · " + it.name, submit: "Save stock", success: "Stock updated",
        intro: "Type what you actually have now. The difference is saved in Stock history.",
        fields: [
          { name: "qty", label: "In stock now", kind: "qty", value: qty(it.qty), required: true, suffix: it.unit },
          { name: "note", label: "Reason (optional)", kind: "text" },
        ],
        run: (v) => Api.post("/api/items/" + id + "/adjust", v),
      });
    }
  }
  function updatePrice(kind, id) {
    if (kind === "cylinder") {
      const c = state.cylinders.find((x) => x.id === id);
      formModal({
        title: "Update price · " + c.name, submit: "Save prices", success: "Prices updated",
        intro: "A new purchase price only applies to cylinders you buy from now on. Cylinders already in stock keep the price they were bought at.",
        fields: [
          ...priceFields(c),
          { name: "purchase_price", label: "Purchase price", kind: "money", value: c.purchase_price, pair: true },
          { name: "security", label: "Security (deposit)", kind: "money", value: c.security },
        ],
        run: (v) => Api.put("/api/cylinders/" + id + "/prices", v),
      });
    } else {
      const it = state.items.find((x) => x.id === id);
      formModal({
        title: "Update price · " + it.name, submit: "Save prices", success: "Prices updated",
        fields: [
          { name: "sale_price", label: "Sale price (per " + it.unit + ")", kind: "money", value: it.sale_price },
          { name: "wholesale_price", label: "Wholesale price (per " + it.unit + ")", kind: "money", value: it.wholesale_price },
          { name: "purchase_price", label: "Purchase price (per " + it.unit + ")", kind: "money", value: it.purchase_price },
        ],
        run: (v) => Api.put("/api/items/" + id + "/prices", v),
      });
    }
  }
  function edit(kind, id) {
    if (kind === "cylinder") {
      const c = state.cylinders.find((x) => x.id === id);
      formModal({
        title: "Edit cylinder", success: "Cylinder updated",
        fields: [{ name: "weight_kg", label: "Cylinder weight (kg)", kind: "qty", value: c.kg, required: true, suffix: "kg" }],
        run: (v) => Api.put("/api/cylinders/" + id, v),
      });
    } else {
      const it = state.items.find((x) => x.id === id);
      formModal({
        title: "Edit item", success: "Item updated",
        fields: [
          { name: "name", label: "Item name", kind: "text", value: it.name, required: true },
          { name: "unit", label: "Sold per", kind: "unit", value: it.unit },
        ],
        run: (v) => Api.put("/api/items/" + id, v),
      });
    }
  }
  function remove(kind, id) {
    const x = (kind === "cylinder" ? state.cylinders : state.items).find((r) => r.id === id);
    Cust.openConfirm({
      title: "Delete " + x.name + "?", danger: true, confirmLabel: "Delete",
      message: "This removes " + x.name + " from your stock list. Old bills and purchases that used it stay as they are. If it still has stock or was used recently, you will be asked to adjust it first.",
      onConfirm: async () => { await Api.del("/api/" + (kind === "cylinder" ? "cylinders/" : "items/") + id); toast(x.name + " deleted"); load(); },
    });
  }

  /* ---------- events ---------- */
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const box = b.closest("[data-kind]");
    const kind = box.dataset.kind, id = Number(box.dataset.id);
    ({ adjust, price: updatePrice, edit, delete: remove })[b.dataset.act](kind, id);
  });
  $("st-add-cylinder").addEventListener("click", addCylinder);
  $("st-add-item").addEventListener("click", addItem);
  $("st-add-item-top").addEventListener("click", addItem);
  $("st-retry").addEventListener("click", load);
  $("st-filter").addEventListener("click", () => toast("The history filter is coming in the next step."));
  $("st-more").addEventListener("click", () => { state.histLimit += PAGE; loadHistory(); });
  $("st-chips").addEventListener("click", (e) => {
    const b = e.target.closest(".chip"); if (!b) return;
    state.histSize = b.dataset.size; state.histLimit = PAGE;
    document.querySelectorAll("#st-chips .chip").forEach((c) => c.classList.toggle("on", c === b));
    loadHistory();
  });
  window.StockUI = { load, toast, state };   // used by stock_extra.js
  load();
})();
