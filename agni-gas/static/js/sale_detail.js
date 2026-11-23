// Printable customer tax invoice. All values come from the saved invoice snapshots.
(function () {
  const $ = (id) => document.getElementById(id);
  const { esc, fmt } = UI;
  const sid = Number(location.pathname.split('/').pop());
  const justSaved = new URLSearchParams(location.search).get('new') === '1';
  let sale = null;
  const rupees = (n) => fmt.money(n);
  const label = (line) => {
    if (line.kind === 'deposit' || line.kind === 'deposit_refund' || line.kind === 'deposit_forfeit' || line.kind === 'deposit_retained' || line.kind === 'empty_in') return line.name;
    return line.name + (line.detail ? ' — ' + line.detail : '');
  };
  const taxAmount = (line) => Number(line.cgst || 0) + Number(line.sgst || 0) + Number(line.igst || 0);

  function lineRow(line, index) {
    const informational = line.kind === 'empty_in' || line.kind === 'deposit_forfeit' || line.kind === 'deposit_retained';
    const amount = Number(line.amount || 0);
    const tax = taxAmount(line);
    return '<tr' + (informational ? ' class="rc-info-line"' : '') + '><td>' + (index + 1) + '</td>' +
      '<td>' + esc(label(line)) + (line.detail && line.kind !== 'product' ? '<small>' + esc(line.detail) + '</small>' : '') + '</td>' +
      '<td>' + esc(line.hsn || '—') + '</td><td class="num">' + esc(line.qty) + '</td><td>' + esc(line.unit || '—') + '</td>' +
      '<td class="num">' + (informational ? '—' : esc(rupees(line.rate))) + '</td>' +
      '<td class="num">' + (line.kind === 'product' ? esc(rupees(line.taxable)) : '—') + '</td>' +
      '<td class="num">' + (line.gst_rate == null ? '—' : esc(String(line.gst_rate)) + '%') + '</td>' +
      '<td class="num">' + (tax ? esc(rupees(tax.toFixed ? tax.toFixed(2) : tax)) : '—') + '</td>' +
      '<td class="num"><b>' + (amount < 0 ? '− ' : '') + (informational ? '—' : esc(rupees(Math.abs(amount)))) + '</b></td></tr>';
  }
  function sumRow(labelText, value, cls, prefix) {
    return '<div class="' + (cls || '') + '"><span>' + labelText + '</span><b>' + (prefix || '') + esc(rupees(value)) + '</b></div>';
  }
  function render() {
    const b = sale.business || {}, c = sale.customer || null, cancelled = sale.status === 'cancelled';
    $('rc-main').hidden = false;
    $('rc-title').textContent = 'Invoice ' + sale.number;
    $('rc-download-pdf').href = '/api/sales/' + sid + '/pdf';
    $('rc-sub').textContent = Cust.date(sale.date) + ' · ' + sale.time;
    $('rc-number').textContent = sale.number;
    $('rc-date').textContent = Cust.date(sale.date);
    $('rc-place').textContent = [sale.place_state_code, sale.place_state_name].filter(Boolean).join(' · ') || '—';
    $('rc-biz-name').textContent = b.name || '';
    $('rc-doc-type').textContent = b.gstin ? 'TAX INVOICE' : 'INVOICE';
    $('rc-copy-label').textContent = b.gstin ? 'Original for recipient' : 'Customer copy';
    $('rc-biz-address').textContent = b.address || '';
    $('rc-biz-contact').textContent = [b.phone, b.email].filter(Boolean).join(' · ');
    $('rc-biz-gstin').textContent = b.gstin ? 'GSTIN: ' + b.gstin : '';
    $('rc-biz-pan').textContent = b.pan ? 'PAN: ' + b.pan : '';
    $('rc-customer').textContent = c ? c.name : 'Walk-in customer';
    $('rc-customer-address').textContent = c ? (c.billing_address || c.address || '') : '';
    $('rc-customer-gstin').textContent = c && c.gstin ? 'GSTIN: ' + c.gstin : 'Unregistered customer';
    $('rc-lines').innerHTML = sale.lines.map(lineRow).join('');

    const taxRows = [];
    if (Number(sale.cgst)) taxRows.push(sumRow('CGST', sale.cgst));
    if (Number(sale.sgst)) taxRows.push(sumRow('SGST', sale.sgst));
    if (Number(sale.igst)) taxRows.push(sumRow('IGST', sale.igst));
    if (!taxRows.length) taxRows.push('<div><span>GST</span><b>—</b></div>');
    $('rc-tax-rows').innerHTML = taxRows.join('');
    const groups = sale.grouped_lines || [];
    $('rc-tax-groups').innerHTML = groups.length ? '<table><thead><tr><th>HSN</th><th>GST</th><th>Taxable</th><th>Tax</th></tr></thead><tbody>' +
      groups.map((g) => '<tr><td>' + esc(g.hsn || '—') + '</td><td>' + esc(g.gst_rate == null ? '—' : String(g.gst_rate) + '%') +
        '</td><td>' + esc(rupees(g.taxable)) + '</td><td>' + esc(rupees(Number(g.cgst || 0) + Number(g.sgst || 0) + Number(g.igst || 0))) + '</td></tr>').join('') +
      '</tbody></table>' : '';

    const rows = [sumRow('Product subtotal', sale.subtotal)];
    if (Number(sale.discount)) rows.push(sumRow('Discount', sale.discount, 'rc-negative', '− '));
    rows.push(sumRow('Taxable value', sale.taxable));
    rows.push(sumRow('Total GST', sale.gst));
    if (Number(sale.deposit_received)) rows.push(sumRow('Refundable security deposit received', sale.deposit_received));
    if (Number(sale.deposit_refunded)) rows.push(sumRow('Refundable security deposit refunded', sale.deposit_refunded, 'rc-negative', '− '));
    if (Number(sale.retained_deposits)) rows.push(sumRow('Customer deposits retained', sale.retained_deposits));
    const total = Number(sale.total);
    rows.push(sumRow(total < 0 ? 'Amount to be paid back' : 'Invoice total payable', Math.abs(total), 'rc-total'));
    rows.push(sumRow(sale.paid_label || (total < 0 ? 'Paid back' : 'Amount received'), Math.abs(Number(sale.paid)), ''));
    if (Number(sale.due) > 0 && !cancelled) rows.push(sumRow('Balance due', sale.due, 'rc-due'));
    $('rc-sums').innerHTML = rows.join('');
    const depositLines = sale.lines.filter((line) => ['deposit', 'deposit_refund', 'deposit_forfeit', 'deposit_retained', 'empty_in'].includes(line.kind));
    $('rc-deposit-box').hidden = !depositLines.length && !Number(sale.retained_deposits);
    $('rc-deposit-lines').innerHTML = depositLines.map((line) => '<div><span>' + esc(label(line)) +
      (line.detail ? '<small>' + esc(line.detail) + '</small>' : '') + '</span><b>' +
      (line.kind === 'deposit_refund' ? '− ' + esc(rupees(Math.abs(Number(line.amount || 0)))) + (Number(line.retained || 0) ? ' · ' + esc(rupees(line.retained)) + ' retained' : '') :
       line.kind === 'deposit' ? '+ ' + esc(rupees(line.amount)) :
       Number(line.retained || 0) ? esc(rupees(line.retained)) + ' retained' : '—') + '</b></div>').join('');
    $('rc-bank').textContent = [b.bank_name, b.bank_account ? 'A/c ' + b.bank_account : '', b.bank_ifsc ? 'IFSC ' + b.bank_ifsc : ''].filter(Boolean).join(' · ');
    $('rc-terms').textContent = b.terms || '';
    $('rc-sign-name').textContent = b.name || '';
    const words = String(sale.amount_in_words || '');
    $('rc-words').textContent = (Number(sale.total) < 0 ? 'Refund payable: ' : 'Amount in words: ') + words.replace(/^Minus\s+/, '');
    $('rc-words').hidden = false;
    $('rc-cancel-detail').textContent = cancelled ? [sale.cancel_reason ? 'Reason: ' + sale.cancel_reason : '', sale.cancelled_at_label ? 'Cancelled: ' + sale.cancelled_at_label : ''].filter(Boolean).join(' · ') : '';
    $('rc-saved').hidden = !(justSaved && !cancelled);
    $('rc-void').hidden = !cancelled;
    $('rc-stamp').hidden = !cancelled;
    $('rc-cancel').hidden = cancelled;
    $('rc-paper').classList.toggle('is-void', cancelled);
    Cust.renderIcons(); if (window.Icons) Icons.render(document);
  }
  async function load() {
    $('rc-error').hidden = true;
    try { sale = await Api.get('/api/sales/' + sid); render(); }
    catch (e) { $('rc-main').hidden = true; $('rc-error').hidden = false; $('rc-error').querySelector('span').textContent = 'Could not load invoice. ' + e.message; }
  }
  function whatsappText() {
    const lines = sale.lines.filter((x) => x.kind !== 'empty_in' && x.kind !== 'deposit_forfeit')
      .map((x) => '• ' + x.qty + ' x ' + label(x) + ' = ' + rupees(x.amount));
    return ['*' + (sale.business && sale.business.name || 'Agency') + '*', 'Invoice ' + sale.number + ' · ' + Cust.date(sale.date), '']
      .concat(lines, ['', 'Total: ' + rupees(Math.abs(Number(sale.total))), 'Paid: ' + rupees(Math.abs(Number(sale.paid)))],
        Number(sale.due) > 0 ? ['Balance due: ' + rupees(sale.due)] : [], ['']).join('\n');
  }
  $('rc-wa').addEventListener('click', () => {
    const digits = ((sale.customer && sale.customer.phone) || '').replace(/\D/g, '');
    const phone = digits.length === 10 ? '91' + digits : digits;
    window.open('https://wa.me/' + phone + '?text=' + encodeURIComponent(whatsappText()), '_blank', 'noopener');
  });
  $('rc-print').addEventListener('click', () => window.print());
  $('rc-retry').addEventListener('click', load);
  $('rc-cancel').addEventListener('click', () => {
    const body = UI.openModal('Cancel invoice ' + (sale && sale.number || ''));
    const paid = sale ? Number(sale.paid || 0) : 0;
    const refund = Math.abs(paid);
    const collect = paid < 0;
    const channel = sale.received_in === 'bank' ? 'bank / UPI' : 'cash';
    body.innerHTML = '<form novalidate><p class="hint">Stock and customer cylinder balances will be reversed. The invoice remains in history as cancelled.</p>' +
      '<div class="rc-cancel-refund"><span>' + (collect ? 'Amount to collect back' : 'Paid amount to refund') + '</span><b>' + esc(rupees(refund)) + '</b><small>' + esc((collect ? 'Collect via ' : 'Refund via ') + channel) + '</small></div>' +
      '<label class="field"><span>Cancellation reason *</span><textarea class="textarea" name="reason" maxlength="200" required placeholder="Why is this invoice being cancelled?"></textarea></label>' +
      '<div class="form-error" role="alert"></div><div class="modal-foot"><button type="button" class="btn btn-white" data-close>Keep invoice</button>' +
      '<button type="submit" class="btn btn-danger">Cancel invoice</button></div></form>';
    const form = body.querySelector('form');
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const reason = form.elements.reason.value.trim();
      if (!reason) { form.querySelector('.form-error').textContent = 'Enter a cancellation reason.'; return; }
      const button = form.querySelector('[type="submit"]'); button.disabled = true;
      try { const result = await Api.post('/api/sales/' + sid + '/cancel', { reason }); UI.closeModal(); Cust.toast(result.refund_direction === 'collect' ? 'Invoice cancelled; collect the payout back' : 'Invoice cancelled'); await load(); }
      catch (err) { form.querySelector('.form-error').textContent = err.message || 'Could not cancel invoice.'; button.disabled = false; }
    });
  });
  load();
})();