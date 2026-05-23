const Sources = {
  // ── State ──────────────────────────────────────────────────────────────────
  newsView: true,
  filterOpen: false,
  savedOnly: false,
  filters: { sourceIds: [], priorities: [], tags: [], categories: [] },
  selectedArticleIds: new Set(),
  selectedSourceIds: new Set(),
  allSources: [],
  allTags: [],
  allCategories: [],
  editingId: null,
  _recommendProvider: null,
  _recommendModel: null,

  // ── Init ───────────────────────────────────────────────────────────────────
  favicon(url) {
    try { return `https://www.google.com/s2/favicons?domain=${new URL(url).hostname}&sz=32`; } catch { return null; }
  },

  load() {
    this._loadMeta().then(() => {
      if (this.newsView) this.loadNews(); else this.loadManage();
    });
  },

  async _loadMeta() {
    try {
      const meta = await API.get('/api/sources/meta');
      this.allTags = meta.tags || [];
      this.allCategories = meta.categories || [];
    } catch {}
    try {
      this.allSources = await API.get('/api/sources');
    } catch {}
  },

  // ── View switching ─────────────────────────────────────────────────────────
  showNewsView() {
    this.newsView = true;
    this.savedOnly = false;
    document.getElementById('sources-news-view').style.display = '';
    document.getElementById('sources-manage-view').style.display = 'none';
    document.getElementById('sources-toolbar-news').style.display = '';
    document.getElementById('sources-toolbar-manage').style.display = 'none';
    document.getElementById('sources-title').textContent = 'Latest News';
    const savedBtn = document.getElementById('src-saved-btn');
    if (savedBtn) savedBtn.classList.remove('active');
    this._hideBulkBar();
    this.loadNews();
  },

  toggleSavedOnly() {
    this.savedOnly = !this.savedOnly;
    const btn = document.getElementById('src-saved-btn');
    if (btn) btn.classList.toggle('active', this.savedOnly);
    document.getElementById('sources-title').textContent = this.savedOnly ? 'Saved Articles' : 'Latest News';
    this.loadNews();
  },

  showManageView() {
    this.newsView = false;
    document.getElementById('sources-news-view').style.display = 'none';
    document.getElementById('sources-manage-view').style.display = '';
    document.getElementById('sources-toolbar-news').style.display = 'none';
    document.getElementById('sources-toolbar-manage').style.display = '';
    document.getElementById('sources-title').textContent = 'Manage Sources';
    this._hideBulkBar();
    this.selectedSourceIds.clear();
    this.loadManage();
  },

  toggleFilter() {
    this.filterOpen = !this.filterOpen;
    const panel = document.getElementById('src-filter-panel');
    panel.classList.toggle('hidden', !this.filterOpen);
    if (this.filterOpen) this._renderFilterPanel();
    const btn = document.getElementById('src-filter-toggle-btn');
    if (btn) btn.classList.toggle('active', this.filterOpen);
  },

  _renderFilterPanel() {
    // Sources chips
    const srcEl = document.getElementById('src-filter-sources');
    if (srcEl) {
      srcEl.innerHTML = this.allSources.map(s => {
        const active = this.filters.sourceIds.includes(s.id);
        return `<span class="src-filter-chip${active ? ' active' : ''}" data-id="${s.id}" onclick="Sources._toggleSourceFilter(${s.id}, this)">${App.escape(s.name)}</span>`;
      }).join('');
    }
    // Priority chips
    const priEl = document.getElementById('src-filter-priorities');
    if (priEl) {
      const labels = { 1: '🔴 P1', 2: '🟠 P2', 3: '🟡 P3', 4: '🔵 P4', 5: '🟢 P5' };
      priEl.innerHTML = [1, 2, 3, 4, 5].map(p => {
        const active = this.filters.priorities.includes(p);
        return `<span class="src-filter-chip${active ? ' active' : ''}" onclick="Sources._togglePriorityFilter(${p}, this)">${labels[p]}</span>`;
      }).join('');
    }
    // Tag chips
    const tagEl = document.getElementById('src-filter-tags');
    if (tagEl) {
      tagEl.innerHTML = this.allTags.map(t => {
        const active = this.filters.tags.includes(t);
        return `<span class="src-filter-chip${active ? ' active' : ''}" onclick="Sources._toggleTagFilter('${App.escape(t)}', this)">${App.escape(t)}</span>`;
      }).join('') || '<span style="color:var(--text3);font-size:12px">No tags yet</span>';
    }
    // Category chips
    const catEl = document.getElementById('src-filter-categories');
    if (catEl) {
      catEl.innerHTML = this.allCategories.map(c => {
        const active = this.filters.categories.includes(c);
        return `<span class="src-filter-chip${active ? ' active' : ''}" onclick="Sources._toggleCatFilter('${App.escape(c)}', this)">${App.escape(c)}</span>`;
      }).join('') || '<span style="color:var(--text3);font-size:12px">No categories yet</span>';
    }
  },

  _toggleSourceFilter(id, el) {
    const idx = this.filters.sourceIds.indexOf(id);
    if (idx >= 0) this.filters.sourceIds.splice(idx, 1);
    else this.filters.sourceIds.push(id);
    el.classList.toggle('active', this.filters.sourceIds.includes(id));
  },
  _togglePriorityFilter(p, el) {
    const idx = this.filters.priorities.indexOf(p);
    if (idx >= 0) this.filters.priorities.splice(idx, 1);
    else this.filters.priorities.push(p);
    el.classList.toggle('active', this.filters.priorities.includes(p));
  },
  _toggleTagFilter(t, el) {
    const idx = this.filters.tags.indexOf(t);
    if (idx >= 0) this.filters.tags.splice(idx, 1);
    else this.filters.tags.push(t);
    el.classList.toggle('active', this.filters.tags.includes(t));
  },
  _toggleCatFilter(c, el) {
    const idx = this.filters.categories.indexOf(c);
    if (idx >= 0) this.filters.categories.splice(idx, 1);
    else this.filters.categories.push(c);
    el.classList.toggle('active', this.filters.categories.includes(c));
  },

  applyFilters() {
    this.loadNews();
    if (this.filterOpen) this.toggleFilter();
  },

  clearFilters() {
    this.filters = { sourceIds: [], priorities: [], tags: [], categories: [] };
    this._renderFilterPanel();
  },

  // ── News loading ───────────────────────────────────────────────────────────
  async loadNews() {
    const el = document.getElementById('sources-news-list');
    if (!el) return;
    App.loading(el, 'Loading news...');
    try {
      const params = new URLSearchParams({ limit: '50' });
      if (this.savedOnly) params.set('saved', 'true');
      if (this.filters.sourceIds.length) params.set('source_ids', this.filters.sourceIds.join(','));
      if (this.filters.priorities.length) params.set('priorities', this.filters.priorities.join(','));
      if (this.filters.tags.length) params.set('tags', this.filters.tags.join(','));
      if (this.filters.categories.length) params.set('categories', this.filters.categories.join(','));

      const items = await API.get(`/api/sources/items?${params}`);
      this.selectedArticleIds.clear();
      this._hideArticleBulkBar();

      if (!items.length) {
        const msg = this.savedOnly
          ? `<div class="empty-state"><div class="empty-icon">★</div><h3>No saved articles</h3><p>Click the ★ button on any article to save it here.</p></div>`
          : `<div class="empty-state"><div class="empty-icon">📰</div><h3>No articles yet</h3><p>Add sources and click ↻ Refresh, or adjust filters.</p></div>`;
        el.innerHTML = msg;
        return;
      }
      el.innerHTML = items.map(item => this._buildArticleCard(item)).join('');
    } catch (e) {
      el.innerHTML = `<div class="empty-state"><p style="color:var(--red)">${App.escape(e.message)}</p></div>`;
    }
  },

  _buildArticleCard(item) {
    const topicTags = (item.topic_tags || []).map(t =>
      `<span class="tag">${App.escape(t)}</span>`).join('');
    const userTags = (item.user_tags || []).map(t =>
      `<span class="user-tag" title="User tag">${App.escape(t)}</span>`).join('');
    const excerpt = (item.body || '').substring(0, 130);
    const fav = item.url ? this.favicon(item.url) : null;
    const faviconHtml = fav
      ? `<img src="${fav}" class="article-source-favicon" onerror="this.style.display='none'">`
      : `<span class="dot dot-source" style="width:8px;height:8px;flex-shrink:0"></span>`;
    const pBadge = `<span class="priority-badge" data-p="${item.source_priority||3}" data-source-id="${item.source_id}" title="Click to change source priority" style="cursor:pointer" onclick="Sources.openPriorityPicker(${item.source_id}, ${item.source_priority||3}, this)">${item.source_priority||3}</span>`;
    const catBadge = item.source_category ? `<span class="tag" style="background:rgba(20,184,166,0.1);color:#2dd4bf;border-color:rgba(20,184,166,0.25);font-size:10px">${App.escape(item.source_category)}</span>` : '';
    const _srcColors = ['99,102,241','139,92,246','236,72,153','20,184,166','59,130,246','16,185,129','249,115,22','168,85,247'];
    const srcRgb = _srcColors[(item.source_id || 0) % _srcColors.length];

    return `
      <div class="feed-item article-card" data-id="${item.id}" data-priority="${item.source_priority||3}">
        <input type="checkbox" class="article-card-checkbox" onchange="Sources._onArticleCheck(${item.id}, this.checked)" ${this.selectedArticleIds.has(item.id) ? 'checked' : ''}>
        <div class="article-source-header" style="background:rgba(${srcRgb},0.07);border-top:2px solid rgba(${srcRgb},0.45)">
          <div class="article-source-info">
            ${faviconHtml}
            ${pBadge}
            <span class="article-source-name">${App.escape(item.source_name || 'Unknown')}</span>
            ${catBadge}
          </div>
          <div class="article-source-meta">
            <span class="article-date">${App.fmtDate(item.published_at)}</span>
            ${item.is_saved ? '<span class="article-saved-badge">★ Saved</span>' : ''}
          </div>
        </div>
        <div class="article-body">
          <div class="article-title">${App.escape(item.title)}</div>
          ${excerpt ? `<div class="article-excerpt">${App.escape(excerpt)}${(item.body||'').length > 130 ? '…' : ''}</div>` : ''}
          <div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px">
            ${topicTags}${userTags}
            <span class="user-tag" style="cursor:pointer;opacity:0.6" onclick="Sources.openTagEditor(${item.id}, this)" title="Edit tags">✎</span>
          </div>
        </div>
        <div class="article-footer">
          <button class="btn btn-secondary btn-sm" style="font-size:11px" onclick="Sources.createPost(${item.id})">✍ Create Post</button>
          ${item.url ? `<a href="${App.escape(item.url)}" target="_blank" class="btn btn-ghost btn-sm" style="font-size:11px">↗ Open</a>` : ''}
          ${!item.is_saved ? `<button class="btn btn-ghost btn-sm" style="font-size:11px" onclick="Sources.saveItem(${item.id}, this)" title="Save">★</button>` : ''}
        </div>
      </div>
    `;
  },

  // ── Article selection ──────────────────────────────────────────────────────
  _onArticleCheck(id, checked) {
    if (checked) this.selectedArticleIds.add(id);
    else this.selectedArticleIds.delete(id);
    const card = document.querySelector(`.article-card[data-id="${id}"]`);
    if (card) card.classList.toggle('selected', checked);
    this._updateArticleBulkBar();
  },

  _updateArticleBulkBar() {
    const bar = document.getElementById('src-article-bulk-bar');
    const count = this.selectedArticleIds.size;
    if (count > 0) {
      bar.classList.remove('hidden');
      document.getElementById('src-article-bulk-count').textContent = `${count} article${count > 1 ? 's' : ''} selected`;
    } else {
      bar.classList.add('hidden');
    }
  },

  _hideArticleBulkBar() {
    const bar = document.getElementById('src-article-bulk-bar');
    if (bar) bar.classList.add('hidden');
  },

  clearArticleSelection() {
    this.selectedArticleIds.clear();
    document.querySelectorAll('.article-card-checkbox').forEach(cb => { cb.checked = false; });
    document.querySelectorAll('.article-card.selected').forEach(c => c.classList.remove('selected'));
    this._hideArticleBulkBar();
  },

  async bulkMarkRead() {
    const ids = [...this.selectedArticleIds];
    if (!ids.length) return;
    try {
      await Promise.all(ids.map(id => API.post(`/api/sources/items/${id}/read`, {})));
      App.toast(`Marked ${ids.length} articles as read`, 'success');
      this.clearArticleSelection();
      this.loadNews();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  async bulkWritePosts() {
    const ids = [...this.selectedArticleIds];
    if (!ids.length) return;
    if (ids.length === 1) { this.createPost(ids[0]); return; }

    let i = 0;
    const writeNext = () => {
      if (i >= ids.length) { App.toast('All posts sent to Writer!', 'success'); return; }
      App.toast(`Writing post ${i+1} of ${ids.length}…`, '');
      App.goTo('write');
      Write.fromSourceItem(ids[i]);
      i++;
      setTimeout(writeNext, 500);
    };
    writeNext();
    this.clearArticleSelection();
  },

  async bulkCombinePost() {
    const ids = [...this.selectedArticleIds];
    if (!ids.length) return;
    App.goTo('write');
    Write.fromSourceItems(ids);
    this.clearArticleSelection();
  },

  bulkTagArticles() {
    const ids = [...this.selectedArticleIds];
    if (!ids.length) return;
    this._openBulkTagModal(ids);
  },

  _openBulkTagModal(ids) {
    const container = 'bulk-tag-input-wrap';
    App.openModal(`
      <div class="modal-title">Tag ${ids.length} Article${ids.length > 1 ? 's' : ''}</div>
      <div class="form-group">
        <label>Tags to apply</label>
        ${this._renderTagInputHtml(container, [], this.allTags)}
      </div>
      <div class="form-group">
        <label>Mode</label>
        <select id="bulk-tag-mode" style="width:auto">
          <option value="add">Add to existing</option>
          <option value="set">Replace all tags</option>
          <option value="remove">Remove these tags</option>
        </select>
      </div>
      <div class="modal-footer">
        <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="Sources._saveBulkTags(${JSON.stringify(ids)})">Apply</button>
      </div>
    `);
    this._initTagInput(container, [], this.allTags);
  },

  async _saveBulkTags(ids) {
    const tags = this._getTagInputValue('bulk-tag-input-wrap');
    const mode = document.getElementById('bulk-tag-mode')?.value || 'add';
    try {
      await API.put('/api/sources/items/bulk-tags', { ids, tags, mode });
      App.closeModal();
      App.toast(`Tags updated for ${ids.length} articles`, 'success');
      this.clearArticleSelection();
      this.loadNews();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  // ── Inline tag editor ──────────────────────────────────────────────────────
  openTagEditor(itemId, btn) {
    // Find current tags from rendered card
    const card = btn.closest('.article-card');
    const currentUserTags = Array.from(card.querySelectorAll('.user-tag'))
      .filter(el => !el.textContent.includes('✎'))
      .map(el => el.textContent.trim());

    const containerId = `tag-edit-wrap-${itemId}`;
    const popover = document.createElement('div');
    popover.className = 'tag-edit-popover';
    popover.innerHTML = `
      <div style="font-size:11px;color:var(--text3);margin-bottom:6px;font-weight:600">EDIT ARTICLE TAGS</div>
      ${this._renderTagInputHtml(containerId, currentUserTags, this.allTags)}
      <div style="display:flex;gap:6px;margin-top:8px">
        <button class="btn btn-primary btn-sm" onclick="Sources._saveItemTags(${itemId}, '${containerId}', this)">Save</button>
        <button class="btn btn-ghost btn-sm" onclick="this.closest('.tag-edit-popover').remove()">Cancel</button>
      </div>
    `;
    card.style.position = 'relative';
    card.appendChild(popover);
    this._initTagInput(containerId, currentUserTags, this.allTags);

    // Close on outside click
    setTimeout(() => {
      document.addEventListener('click', function close(e) {
        if (!popover.contains(e.target) && e.target !== btn) {
          popover.remove();
          document.removeEventListener('click', close);
        }
      });
    }, 100);
  },

  async _saveItemTags(itemId, containerId, btn) {
    const tags = this._getTagInputValue(containerId);
    try {
      await API.put(`/api/sources/items/${itemId}/tags`, { tags });
      App.toast('Tags saved!', 'success');
      btn.closest('.tag-edit-popover').remove();
      // Update allTags with any new ones
      tags.forEach(t => { if (!this.allTags.includes(t)) this.allTags.push(t); });
      this.loadNews();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  // ── Tag input widget ───────────────────────────────────────────────────────
  _renderTagInputHtml(containerId, initial, known) {
    return `<div class="tag-input-wrap" id="${containerId}"><input type="text" placeholder="Type and press Enter…" autocomplete="off" /></div>`;
  },

  _initTagInput(containerId, initial, known) {
    const wrap = document.getElementById(containerId);
    if (!wrap) return;
    const input = wrap.querySelector('input');
    let tags = [...initial];

    const render = () => {
      // Remove existing chips (not the input)
      wrap.querySelectorAll('.tag-chip-rm').forEach(c => c.remove());
      tags.forEach(t => {
        const chip = document.createElement('span');
        chip.className = 'tag-chip-rm';
        chip.innerHTML = `${App.escape(t)}<span onclick="rmTag('${t}')">×</span>`;
        chip.querySelector('span').onclick = () => { tags = tags.filter(x => x !== t); render(); };
        wrap.insertBefore(chip, input);
      });
    };

    const addTag = (t) => {
      t = t.trim().toLowerCase().replace(/[^a-z0-9؀-ۿ\-_ ]/g, '');
      if (t && !tags.includes(t)) { tags.push(t); render(); input.value = ''; hideAC(); }
    };

    // Autocomplete
    let acEl = null;
    const showAC = (q) => {
      if (acEl) acEl.remove();
      const matches = known.filter(k => k.toLowerCase().includes(q.toLowerCase()) && !tags.includes(k));
      if (!matches.length) return;
      acEl = document.createElement('div');
      acEl.className = 'tag-autocomplete';
      matches.slice(0, 8).forEach(m => {
        const item = document.createElement('div');
        item.className = 'tag-ac-item';
        item.textContent = m;
        item.onmousedown = (e) => { e.preventDefault(); addTag(m); };
        acEl.appendChild(item);
      });
      wrap.style.position = 'relative';
      wrap.appendChild(acEl);
    };
    const hideAC = () => { if (acEl) { acEl.remove(); acEl = null; } };

    input.oninput = () => {
      const v = input.value;
      if (v.endsWith(',')) { addTag(v.slice(0, -1)); return; }
      if (v.length >= 1) showAC(v); else hideAC();
    };
    input.onkeydown = (e) => {
      if (e.key === 'Enter') { e.preventDefault(); addTag(input.value); }
      if (e.key === 'Backspace' && !input.value && tags.length) { tags.pop(); render(); }
      if (e.key === 'Escape') hideAC();
    };
    input.onblur = () => setTimeout(hideAC, 150);

    // Store tags ref on wrap for retrieval
    wrap._getTags = () => tags;

    render();
  },

  _getTagInputValue(containerId) {
    const wrap = document.getElementById(containerId);
    if (!wrap) return [];
    if (wrap._getTags) return wrap._getTags();
    return [];
  },

  // ── Priority selector widget ───────────────────────────────────────────────
  _renderPrioritySelector(value = 3, inputId = 'src-priority-val') {
    return `
      <div class="priority-selector" id="priority-selector-wrap">
        ${[1,2,3,4,5].map(p => `
          <button type="button" class="priority-btn${p === value ? ' active' : ''}" data-p="${p}"
            onclick="Sources._selectPriority(${p})" title="Priority ${p}">${p}</button>
        `).join('')}
      </div>
      <input type="hidden" id="${inputId}" value="${value}">
    `;
  },

  _selectPriority(p) {
    document.querySelectorAll('.priority-btn').forEach(btn => {
      btn.classList.toggle('active', parseInt(btn.dataset.p) === p);
    });
    const inp = document.getElementById('src-priority-val');
    if (inp) inp.value = p;
  },

  openPriorityPicker(sourceId, currentPriority, badgeEl) {
    document.querySelectorAll('.priority-picker-popover').forEach(el => el.remove());

    const labels = { 1: '🔴 P1', 2: '🟠 P2', 3: '🟡 P3', 4: '🔵 P4', 5: '🟢 P5' };
    const popover = document.createElement('div');
    popover.className = 'priority-picker-popover';
    popover.innerHTML = [1, 2, 3, 4, 5].map(p => `
      <button class="priority-picker-btn${p === currentPriority ? ' active' : ''}" onclick="Sources._setSourcePriority(${sourceId}, ${p}, this)">${labels[p]}</button>
    `).join('');
    badgeEl.style.position = 'relative';
    badgeEl.appendChild(popover);

    setTimeout(() => {
      document.addEventListener('click', function close(e) {
        if (!popover.contains(e.target) && e.target !== badgeEl) {
          popover.remove();
          document.removeEventListener('click', close);
        }
      });
    }, 100);
  },

  async _setSourcePriority(sourceId, p, btn) {
    const popover = btn.closest('.priority-picker-popover');
    try {
      const src = this.allSources.find(s => s.id === sourceId);
      if (!src) throw new Error('Source not found');
      await API.put(`/api/sources/${sourceId}`, {
        name: src.name, url: src.url,
        rss_url: src.rss_url || null,
        notes: src.notes || null,
        fetch_from_date: src.fetch_from_date || null,
        priority: p,
        category: src.category || null,
        tags: src.tags || [],
      });
      src.priority = p;
      // Update all badges for this source on the page
      document.querySelectorAll(`.priority-badge[data-source-id="${sourceId}"]`).forEach(badge => {
        badge.dataset.p = p;
        badge.textContent = p;
        badge.onclick = () => Sources.openPriorityPicker(sourceId, p, badge);
        const card = badge.closest('.article-card');
        if (card) card.dataset.priority = p;
      });
      App.toast(`Priority updated to P${p}`, 'success');
    } catch (e) {
      App.toast(e.message, 'error');
    }
    if (popover) popover.remove();
  },

  // ── Source CRUD ────────────────────────────────────────────────────────────
  async loadManage() {
    const el = document.getElementById('sources-manage-list');
    if (!el) return;
    App.loading(el, 'Loading sources...');
    try {
      const sources = await API.get('/api/sources');
      this.allSources = sources;
      if (!sources.length) {
        el.innerHTML = `<div class="empty-state"><p>No sources yet. Click "+ Add Source" to add websites and blogs to follow.</p></div>`;
        return;
      }
      el.innerHTML = sources.map(s => this._renderSourceRow(s)).join('');
    } catch (e) {
      el.innerHTML = `<p style="color:var(--red)">${App.escape(e.message)}</p>`;
    }
  },

  _renderSourceRow(s) {
    const fav = this.favicon(s.url);
    const avatarHtml = fav
      ? `<img src="${fav}" style="width:32px;height:32px;border-radius:6px;object-fit:contain;background:var(--bg3);padding:2px" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'creator-avatar',textContent:'🌐'}))">`
      : `<div class="creator-avatar">🌐</div>`;
    const pBadge = `<span class="priority-badge" data-p="${s.priority||3}" title="Priority ${s.priority||3}">${s.priority||3}</span>`;
    const catBadge = s.category ? `<span class="tag" style="background:rgba(20,184,166,0.1);color:#2dd4bf;border-color:rgba(20,184,166,0.25);font-size:10px">${App.escape(s.category)}</span>` : '';
    const tagChips = (s.tags || []).map(t => `<span class="tag" style="font-size:10px">${App.escape(t)}</span>`).join('');
    return `
      <div class="creator-row" id="src-row-${s.id}">
        <input type="checkbox" class="src-row-checkbox" onchange="Sources._onSourceCheck(${s.id}, this.checked)" ${this.selectedSourceIds.has(s.id) ? 'checked' : ''}>
        ${avatarHtml}
        <div class="creator-info" style="flex:1;min-width:0">
          <div class="creator-name" style="display:flex;align-items:center;gap:6px">
            ${pBadge}
            <a href="${App.escape(s.url)}" target="_blank" style="color:var(--text)">${App.escape(s.name)} ↗</a>
            ${catBadge}
          </div>
          <div class="creator-meta">
            ${App.escape(s.url)}
            · ${s.unread_count || 0} unread
            · ${s.total_count || 0} posts
            ${s.oldest_post_at ? `· since ${App.fmtDate(s.oldest_post_at)}` : ''}
            ${s.rss_url ? '· RSS ✓' : ''}
            ${s.last_fetched_at ? `· Fetched ${App.fmtDate(s.last_fetched_at)}` : ''}
          </div>
          ${tagChips ? `<div style="margin-top:3px;display:flex;flex-wrap:wrap;gap:3px">${tagChips}</div>` : ''}
          ${s.notes ? `<div style="font-size:11px;color:var(--text3);font-style:italic;margin-top:2px">${App.escape(s.notes)}</div>` : ''}
        </div>
        <div class="creator-actions">
          <button class="btn btn-ghost btn-sm" onclick="Sources.fetchOne(${s.id})" title="Refresh">↻</button>
          <button class="btn btn-ghost btn-sm" onclick="Sources.openModal(${s.id})">Edit</button>
          <button class="btn btn-danger btn-sm" onclick="Sources.delete(${s.id})">Del</button>
        </div>
      </div>
    `;
  },

  _onSourceCheck(id, checked) {
    if (checked) this.selectedSourceIds.add(id);
    else this.selectedSourceIds.delete(id);
    this._updateSourceBulkBar();
  },

  _updateSourceBulkBar() {
    const bar = document.getElementById('src-bulk-bar');
    const count = this.selectedSourceIds.size;
    if (count > 0) {
      bar.classList.remove('hidden');
      document.getElementById('src-bulk-count').textContent = `${count} source${count > 1 ? 's' : ''} selected`;
    } else {
      bar.classList.add('hidden');
    }
  },

  _hideBulkBar() {
    document.getElementById('src-bulk-bar')?.classList.add('hidden');
    document.getElementById('src-article-bulk-bar')?.classList.add('hidden');
  },

  clearSelection() {
    this.selectedSourceIds.clear();
    document.querySelectorAll('.src-row-checkbox').forEach(cb => { cb.checked = false; });
    this._hideBulkBar();
  },

  openModal(id) {
    this.editingId = id || null;
    const src = id ? (this.allSources || []).find(s => s.id === id) : null;
    const fromDateVal = src?.fetch_from_date ? src.fetch_from_date.substring(0, 10) : '';
    const pVal = src?.priority || 3;
    const tagContainerId = 'modal-src-tags';

    App.openModal(`
      <div class="modal-title">${id ? 'Edit Source' : '+ Add Source'}</div>
      <div class="form-group">
        <label>URL</label>
        <input type="url" id="m-src-url" placeholder="https://marketingweek.com" value="${App.escape(src?.url || '')}" oninput="Sources._onSrcUrlInput()" onblur="Sources._onSrcUrlBlur()" />
        <div id="m-src-url-warning" style="display:none;color:var(--red);font-size:11px;margin-top:4px"></div>
      </div>
      <div class="form-group"><label>Name</label><input type="text" id="m-src-name" placeholder="Auto-detected from URL" value="${App.escape(src?.name || '')}" /></div>
      <div class="form-group"><label>RSS URL <span style="color:var(--text3);font-size:11px">(leave blank to auto-detect)</span></label><input type="url" id="m-src-rss" placeholder="https://marketingweek.com/feed/" value="${App.escape(src?.rss_url || '')}" /></div>
      <div class="form-group">
        <label>Priority <span style="color:var(--text3);font-size:11px">(1=highest, 5=lowest)</span></label>
        ${this._renderPrioritySelector(pVal)}
      </div>
      <div class="form-group">
        <label>Category</label>
        <input type="text" id="m-src-category" list="src-cat-list" placeholder="e.g. AI, Marketing, SME" value="${App.escape(src?.category || '')}" />
        <datalist id="src-cat-list">${this.allCategories.map(c => `<option value="${App.escape(c)}">`).join('')}</datalist>
      </div>
      <div class="form-group">
        <label>Tags</label>
        ${this._renderTagInputHtml(tagContainerId, src?.tags || [], this.allTags)}
      </div>
      <div class="form-group"><label>Fetch articles from <span style="color:var(--text3);font-size:11px">(leave blank = all available)</span></label><input type="date" id="m-src-from-date" value="${fromDateVal}" /></div>
      <div class="form-group"><label>Notes</label><input type="text" id="m-src-notes" placeholder="Optional notes..." value="${App.escape(src?.notes || '')}" /></div>
      <div class="modal-footer">
        <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="Sources.saveSource()">Save</button>
      </div>
    `);
    this._initTagInput(tagContainerId, src?.tags || [], this.allTags);
  },

  _onSrcUrlInput() {
    const warn = document.getElementById('m-src-url-warning');
    if (warn) warn.style.display = 'none';
  },

  _onSrcUrlBlur() {
    const urlEl = document.getElementById('m-src-url');
    const nameEl = document.getElementById('m-src-name');
    const warn = document.getElementById('m-src-url-warning');
    const url = urlEl?.value?.trim();
    if (!url) return;
    try {
      const u = new URL(url);
      if (nameEl && !nameEl.value) nameEl.value = u.hostname.replace(/^www\./, '');
      if (warn) warn.style.display = 'none';
    } catch {
      if (warn) { warn.textContent = 'Invalid URL format'; warn.style.display = ''; }
    }
  },

  async saveSource() {
    const url = document.getElementById('m-src-url')?.value?.trim();
    if (!url) { App.toast('URL is required', 'error'); return; }
    let name = document.getElementById('m-src-name')?.value?.trim();
    if (!name) {
      try { name = new URL(url).hostname.replace('www.', ''); } catch {}
    }
    if (!name) { App.toast('Name is required', 'error'); return; }
    const fromDate = document.getElementById('m-src-from-date')?.value;
    const priority = parseInt(document.getElementById('src-priority-val')?.value || '3');
    const tags = this._getTagInputValue('modal-src-tags');
    const data = {
      name, url,
      rss_url: document.getElementById('m-src-rss')?.value?.trim() || null,
      notes: document.getElementById('m-src-notes')?.value?.trim() || null,
      fetch_from_date: fromDate ? new Date(fromDate).toISOString() : null,
      priority,
      category: document.getElementById('m-src-category')?.value?.trim() || null,
      tags,
    };
    try {
      if (this.editingId) {
        await API.put(`/api/sources/${this.editingId}`, data);
        App.closeModal();
        App.toast('Source saved!', 'success');
        this.loadManage();
      } else {
        const created = await API.post('/api/sources', data);
        App.closeModal();
        App.toast('Source added — fetching articles...', '');
        await this.loadManage();
        const result = await API.post(`/api/fetch/source/${created.id}`, {});
        App.toast(`Done! ${result.new_items} new articles.`, 'success');
        if (result.errors?.length) App.toast(result.errors.join(', '), 'error');
        this.loadManage();
      }
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  async delete(id) {
    if (!confirm('Delete this source and all its articles?')) return;
    try {
      await API.del(`/api/sources/${id}`);
      App.toast('Deleted', 'success');
      this.selectedSourceIds.delete(id);
      this.loadManage();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  // ── Single-add URL helpers ─────────────────────────────────────────────────
  _onSrcUrlInput() {
    const url = document.getElementById('m-src-url')?.value?.trim();
    const nameInput = document.getElementById('m-src-name');
    if (url && nameInput && !nameInput.value) {
      try { nameInput.value = new URL(url).hostname.replace('www.', ''); } catch {}
    }
    const warn = document.getElementById('m-src-url-warning');
    if (warn) warn.style.display = 'none';
  },

  _onSrcUrlBlur() {
    const url = document.getElementById('m-src-url')?.value?.trim();
    if (!url) return;
    const nameInput = document.getElementById('m-src-name');
    if (nameInput && !nameInput.value) {
      try { nameInput.value = new URL(url).hostname.replace('www.', ''); } catch {}
    }
    const normalised = url.replace(/\/$/, '');
    const existing = (this.allSources || []).find(s => s.url.replace(/\/$/, '') === normalised);
    const warn = document.getElementById('m-src-url-warning');
    if (warn) {
      if (existing && !this.editingId) {
        warn.style.display = '';
        warn.textContent = `⚠ "${existing.name}" already uses this URL`;
      } else {
        warn.style.display = 'none';
      }
    }
  },

  // ── Bulk source operations ─────────────────────────────────────────────────
  openBulkAddModal() {
    const tagContainerId = 'bulk-add-tags';
    App.openModal(`
      <div class="modal-title">⊞ Bulk Add Sources</div>
      <div class="form-group">
        <label>URLs <span style="color:var(--text3);font-size:11px">(one per line)</span></label>
        <textarea id="bulk-add-urls" rows="6" placeholder="https://site1.com&#10;https://site2.com&#10;https://site3.com"></textarea>
        <div id="bulk-dup-warning" style="display:none;color:var(--red);font-size:11px;margin-top:4px"></div>
      </div>
      <div class="form-group">
        <label>Priority for all <span style="color:var(--text3);font-size:11px">(1=highest)</span></label>
        ${this._renderPrioritySelector(3, 'bulk-priority-val')}
      </div>
      <div class="form-group">
        <label>Category for all</label>
        <input type="text" id="bulk-add-category" list="src-cat-list" placeholder="e.g. AI" />
        <datalist id="src-cat-list">${this.allCategories.map(c => `<option value="${App.escape(c)}">`).join('')}</datalist>
      </div>
      <div class="form-group">
        <label>Tags for all</label>
        ${this._renderTagInputHtml(tagContainerId, [], this.allTags)}
      </div>
      <div class="form-group">
        <label>Fetch articles from <span style="color:var(--text3);font-size:11px">(leave blank = all available)</span></label>
        <input type="date" id="bulk-add-from-date" />
      </div>
      <div class="form-group">
        <label>Notes for all</label>
        <input type="text" id="bulk-add-notes" placeholder="Optional notes..." />
      </div>
      <div class="modal-footer">
        <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="Sources.saveBulkAdd()">Add All</button>
      </div>
    `);
    this._initTagInput(tagContainerId, [], this.allTags);
    document.getElementById('bulk-add-urls')?.addEventListener('input', () => this._checkBulkDuplicates());
  },

  _checkBulkDuplicates() {
    const raw = document.getElementById('bulk-add-urls')?.value || '';
    const urls = raw.split('\n').map(u => u.trim()).filter(u => u.startsWith('http'));
    const existingUrls = new Set((this.allSources || []).map(s => s.url.replace(/\/$/, '')));
    const dups = urls.filter(u => existingUrls.has(u.replace(/\/$/, '')));
    const warn = document.getElementById('bulk-dup-warning');
    if (!warn) return;
    if (dups.length) {
      warn.style.display = '';
      warn.textContent = `⚠ ${dups.length} duplicate${dups.length > 1 ? 's' : ''} will be skipped: ${dups.map(u => { try { return new URL(u).hostname; } catch { return u; } }).join(', ')}`;
    } else {
      warn.style.display = 'none';
    }
  },

  async saveBulkAdd() {
    const raw = document.getElementById('bulk-add-urls')?.value?.trim() || '';
    const allUrls = raw.split('\n').map(u => u.trim()).filter(u => u && u.startsWith('http'));
    if (!allUrls.length) { App.toast('No valid URLs entered', 'error'); return; }

    const existingUrls = new Set((this.allSources || []).map(s => s.url.replace(/\/$/, '')));
    const urls = allUrls.filter(u => !existingUrls.has(u.replace(/\/$/, '')));
    const skipped = allUrls.length - urls.length;

    if (!urls.length) {
      App.toast(`All ${skipped} URL${skipped > 1 ? 's' : ''} already exist as sources.`, 'error');
      return;
    }
    if (skipped > 0) App.toast(`Skipping ${skipped} duplicate${skipped > 1 ? 's' : ''}`, '');

    const priority = parseInt(document.getElementById('bulk-priority-val')?.value || '3');
    const category = document.getElementById('bulk-add-category')?.value?.trim() || null;
    const tags = this._getTagInputValue('bulk-add-tags');
    const fromDate = document.getElementById('bulk-add-from-date')?.value;
    const notes = document.getElementById('bulk-add-notes')?.value?.trim() || null;

    const sources = urls.map(url => ({
      name: (() => { try { return new URL(url).hostname.replace('www.', ''); } catch { return url; } })(),
      url, priority, category, tags,
      rss_url: null,
      notes,
      fetch_from_date: fromDate ? new Date(fromDate).toISOString() : null,
    }));

    try {
      App.closeModal();
      App.toast(`Adding ${sources.length} source${sources.length !== 1 ? 's' : ''}...`, '');
      const created = await API.post('/api/sources/bulk-create', { sources });
      App.toast(`Added ${created.length} source${created.length !== 1 ? 's' : ''}! Fetching articles...`, 'success');

      for (const s of created) {
        try { await API.post(`/api/fetch/source/${s.id}`, {}); } catch {}
      }
      App.toast('All done!', 'success');
      this.loadManage();
      await this._loadMeta();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  openBulkEditModal() {
    const ids = [...this.selectedSourceIds];
    if (!ids.length) return;
    const tagContainerId = 'bulk-edit-tags';
    App.openModal(`
      <div class="modal-title">Edit ${ids.length} Source${ids.length > 1 ? 's' : ''}</div>
      <p style="font-size:12px;color:var(--text3);margin-bottom:12px">Only filled fields will be updated. Empty fields left unchanged.</p>
      <div class="form-group">
        <label>Priority</label>
        ${this._renderPrioritySelector(3, 'bulk-edit-priority-val')}
      </div>
      <div class="form-group">
        <label>Category</label>
        <input type="text" id="bulk-edit-category" list="src-cat-list2" placeholder="Leave blank to keep current" />
        <datalist id="src-cat-list2">${this.allCategories.map(c => `<option value="${App.escape(c)}">`).join('')}</datalist>
      </div>
      <div class="form-group">
        <label>Tags (replaces existing tags)</label>
        ${this._renderTagInputHtml(tagContainerId, [], this.allTags)}
      </div>
      <div class="modal-footer">
        <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="Sources.saveBulkEdit(${JSON.stringify(ids)})">Save</button>
      </div>
    `);
    this._initTagInput(tagContainerId, [], this.allTags);
  },

  async saveBulkEdit(ids) {
    const priority = parseInt(document.getElementById('bulk-edit-priority-val')?.value || '3');
    const category = document.getElementById('bulk-edit-category')?.value?.trim() || null;
    const tags = this._getTagInputValue('bulk-edit-tags');

    const payload = { ids, priority };
    if (category) payload.category = category;
    if (tags.length) payload.tags = tags;

    try {
      await API.put('/api/sources/bulk-update', payload);
      App.closeModal();
      App.toast(`Updated ${ids.length} sources`, 'success');
      this.clearSelection();
      this.loadManage();
      await this._loadMeta();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  async bulkDelete() {
    const ids = [...this.selectedSourceIds];
    if (!ids.length) return;
    if (!confirm(`Delete ${ids.length} source${ids.length > 1 ? 's' : ''} and all their articles? This cannot be undone.`)) return;
    try {
      const r = await API.del('/api/sources/bulk-delete', { ids });
      App.toast(`Deleted ${r.deleted_count} sources`, 'success');
      this.clearSelection();
      this.loadManage();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  // ── Fetch / Refresh ────────────────────────────────────────────────────────
  async fetchOne(id) {
    App.toast('Fetching articles...', '');
    try {
      const result = await API.post(`/api/fetch/source/${id}`, {});
      App.toast(`Done! ${result.new_items} new articles.`, 'success');
      if (result.errors?.length) App.toast(result.errors.join(', '), 'error');
      this.loadManage();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  async refreshAll(opts = {}) {
    const btn = document.getElementById('sources-refresh-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Refreshing...'; }
    this.hideRefreshDropdown();
    const body = {};
    if (opts.fromDate) body.from_date = opts.fromDate;
    if (opts.ignoreHistory) body.ignore_last_fetched = true;
    App.toast('Fetching all news sources...', '');
    try {
      const sources = await API.get('/api/sources');
      let total = 0;
      for (const s of sources) {
        try {
          const r = await API.post(`/api/fetch/source/${s.id}`, body);
          total += r.new_items || 0;
        } catch {}
      }
      App.toast(`Done! ${total} new articles.`, 'success');
      this.loadNews();
    } catch (e) {
      App.toast(e.message, 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '↻ Refresh'; }
    }
  },

  toggleRefreshDropdown() {
    const dd = document.getElementById('sources-refresh-dropdown');
    if (dd) dd.classList.toggle('hidden');
  },

  hideRefreshDropdown() {
    const dd = document.getElementById('sources-refresh-dropdown');
    if (dd) dd.classList.add('hidden');
  },

  promptRefreshFromDate() {
    this.hideRefreshDropdown();
    const today = new Date().toISOString().slice(0, 10);
    App.openModal(`
      <div class="modal-title">📅 Fetch Articles From Date</div>
      <p style="font-size:12px;color:var(--text2);margin-bottom:14px">Fetch articles published on or after this date from all sources.</p>
      <div class="form-group">
        <label>From Date</label>
        <input type="date" id="refresh-from-date-input" value="${today}" />
      </div>
      <div class="modal-footer">
        <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="Sources._doRefreshFromDate()">Fetch</button>
      </div>
    `);
  },

  async _doRefreshFromDate() {
    const fromDate = document.getElementById('refresh-from-date-input')?.value;
    App.closeModal();
    await this.refreshAll({ fromDate });
  },

  selectAllSources() {
    const checkboxes = document.querySelectorAll('.src-row-checkbox');
    const allChecked = [...checkboxes].every(cb => cb.checked);
    checkboxes.forEach(cb => {
      const row = cb.closest('[id^="src-row-"]');
      const id = row ? parseInt(row.id.replace('src-row-', '')) : null;
      if (id) {
        if (allChecked) {
          this.selectedSourceIds.delete(id);
          cb.checked = false;
        } else {
          this.selectedSourceIds.add(id);
          cb.checked = true;
        }
      }
    });
    const selBtn = document.getElementById('src-select-all-btn');
    if (selBtn) selBtn.textContent = allChecked ? 'Select All' : 'Deselect All';
    this._updateSourceBulkBar();
  },

  // ── Article actions ────────────────────────────────────────────────────────
  async saveItem(id, btn) {
    try {
      await API.post(`/api/sources/items/${id}/save`, {});
      btn.remove();
      App.toast('Saved!', 'success');
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  createPost(itemId) {
    App.goTo('write');
    Write.fromSourceItem(itemId);
  },

  // ── AI Topics ──────────────────────────────────────────────────────────────
  async openRecommendModal() {
    let providers = {};
    try { providers = await API.get('/api/settings/ai-providers'); } catch {}

    const providerMeta = {
      claude_cli: { label: 'Claude CLI', sublabel: 'Local claude command' },
      groq: { label: 'Groq', sublabel: 'llama-3.3-70b-versatile (free)' },
      openrouter: { label: 'OpenRouter', sublabel: 'Multiple free models available' },
      gemini: { label: 'Google Gemini', sublabel: 'gemini-1.5-flash (free tier)' },
    };

    const rows = Object.entries(providerMeta).map(([key, meta]) => {
      const info = providers[key] || {};
      const models = info.models || (info.default_model ? [info.default_model] : []);
      const defaultModel = info.default_model || '';
      let badge, badgeClass;
      if (key === 'claude_cli') {
        badge = 'Built-in'; badgeClass = 'always';
      } else if (info.has_key) {
        badge = '\u2713 Key saved'; badgeClass = 'has-key';
      } else {
        badge = 'No key'; badgeClass = 'no-key';
      }
      const modelPicker = models.length > 1
        ? `<select id="provider-model-${key}" style="font-size:11px;padding:2px 4px;margin-top:4px;border:1px solid var(--border);background:var(--bg2);border-radius:4px;color:var(--text1);width:100%" onclick="event.stopPropagation()" onchange="Sources._onProviderModelChange('${key}', this.value)">${models.map(m => `<option value="${m}">${m.split('/').pop()}</option>`).join('')}</select>`
        : `<div style="font-size:11px;color:var(--text3);margin-top:2px">${defaultModel.split('/').pop() || 'built-in'}</div>`;
      return `
        <div class="provider-option" data-provider="${key}" data-model="${defaultModel}" onclick="Sources._selectProvider('${key}', document.getElementById('provider-model-${key}')?.value || '${defaultModel}', this)">
          <div style="flex:1">
            <div class="provider-option-name">${meta.label}</div>
            <div class="provider-option-model">${meta.sublabel}</div>
            ${modelPicker}
          </div>
          <span class="provider-key-badge ${badgeClass}">${badge}</span>
        </div>
      `;
    }).join('');

    App.openModal(`
      <div class="modal-title">✨ AI Topic Recommendations</div>
      <p style="font-size:12px;color:var(--text2);margin-bottom:14px">Choose an AI model to analyze your latest articles and suggest content topics + tags.</p>
      <div id="provider-list">${rows}</div>
      <div id="token-inline-form" style="display:none" class="token-inline-form">
        <label id="token-inline-label">Enter API key for this provider:</label>
        <div style="display:flex;gap:8px;margin-top:6px">
          <input type="password" id="token-inline-input" placeholder="sk-..." style="flex:1" />
          <button class="btn btn-primary btn-sm" onclick="Sources._saveInlineToken()">Save & Retry</button>
        </div>
        <div style="margin-top:6px;font-size:11px;color:var(--text3)">Or <button class="btn btn-ghost btn-sm" style="font-size:11px;padding:2px 6px" onclick="App.goTo('settings')">go to Settings ⚙</button> to manage all keys</div>
      </div>
      <div id="recommend-error" style="display:none;margin-top:8px;font-size:12px;color:var(--red)"></div>
      <div id="recommend-results" style="display:none"></div>
      <div class="modal-footer">
        <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
        <button class="btn btn-primary" id="recommend-run-btn" onclick="Sources._runRecommend()" disabled>Get Recommendations</button>
      </div>
    `);
  },

  _selectProvider(key, model, el) {
    document.querySelectorAll('.provider-option').forEach(o => o.classList.remove('selected'));
    el.classList.add('selected');
    this._recommendProvider = key;
    this._recommendModel = model;
    document.getElementById('recommend-run-btn').disabled = false;
    document.getElementById('token-inline-form').style.display = 'none';
  },

  _onProviderModelChange(key, model) {
    if (this._recommendProvider === key) {
      this._recommendModel = model;
    }
  },

  async _runRecommend() {
    const provider = this._recommendProvider;
    const model = this._recommendModel;
    if (!provider) { App.toast('Select a provider first', 'error'); return; }

    const btn = document.getElementById('recommend-run-btn');
    btn.disabled = true; btn.textContent = 'Analyzing…';
    document.getElementById('recommend-error').style.display = 'none';
    document.getElementById('recommend-results').style.display = 'none';

    try {
      const result = await API.post('/api/sources/ai-recommend', {
        provider, model,
        source_ids: [],
        num_topics: 5,
      });
      btn.textContent = 'Get Recommendations'; btn.disabled = false;
      this._renderRecommendResults(result);
    } catch (e) {
      btn.textContent = 'Get Recommendations'; btn.disabled = false;
      const detail = e._detail || {};
      if (detail.error === 'token_missing') {
        this._showTokenInlineForm(provider);
      } else if (detail.error === 'token_invalid') {
        this._showRecommendError('Invalid API key. Update it in Settings ⚙');
      } else if (detail.error === 'cli_not_found') {
        this._showRecommendError('Claude CLI not found. Run: npm install -g @anthropic-ai/claude-code');
      } else if (detail.error === 'rate_limit') {
        this._showRecommendError('Rate limit reached. Wait a moment and try again.');
      } else {
        this._showRecommendError(e.message || 'Unknown error');
      }
    }
  },

  _showTokenInlineForm(provider) {
    const form = document.getElementById('token-inline-form');
    const label = document.getElementById('token-inline-label');
    if (label) label.textContent = `Enter API key for ${provider}:`;
    form.style.display = '';
    form.dataset.provider = provider;
    document.getElementById('token-inline-input')?.focus();
  },

  async _saveInlineToken() {
    const form = document.getElementById('token-inline-form');
    const provider = form.dataset.provider;
    const key = document.getElementById('token-inline-input')?.value?.trim();
    if (!key) { App.toast('Please enter a key', 'error'); return; }

    const settingKey = `ai_provider_${provider}_key`;
    try {
      await API.post('/api/settings', { [settingKey]: key });
      form.style.display = 'none';
      App.toast('Key saved! Retrying...', 'success');
      await this._runRecommend();
    } catch (e) {
      App.toast('Failed to save key: ' + e.message, 'error');
    }
  },

  _showRecommendError(msg) {
    const el = document.getElementById('recommend-error');
    if (el) { el.textContent = msg; el.style.display = ''; }
  },

  _renderRecommendResults(result) {
    const topics = result.topics || [];
    const tagSugs = result.tag_suggestions || [];

    const topicsHtml = topics.length
      ? topics.map(t => `
          <div class="ai-topic-item">
            <div class="ai-topic-title">${App.escape(t.title || '')}</div>
            <div class="ai-topic-desc">${App.escape(t.description || '')}</div>
            ${t.angle ? `<div class="ai-topic-angle">Angle: ${App.escape(t.angle)}</div>` : ''}
            <button class="btn btn-secondary btn-sm" style="margin-top:6px;font-size:11px" onclick="Sources._sendTopicToWriter('${App.escape(t.title)}', '${App.escape(t.angle||t.description||'')}')">✍ Send to Writer</button>
          </div>
        `).join('')
      : '<p style="color:var(--text3);font-size:12px">No topic ideas generated.</p>';

    const tagsHtml = tagSugs.length
      ? tagSugs.map(s => `
          <div class="ai-topic-item">
            <div class="ai-topic-title" style="font-size:12px">Article #${s.item_id}</div>
            <div style="display:flex;flex-wrap:wrap;gap:4px;margin:4px 0">
              ${(s.suggested_tags||[]).map(t => `<span class="tag">${App.escape(t)}</span>`).join('')}
            </div>
            <button class="btn btn-ghost btn-sm" style="font-size:11px" onclick="Sources._applyTagSuggestion(${s.item_id}, ${JSON.stringify(s.suggested_tags)}, this)">Apply</button>
          </div>
        `).join('')
      : '<p style="color:var(--text3);font-size:12px">No untagged articles found.</p>';

    const el = document.getElementById('recommend-results');
    el.innerHTML = `
      <div class="ai-topics-results" style="margin-top:14px">
        <div>
          <div class="ai-topics-col-title">Content Ideas</div>
          ${topicsHtml}
        </div>
        <div>
          <div class="ai-topics-col-title">Tag Suggestions</div>
          ${tagsHtml}
        </div>
      </div>
    `;
    el.style.display = '';
  },

  _sendTopicToWriter(title, angle) {
    App.closeModal();
    App.goTo('write');
    if (window.Write?.setIdea) Write.setIdea(title + (angle ? ' — ' + angle : ''));
  },

  async _applyTagSuggestion(itemId, tags, btn) {
    try {
      await API.put(`/api/sources/items/${itemId}/tags`, { tags });
      btn.textContent = '✓ Applied';
      btn.disabled = true;
      tags.forEach(t => { if (!this.allTags.includes(t)) this.allTags.push(t); });
      App.toast('Tags applied!', 'success');
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },
};
