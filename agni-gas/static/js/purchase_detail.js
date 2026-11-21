(function () {
  const $ = (id) => document.getElementById(id);
  const esc = UI.esc, fmt = UI.fmt;
  const pid = Number(location.pathname.split("/").pop());
  let purchase = null;

  function money(value) { return esc(fmt.money(value)); }
  function attachmentUrl(path) {
    const base = (window.APP_CONFIG && window.APP_CONFIG.apiBase) || "";
    return (base ? base.replace(/\/$/, "") : "") + path;
  }
  function showError(message) {
    $("pd-error-text").textContent = message || "";
    $("pd-error").hidden = !message;
  }

  function renderAttachment() {
    const hasAttachment = !!purchase.attachment_url;
    const url = hasAttachment ? attachmentUrl(purchase.attachment_url) : "";
    const mime = purchase.attachment_mime || "";

    $("pd-no-attachment").hidden = hasAttachment;
    $("pd-image-wrap").hidden = !(hasAttachment && mime.startsWith("image/"));
    $("pd-pdf-wrap").hidden = !(hasAttachment && mime === "application/pdf");
    $("pd-attachment-file").hidden = !hasAttachment;
    $("pd-remove-attachment").hidden = !hasAttachment;
    $("pd-file-label").textContent = hasAttachment ? "Replace supplier invoice" : "Choose supplier invoice";
    $("pd-upload-attachment").textContent = hasAttachment ? "Replace invoice file" : "Attach supplier invoice";

    if (hasAttachment) {
      $("pd-attachment-name").textContent = purchase.attachment_name || "Supplier invoice";
      $("pd-open-attachment").href = url;
      if (mime.startsWith("image/")) {
        $("pd-invoice-image").src = url;
      } else if (mime === "application/pdf") {
        $("pd-invoice-pdf").src = url;
      }
    } else {
      $("pd-invoice-image").removeAttribute("src");
      $("pd-invoice-pdf").removeAttribute("src");
    }
  }

  async function load() {
    showError("");
    try {
      purchase = await Api.get("/api/purchases/" + pid);
      $("pd-main").hidden = false;
      $("pd-title").textContent = "Purchase " + purchase.number;
      $("pd-subtitle").textContent = purchase.date + " · Internal purchase entry";
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
        ["Purchase total", purchase.total], ["Paid", purchase.paid], ["Outstanding", purchase.due],
      ].map((row, index) => '<div class="pd-total-row ' + (index === 2 ? 'grand' : '') + '"><span>' + esc(row[0]) + '</span><b>' + money(row[1]) + '</b></div>').join("");
      $("pd-payments-list").innerHTML = purchase.payments.length ? purchase.payments.map((payment) =>
        '<div class="pd-payment-line"><span><b>' + esc(payment.number) + '</b><br><small>' + esc(payment.date) + ' · ' +
        (payment.paid_from === "cash" ? "Cash in hand" : "Bank / UPI") +
        (payment.status === "cancelled" ? " · Cancelled" : "") +
        (payment.note ? ' · ' + esc(payment.note) : '') + '</small></span><b>' + money(payment.amount) + '</b></div>'
      ).join("") : '<small class="sub">No payments have been recorded against this purchase yet.</small>';
      $("pd-note").textContent = purchase.note ? "Note: " + purchase.note : "";
      renderAttachment();
    } catch (err) {
      $("pd-main").hidden = true;
      showError("Could not load purchase. " + err.message);
    }
  }

  $("pd-retry").addEventListener("click", load);
  $("pd-attachment-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = $("pd-invoice-file").files[0];
    $("pd-file-error").textContent = "";
    $("pd-file-status").textContent = "";
    if (!file) {
      $("pd-file-error").textContent = "Choose the supplier's original invoice first.";
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      $("pd-file-error").textContent = "The invoice file must be 5 MB or smaller.";
      return;
    }
    const formData = new FormData();
    formData.append("supplier_bill", file, file.name);
    const button = $("pd-upload-attachment");
    button.disabled = true;
    button.textContent = "Uploading…";
    try {
      await Api.postForm("/api/purchases/" + pid + "/attachment", formData);
      $("pd-invoice-file").value = "";
      $("pd-file-status").textContent = "Supplier invoice attached.";
      await load();
    } catch (err) {
      $("pd-file-error").textContent = err.message || "Could not attach the supplier invoice.";
    } finally {
      button.disabled = false;
      button.textContent = purchase && purchase.attachment_url ? "Replace invoice file" : "Attach supplier invoice";
    }
  });

  $("pd-remove-attachment").addEventListener("click", () => {
    SupplierUI.openConfirm({
      title: "Remove supplier invoice attachment?",
      message: "The attached file will be removed. The purchase entry, stock and supplier ledger will not change.",
      confirmLabel: "Remove attachment", danger: true,
      onConfirm: async () => {
        await Api.del("/api/purchases/" + pid + "/attachment");
        $("pd-invoice-file").value = "";
        $("pd-file-status").textContent = "Supplier invoice attachment removed.";
        await load();
      },
    });
  });

  load();
})();
