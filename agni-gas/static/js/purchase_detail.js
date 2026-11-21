(function () {
  const $ = (id) => document.getElementById(id);
  const esc = UI.esc, fmt = UI.fmt;
  const pid = Number(location.pathname.split("/").pop());
  let purchase = null;
  function money(value) { return esc(fmt.money(value)); }

  async function load() {
    $("pd-error").hidden = true;
    try {
      purchase = await Api.get("/api/purchases/" + pid);
      $("pd-main").hidden = false;
      $("pd-title").textContent = "Purchase " + purchase.number;
      $("pd-subtitle").textContent = purchase.date;
      $("pd-number").textContent = purchase.number;
      $("pd-supplier").textContent = purchase.supplier;
      $("pd-gstin").textContent = "GSTIN: " + (purchase.gstin || "—");
      $("pd-date").textContent = purchase.date;
      const cylinders = (purchase.items || []).map((item) =>
        '<tr><td><b>' + esc(item.name) + '</b><small class="sub">Cylinder · full rate ' + money(item.rate) + ' · empty security rate ' + money(item.security_rate) + '</small></td>' +
        '<td class="num">' + item.full_in + '</td><td class="num">' + item.empty_out + '</td><td class="num">' + item.new_empty + '</td><td class="num">' + money(item.rate) + '</td><td class="num">' + money(item.amount) + '</td></tr>'
      );
      const goods = (purchase.catalog_items || []).map((item) =>
        '<tr><td><b>' + esc(item.name) + '</b><small class="sub">Other item · ' + esc(item.unit) + '</small></td>' +
        '<td class="num">' + esc(item.quantity) + ' ' + esc(item.unit) + '</td><td class="num">—</td><td class="num">—</td><td class="num">' + money(item.rate) + '</td><td class="num">' + money(item.amount) + '</td></tr>'
      );
      $("pd-items").innerHTML = cylinders.concat(goods).join("") || '<tr><td colspan="6">No items recorded.</td></tr>';
      $("pd-totals").innerHTML = [
        ["Subtotal", purchase.subtotal], ["GST (" + purchase.gst_percent + "%)", purchase.gst],
        ["Total (incl. GST)", purchase.total], ["Paid", purchase.paid], ["Outstanding", purchase.due],
      ].map((row, index) => '<div class="pd-total-row ' + (index === 2 ? 'grand' : '') + '"><span>' + esc(row[0]) + '</span><b>' + money(row[1]) + '</b></div>').join("");
      $("pd-payments-list").innerHTML = purchase.payments.length ? purchase.payments.map((payment) =>
        '<div class="pd-payment-line"><span><b>' + esc(payment.number) + '</b><br><small>' + esc(payment.date) + ' · ' +
        (payment.paid_from === "cash" ? "Cash in hand" : "Bank / UPI") +
        (payment.status === "cancelled" ? " · Cancelled" : "") +
        (payment.note ? ' · ' + esc(payment.note) : '') + '</small></span><b>' + money(payment.amount) + '</b></div>'
      ).join("") : '<small class="sub">No payments have been recorded against this purchase yet.</small>';
      $("pd-note").textContent = purchase.note ? "Note: " + purchase.note : "";
      const attachment = $("pd-attachment");
      if (purchase.attachment_url) {
        attachment.href = purchase.attachment_url;
        attachment.hidden = false;
        attachment.textContent = "View supplier bill";
      } else attachment.hidden = true;
      if (window.APP_CONFIG && window.APP_CONFIG.businessName) {
        document.querySelectorAll("[data-biz-name]").forEach((node) => node.textContent = window.APP_CONFIG.businessName);
      }
    } catch (err) {
      $("pd-main").hidden = true;
      $("pd-error-text").textContent = "Could not load purchase. " + err.message;
      $("pd-error").hidden = false;
    }
  }
  function printRecord() { window.print(); }
  function shareWhatsApp() {
    if (!purchase) return;
    const lines = [
      "Agni Gas Agency — purchase record",
      "Internal record; original supplier invoice should be retained.",
      "Purchase: " + purchase.number,
      "Date: " + purchase.date,
      "Supplier: " + purchase.supplier,
      "Items: " + purchase.items_summary,
      "Total: " + fmt.money(purchase.total),
      "Paid: " + fmt.money(purchase.paid),
      "Due: " + fmt.money(purchase.due),
    ];
    window.open("https://wa.me/?text=" + encodeURIComponent(lines.join("\n")), "_blank", "noopener");
  }
  $("pd-retry").addEventListener("click", load);
  $("pd-print").addEventListener("click", printRecord);
  $("pd-print-bottom").addEventListener("click", printRecord);
  $("pd-whatsapp").addEventListener("click", shareWhatsApp);
  load();
})();
