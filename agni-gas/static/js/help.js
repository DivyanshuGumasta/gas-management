// Help & support: contacts are supplied by the read-only support API.
(function () {
  const { esc } = UI;
  const $ = (id) => document.getElementById(id);
  const root = $("help-contacts");
  const error = $("help-error");

  function render(contacts) {
    if (!Array.isArray(contacts) || !contacts.length) {
      root.innerHTML = '<div class="sd-loading card">No support contacts are configured.</div>';
      return;
    }
    root.innerHTML = contacts.map((contact) => {
      const email = String(contact.email || "");
      const phone = String(contact.phone || "");
      const phoneTarget = phone.replace(/[^+\d]/g, "");
      return '<article class="card sd-contact-card">' +
        '<div class="sd-contact-top"><small>Support contact</small><h2>' + esc(contact.name || "Support") + '</h2></div>' +
        '<div class="sd-contact-details">' +
          '<div class="sd-detail-row"><span class="sd-detail-icon"><i data-icon="mail"></i></span>' +
            '<span class="sd-detail-copy"><small>Email address</small><strong>' + esc(email) + '</strong></span></div>' +
          '<div class="sd-detail-row"><span class="sd-detail-icon"><i data-icon="phone"></i></span>' +
            '<span class="sd-detail-copy"><small>Mobile number</small><strong>' + esc(phone) + '</strong></span></div>' +
        '</div>' +
        '<div class="sd-contact-actions">' +
          '<a class="sd-contact-email" href="' + esc("mailto:" + email) + '"><i data-icon="mail"></i>Email</a>' +
          '<a class="sd-contact-call" href="' + esc("tel:" + phoneTarget) + '"><i data-icon="phone"></i>Call</a>' +
        '</div>' +
      '</article>';
    }).join("");
    if (window.Icons) Icons.render(root);
  }

  async function load() {
    error.hidden = true;
    root.setAttribute("aria-busy", "true");
    try {
      render(await Api.get("/api/support"));
    } catch (err) {
      error.hidden = false;
      error.querySelector("span").textContent = "Could not load support contacts. " + (err.message || "");
    } finally {
      root.setAttribute("aria-busy", "false");
    }
  }

  $("help-retry").addEventListener("click", load);
  load();
})();
