// Printable customer tax invoice. All values come from the saved invoice snapshots.
(function () {
  const $ = (id) => document.getElementById(id);
  const { esc, fmt } = UI;
  const sid = Number(location.pathname.split('/').pop());
  const justSaved = new URLSearchParams(location.search).get('new') === '1';
  let sale = null;
  const rupees = (n) => fmt.money(n);
  function indianWords(value) {
    const ones = ['Zero','One','Two','Three','Four','Five','Six','Seven','Eight','Nine','Ten','Eleven','Twelve','Thirteen','Fourteen','Fifteen','Sixteen','Seventeen','Eighteen','Nineteen'];
    const tens = ['', '', 'Twenty','Thirty','Forty','Fifty','Sixty','Seventy','Eighty','Ninety'];
    const underHundred = (n) => n < 20 ? ones[n] : tens[Math.floor(n / 10)] + (n % 10 ? ' ' + ones[n % 10] : '');
    function words(n) {
      if (n < 100) return underHundred(n);
      const parts = [];
      if (n >= 10000000) { parts.push(words(Math.floor(n / 10000000)) + ' Crore'); n %= 10000000; }
      if (n >= 100000) { parts.push(words(Math.floor(n / 100000)) + ' Lakh'); n %= 100000; }
      if (n >= 1000) { parts.push(words(Math.floor(n / 1000)) + ' Thousand'); n %= 1000; }
      if (n >= 100) { parts.push(ones[Math.floor(n / 100)] + ' Hundred'); n %= 100; }
      if (n) parts.push(underHundred(n));
      return parts.join(' ');
    }
    return words(Math.floor(Math.abs(value)));
  }
  const label = (line) => {
    if (line.kind === 'deposit' || line.kind === 'deposit_refund' || line.kind === 'deposit_forfeit' || line.kind === 'empty_in') return line.name;
    return line.name + (line.detail ? ' — ' + line.detail : '');
  };
  const taxAmount = (line) => Number(line.cgst || 0) + Number(line.sgst || 0) + Number(line.igst || 0);

  function lineRow(line, index) {
    const informational = line.kind === 'empty_in' || line.kind === 'deposit_forfeit';
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
    $('rc-sub').textContent = Cust.date(sale.date) + ' · ' + sale.time;
    $('rc-number').textContent = sale.number;
    $('rc-date').textContent = Cust.date(sale.date);
    $('rc-place').textContent = sale.place_state_code || '—';
    $('rc-rcm').textContent = sale.reverse_charge ? 'Yes' : 'No';
    $('rc-biz-name').textContent = b.name || '';
    $('rc-doc-type').textContent = b.gstin ? 'TAX INVOICE' : 'INVOICE';
    $('rc-copy-label').textContent = b.gstin ? 'Original for recipient' : 'Customer copy';
    $('rc-biz-address').textContent = b.address || '';
    $('rc-biz-contact').textContent = [b.phone, b.email].filter(Boolean).join(' · ');
    $('rc-biz-gstin').textContent = b.gstin ? 'GSTIN: ' + b.gstin : '';
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

    const rows = [sumRow('Product subtotal', sale.subtotal)];
    if (Number(sale.discount)) rows.push(sumRow('Discount', sale.discount, 'rc-negative', '− '));
    rows.push(sumRow('Taxable value', sale.taxable));
    rows.push(sumRow('Total GST', sale.gst));
    if (Number(sale.deposit_received)) rows.push(sumRow('Refundable security deposit received', sale.deposit_received));
    if (Number(sale.deposit_refunded)) rows.push(sumRow('Refundable security deposit refunded', sale.deposit_refunded, 'rc-negative', '− '));
    const total = Number(sale.total);
    rows.push(sumRow(total < 0 ? 'Amount to be paid back' : 'Invoice total payable', Math.abs(total), 'rc-total'));
    rows.push(sumRow(total < 0 ? 'Paid back' : 'Amount received', Math.abs(Number(sale.paid)), ''));
    if (Number(sale.due) > 0 && !cancelled) rows.push(sumRow('Balance due', sale.due, 'rc-due'));
    $('rc-sums').innerHTML = rows.join('');
    $('rc-bank').textContent = [b.bank_name, b.bank_account ? 'A/c ' + b.bank_account : '', b.bank_ifsc ? 'IFSC ' + b.bank_ifsc : ''].filter(Boolean).join(' · ');
    $('rc-terms').textContent = b.terms || '';
    $('rc-sign-name').textContent = b.name || '';
    const totalPaise = Math.round(Math.abs(Number(sale.total)) * 100);
    const words = 'Rupees ' + indianWords(Math.floor(totalPaise / 100)) +
      (totalPaise % 100 ? ' and ' + indianWords(totalPaise % 100) + ' Paise' : '') + ' Only';
    $('rc-words').textContent = (Number(sale.total) < 0 ? 'Refund payable: ' : 'Amount in words: ') + words;
    $('rc-words').hidden = false;
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
  $('rc-cancel').addEventListener('click', () => Cust.openConfirm({
    title: 'Cancel this invoice?', danger: true, confirmLabel: 'Cancel invoice', cancelLabel: 'Keep invoice',
    message: 'Stock and customer cylinder balances will be reversed. The original invoice remains in history, marked cancelled. A damaged cylinder already dispatched to a supplier cannot be cancelled.',
    onConfirm: async () => { await Api.post('/api/sales/' + sid + '/cancel', {}); Cust.toast('Invoice cancelled'); await load(); },
  }));
  load();
})();