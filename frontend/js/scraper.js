const Scraper = (() => {
  let _providers = [];
  let _connections = {};
  let _pollTimer = null;
  let _browserPollTimer = null;

  const PLATFORM_ICONS = {
    reddit:    '🟠',
    youtube:   '▶️',
    facebook:  '🔵',
    instagram: '📸',
    tiktok:    '🎵',
    linkedin:  '💼',
  };

  // ── Init ──────────────────────────────────────────────────────────────

  async function init() {
    _setupTabs();
    _checkOAuthCallback();
    await refresh();
  }

  async function refresh() {
    await Promise.all([_loadProviders(), _loadConnections()]);
    _renderAccounts();
    _populatePlatformSelect();
    await _loadDatasets();
  }

  // ── Tabs ─────────────────────────────────────────────────────────────

  function _setupTabs() {
    document.querySelectorAll('#scraper-tabs .tab').forEach(tab => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('#scraper-tabs .tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('#screen-scraper .tab-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
        if (tab.dataset.tab === 'scraper-datasets' || tab.dataset.tab === 'scraper-browser') _loadDatasets();
      });
    });
  }

  // ── OAuth callback detection ──────────────────────────────────────────

  function _checkOAuthCallback() {
    const params = new URLSearchParams(window.location.search);
    const connected = params.get('scraper_connected');
    const error = params.get('scraper_error');
    if (connected) {
      App.toast(`Connected: ${connected.split(',').join(', ')}`, 'success');
      window.history.replaceState({}, '', window.location.pathname);
    }
    if (error) {
      App.toast(`OAuth error: ${error}`, 'error');
      window.history.replaceState({}, '', window.location.pathname);
    }
  }

  // ── Data loading ──────────────────────────────────────────────────────

  async function _loadProviders() {
    try {
      const data = await API.get('/api/scraper/providers');
      _providers = data.providers || [];
    } catch (e) { console.error(e); }
  }

  async function _loadConnections() {
    try {
      const data = await API.get('/api/scraper/connections');
      _connections = {};
      (data.connections || []).forEach(c => { _connections[c.platform] = c; });
    } catch (e) { console.error(e); }
  }

  // ── Accounts tab ─────────────────────────────────────────────────────

  function _renderAccounts() {
    const el = document.getElementById('scraper-accounts-list');
    if (!_providers.length) { el.innerHTML = '<div style="color:var(--text3);font-size:13px">Loading…</div>'; return; }

    el.innerHTML = _providers.map(p => {
      const conn = _connections[p.id];
      const isConnected = !!conn;
      return `
        <div class="card" style="padding:16px">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
            <span style="font-size:22px">${PLATFORM_ICONS[p.id] || '🔗'}</span>
            <div>
              <div style="font-weight:600;font-size:14px">${p.name}</div>
              <div style="font-size:11px;color:${isConnected ? 'var(--green,#22c55e)' : 'var(--text3)'}">
                ${isConnected ? '● Connected' + (conn.account_handle ? ' · @' + conn.account_handle : '') : '○ Not connected'}
              </div>
            </div>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap">
            ${isConnected
              ? `<button class="btn btn-ghost btn-sm" onclick="Scraper.disconnect('${p.id}')">Disconnect</button>`
              : `<button class="btn btn-primary btn-sm" onclick="Scraper.startConnect('${p.id}')">Connect</button>`
            }
            <a href="${p.setup_url}" target="_blank" class="btn btn-ghost btn-sm">Dev App ↗</a>
          </div>
          ${isConnected && conn.saved_at ? `<div style="font-size:11px;color:var(--text3);margin-top:8px">Connected ${_relTime(conn.saved_at)}</div>` : ''}
        </div>`;
    }).join('');
  }

  // ── Connect / Disconnect ──────────────────────────────────────────────

  async function startConnect(platform) {
    // Show credentials modal first if platform supports stored creds
    try {
      const info = await API.get(`/api/scraper/credentials/${platform}`);
      if (info.supported && !info.configured) {
        _openCredentialsModal(platform, info, () => _doConnect(platform));
        return;
      }
    } catch (_) {}
    await _doConnect(platform);
  }

  async function _doConnect(platform) {
    try {
      const data = await API.get(`/api/scraper/connect/${platform}`);
      if (data.error) { App.toast(data.error, 'error'); return; }
      window.location.href = data.auth_url;
    } catch (e) { App.toast(e.message, 'error'); }
  }

  async function disconnect(platform) {
    try {
      await API.post(`/api/scraper/disconnect/${platform}`, {});
      App.toast(`${platform} disconnected`, 'success');
      await _loadConnections();
      _renderAccounts();
    } catch (e) { App.toast(e.message, 'error'); }
  }

  // ── Credentials modal ─────────────────────────────────────────────────

  function _openCredentialsModal(platform, info, onSaved) {
    const fields = (info.fields || []).map(f => `
      <div class="form-group">
        <label>${f.label}${f.secret ? ' <span style="color:var(--text3);font-weight:400">(secret)</span>' : ''}</label>
        <input type="${f.secret ? 'password' : 'text'}" id="cred-field-${f.key}"
               placeholder="${f.set ? '(already set — leave blank to keep)' : ''}" />
      </div>`).join('');

    document.getElementById('modal-content').innerHTML = `
      <div style="padding:4px 0 8px">
        <div style="font-size:16px;font-weight:600;margin-bottom:4px">Connect ${info.name}</div>
        <div style="font-size:13px;color:var(--text3);margin-bottom:16px">${info.docs_note || ''}</div>
        <div style="font-size:12px;background:var(--bg2);border-radius:6px;padding:10px 12px;margin-bottom:16px;font-family:monospace;word-break:break-all;color:var(--text2)">
          Redirect URI: ${info.redirect_uri}
        </div>
        ${fields}
        <div style="display:flex;gap:8px;margin-top:4px">
          <button class="btn btn-primary" onclick="Scraper._saveCredentials('${platform}')">Save &amp; Continue</button>
          <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
        </div>
      </div>`;
    document.getElementById('modal-overlay').style.display = 'flex';
    window._scraperCredCb = onSaved;
  }

  async function _saveCredentials(platform) {
    const info = await API.get(`/api/scraper/credentials/${platform}`);
    const body = {};
    (info.fields || []).forEach(f => {
      const val = document.getElementById(`cred-field-${f.key}`)?.value?.trim();
      if (val) body[f.key] = val;
    });
    try {
      const res = await API.post(`/api/scraper/credentials/${platform}`, body);
      if (res.error) { App.toast(res.error, 'error'); return; }
      App.closeModal();
      App.toast('Credentials saved', 'success');
      if (window._scraperCredCb) { window._scraperCredCb(); window._scraperCredCb = null; }
    } catch (e) { App.toast(e.message, 'error'); }
  }

  // ── Platform select ───────────────────────────────────────────────────

  function _populatePlatformSelect() {
    const sel = document.getElementById('scraper-platform-select');
    sel.innerHTML = _providers.map(p => {
      const conn = _connections[p.id];
      const label = conn ? `${PLATFORM_ICONS[p.id]} ${p.name} (connected)` : `${PLATFORM_ICONS[p.id]} ${p.name}`;
      return `<option value="${p.id}" ${!conn ? 'disabled' : ''}>${label}</option>`;
    }).join('');
    // Select first connected one
    const first = _providers.find(p => _connections[p.id]);
    if (first) sel.value = first.id;
  }

  // ── Fetch Data tab ────────────────────────────────────────────────────

  async function runFetch() {
    const platform = document.getElementById('scraper-platform-select').value;
    const kind = document.getElementById('scraper-kind-select').value;
    const maxItems = parseInt(document.getElementById('scraper-max-items').value) || 50;

    if (!_connections[platform]) {
      App.toast(`${platform} is not connected. Go to My Accounts to connect it first.`, 'error');
      return;
    }

    const bar = document.getElementById('scraper-status-bar');
    bar.style.display = 'block';
    document.getElementById('scraper-status-result').style.display = 'none';
    _setStatus('running', 'Starting…');

    try {
      const res = await API.post('/api/scraper/fetch', { platform, kind, options: { max_items: maxItems } });
      if (res.error) { _setStatus('error', res.error); return; }
      _pollStatus();
    } catch (e) { _setStatus('error', e.message); }
  }

  function _pollStatus() {
    if (_pollTimer) clearInterval(_pollTimer);
    _pollTimer = setInterval(async () => {
      try {
        const s = await API.get('/api/scraper/status');
        _setStatus(s.running ? 'running' : (s.done ? 'done' : 'idle'), s.progress || 'Idle');
        if (!s.running && s.done) {
          clearInterval(_pollTimer);
          _pollTimer = null;
          const res = document.getElementById('scraper-status-result');
          if (s.latest) {
            res.style.display = 'block';
            if (s.latest.error) {
              res.textContent = 'Error: ' + s.latest.error;
            } else {
              res.innerHTML = `Saved <strong>${s.latest.count}</strong> records · run ID: <code>${s.latest.run_id}</code>`;
              _loadDatasets();
            }
          }
        }
      } catch (_) {}
    }, 1500);
  }

  function _setStatus(state, text) {
    const dot = document.getElementById('scraper-status-dot');
    document.getElementById('scraper-status-text').textContent = text;
    dot.style.background = state === 'running' ? '#f59e0b' : state === 'done' ? '#22c55e' : state === 'error' ? '#ef4444' : 'var(--accent)';
  }

  // ── Browser Scrape tab ────────────────────────────────────────────────

  // Toggle comment-limit field visibility
  document.addEventListener('DOMContentLoaded', () => {
    const cb = document.getElementById('browser-fetch-comments');
    if (cb) cb.addEventListener('change', () => {
      const grp = document.getElementById('browser-comments-limit-group');
      if (grp) grp.style.display = cb.checked ? '' : 'none';
    });
  });

  async function runBrowserFetch() {
    const platform = document.getElementById('browser-platform-select').value;
    const target = document.getElementById('browser-target').value.trim();
    const maxRecords = parseInt(document.getElementById('browser-max-records').value) || 50;
    const enrichPosts = document.getElementById('browser-enrich-posts')?.checked || false;
    const fetchComments = document.getElementById('browser-fetch-comments')?.checked || false;
    const maxComments = parseInt(document.getElementById('browser-max-comments')?.value) || 20;

    if (!target) { App.toast('Enter a profile URL or handle', 'error'); return; }

    const bar = document.getElementById('browser-status-bar');
    bar.style.display = 'block';
    document.getElementById('browser-status-result').style.display = 'none';
    _setBrowserStatus('running', 'Starting browser…');

    try {
      const res = await API.post('/api/scraper/browser-fetch', {
        platform, target, max_records: maxRecords,
        enrich_posts: enrichPosts,
        fetch_comments: fetchComments,
        max_comments_per_post: maxComments,
        max_posts_to_enrich: maxRecords,
      });
      if (res.error) { _setBrowserStatus('error', res.error); return; }
      _pollBrowserStatus();
    } catch (e) { _setBrowserStatus('error', e.message); }
  }

  function _pollBrowserStatus() {
    if (_browserPollTimer) clearInterval(_browserPollTimer);
    _browserPollTimer = setInterval(async () => {
      try {
        const s = await API.get('/api/scraper/status');
        _setBrowserStatus(s.running ? 'running' : (s.done ? 'done' : 'idle'), s.progress || 'Idle');
        if (!s.running && s.done) {
          clearInterval(_browserPollTimer);
          _browserPollTimer = null;
          const res = document.getElementById('browser-status-result');
          if (s.latest) {
            res.style.display = 'block';
            if (s.latest.error) {
              res.textContent = 'Error: ' + s.latest.error;
            } else {
              res.innerHTML = `Saved <strong>${s.latest.count}</strong> records · run ID: <code>${s.latest.run_id}</code>`;
              _loadDatasets();
            }
          }
        }
      } catch (_) {}
    }, 1500);
  }

  function _setBrowserStatus(state, text) {
    const dot = document.getElementById('browser-status-dot');
    if (!dot) return;
    document.getElementById('browser-status-text').textContent = text;
    dot.style.background = state === 'running' ? '#f59e0b' : state === 'done' ? '#22c55e' : state === 'error' ? '#ef4444' : 'var(--accent)';
  }

  // ── Datasets tab ──────────────────────────────────────────────────────

  async function _loadDatasets() {
    const el = document.getElementById('scraper-datasets-list');
    try {
      const data = await API.get('/api/scraper/datasets?project_slug=default');
      const datasets = data.datasets || [];
      if (!datasets.length) {
        el.innerHTML = '<div style="color:var(--text3);font-size:13px;padding:20px 0">No datasets yet. Run a fetch to create one.</div>';
        return;
      }
      el.innerHTML = `
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <thead>
            <tr style="border-bottom:1px solid var(--border);color:var(--text3)">
              <th style="text-align:left;padding:6px 10px;font-weight:500">Platform</th>
              <th style="text-align:left;padding:6px 10px;font-weight:500">Type</th>
              <th style="text-align:left;padding:6px 10px;font-weight:500">Account</th>
              <th style="text-align:left;padding:6px 10px;font-weight:500">Records</th>
              <th style="text-align:left;padding:6px 10px;font-weight:500">Date</th>
              <th style="padding:6px 10px"></th>
            </tr>
          </thead>
          <tbody>
            ${datasets.map(d => `
              <tr style="border-bottom:1px solid var(--border)">
                <td style="padding:8px 10px">${PLATFORM_ICONS[d.platform] || ''} ${d.platform}</td>
                <td style="padding:8px 10px;color:var(--text2)">${d.kind}</td>
                <td style="padding:8px 10px;color:var(--text2)">${d.account_handle || '—'}</td>
                <td style="padding:8px 10px;font-weight:600">${d.count}</td>
                <td style="padding:8px 10px;color:var(--text3)">${_relTime(d.saved_at)}</td>
                <td style="padding:8px 10px;display:flex;gap:6px">
                  <button class="btn btn-ghost btn-sm" onclick="Scraper.viewDataset('${d.run_id}')">View</button>
                  <button class="btn btn-ghost btn-sm" style="color:var(--red,#ef4444)" onclick="Scraper.deleteDataset('${d.run_id}')">✕</button>
                </td>
              </tr>`).join('')}
          </tbody>
        </table>`;
    } catch (e) {
      el.textContent = '';
      const errEl = document.createElement('div');
      errEl.style.cssText = 'color:var(--text3);font-size:13px';
      errEl.textContent = 'Error loading datasets: ' + e.message;
      el.appendChild(errEl);
    }
  }

  async function viewDataset(runId) {
    try {
      const data = await API.get(`/api/scraper/dataset/${runId}?project_slug=default&include_raw=1`);
      const records = data.records || [];

      const _esc = s => String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

      const preview = records.slice(0, 20).map((r, i) => {
        const imgs = (r.images || []).filter(Boolean);
        const videos = (r.videos || []).filter(Boolean);
        const videoPosters = (r.video_posters || []).filter(Boolean);
        const imgsHtml = imgs.length ? `
          <div style="display:flex;flex-wrap:wrap;gap:6px;margin:8px 0">
            ${imgs.map(src => `<img src="${_esc(src)}" style="max-width:160px;max-height:120px;border-radius:4px;object-fit:cover;border:1px solid var(--border)" onerror="this.style.display='none'" />`).join('')}
          </div>` : '';
        const videosHtml = videos.length ? `
          <div style="display:flex;flex-wrap:wrap;gap:6px;margin:8px 0">
            ${videos.map((src, vi) => `<video src="${_esc(src)}" ${videoPosters[vi] ? `poster="${_esc(videoPosters[vi])}"` : ''} controls style="max-width:260px;max-height:160px;border-radius:4px;border:1px solid var(--border)" />`).join('')}
          </div>` : (r.has_video && videoPosters.length ? `
          <div style="display:flex;flex-wrap:wrap;gap:6px;margin:8px 0">
            ${videoPosters.map(p => `<div style="position:relative;display:inline-block"><img src="${_esc(p)}" style="max-width:160px;max-height:120px;border-radius:4px;object-fit:cover;border:1px solid var(--border)" onerror="this.style.display='none'" /><div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:28px;pointer-events:none">▶</div></div>`).join('')}
          </div>` : (r.has_video ? `<div style="margin:6px 0;font-size:11px;color:var(--text3)">📹 Contains video</div>` : ''));

        const engagement = [
          r.likes    ? `👍 ${r.likes}`    : '',
          r.comments ? `💬 ${r.comments}` : '',
          r.reposts  ? `🔁 ${r.reposts}`  : '',
          r.replies  ? `↩ ${r.replies}`   : '',
          r.retweets ? `🔁 ${r.retweets}` : '',
          r.views    ? `👁 ${r.views}`    : '',
        ].filter(Boolean).join('  ·  ');

        const commentsData = (r.comments_data || []);
        const commentsHtml = commentsData.length ? `
          <div style="margin-top:8px;border-left:2px solid var(--border);padding-left:8px">
            <div style="font-size:11px;color:var(--text3);margin-bottom:4px">💬 ${commentsData.length} comment${commentsData.length>1?'s':''}</div>
            ${commentsData.slice(0,5).map(c => `
              <div style="font-size:11px;margin-bottom:4px">
                <span style="font-weight:600;color:var(--text2)">${_esc(c.author)}</span>
                <span style="color:var(--text3);margin-left:4px">${_esc(c.text).slice(0,120)}${c.text?.length>120?'…':''}</span>
                ${c.likes ? `<span style="color:var(--text3);margin-left:4px">· 👍 ${c.likes}</span>` : ''}
              </div>`).join('')}
          </div>` : '';

        return `
          <div style="padding:12px 14px;background:var(--bg2);border-radius:8px;margin-bottom:10px;font-size:12px">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;color:var(--text3);font-size:11px">
              <span style="font-weight:600;color:var(--text)">#${i+1}</span>
              ${r.timestamp ? `<span>${_esc(r.timestamp.slice(0,10))}</span>` : ''}
              ${r.url ? `<a href="${_esc(r.url)}" target="_blank" style="color:var(--accent);text-decoration:none">↗ open post</a>` : ''}
            </div>
            ${(r.caption || r.text) ? `<div style="color:var(--text);white-space:pre-wrap;line-height:1.5;max-height:120px;overflow:hidden">${_esc(r.caption || r.text).slice(0,400)}${((r.caption||r.text)||'').length>400?'…':''}</div>` : ''}
            ${imgsHtml}
            ${videosHtml}
            ${engagement ? `<div style="margin-top:6px;color:var(--text3);font-size:11px">${engagement}</div>` : ''}
            ${commentsHtml}
          </div>`;
      }).join('');

      // Widen modal for image-rich dataset view
      const modalBox = document.getElementById('modal-box');
      if (modalBox) modalBox.style.width = '760px';

      document.getElementById('modal-content').innerHTML = `
        <div style="padding:4px 0 8px">
          <div style="font-size:16px;font-weight:600;margin-bottom:2px">Dataset: ${_esc(runId)}</div>
          <div style="font-size:13px;color:var(--text3);margin-bottom:14px">${records.length} records · showing first 20</div>
          <div style="max-height:65vh;overflow-y:auto;padding-right:4px">${preview}</div>
          <button class="btn btn-ghost" style="margin-top:10px" onclick="App.closeModal();document.getElementById('modal-box').style.width=''">Close</button>
        </div>`;
      document.getElementById('modal-overlay').style.display = 'flex';
    } catch (e) { App.toast(e.message, 'error'); }
  }

  async function deleteDataset(runId) {
    if (!confirm('Delete this dataset?')) return;
    try {
      await API.post(`/api/scraper/dataset/${runId}/delete?project_slug=default`, {});
      App.toast('Deleted', 'success');
      _loadDatasets();
    } catch (e) { App.toast(e.message, 'error'); }
  }

  // ── Helpers ───────────────────────────────────────────────────────────

  function _relTime(isoStr) {
    if (!isoStr) return '';
    const diff = Date.now() - new Date(isoStr).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 1) return 'just now';
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  }

  function _stopPolling() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    if (_browserPollTimer) { clearInterval(_browserPollTimer); _browserPollTimer = null; }
  }

  return { init, refresh, startConnect, disconnect, runFetch, runBrowserFetch, viewDataset, deleteDataset, _saveCredentials, _stopPolling };
})();

// Hook into app lifecycle
document.addEventListener('DOMContentLoaded', () => {
  // Init when the scraper screen is first shown
  const origGoTo = App.goTo;
  const _scraperInit = { done: false };
  App.goTo = function(screen, ...args) {
    const prevScreen = App.currentScreen;
    origGoTo.call(this, screen, ...args);
    if (screen === 'scraper' && !_scraperInit.done) {
      _scraperInit.done = true;
      Scraper.init();
    }
    // Stop any background polling when leaving the scraper screen
    if (prevScreen === 'scraper' && screen !== 'scraper') Scraper._stopPolling();
  };
  // Also check if we landed on scraper via OAuth redirect
  if (new URLSearchParams(window.location.search).has('scraper_connected') ||
      new URLSearchParams(window.location.search).has('scraper_error')) {
    setTimeout(() => { App.goTo('scraper'); }, 100);
  }
});
