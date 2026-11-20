(function () {
  const { fmt, esc } = UI;
  const $ = (id) => document.getElementById(id);

  function renderBars(days) {
    const max = Math.max(...days.map((d) => Number(d.total)), 0);
    const todayIdx = days.length - 1;
    $("bars").innerHTML = days.map((d, i) => {
      const total = Number(d.total);
      const h = total > 0 && max > 0 ? Math.max(6, (total / max) * 100) : 0;
      return (
        '<div class="bar-col' + (i === todayIdx ? " is-today" : "") + '">' +
        '<div class="bar-track">' +
        (total > 0 ? '<span class="bar-val">' + esc(fmt.money(d.total)) + "</span>" : "") +
        '<div class="bar' + (h ? "" : " bar-zero") + '" style="height:' + (h ? h + "%" : "1px") + '"></div>' +
        "</div>" +
        '<div class="bar-label">' + (i === todayIdx ? "Today" : esc(d.label)) + "</div></div>"
      );
    }).join("");
  }

  function renderRecent(rows) {
    if (!rows.length) {
      $("recent-list").innerHTML = '<li class="recent-empty">No sales yet</li>';
      return;
    }
    $("recent-list").innerHTML = rows.map((r) => (
      '<li><a class="recent-row" href="/sales/' + encodeURIComponent(r.id) + '">' +
      '<span class="avatar' + (r.walk_in ? " avatar-walkin" : "") + '">' + esc(fmt.initials(r.customer)) + "</span>" +
      '<span class="recent-info"><b>' + esc(r.customer) + "</b>" +
      "<small>" + esc(r.number) + " · " + esc(r.time) + "</small><small>" + esc(r.items) + "</small></span>" +
      '<span class="recent-amt"><b>' + esc(fmt.money(r.amount)) + "</b>" +
      '<span class="badge badge-' + esc(r.status) + '">' + (r.status === "paid" ? "Paid" : "Pending") + "</span></span>" +
      "</a></li>"
    )).join("");
  }

  function render(d) {
    $("hero-sales").textContent = fmt.money(d.today.sales);
    $("hero-payments").textContent = fmt.money(d.today.payments);
    $("hero-udhaar").textContent = fmt.money(d.today.udhaar_amount);
    $("hero-udhaar-count").textContent = d.today.udhaar_customers + " customer" + (d.today.udhaar_customers === 1 ? "" : "s");
    $("stat-full").textContent = d.stock.full;
    $("stat-empty").textContent = d.stock.empty;
    $("stat-with").textContent = d.stock.with_customers;
    $("stat-customers").textContent = d.stock.total_customers;
    $("chart-total").textContent = fmt.money(d.last7_total);
    renderBars(d.last7);
    renderRecent(d.recent);
  }

  async function load() {
    $("dash-error").hidden = true;
    try {
      render(await Api.get("/api/dashboard"));
    } catch (e) {
      $("dash-error").hidden = false;
      $("dash-error").querySelector("span").textContent = "Could not load the dashboard. " + e.message;
    }
  }

  $("dash-retry").addEventListener("click", load);
  $("qa-receive").addEventListener("click", UI.receivePayment);
  $("qa-purchase").addEventListener("click", UI.newPurchase);
  load();
})();
