(function () {
  const $ = (id) => document.getElementById(id);
  const fmt = UI.fmt;
  const esc = UI.esc;
  const config = window.APP_CONFIG || {};
  const apiBase = config.apiBase || "";
  let selectedPeriod = "month";
  let lastData = null;

  function queryForPeriod() {
    const params = new URLSearchParams();
    params.set("period", selectedPeriod);
    if (selectedPeriod === "custom") {
      params.set("from", $("reports-from").value);
      params.set("to", $("reports-to").value);
    }
    return params.toString();
  }

  function setActiveChip(period) {
    document.querySelectorAll("[data-period]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.period === period);
    });
  }

  function showError(message) {
    $("reports-error").hidden = false;
    $("reports-error-text").textContent = message;
  }

  function money(value) {
    return fmt.money(value);
  }

  function renderBars(data) {
    const rows = data.by_day || [];
    const host = $("reports-bars");
    $("reports-chart-empty").hidden = rows.some((row) => Number(row.total) !== 0);
    if (!rows.length) {
      host.innerHTML = "";
      return;
    }
    const max = Math.max(0, ...rows.map((row) => Number(row.total) || 0));
    const bestDate = data.best_day && data.best_day.date;
    const periodEnd = data.period.to;
    host.innerHTML = rows.map((row, index) => {
      const value = Number(row.total) || 0;
      const height = max > 0 && value > 0 ? Math.max(5, value / max * 100) : 0;
      const isBest = bestDate && row.date === bestDate;
      const now = new Date();
      const today = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" + String(now.getDate()).padStart(2, "0");
      const includesToday = index === rows.length - 1 && periodEnd === today;
      const klass = isBest ? " is-best" : (includesToday && row.date <= periodEnd ? " is-today" : "");
      return '<div class="reports-bar-col' + klass + '" title="' + esc(row.label + ': ' + money(row.total)) + '">' +
        '<div class="reports-bar-track"><span class="reports-bar-value">' + esc(money(row.total)) + '</span>' +
        '<span class="reports-bar' + (height ? "" : " is-zero") + '" style="height:' + (height || 2) + '%"></span></div>' +
        '<span class="reports-bar-label">' + esc(row.label) + '</span></div>';
    }).join("");
  }

  function renderMoney(rows) {
    const body = $("reports-money-body");
    const data = (rows || []).filter((row) => row.method !== "Total");
    $("reports-money-empty").hidden = data.length > 0;
    if (!data.length) {
      body.innerHTML = "";
    } else {
      body.innerHTML = data.map((row) => '<tr><td>' + esc(row.method) + '</td><td>' + esc(row.count) +
        '</td><td class="num">' + esc(money(row.amount)) + '</td></tr>').join("");
    }
    const total = (rows || []).find((row) => row.method === "Total");
    if (total) body.innerHTML += '<tr class="reports-total-row"><td>Total</td><td>' + esc(total.count) +
      '</td><td class="num">' + esc(money(total.amount)) + '</td></tr>';
  }

  function renderItems(rows) {
    const body = $("reports-items-body");
    const data = (rows || []).filter((row) => row.type !== "Total");
    $("reports-items-empty").hidden = data.length > 0;
    if (!data.length) {
      body.innerHTML = "";
    } else {
      body.innerHTML = data.map((row) => '<tr><td>' + esc(row.type) + '</td><td class="num">' +
        esc(Number(row.qty || 0).toLocaleString("en-IN", { maximumFractionDigits: 3 })) + '</td><td class="num">' +
        esc(money(row.amount)) + '</td><td class="num">' + esc(row.cost === null ? "—" : money(row.cost)) + '</td><td class="num">' +
        esc(row.margin === null ? "—" : money(row.margin)) + '</td></tr>').join("");
    }
    const total = (rows || []).find((row) => row.type === "Total");
    if (total) body.innerHTML += '<tr class="reports-total-row"><td>Total</td><td class="num">' +
      esc(Number(total.qty || 0).toLocaleString("en-IN", { maximumFractionDigits: 3 })) + '</td><td class="num">' +
      esc(money(total.amount)) + '</td><td class="num">' + esc(total.cost === null ? "—" : money(total.cost)) + '</td><td class="num">' +
      esc(total.margin === null ? "—" : money(total.margin)) + '</td></tr>';
  }

  function renderDefinitionList(target, values) {
    $(target).innerHTML = values.map(([label, value]) =>
      '<div class="reports-summary-row"><dt>' + esc(label) + '</dt><dd>' + esc(String(value)) + '</dd></div>'
    ).join("");
  }

  function render(data) {
    lastData = data;
    const k = data.kpis;
    const s = data.summary;
    $("kpi-sales").textContent = money(k.sales);
    $("kpi-bills").textContent = Number(k.bills || 0).toLocaleString("en-IN") + " bills · incl. GST, excl. refundable deposits";
    $("kpi-cash").textContent = money(k.cash_received);
    $("kpi-purchases").textContent = money(k.purchases);
    $("kpi-purchase-bills").textContent = Number(k.purchase_bills || 0).toLocaleString("en-IN") + " bills · incl. GST/deposits";
    $("kpi-profit").textContent = s.cogs_costing_complete ? money(k.profit) : "Incomplete";
    $("kpi-cylinders").textContent = Number(k.cylinders || 0).toLocaleString("en-IN") + " cylinders sold";

    $("reports-average").textContent = money(data.avg_per_day);
    $("reports-best-day").textContent = "Best: " + (data.best_day.label || "—") + ", " + money(data.best_day.total);
    $("reports-period-caption").textContent = data.period.label;
    document.querySelectorAll("[data-biz-name]").forEach((el) => { el.textContent = data.agency_name || "Agni Gas Agency"; });
    $("reports-print-period").textContent = "Period: " + data.period.label + " (" + data.period.from + " to " + data.period.to + ")";
    $("reports-print-generated").textContent = "Generated: " + data.generated_at;

    renderBars(data);
    renderMoney(data.money_in);
    renderItems(data.by_item);
    renderDefinitionList("reports-summary", [
      ["Taxable revenue", money(s.taxable_sales)],
      ["Output GST collected", money(s.gst_collected)],
      ["Input GST on supplier bills", money(s.gst_paid_on_purchases)],
      ["FIFO COGS — filled cylinders", money(s.cogs_cylinders)],
      ["FIFO COGS — catalogue items", money(s.cogs_catalogue)],
      ["Costing status", s.cogs_costing_complete ? "Complete (any fallback estimates are disclosed)" : "INCOMPLETE — " + s.cogs_uncosted_units + " sold unit(s) have no cost"],
      ["Estimated gross profit", s.cogs_costing_complete ? money(s.gross_profit) : "Incomplete — see CA workbook costing sheets"],
      ["Catalogue stock write-offs", money(s.catalogue_writeoffs)],
      ["Cylinder stock write-offs", money(s.cylinder_writeoffs)],
      ["Trading result after stock write-offs", s.trading_result_costing_complete ? money(s.trading_result_after_writeoffs) : "Incomplete — see stock adjustment sheets"],
      ["Supplier deposit losses", money(s.supplier_deposit_forfeited)],
      ["Result after stock write-offs and supplier deposit losses (before overheads)", s.trading_result_costing_complete ? money(s.result_after_recorded_losses) : "Incomplete — see stock adjustment sheets"],
      ["Customer deposits forfeited / retained", money(s.customer_deposit_forfeited)],
      ["New empty cylinders acquired", Number(s.new_empty_purchased_qty || 0).toLocaleString("en-IN")],
      ["New-empty shell acquisition cost capitalised (period)", money(s.new_empty_shell_acquisition_cost)],
      ["Gross recorded shell cost to date (before disposals / depreciation)", money(s.new_empty_shell_gross_cost_to_date)],
      ["New empty cylinders with unknown / legacy shell cost", Number(s.new_empty_uncosted_qty || 0).toLocaleString("en-IN")],
      ["Supplier deposit paid for new empty cylinders", money(s.new_empty_supplier_deposit_paid)],
      ["New empty cylinders issued", Number(s.new_empty_issued_qty || 0).toLocaleString("en-IN")],
      ["Customer deposits received for new empty cylinders", money(s.new_empty_customer_deposit_received)],
      ["Payments made to suppliers", money(s.paid_to_supplier)],
      ["New customers", Number(s.new_customers || 0).toLocaleString("en-IN")],
    ]);
    renderDefinitionList("reports-snapshots", [
      ["Customer receivables / udhaar", money(data.snapshots.udhaar_outstanding)],
      ["Supplier payables", money(data.snapshots.payable_to_suppliers)],
      ["Supplier cylinder deposits (recoverable asset)", money(data.snapshots.supplier_cylinder_deposits)],
      ["Customer cylinder deposits (refundable liability)", money(data.snapshots.customer_cylinder_deposits)],
    ]);

    const notes = data.notes || [];
    $("reports-notes-wrap").hidden = notes.length === 0;
    $("reports-notes").innerHTML = notes.map((note) => "<li>" + esc(note) + "</li>").join("");
  }

  async function load() {
    $("reports-error").hidden = true;
    const url = "/api/reports?" + queryForPeriod();
    try {
      const data = await Api.get(url);
      render(data);
    } catch (error) {
      showError("Could not load reports. " + error.message);
    }
  }

  function selectPeriod(period) {
    selectedPeriod = period;
    setActiveChip(period);
    $("reports-custom-range").hidden = period !== "custom";
    if (period === "custom") {
      const now = new Date();
      const first = new Date(now.getFullYear(), now.getMonth(), 1);
      const localIso = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
      $("reports-from").value = localIso(first);
      $("reports-to").value = localIso(now);
      $("reports-range-error").textContent = "";
      return;
    }
    load();
  }

  function download(format) {
    const params = queryForPeriod();
    const path = "/api/reports/export." + format + "?" + params;
    window.location.href = apiBase + path;
    $("reports-export-menu").hidden = true;
    $("reports-export-toggle").setAttribute("aria-expanded", "false");
  }

  document.querySelectorAll("[data-period]").forEach((button) => {
    button.addEventListener("click", () => selectPeriod(button.dataset.period));
  });
  $("reports-apply-custom").addEventListener("click", () => {
    const from = $("reports-from").value;
    const to = $("reports-to").value;
    if (!from || !to) {
      $("reports-range-error").textContent = "Choose both dates.";
      return;
    }
    if (from > to) {
      $("reports-range-error").textContent = "From date must be before or equal to To date.";
      return;
    }
    $("reports-range-error").textContent = "";
    load();
  });
  $("reports-retry").addEventListener("click", load);
  $("reports-print").addEventListener("click", () => window.print());
  $("reports-export-toggle").addEventListener("click", () => {
    const menu = $("reports-export-menu");
    menu.hidden = !menu.hidden;
    $("reports-export-toggle").setAttribute("aria-expanded", String(!menu.hidden));
  });
  document.querySelectorAll("[data-export]").forEach((button) => {
    button.addEventListener("click", () => download(button.dataset.export));
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".reports-export-wrap")) {
      $("reports-export-menu").hidden = true;
      $("reports-export-toggle").setAttribute("aria-expanded", "false");
    }
  });

  load();
})();
