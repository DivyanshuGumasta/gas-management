// One customer: profile card + Ledger / Cylinders / Special price tabs.
(function () {
  const { fmt, esc } = UI;
  const $ = (id) => document.getElementById(id);
  const id = Number(location.pathname.split("/").filter(Boolean).pop());
  let c = null, ledger = null, cyl = null, prices = null, tab = "ledger";

  const moneyCell = (v) => (v == null ? "" : esc(fmt.money(v)));
  function balCell(raw) {                       // + owes us (red) / - paid extra (green)
    const b = Number(raw) || 0;
    return '<span class="' + (b > 0 ? "text-red" : b < 0 ? "text-green" : "") + '">' +
      esc(fmt.money(b)) + "</span>";
  }

  /* ---------- profile card ---------- */
  function renderProfile() {
    const bal = Number(c.balance) || 0;
    document.title = c.name + " · Agni Gas Agency";
    $("cd-name").textContent = $("cd-name2").textContent = c.name;
    $("cd-type").textContent = $("cd-type2").textContent = c.type_label;
    $("cd-avatar").textContent = fmt.initials(c.name);
    $("cd-bal-label").textContent = bal > 0 ? "To receive" : bal < 0 ? "Advance" : "Balance";
    const b = $("cd-bal");
    b.textContent = bal === 0 ? "Clear" : fmt.money(Math.abs(bal));
    b.className = bal > 0 ? "text-red" : bal < 0 ? "text-green" : "";
    $("cd-cyl").textContent = c.cylinders;
    $("cd-cyl-count").textContent = c.cylinders > 0 ? c.cylinders : "";
    $("cd-meta").innerHTML = [c.phone, c.address, c.note].filter(Boolean).map((t) => "<span>" + esc(t) + "</span>").join("");
    $("cd-newsale").href = "/sales/new?customer=" + c.id;
    $("cd-export").dataset.scope = "customer:" + c.id;
    $("cd-statement").dataset.scope = "statement:" + c.id;
    $("cd-statement").closest("aside").dataset.scope = "statement:" + c.id;
  }

  /* ---------- tabs ---------- */
  function ledgerHtml() {
    const rows = ledger.rows.map((r) => {
      const off = r.status === "cancelled";
      const detail = r.kind === "sale"
        ? '<a href="/sales/' + r.id + '">' + esc(r.detail) + "</a>" : "<b>" + esc(r.detail) + "</b>";
      return '<tr class="' + (off ? "is-cancelled" : "") + '"><td>' + esc(Cust.date(r.date)) + "</td>" +
        "<td>" + detail + (off ? '<span class="badge badge-cancelled">Cancelled</span>' : "") +
        (r.sub ? '<span class="sub">' + esc(r.sub) + "</span>" : "") + "</td>" +
        '<td class="num ' + (off ? "strike" : "") + '">' + moneyCell(r.sale) + "</td>" +
        '<td class="num ' + (off ? "strike" : "text-green") + '" style="font-weight:' + (off ? 400 : 600) + '">' + moneyCell(r.paid) + "</td>" +
        '<td class="num">' + (off ? "" : balCell(r.balance)) + "</td></tr>";
    }).join("");
    return '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Date</th><th>Detail</th><th class="num">Sale</th>' +
      '<th class="num">Paid</th><th class="num">Balance</th></tr></thead><tbody>' + rows + "</tbody></table></div>" +
      (ledger.rows.length === 1 ? '<div class="state">No sales or payments yet.</div>' : "");
  }

  function cylindersHtml() {
    const held = cyl.held.map((h) => '<div class="held">' + h.qty + " × " + esc(h.name) + "<small>with customer</small></div>").join("");
    const hist = cyl.history.length ? '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Date</th><th>Detail</th><th>Size</th>' +
      '<th class="num">Change</th></tr></thead><tbody>' + cyl.history.map((h) =>
        "<tr><td>" + esc(Cust.date(h.date)) + "</td><td>" + esc(h.detail) + (h.note ? '<span class="sub">' + esc(h.note) + "</span>" : "") +
        "</td><td>" + esc(h.type) + '</td><td class="num ' + (h.delta > 0 ? "text-red" : "text-green") + '">' +
        (h.delta > 0 ? "+" : "") + h.delta + "</td></tr>").join("") + "</tbody></table></div>" : "";
    return '<div class="panel-pad">' +
      (cyl.total > 0
        ? "<h3>Cylinders with this customer</h3><div class=\"held-grid\">" + held + "</div>" +
          '<button class="btn btn-dark" id="cd-return2" type="button">Return empties</button>'
        : '<div class="hint-text" style="margin:0">No cylinders with this customer.</div>') +
      "</div>" + hist;
  }

  function pricesHtml() {
    return '<div class="panel-pad"><p class="hint-text">Set a special price for this customer. Leave blank to use the normal ' +
      esc(c.type_label.toLowerCase()) + " price.</p></div>" +
      '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Cylinder</th><th class="num">Normal price</th>' +
      '<th class="num">Special price</th></tr></thead><tbody>' + prices.map((p) =>
        "<tr><td><b>" + esc(p.name) + '</b></td><td class="num">' + esc(fmt.money(p.default_price)) + '</td><td class="num">' +
        '<input class="price-input" inputmode="decimal" data-tid="' + p.cylinder_type_id + '" placeholder="' +
        esc(Number(p.default_price)) + '" value="' + esc(p.special_price == null ? "" : Number(p.special_price)) + '"></td></tr>').join("") +
      '</tbody></table></div><div class="panel-pad"><div class="form-error" id="price-error" role="alert"></div>' +
      '<button class="btn btn-dark" id="price-save" type="button"><i data-cicon="check"></i>Save prices</button></div>';
  }

  function renderTab() {
    document.querySelectorAll("[data-tab]").forEach((t) => t.classList.toggle("on", t.dataset.tab === tab));
    $("cd-panel").innerHTML = tab === "ledger" ? ledgerHtml() : tab === "cylinders" ? cylindersHtml() : pricesHtml();
    Cust.renderIcons($("cd-panel"));
  }

  /* ---------- load ---------- */
  async function load() {
    $("cd-error").hidden = true;
    try {
      [c, ledger, cyl, prices] = await Promise.all([
        Api.get("/api/customers/" + id), Api.get("/api/customers/" + id + "/ledger"),
        Api.get("/api/customers/" + id + "/cylinders"), Api.get("/api/customers/" + id + "/prices"),
      ]);
    } catch (e) {
      if (e.status === 404) { $("cd-main").hidden = true; $("cd-missing").hidden = false; return; }
      $("cd-error").hidden = false;
      $("cd-error").querySelector("span").textContent = "Could not load this customer. " + e.message;
      return;
    }
    $("cd-missing").hidden = true;
    $("cd-main").hidden = false;
    renderProfile();
    renderTab();
  }

  /* ---------- actions ---------- */
  function returnEmpties() {
    Cust.openReturnEmpties({ customerId: c.id, customerName: c.name, held: cyl.held, onSaved: load });
  }

  document.querySelector(".detail-grid").addEventListener("click", (e) => {
    const t = e.target.closest("[data-tab]");
    if (t) { tab = t.dataset.tab; renderTab(); }
    if (e.target.closest("#cd-return2")) returnEmpties();
  });
  $("cd-retry").addEventListener("click", load);
  $("cd-receive").addEventListener("click", () => Cust.openReceive({ customer: c, onSaved: load }));
  $("cd-return").addEventListener("click", returnEmpties);
  $("cd-edit").addEventListener("click", () => Cust.openCustomerForm({ customer: c, onSaved: load }));

  $("cd-delete").addEventListener("click", () => {
    Cust.openConfirm({
      title: "Delete " + c.name + "?",
      message: "Their sales, payments and ledger stay in your records and reports. They will no longer appear in the customer list. " +
        "A customer who still owes money, has paid extra or holds cylinders cannot be deleted.",
      confirmLabel: "Yes, delete", cancelLabel: "Keep customer", danger: true,
      onConfirm: async () => {
        await Api.del("/api/customers/" + c.id);
        Cust.flash(c.name + " deleted");
        location.href = "/customers";
      },
    });
  });

  $("cd-panel").addEventListener("input", (e) => {
    if (e.target.classList.contains("price-input")) {
      let v = e.target.value.replace(/[^0-9.]/g, "");
      const i = v.indexOf(".");
      if (i !== -1) v = v.slice(0, i + 1) + v.slice(i + 1).replace(/\./g, "").slice(0, 2);
      e.target.value = v;
    }
  });
  $("cd-panel").addEventListener("click", async (e) => {
    const btn = e.target.closest("#price-save");
    if (!btn) return;
    const payload = {};
    document.querySelectorAll(".price-input").forEach((i) => { payload[i.dataset.tid] = i.value.trim(); });
    btn.disabled = true;
    $("price-error").textContent = "";
    try {
      prices = await Api.put("/api/customers/" + id + "/prices", { prices: payload });
      Cust.toast("Prices saved");
      renderTab();
    } catch (err) {
      $("price-error").textContent = err.message;
      btn.disabled = false;
    }
  });

  load();
})();
