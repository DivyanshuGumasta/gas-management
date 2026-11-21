(function () {
  const $ = (id) => document.getElementById(id);
  const esc = UI.esc, fmt = UI.fmt;
  const pid = Number(location.pathname.split("/").pop());
  function money(v) { return esc(fmt.money(v)); }

  async function load() {
    $("pd-error").hidden = true;
    try {
      const p = await Api.get("/api/purchases/" + pid);
      $("pd-main").hidden = false;
      $("pd-title").textContent = "Purchase " + p.number;
      $("pd-subtitle").textContent = p.date;
      $("pd-number").textContent = p.number;
      $("pd-supplier").textContent = p.supplier;
      $("pd-gstin").textContent = "GSTIN: " + (p.gstin || "—");
      $("pd-date").textContent = p.date;
      const cylinderRows = (p.items || []).map((it) => '<tr><td><b>' + esc(it.name) + '</b><small class="sub">Cylinder · full cylinder rate ' + money(it.rate) + ' · empty security rate ' + money(it.security_rate) + '</small></td>' +
        '<td class="num">' + it.full_in + '</td><td class="num">' + it.empty_out + '</td><td class="num">' + it.new_empty + '</td><td class="num">' + money(it.rate) + '</td><td class="num">' + money(it.amount) + '</td></tr>');
      const catalogRows = (p.catalog_items || []).map((it) => '<tr><td><b>' + esc(it.name) + '</b><small class="sub">General item · ' + esc(it.unit) + '</small></td>' +
        '<td class="num">' + esc(it.quantity) + ' ' + esc(it.unit) + '</td><td class="num">—</td><td class="num">—</td><td class="num">' + money(it.rate) + '</td><td class="num">' + money(it.amount) + '</td></tr>');
      $("pd-items").innerHTML = cylinderRows.concat(catalogRows).join("") || '<tr><td colspan="6">No items recorded.</td></tr>';
      $("pd-totals").innerHTML = [
        ["Subtotal",p.subtotal], ["GST (" + p.gst_percent + "%)",p.gst], ["Total",p.total], ["Paid",p.paid], ["Outstanding on purchase",p.due],
      ].map((row,i) => '<div class="pd-total-row ' + (i===2 ? 'grand' : '') + '"><span>' + esc(row[0]) + '</span><b>' + money(row[1]) + '</b></div>').join("");
      $("pd-payments-list").innerHTML = p.payments.length ? p.payments.map((pay) => '<div class="pd-payment-line"><span><b>' + esc(pay.number) + '</b><br><small>' + esc(pay.date) + ' · ' + (pay.paid_from === "cash" ? "Cash" : "Bank / UPI") + (pay.status === "cancelled" ? " · Cancelled" : "") + '</small></span><b>' + money(pay.amount) + '</b></div>').join("") : '<small class="sub">No payments have been recorded against this purchase yet.</small>';
      $("pd-note").textContent = p.note ? "Note: " + p.note : "";
      const attachment = $("pd-attachment");
      if (p.attachment_url) { attachment.href = p.attachment_url; attachment.hidden = false; attachment.textContent = "View supplier bill · " + p.attachment_name; }
      else attachment.hidden = true;
    } catch (err) {
      $("pd-main").hidden = true;
      $("pd-error-text").textContent = "Could not load purchase. " + err.message;
      $("pd-error").hidden = false;
    }
  }
  $("pd-retry").addEventListener("click", load);
  $("pd-print").addEventListener("click", () => window.print());
  load();
})();
