const API = {
  base: '',

  async get(path) {
    const r = await fetch(this.base + path);
    if (!r.ok) throw new Error(`GET ${path} → ${r.status}`);
    return r.json();
  },

  async post(path, body) {
    const r = await fetch(this.base + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      let msg = `POST ${path} → ${r.status}`;
      let detail = {};
      try { const d = await r.json(); detail = d.detail || {}; msg = (typeof detail === 'string' ? detail : detail.message) || msg; } catch {}
      const err = new Error(msg);
      err._detail = typeof detail === 'object' ? detail : { message: detail };
      throw err;
    }
    return r.json();
  },

  async put(path, body) {
    const r = await fetch(this.base + path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      let msg = `PUT ${path} → ${r.status}`;
      let detail = {};
      try { const d = await r.json(); detail = d.detail || {}; msg = (typeof detail === 'string' ? detail : detail.message) || msg; } catch {}
      const err = new Error(msg);
      err._detail = typeof detail === 'object' ? detail : { message: detail };
      throw err;
    }
    return r.json();
  },

  async del(path, body) {
    const opts = { method: 'DELETE' };
    if (body !== undefined) {
      opts.headers = { 'Content-Type': 'application/json' };
      opts.body = JSON.stringify(body);
    }
    const r = await fetch(this.base + path, opts);
    if (!r.ok) throw new Error(`DELETE ${path} → ${r.status}`);
    return r.json();
  },

  async patch(path, body) {
    const r = await fetch(this.base + path, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`PATCH ${path} → ${r.status}`);
    return r.json();
  },

  async postQuery(path, params) {
    const qs = new URLSearchParams(params).toString();
    const r = await fetch(`${this.base}${path}?${qs}`, { method: 'POST' });
    if (!r.ok) {
      let msg = `POST ${path} → ${r.status}`;
      try { const d = await r.json(); msg = d.detail || msg; } catch {}
      throw new Error(msg);
    }
    return r.json();
  }
};
