// Sale receipt: print, WhatsApp, cancel bill.
(function () {
  const $ = (id) => document.getElementById(id);
  const { esc, fmt } = UI;
  const sid = Number(location.pathname.split("/").pop());
  const justSaved = new URLSearchParams(location.search).get("new") === "1";
  let sale = null;

  const KIND = { deposit_back: "Deposit given back", refill: "Refill", new_full: "New cylinder + gas", new_empty: "Empty cylinder", empty_in: "Empty received", item: "" };
  const MODE = { cash: "Cash in hand", bank: "Bank / UPI" };
  const showError = (m) => { const b = $("rc-error"); b.querySelector("span").textContent = m || ""; b.hidden = !m; };

  function lineRow(l) {
    const label = l.kind === "item" ? esc(l.name) + (l.detail ? " <small>(" + esc(l.detail) + ")</small>" : "")
      : esc(l.name) + " <small>" + esc(KIND[l.kind] || "") + "</small>";
    const free = l.kind === "empty_in", back = l.kind === "deposit_back";
    return "<tr><td>" + label + '</td><td class="num">' + esc(l.qty) + '</td><td class="num">' + (free ? "—" : esc(fmt.money(l.rate))) +
      '</td><td class="num"><b>' + (free ? "—" : (back ? "- " : "") + esc(fmt.money(l.amount))) + "</b></td></tr>";
  }
  function sumRow(label, value, cls) { return '<div class="' + (cls || "") + '"><span>' + label + "</span><b>" + esc(fmt.money(value)) + "</b></div>"; }

  function render() {
    const cancelled = sale.status === "cancelled";
    $("rc-main").hidden = false;
    $("rc-title").textContent = "Sale " + sale.number;
    $("rc-sub").textContent = Cust.date(sale.date) + " · " + sale.time;
    $("rc-number").textContent = sale.number;
    $("rc-date").textContent = Cust.date(sale.date) + ", " + sale.time;
    $("rc-customer").textContent = sale.customer ? sale.customer.name : "Walk-in customer";
    $("rc-lines").innerHTML = sale.lines.map(lineRow).join("");
    const rows = [sumRow("Subtotal", sale.subtotal)];
    if (Number(sale.discount)) rows.push("<div><span>Discount</span><b>- " + esc(fmt.money(sale.discount)) + "</b></div>");
    rows.push(sumRow("GST (" + sale.gst_percent + "%)", sale.gst));
    if (Number(sale.deposit_back)) rows.push("<div><span>Deposit given back</span><b>- " + esc(fmt.money(sale.deposit_back)) + "</b></div>");
    const out = Number(sale.total) < 0;                      // more deposit handed back than the customer bought
    rows.push(sumRow(out ? "Given back to customer" : "Total (incl. GST)", out ? String(-Number(sale.total)) : sale.total, "rc-total"));
    rows.push(sumRow((out ? "Paid out (" : "Paid (") + (MODE[sale.received_in] || "Cash in hand") + ")", out ? String(-Number(sale.paid)) : sale.paid));
    if (Number(sale.due) > 0 && !cancelled) rows.push(sumRow("Udhaar (to pay)", sale.due, "rc-due"));
    $("rc-sums").innerHTML = rows.join("");
    $("rc-saved").hidden = !(justSaved && !cancelled);
    $("rc-void").hidden = !cancelled;
    $("rc-stamp").hidden = !cancelled;
    $("rc-cancel").hidden = cancelled;
    $("rc-paper").classList.toggle("is-void", cancelled);
    Cust.renderIcons(); if (window.Icons) Icons.render(document);
  }

  async function load() {
    showError("");
    try { sale = await Api.get("/api/sales/" + sid); render(); }
    catch (e) { $("rc-main").hidden = true; showError("Could not load this sale. " + e.message); }
  }

  function whatsappText() {
    const lines = sale.lines.filter((l) => l.kind !== "empty_in").map((l) => "• " + l.qty + " x " + l.name + (l.kind === "item" ? "" : " (" + (KIND[l.kind] || "").toLowerCase() + ")") + " = " + fmt.money(l.amount));
    return ["*" + ($("rc-main").querySelector("[data-biz-name]").textContent || "Agni Gas Agency") + "*", "Receipt " + sale.number + " · " + Cust.date(sale.date), ""]
      .concat(lines, ["", "Total: " + fmt.money(sale.total), "Paid: " + fmt.money(sale.paid)],
        Number(sale.due) > 0 ? ["To pay: " + fmt.money(sale.due)] : [], ["", "Thank you!"]).join("\n");
  }
  $("rc-wa").addEventListener("click", () => {
    const digits = ((sale.customer && sale.customer.phone) || "").replace(/\D/g, "");
    const phone = digits.length === 10 ? "91" + digits : digits;     // 10-digit Indian numbers get +91
    window.open("https://wa.me/" + phone + "?text=" + encodeURIComponent(whatsappText()), "_blank", "noopener");
  });
  $("rc-print").addEventListener("click", () => window.print());
  $("rc-retry").addEventListener("click", load);
  $("rc-cancel").addEventListener("click", () => Cust.openConfirm({
    title: "Cancel this bill?", danger: true, confirmLabel: "Yes, cancel bill", cancelLabel: "Keep bill",
    message: "Stock goes back on the shelf and any udhaar on this bill is removed. The receipt stays on record, marked cancelled. This cannot be undone.",
    onConfirm: async () => { await Api.post("/api/sales/" + sid + "/cancel", {}); Cust.toast("Bill cancelled"); await load(); },
  }));
  load();
})();