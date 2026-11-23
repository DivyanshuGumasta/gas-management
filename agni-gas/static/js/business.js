(function () {
  const form = document.getElementById('biz-form');
  const error = document.getElementById('biz-error');
  const fields = ['name','gstin','address','state_code','phone','email','bank_name','bank_account','bank_ifsc','terms','invoice_prefix'];
  function show(message) { error.hidden = !message; error.querySelector('span').textContent = message || ''; }
  async function load() {
    try {
      const data = await Api.get('/api/business');
      fields.forEach((key) => { if (form.elements[key]) form.elements[key].value = data[key] || (key === 'invoice_prefix' ? 'S' : ''); });
    } catch (e) { show('Could not load invoice settings. ' + e.message); }
  }
  form.addEventListener('submit', async (event) => {
    event.preventDefault(); show('');
    const payload = {};
    fields.forEach((key) => { payload[key] = form.elements[key].value.trim(); });
    const button = form.querySelector('[type="submit"]'); button.disabled = true;
    try { await Api.put('/api/business', payload); Cust.toast('Invoice settings saved'); }
    catch (e) { show(e.message || 'Could not save invoice settings.'); }
    finally { button.disabled = false; }
  });
  load();
})();