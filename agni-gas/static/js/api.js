// Thin fetch wrapper. Every screen talks to the backend ONLY through this.
window.Api = (function () {
  const base = () => (window.APP_CONFIG && window.APP_CONFIG.apiBase) || "";

  async function decode(res) {
    let data = null;
    try { data = await res.json(); } catch (_) { /* empty/non-JSON body */ }
    if (!res.ok) {
      const err = new Error((data && data.error) || "Request failed (" + res.status + ")");
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  async function request(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return decode(await fetch(base() + path, opts));
  }

  async function requestForm(method, path, formData) {
    // Let the browser set the multipart boundary; never set Content-Type manually.
    return decode(await fetch(base() + path, { method, body: formData }));
  }

  return {
    get: (p) => request("GET", p),
    post: (p, b) => request("POST", p, b),
    put: (p, b) => request("PUT", p, b),
    del: (p) => request("DELETE", p),
    postForm: (p, formData) => requestForm("POST", p, formData),
  };
})();
