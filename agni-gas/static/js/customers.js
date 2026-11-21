// Customers page: customer list (+ Udhaar filter) and Payment history.
(function () {
  const { fmt, esc } = UI;
  const $ = (id) => document.getElementById(id);
  const state = { tab: "list", type: "all", q: "", payQ: "", from: "", to: "" };
  let listSeq = 0, paySeq = 0;

  function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
  function showError(msg) {
    const box = $("cust-error");
    box.hidden = !msg;
    if (msg) box.querySelector("span").textContent = msg;
  }

  /* ---------- customer list ---------- */
  function emptyState() {
    if (state.q || state.type !== "all") {
      return '<div class="state"><b>Nothing found</b>' +
        (state.type === "udhaar" && !state.q ? "No customer owes you money right now." : "Try a different name, phone or filter.") + "</div>";
    }
    return '<div class="state"><b>No customers yet</b>Add your first customer to get started.' +
      '<button class="btn btn-dark" data-add type="button"><i data-icon="userPlus"></i>Add customer</button></div>';
  }

  function renderList(rows) {
    $("list").innerHTML = rows.length ? rows.map((r) => {
      const owes = Number(r.balance) > 0;
      return '<a class="row" href="/customers/' + r.id + '">' +
        '<span class="avatar' + (owes ? " avatar-owe" : "") + '">' + esc(fmt.initials(r.name)) + "</span>" +
        '<span class="row-name"><b>' + esc(r.name) + "</b><small>" + esc(r.type_label) +
        (r.phone ? " · " + esc(r.phone) : "") + "</small></span>" +
        (r.cylinders > 0 ? '<span class="pill">' + r.cylinders + " cylinder" + (r.cylinders === 1 ? "" : "s") + "</span>" : "") +
        Cust.balanceTag(r.balance) + "</a>";
    }).join("") : emptyState();
    Icons.render($("list"));
  }

  async function loadList() {
    const seq = ++listSeq;
    const p = new URLSearchParams();
    if (state.q) p.set("q", state.q);
    if (state.type === "retail" || state.type === "wholesale") p.set("type", state.type);
    if (state.type === "udhaar") p.set("owing", "1");
    try {
      const [rows, sum] = await Promise.all([
        Api.get("/api/customers?" + p),
        state.type === "udhaar" ? Api.get("/api/customers/summary") : Promise.resolve(null),
      ]);
      if (seq !== listSeq) return;                 // a newer search already started
      showError("");
      $("sum").hidden = !sum;
      if (sum) {
        $("sum-total").textContent = fmt.money(sum.total_udhaar);
        $("sum-count").textContent = sum.owing_count;
      }
      renderList(rows);
    } catch (e) {
      if (seq === listSeq) showError("Could not load customers. " + e.message);
    }
  }

  /* ---------- payment history ---------- */
  function renderPayments(rows) {
    if (!rows.length) {
      $("pay-table").innerHTML = '<div class="state"><b>No payments found</b>' +
        (state.payQ || state.from || state.to ? "Try a different search or dates." : "Payments you receive will show up here.") + "</div>";
      return;
    }
    $("pay-table").innerHTML =
      '<table class="tbl"><thead><tr><th>Date</th><th>Receipt</th><th>Customer</th><th>Received in</th><th>Note</th>' +
      '<th class="num">Amount</th><th></th></tr></thead><tbody>' +
      rows.map((p) => {
        const off = p.status === "cancelled";
        return '<tr class="' + (off ? "is-cancelled" : "") + '"><td>' + esc(Cust.date(p.date)) + "</td>" +
          "<td>" + esc(p.number) + (off ? '<span class="badge badge-cancelled">Cancelled</span>' : "") + "</td>" +
          '<td><a href="/customers/' + p.customer_id + '">' + esc(p.customer) + "</a></td>" +
          "<td>" + esc(p.received_in_label) + "</td><td>" + esc(p.note || "") + "</td>" +
          '<td class="num ' + (off ? "strike" : "text-green") + '">' + esc(fmt.money(p.amount)) + "</td>" +
          "<td>" + (off ? "" : '<button class="link-btn" data-cancel="' + p.id + '" data-num="' + esc(p.number) +
            '" data-amt="' + esc(p.amount) + '" type="button">Cancel</button>') + "</td></tr>";
      }).join("") + "</tbody></table>";
  }

  async function loadPayments() {
    const seq = ++paySeq;
    const p = new URLSearchParams();
    if (state.payQ) p.set("q", state.payQ);
    if (state.from) p.set("from", state.from);
    if (state.to) p.set("to", state.to);
    try {
      const rows = await Api.get("/api/payments?" + p);
      if (seq !== paySeq) return;
      showError("");
      renderPayments(rows);
    } catch (e) {
      if (seq === paySeq) showError("Could not load payments. " + e.message);
    }
  }

  /* ---------- tabs and actions ---------- */
  function setTab(tab) {
    state.tab = tab;
    $("tab-list").classList.toggle("on", tab === "list");
    $("tab-history").classList.toggle("on", tab === "history");
    $("view-list").hidden = tab !== "list";
    $("view-history").hidden = tab !== "history";
    try { history.replaceState(null, "", tab === "history" ? "#history" : location.pathname); } catch (_) { /* ignore */ }
    refresh();
  }
  const refresh = () => (state.tab === "list" ? loadList() : loadPayments());
  const addCustomer = () => Cust.openCustomerForm({ onSaved: refresh });
  const receive = (customer) => Cust.openReceive({ customer, onSaved: refresh });

  $("tab-list").addEventListener("click", () => setTab("list"));
  $("tab-history").addEventListener("click", () => setTab("history"));
  $("btn-add").addEventListener("click", addCustomer);
  $("btn-receive").addEventListener("click", () => UI.selectCustomer(receive));
  $("cust-retry").addEventListener("click", refresh);
  $("list").addEventListener("click", (e) => { if (e.target.closest("[data-add]")) addCustomer(); });

  $("chips").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    state.type = chip.dataset.type;
    document.querySelectorAll("#chips .chip").forEach((c) => c.classList.toggle("on", c === chip));
    loadList();
  });
  $("search").addEventListener("input", debounce((e) => { state.q = e.target.value.trim(); loadList(); }, 250));
  $("pay-search").addEventListener("input", debounce((e) => { state.payQ = e.target.value.trim(); loadPayments(); }, 250));
  $("pay-from").addEventListener("change", (e) => { state.from = e.target.value; loadPayments(); });
  $("pay-to").addEventListener("change", (e) => { state.to = e.target.value; loadPayments(); });

  $("pay-table").addEventListener("click", (e) => {
    const b = e.target.closest("[data-cancel]");
    if (!b) return;
    Cust.openConfirm({
      title: "Cancel payment " + b.dataset.num + "?",
      message: "The payment of " + fmt.money(b.dataset.amt) + " will be marked cancelled and added back to the customer's balance. The entry stays in the records.",
      confirmLabel: "Yes, cancel payment", cancelLabel: "Keep payment", danger: true,
      onConfirm: async () => { await Api.post("/api/payments/" + b.dataset.cancel + "/cancel"); Cust.toast("Payment cancelled"); loadPayments(); },
    });
  });

  /* ---------- start ---------- */
  const params = new URLSearchParams(location.search);   // read BEFORE setTab() cleans the URL
  setTab(location.hash === "#history" ? "history" : "list");
  if (params.get("add") === "1") {
    history.replaceState(null, "", location.pathname);
    addCustomer();
  } else if (params.get("receive")) {
    const id = Number(params.get("receive"));
    history.replaceState(null, "", location.pathname);
    Api.get("/api/customers/" + id).then(receive).catch((e) => Cust.toast(e.message, "error"));
  }
})();
