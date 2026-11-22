// Stock & Price, part 2: suppliers on each cylinder, the damaged-cylinders area and sending cylinders back.
// Loads after stock.js and re-draws these parts every time stock.js has drawn the page.
(function () {
  const { esc, fmt } = UI;
  const money = (v) => fmt.money(v);
  const $ = (id) => document.getElementById(id);
  let ext = { cylinders: {}, damaged: [], damaged_dispatch_options: [], suppliers: [], deposits: {} };
  const supOf = (tid) => (ext.cylinders[tid] && ext.cylinders[tid].suppliers) || [];

  /* ---------- a tiny popup helper ---------- */
  function popup(title, intro, bodyHtml, submitLabel, run, success, onOpen) {
    const body = UI.openModal(title);
    body.innerHTML = '<form novalidate autocomplete="off">' + (intro ? '<p class="st-intro hint">' + esc(intro) + "</p>" : "") + bodyHtml +
      '<div class="form-error" role="alert"></div><div class="modal-foot"><button type="button" class="btn btn-white" data-close>Cancel</button>' +
      '<button type="submit" class="btn btn-dark">' + esc(submitLabel) + "</button></div></form>";
    const form = body.querySelector("form"), err = body.querySelector(".form-error");
    if (onOpen) onOpen(form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault(); err.textContent = "";
      const btn = form.querySelector("[type=submit]"); btn.disabled = true;
      try { await run(form); UI.closeModal(); StockUI.toast(success); StockUI.load(); }
      catch (ex) { err.textContent = ex.message || "Could not save."; btn.disabled = false; }
    });
  }
  const moneyBox = (name, label, value) => '<label class="field"><span>' + label + '</span><div class="amt"><i>Rs</i><input name="' + name +
    '" inputmode="decimal" autocomplete="off" placeholder="0" value="' + esc(value == null ? "" : value) + '"></div></label>';
  const supplierSelect = (name, label, list, blank, selectedId = null) => '<label class="field"><span>' + label + '</span><select name="' + name + '" class="amt">' +
    (blank ? '<option value="">' + blank + "</option>" : "") + list.map((s) =>
      '<option value="' + s.id + '"' + (String(selectedId) === String(s.id) ? ' selected' : '') + '>' + esc(s.name) + "</option>"
    ).join("") + "</select></label>";
  const cyl = (id) => StockUI.state.cylinders.find((c) => c.id === id);

  /* ---------- suppliers on each cylinder card (every number is that supplier's own) ---------- */
  function supplierPanel(c) {
    const list = supOf(c.id), x = ext.cylinders[c.id] || {};
    const cards = list.map((s) => {
      const neg = Number(s.margin) < 0;
      return '<div class="st-sup" data-tid="' + c.id + '" data-sid="' + s.supplier_id + '">' +
        '<div class="st-sup-top"><b>' + esc(s.name) + "</b></div>" +
        '<div class="st-sup-grid"><div><small>Buy at</small><b>' + money(s.price) + "</b></div>" +
        '<div><small>Security deposit</small><b>' + money(s.security) + "</b></div>" +
        '<div><small>Margin</small><b class="' + (neg ? "neg" : "pos") + '">' + money(s.margin) + "</b></div>" +
        "<div><small>Full</small><b>" + s.full + "</b></div><div><small>Empty</small><b>" + s.empty + "</b></div>" +
        "<div><small>Deposit held</small><b>" + money(s.deposit_held) + "</b></div></div>" +
        '<div class="st-sup-btns"><button type="button" class="link" data-xact="sup-adjust">Adjust stock</button>' +
        '<button type="button" class="link" data-xact="sup-edit">Change price &amp; deposit</button>' +
        '<button type="button" class="link" data-xact="sup-sendback">Send back</button>' +
        '<button type="button" class="link del" data-xact="sup-remove">Remove</button></div></div>';
    }).join("");
    const loose = (x.unassigned_full || x.unassigned_empty)
      ? '<p class="st-supplier">Not tied to a supplier: <b>' + (x.unassigned_full || 0) + " full, " + (x.unassigned_empty || 0) + " empty</b></p>" : "";
    return '<div class="st-sups"><div class="st-sups-head"><b>Suppliers</b>' +
      '<button type="button" class="btn btn-white" data-xact="sup-add" data-tid="' + c.id + '">＋ Add supplier</button></div>' +
      (cards || '<p class="st-supplier">No supplier sells this size yet.</p>') + loose + "</div>";
  }
  function decorateCards() {
    StockUI.state.cylinders.forEach((c) => {
      const card = $("cyl-" + c.id); if (!card) return;
      const old = card.querySelector(".st-supplier"); if (old) old.remove();
      const acts = card.querySelector(".st-actions");
      acts.insertAdjacentHTML("beforebegin", supplierPanel(c));
      acts.insertAdjacentHTML("afterbegin", '<button class="btn btn-white" data-xact="send-back" data-tid="' + c.id + '" type="button">Send back</button>');
    });
  }
  function addSupplier(tid) {
    const c = cyl(tid), linked = supOf(tid).map((s) => s.supplier_id);
    const free = ext.suppliers.filter((s) => !linked.includes(s.id));
    if (!free.length) { StockUI.toast(ext.suppliers.length ? "Every supplier already sells this size." : "Add a supplier first (Suppliers & Purchases).", true); return; }
    popup("Add supplier · " + c.name, "Each supplier has their own price and security deposit for this cylinder.",
      supplierSelect("supplier_id", "Supplier", free, null,
        ext.suppliers.length === 1 ? ext.suppliers[0].id : null) +
      '<div class="two">' + moneyBox("purchase_price", "Their price (full cylinder)") + moneyBox("security", "Their security deposit", c.security) + "</div>", "Add supplier",
      (f) => Api.post("/api/cylinders/" + tid + "/suppliers", { supplier_id: f.elements.supplier_id.value,
        purchase_price: f.elements.purchase_price.value.trim(), security: f.elements.security.value.trim() }),
      "Supplier added");
  }
  function editSupplier(tid, sid) {
    const s = supOf(tid).find((x) => x.supplier_id === sid);
    popup("Change price & deposit · " + s.name, "Applies to cylinders you buy from now on. Cylinders already bought keep the price they were bought at.",
      '<div class="two">' + moneyBox("purchase_price", "Their price (full cylinder)", s.price) + moneyBox("security", "Their security deposit", s.security) + "</div>", "Save",
      (f) => Api.put("/api/cylinders/" + tid + "/suppliers/" + sid, { purchase_price: f.elements.purchase_price.value.trim(), security: f.elements.security.value.trim() }),
      "Saved");
  }
  function adjustSupplier(tid, sid) {
    const s = supOf(tid).find((x) => x.supplier_id === sid), c = cyl(tid);
    popup("Adjust stock · " + c.name + " from " + s.name, "Type what you really have from this supplier. The difference is saved in Stock history and added to the size's total.",
      '<div class="two"><label class="field"><span>Full cylinders</span><div class="amt"><input name="full" type="number" min="0" step="1" value="' + s.full + '"><i>cyl</i></div></label>' +
      '<label class="field"><span>Empty cylinders</span><div class="amt"><input name="empty" type="number" min="0" step="1" value="' + s.empty + '"><i>cyl</i></div></label></div>', "Save stock",
      (f) => Api.post("/api/cylinders/" + tid + "/suppliers/" + sid + "/adjust", { full: f.elements.full.value.trim(), empty: f.elements.empty.value.trim() }),
      "Stock updated");
  }
  function removeSupplier(tid, sid) {
    const s = supOf(tid).find((x) => x.supplier_id === sid);
    Cust.openConfirm({ title: "Remove " + s.name + "?", danger: true, confirmLabel: "Remove",
      message: s.name + " will no longer be offered for " + cyl(tid).name + " in new purchases. Past purchases stay as they are.",
      onConfirm: async () => { await Api.del("/api/cylinders/" + tid + "/suppliers/" + sid); StockUI.toast("Supplier removed"); StockUI.load(); } });
  }

  /* ---------- send back ---------- */
  function sendBack(tid, sid) {
    const selectedSid = sid || (ext.suppliers.length === 1 ? ext.suppliers[0].id : 0);
    const c = cyl(tid), s = selectedSid ? supOf(tid).find((x) => x.supplier_id === selectedSid) : null;
    const opts = ext.suppliers.map((p) => '<option value="' + p.id + '"' + (p.id === selectedSid ? " selected" : "") + ">" + esc(p.name) + "</option>").join("");
    popup("Send back · " + c.name, "Good empty cylinders going back to a supplier. The security deposit comes back to you as money.",
      '<label class="field"><span>Sent to</span><select name="supplier_id" class="amt"><option value="">Not sure / skip</option>' + opts + "</select></label>" +
      '<div class="two"><label class="field"><span>How many</span><div class="amt"><input name="qty" type="number" min="1" step="1" inputmode="numeric" value="1"><i>cyl</i></div></label>' +
      moneyBox("deposit", "Deposit per cylinder", s ? s.security : c.security) + "</div>" +
      '<label class="field"><span>Money received in</span><select name="received_in" class="amt"><option value="cash">Cash in hand</option><option value="bank">Bank / UPI</option></select></label>' +
      '<p class="hint st-refund" id="st-refund">Money back: Rs 0</p><p class="hint">You have ' + c.empty + " empty " + esc(c.name) + " cylinder(s) in total.</p>", "Send back & receive money",
      (f) => Api.post("/api/cylinders/" + tid + "/send-back", { qty: f.elements.qty.value.trim(), deposit: f.elements.deposit.value.trim(),
        supplier_id: f.elements.supplier_id.value, received_in: f.elements.received_in.value }),
      "Cylinders sent back, deposit received",
      (f) => {
        const calc = () => { f.querySelector("#st-refund").textContent = "Money back: " + money(((Number(f.elements.qty.value) || 0) * (Number(f.elements.deposit.value) || 0)).toFixed(2)); };
        f.elements.supplier_id.addEventListener("change", () => {
          const row = supOf(tid).find((x) => String(x.supplier_id) === f.elements.supplier_id.value);
          f.elements.deposit.value = row ? row.security : c.security; calc();
        });
        f.addEventListener("input", calc); calc();
      });
  }

  /* ---------- damaged cylinders ---------- */
  function renderDamagedArea() {
    const d = ext.deposits || {};
    $("st-damaged-list").innerHTML = ext.damaged.length ? ext.damaged.map((r) =>
      '<div class="st-dmg-chip"><b>' + r.qty + "</b> × " + esc(r.name) + (Number(r.deposit_lost) ? "<small>deposit lost " + money(r.deposit_lost) + "</small>" : "") + "</div>").join("")
      : '<span class="card-sub">No damaged cylinders.</span>';
    $("st-deposit-line").innerHTML = "Deposits held with suppliers <b>" + money(d.held) + "</b> · lost on damaged <b>" + money(d.cancelled) +
      "</b> · received back <b>" + money(d.refunded) + "</b>" +
      (Number(d.refunded) ? " (cash " + money(d.refunded_cash) + ", bank " + money(d.refunded_bank) + ")" : "");
    const sendButton = $("st-damaged-sendback");
    sendButton.disabled = !ext.damaged_dispatch_options.length;
  }
  function addDamaged() {
    const cyls = StockUI.state.cylinders;
    if (!cyls.length) { StockUI.toast("Add a cylinder first.", true); return; }
    const rows = cyls.map((c) => '<div class="st-dmg-row" data-id="' + c.id + '">' +
      '<label class="st-dmg-pick"><input type="checkbox" name="pick' + c.id + '"><span>' + esc(c.name) + "<small>" + c.empty + " empty · " + c.full + " full</small></span></label>" +
      '<div class="amt"><input name="q' + c.id + '" type="number" min="1" step="1" inputmode="numeric" value="1" disabled><i>cyl</i></div>' +
      '<div class="amt"><i>Rs</i><input name="d' + c.id + '" inputmode="decimal" value="' + esc(c.security) + '" disabled></div></div>').join("");
    popup("Add damaged cylinder", "Tick the cylinders that are damaged. They leave your stock and their security deposit is cancelled, because they can no longer be used.",
      '<label class="field"><span>They were</span><select name="source" class="amt"><option value="empty">Empty</option><option value="full">Full</option></select></label>' +
      supplierSelect("supplier_id", "Bought from", ext.suppliers, "Not sure / skip",
        ext.suppliers.length === 1 ? ext.suppliers[0].id : null) +
      '<div class="st-dmg-head"><span>Cylinder</span><span>How many</span><span>Deposit each</span></div>' + rows +
      '<p class="st-dmg-total hint" id="st-dmg-total">Deposit cancelled: Rs 0</p>', "Update damaged stock",
      async (f) => {
        const items = cyls.filter((c) => f.elements["pick" + c.id].checked).map((c) => ({
          cylinder_type_id: c.id, qty: f.elements["q" + c.id].value.trim(), deposit: f.elements["d" + c.id].value.trim() }));
        if (!items.length) throw new Error("Tick at least one cylinder.");
        await Api.post("/api/stock/damaged/add", { source: f.elements.source.value, supplier_id: f.elements.supplier_id.value, items });
      }, "Damaged stock updated",
      (f) => {
        const total = () => {
          const t = cyls.reduce((a, c) => a + (f.elements["pick" + c.id].checked ? (Number(f.elements["q" + c.id].value) || 0) * (Number(f.elements["d" + c.id].value) || 0) : 0), 0);
          f.querySelector("#st-dmg-total").textContent = "Deposit cancelled: " + money(t.toFixed(2));
        };
        f.elements.supplier_id.addEventListener("change", () => {      // each supplier has its own deposit
          cyls.forEach((c) => {
            const row = supOf(c.id).find((x) => String(x.supplier_id) === f.elements.supplier_id.value);
            f.elements["d" + c.id].value = row ? row.security : c.security;
          });
          total();
        });
        f.addEventListener("change", (e) => {
          const m = /^pick(\d+)$/.exec(e.target.name || "");
          if (m) { f.elements["q" + m[1]].disabled = f.elements["d" + m[1]].disabled = !e.target.checked; }
          total();
        });
        f.addEventListener("input", total);
      });
  }

  function sendDamagedBack() {
    const rows = ext.damaged_dispatch_options || [];
    if (!rows.length) {
      StockUI.toast("There are no damaged cylinders awaiting dispatch.", true);
      return;
    }

    const soleSupplierId = ext.suppliers.length === 1 ? ext.suppliers[0].id : null;
    const now = new Date();
    const today = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    const supplierOptions = (selected) =>
      '<option value="">Not sure / unassigned</option>' + ext.suppliers.map((s) =>
        '<option value="' + s.id + '"' + (Number(selected) === Number(s.id) ? " selected" : "") + '>' + esc(s.name) + '</option>'
      ).join("");

    const rowHtml = rows.map((r) => {
      const id = r.damage_event_id;
      const markedDate = String(r.damaged_at || "").split(" ")[0];
      return '<div class="st-dmg-dispatch-row" data-event="' + id + '">' +
        '<label class="st-dmg-dispatch-name"><input type="checkbox" name="pick' + id + '"><span>' +
          esc(r.name) + '<small>' + r.remaining_qty + ' awaiting dispatch' + (markedDate ? ' · marked ' + esc(markedDate) : '') + '</small></span></label>' +
        '<label class="field"><span>Supplier</span><select name="s' + id + '" class="amt">' + supplierOptions(r.supplier_id || soleSupplierId) + '</select></label>' +
        '<label class="field"><span>Deposit / cylinder</span><div class="amt"><i>Rs</i><input name="d' + id + '" inputmode="decimal" value="' + esc(r.deposit_reference) + '"></div></label>' +
        '<label class="field"><span>Sending</span><div class="amt"><input name="q' + id + '" type="number" min="1" max="' + r.remaining_qty + '" step="1" inputmode="numeric" value="1" disabled><i>cyl</i></div></label>' +
      '</div>';
    }).join("");

    popup(
      "Send damaged cylinders back",
      "Tick the damaged-cylinder batches being sent to the supplier. This records the physical dispatch only; their security deposits were already cancelled when they were marked damaged.",
      '<label class="field"><span>Dispatch date</span><input type="date" name="date" value="' + today + '" max="' + today + '"></label>' +
      '<label class="field"><span>Note (optional)</span><input name="note" maxlength="200" autocomplete="off" placeholder="Dispatch reference or note"></label>' +
      '<div class="st-dmg-dispatch-head"><span>Cylinder</span><span>Supplier</span><span>Deposit / cylinder</span><span>Quantity</span></div>' +
      rowHtml +
      '<p class="hint">The deposit value is editable for reference only. It will not change the cancelled deposit or any financial report.</p>',
      "Record dispatch",
      async (f) => {
        const items = rows.filter((r) => f.elements["pick" + r.damage_event_id].checked).map((r) => ({
          damage_event_id: r.damage_event_id,
          qty: f.elements["q" + r.damage_event_id].value.trim(),
          supplier_id: f.elements["s" + r.damage_event_id].value,
          deposit_reference: f.elements["d" + r.damage_event_id].value.trim(),
        }));
        if (!items.length) throw new Error("Tick at least one damaged-cylinder row.");
        await Api.post("/api/stock/damaged/send-back", {
          date: f.elements.date.value,
          note: f.elements.note.value.trim(),
          items,
        });
      },
      "Damaged cylinders sent back",
      (f) => {
        f.addEventListener("change", (e) => {
          const match = /^pick(\d+)$/.exec(e.target.name || "");
          if (match) f.elements["q" + match[1]].disabled = !e.target.checked;
        });
      }
    );
  }

  /* ---------- wiring ---------- */
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-xact]"); if (!b) return;
    const sup = b.closest(".st-sup");
    const tid = Number(b.dataset.tid || (sup && sup.dataset.tid)), sid = sup ? Number(sup.dataset.sid) : 0;
    ({ "sup-add": () => addSupplier(tid), "sup-edit": () => editSupplier(tid, sid), "sup-remove": () => removeSupplier(tid, sid),
       "sup-adjust": () => adjustSupplier(tid, sid), "sup-sendback": () => sendBack(tid, sid), "send-back": () => sendBack(tid, 0) })[b.dataset.xact]();
  });
  $("st-damaged-add").addEventListener("click", addDamaged);
  $("st-damaged-sendback").addEventListener("click", sendDamagedBack);
  document.addEventListener("stock:rendered", async () => {
    try { ext = await Api.get("/api/stock/extra"); } catch (e) { return; }
    decorateCards();
    renderDamagedArea();
  });
})();