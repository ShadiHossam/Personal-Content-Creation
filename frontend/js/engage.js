const Engage = (() => {
  let _items = [];
  let _polling = null;

  // ── Public: screen entry ────────────────────────────────────────────────────

  async function load() {
    await _loadItems();
  }

  // ── Fetch (trigger background scrape) ──────────────────────────────────────

  async function refresh() {
    const btn = document.getElementById('engage-refresh-btn');
    const bar = document.getElementById('engage-status-bar');
    const txt = document.getElementById('engage-status-text');

    if (btn) { btn.disabled = true; btn.textContent = 'Fetching…'; }
    if (bar) bar.style.display = '';
    if (txt) txt.textContent = 'Scraping LinkedIn feed and hashtags… this takes ~60–90 seconds.';

    try {
      await API.post('/api/engage/fetch', {});
    } catch (e) {
      App.toast('Error: ' + e.message, 'error');
      _resetBtn(btn, bar);
      return;
    }

    // Poll for new items every 10s for up to 2 minutes
    let attempts = 0;
    const prevCount = _items.length;
    if (_polling) clearInterval(_polling);
    _polling = setInterval(async () => {
      attempts++;
      await _loadItems(true);
      if (_items.length > prevCount || attempts >= 12) {
        clearInterval(_polling);
        _polling = null;
        _resetBtn(btn, bar);
        if (_items.length > prevCount) {
          App.toast(`${_items.length - prevCount} new posts added!`, 'success');
        } else {
          if (txt) txt.textContent = 'Done — no new posts found. Try adding more hashtags in Settings.';
          setTimeout(() => { if (bar) bar.style.display = 'none'; }, 4000);
        }
      }
    }, 10000);
  }

  function _resetBtn(btn, bar) {
    if (btn) { btn.disabled = false; btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:5px"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/></svg>Refresh Today's Posts`; }
  }

  // ── Load items from DB ──────────────────────────────────────────────────────

  async function _loadItems(silent = false) {
    const statusEl = document.getElementById('engage-filter-status');
    const scoreEl  = document.getElementById('engage-filter-score');
    const sourceEl = document.getElementById('engage-filter-source');

    const params = new URLSearchParams();
    if (statusEl?.value) params.set('status', statusEl.value);
    if (scoreEl?.value)  params.set('min_score', scoreEl.value);
    if (sourceEl?.value) params.set('source_type', sourceEl.value);

    try {
      _items = await API.get('/api/engage/items?' + params.toString());
      _render();
      _updateBadge();
    } catch (e) {
      if (!silent) App.toast('Could not load engage items', 'error');
    }
  }

  function applyFilters() {
    _loadItems();
  }

  // ── Render cards ────────────────────────────────────────────────────────────

  function _render() {
    const el = document.getElementById('engage-cards');
    if (!el) return;

    if (!_items.length) {
      el.innerHTML = `
        <div class="empty-state">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:.4;margin-bottom:8px"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
          <div>No posts match your filters — try clearing the status filter or clicking <strong>Refresh</strong>.</div>
        </div>`;
      return;
    }

    el.innerHTML = _items.map(item => _renderCard(item)).join('');
    el.onclick = (e) => {
      const btn = e.target.closest('.engage-reply-btn');
      if (btn) generateReply(btn.dataset.postText, btn.dataset.authorName);
    };
  }

  function _renderCard(item) {
    const score = item.ai_score != null ? item.ai_score.toFixed(1) : '—';
    const scoreColor = item.ai_score >= 8 ? 'var(--accent)' : item.ai_score >= 6 ? 'var(--green)' : 'var(--text3)';
    const statusBadge = item.status === 'engaged'
      ? '<span style="background:var(--green-dim);color:var(--green);padding:2px 8px;border-radius:4px;font-size:11px">✓ Engaged</span>'
      : item.status === 'skipped'
      ? '<span style="background:var(--bg3);color:var(--text3);padding:2px 8px;border-radius:4px;font-size:11px">Skipped</span>'
      : '';

    const sourceChip = `<span class="engage-source-chip engage-source-${item.source_type || 'connection'}">${_escHtml(item.source_label || item.source_type || 'Feed')}</span>`;
    const authorLink = item.author_url
      ? `<a href="${_escHtml(item.author_url)}" target="_blank" rel="noopener" class="engage-author-link">${_escHtml(item.author_name || 'Unknown')}</a>`
      : `<span>${_escHtml(item.author_name || 'Unknown')}</span>`;

    const truncText = (item.post_text || '').length > 300
      ? _escHtml((item.post_text || '').slice(0, 300)) + '…'
      : _escHtml(item.post_text || '');

    const postLink = item.post_url
      ? `<a href="${_escHtml(item.post_url)}" target="_blank" rel="noopener" class="engage-post-link">View on LinkedIn →</a>`
      : '';

    const engageBtn = item.status !== 'engaged'
      ? `<button class="btn btn-primary btn-sm" onclick="Engage.markStatus(${item.id}, 'engaged')">✓ Mark Engaged</button>`
      : `<button class="btn btn-ghost btn-sm" onclick="Engage.markStatus(${item.id}, 'pending')">Undo</button>`;
    const skipBtn = item.status === 'pending'
      ? `<button class="btn btn-ghost btn-sm" onclick="Engage.markStatus(${item.id}, 'skipped')">Skip</button>`
      : '';
    const replyBtn = `<button class="btn btn-ghost btn-sm engage-reply-btn" data-post-text="${_escHtml(item.post_text || '')}" data-author-name="${_escHtml(item.author_name || '')}">Generate Reply</button>`;

    return `
      <div class="engage-card ${item.status !== 'pending' ? 'engage-card--done' : ''}" id="engage-card-${item.id}">
        <div class="engage-card-header">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
            ${sourceChip}
            <span style="color:${scoreColor};font-weight:600;font-size:13px">Score ${score}</span>
            <span style="color:var(--text3);font-size:12px">❤️ ${item.likes || 0}  💬 ${item.comments_count || 0}</span>
            ${statusBadge}
          </div>
          ${postLink}
        </div>
        <div class="engage-card-author">${authorLink}</div>
        ${item.ai_reason ? `<div class="engage-card-reason">${_escHtml(item.ai_reason)}</div>` : ''}
        <div class="engage-card-text">${truncText}</div>
        <div class="engage-card-actions">
          ${engageBtn}
          ${skipBtn}
          ${replyBtn}
        </div>
      </div>`;
  }

  // ── Actions ─────────────────────────────────────────────────────────────────

  async function markStatus(id, status) {
    try {
      await API.patch(`/api/engage/items/${id}`, { status });
      await _loadItems(true);
    } catch (e) {
      App.toast('Failed to update: ' + e.message, 'error');
    }
  }

  async function clearDone() {
    const confirm = window.confirm('Clear all Engaged and Skipped posts?');
    if (!confirm) return;
    try {
      await API.del('/api/engage/items?status=engaged,skipped');
    } catch (e) {
      App.toast('Failed to clear: ' + e.message, 'error');
      return;
    }
    await _loadItems();
  }

  function generateReply(postText, authorName) {
    // Switch to Write screen with post context pre-filled
    App.navigate('write');
    setTimeout(() => {
      const ideaEl = document.getElementById('write-idea');
      if (ideaEl) {
        ideaEl.value = `Craft a thoughtful LinkedIn comment reply to this post by ${authorName}:\n\n"${postText}"`;
      }
      const formatOpt = document.querySelector('#write-format-toggle .toggle-option[data-val="caption"]');
      if (formatOpt) {
        document.querySelectorAll('#write-format-toggle .toggle-option').forEach(o => o.classList.remove('active'));
        formatOpt.classList.add('active');
        if (window.Write) Write.format = 'caption';
      }
    }, 300);
  }

  // ── Profile Search ──────────────────────────────────────────────────────────

  async function searchProfiles() {
    const keywords = document.getElementById('engage-search-keywords')?.value?.trim();
    const preset = document.getElementById('engage-search-location-preset');
    const customInput = document.getElementById('engage-search-location-custom');
    const location = preset?.value === '__custom__'
      ? (customInput?.value?.trim() || '')
      : (preset?.value || '');
    const maxResults = parseInt(document.getElementById('engage-search-max')?.value) || 30;

    if (!keywords) { App.toast('Enter keywords to search', 'error'); return; }

    const resultsEl = document.getElementById('engage-search-results');
    const tableEl = document.getElementById('engage-search-table');
    if (resultsEl) resultsEl.style.display = '';
    if (tableEl) tableEl.innerHTML = '<div style="color:var(--text3);font-size:13px;padding:16px">Searching LinkedIn profiles…</div>';

    try {
      const data = await API.post('/api/engage/search-profiles', { keywords, location, max_results: maxResults });
      const profiles = data.profiles || [];
      if (!profiles.length) {
        tableEl.innerHTML = '<div style="color:var(--text3);font-size:13px;padding:16px">No profiles found. Try different keywords.</div>';
        return;
      }
      tableEl.innerHTML = _renderProfileTable(profiles);
    } catch (e) {
      const isConfig = e.message && e.message.toLowerCase().includes('no scraping method');
      tableEl.innerHTML = isConfig
        ? `<div style="color:var(--red);font-size:13px;padding:16px">
             No scraping method configured.
             <a href="#" onclick="App.navigate('settings');return false" style="color:var(--accent)">
               Go to Settings → Scraping Options
             </a> to add an Apify key or LinkedIn li_at cookie.
           </div>`
        : `<div style="color:var(--red);font-size:13px;padding:16px">Error: ${_escHtml(e.message)}</div>`;
    }
  }

  function _renderProfileTable(profiles) {
    const rows = profiles.map((p, idx) => `
      <tr>
        <td style="padding:10px 8px">
          ${p.profile_image_url
            ? `<img src="${_escHtml(p.profile_image_url)}" style="width:36px;height:36px;border-radius:50%;object-fit:cover" onerror="this.style.display='none'" />`
            : `<div style="width:36px;height:36px;border-radius:50%;background:var(--bg3);display:flex;align-items:center;justify-content:center;color:var(--text3);font-size:14px">${_escHtml((p.name||'?')[0].toUpperCase())}</div>`}
        </td>
        <td style="padding:10px 8px">
          ${p.linkedin_url
            ? `<a href="${_escHtml(p.linkedin_url)}" target="_blank" rel="noopener" style="font-weight:500;color:var(--text)">${_escHtml(p.name)}</a>`
            : `<span style="font-weight:500">${_escHtml(p.name)}</span>`}
        </td>
        <td style="padding:10px 8px;color:var(--text2);font-size:12px">${_escHtml(p.headline || '')}</td>
        <td style="padding:10px 8px;color:var(--text3);font-size:12px">${_escHtml(p.location || '')}</td>
        <td style="padding:10px 8px;color:var(--text3);font-size:12px">${p.followers ? p.followers.toLocaleString() : '—'}</td>
        <td style="padding:10px 8px">
          <button class="btn btn-ghost btn-sm" onclick="Engage.addCreatorFromSearch(${idx})" data-profile-idx="${idx}">+ Add Creator</button>
        </td>
      </tr>`).join('');

    // Stash profiles for add action
    window._engageSearchProfiles = profiles;

    return `
      <div style="font-size:12px;color:var(--text3);margin-bottom:8px">${profiles.length} profiles found</div>
      <table style="width:100%;border-collapse:collapse">
        <thead>
          <tr style="border-bottom:1px solid var(--border)">
            <th style="padding:8px;text-align:left;font-size:11px;color:var(--text3);width:44px"></th>
            <th style="padding:8px;text-align:left;font-size:11px;color:var(--text3)">Name</th>
            <th style="padding:8px;text-align:left;font-size:11px;color:var(--text3)">Headline</th>
            <th style="padding:8px;text-align:left;font-size:11px;color:var(--text3)">Location</th>
            <th style="padding:8px;text-align:left;font-size:11px;color:var(--text3)">Followers</th>
            <th style="padding:8px;text-align:left;font-size:11px;color:var(--text3)"></th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  async function addCreatorFromSearch(idx) {
    const profile = (window._engageSearchProfiles || [])[idx];
    if (!profile) return;
    try {
      await API.post('/api/creators/', {
        name: profile.name,
        category: 'inspiration',
        linkedin_url: profile.linkedin_url,
        country: profile.location || '',
        notes: profile.headline || '',
      });
      App.toast(`${profile.name} added as creator!`, 'success');
    } catch (e) {
      App.toast('Failed to add: ' + e.message, 'error');
    }
  }

  // ── Badge ───────────────────────────────────────────────────────────────────

  function _updateBadge() {
    const badge = document.getElementById('nav-engage-badge');
    if (!badge) return;
    const pending = _items.filter(i => i.status === 'pending').length;
    if (pending > 0) {
      badge.textContent = pending;
      badge.style.display = '';
    } else {
      badge.style.display = 'none';
    }
  }

  // ── Utility ─────────────────────────────────────────────────────────────────

  function _escHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function locationPresetChange() {
    const preset = document.getElementById('engage-search-location-preset');
    const custom = document.getElementById('engage-search-location-custom');
    if (!preset || !custom) return;
    custom.style.display = preset.value === '__custom__' ? '' : 'none';
    if (preset.value !== '__custom__') custom.value = '';
  }

  async function getAIRecommendations() {
    const btn = document.getElementById('engage-ai-rec-btn');
    const status = document.getElementById('engage-ai-rec-status');
    const chips = document.getElementById('engage-ai-rec-chips');
    if (btn) { btn.disabled = true; btn.textContent = 'Thinking…'; }
    if (status) status.textContent = '';
    if (chips) chips.innerHTML = '';

    try {
      const data = await API.post('/api/engage/ai-recommendations', {});
      const suggestions = data.suggestions || [];
      if (!suggestions.length) {
        if (status) status.textContent = 'No suggestions returned.';
        return;
      }
      if (chips) {
        chips.innerHTML = suggestions.map((s) => `
          <div class="engage-ai-chip" title="${_escHtml(s.reason)}"
               onclick="Engage._applyRecommendation(${JSON.stringify(_escHtml(s.keywords))}, ${JSON.stringify(_escHtml(s.location))})"
               style="cursor:pointer;background:var(--bg2);border:1px solid var(--border);border-radius:20px;
                      padding:6px 14px;font-size:12px;color:var(--text);transition:background 0.15s"
               onmouseover="this.style.background='var(--bg3)'"
               onmouseout="this.style.background='var(--bg2)'">
            <span style="font-weight:500">${_escHtml(s.keywords)}</span>
            ${s.location ? `<span style="color:var(--text3);margin-left:4px">· ${_escHtml(s.location)}</span>` : ''}
          </div>`).join('');
      }
      if (status) status.textContent = `${suggestions.length} suggestions — click any to search`;
    } catch (e) {
      if (status) status.textContent = 'Error: ' + e.message;
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '✦ Get AI Suggestions'; }
    }
  }

  function _applyRecommendation(keywords, location) {
    const kw = document.getElementById('engage-search-keywords');
    const preset = document.getElementById('engage-search-location-preset');
    const custom = document.getElementById('engage-search-location-custom');
    if (kw) kw.value = keywords;

    if (preset) {
      const match = Array.from(preset.options).find(
        o => o.value.toLowerCase() === location.toLowerCase()
      );
      if (match) {
        preset.value = match.value;
        if (custom) { custom.style.display = 'none'; custom.value = ''; }
      } else {
        preset.value = '__custom__';
        if (custom) { custom.style.display = ''; custom.value = location; }
      }
    }

    searchProfiles();
  }

  return { load, refresh, applyFilters, markStatus, clearDone, generateReply, searchProfiles, addCreatorFromSearch, locationPresetChange, getAIRecommendations, _applyRecommendation };
})();
