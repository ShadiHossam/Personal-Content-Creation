const Creators = {
  data: [],
  categoryFilter: '',
  countryFilter: '',
  platformFilters: new Set(),
  priorityFilter: null,
  tagFilters: new Set(),
  sortBy: 'rank',
  allTags: [],
  editingId: null,
  _selectedIds: new Set(),
  _bulkFetchRunning: false,
  _bulkProgressInterval: null,

  async load() {
    const el = document.getElementById('creators-list');
    if (!el) return;
    App.loading(el, 'Loading creators...');
    try {
      [this.data, this.allTags] = await Promise.all([
        API.get('/api/creators'),
        API.get('/api/creators/tags'),
      ]);
      this.renderList();
      this.bindFilters();
    } catch (e) {
      el.innerHTML = `<div class="empty-state"><p style="color:var(--red)">${App.escape(e.message)}</p></div>`;
    }
  },

  async bulkDelete() {
    const ids = [...this._selectedIds];
    if (!ids.length) return;
    if (!confirm(`Delete ${ids.length} creator${ids.length > 1 ? 's' : ''} and all their content?`)) return;
    let done = 0, failed = 0;
    for (const id of ids) {
      try { await API.del(`/api/creators/${id}`); done++; } catch { failed++; }
    }
    this._selectedIds.clear();
    App.toast(`Deleted ${done}${failed ? `, ${failed} failed` : ''}.`, done ? 'success' : 'error');
    this.load();
  },

  openFetchOptionsModal(mode = 'selected') {
    const ids = mode === 'selected' ? [...this._selectedIds] : this.data.map(c => c.id);
    if (!ids.length) return;
    App.openModal(`
      <h2 style="margin:0 0 16px;font-size:16px;font-weight:600">Fetch Options</h2>
      <div style="display:flex;flex-direction:column;gap:12px">
        <div>
          <label style="font-size:13px;color:var(--text2);display:block;margin-bottom:4px">Max posts per creator</label>
          <input id="fo-max-posts" type="number" min="1" max="500" placeholder="Use default setting"
            class="input" style="width:100%">
        </div>
        <div style="display:flex;gap:10px">
          <div style="flex:1">
            <label style="font-size:13px;color:var(--text2);display:block;margin-bottom:4px">From date</label>
            <input id="fo-from-date" type="date" class="input" style="width:100%">
          </div>
          <div style="flex:1">
            <label style="font-size:13px;color:var(--text2);display:block;margin-bottom:4px">To date</label>
            <input id="fo-to-date" type="date" class="input" style="width:100%">
          </div>
        </div>
        <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer">
          <input id="fo-ignore-last" type="checkbox">
          <span>Backfill mode <span style="color:var(--text3)">(ignore last-fetched cutoff)</span></span>
        </label>
      </div>
      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:20px">
        <button class="btn btn-ghost btn-sm" onclick="App.closeModal()">Cancel</button>
        <button class="btn btn-primary btn-sm" onclick="Creators._submitFetchOptions(${JSON.stringify(ids)})">↻ Fetch ${ids.length} Creator${ids.length > 1 ? 's' : ''}</button>
      </div>
    `);
  },

  _submitFetchOptions(ids) {
    const maxPosts = parseInt(document.getElementById('fo-max-posts').value) || null;
    const fromDate = document.getElementById('fo-from-date').value || null;
    const toDate = document.getElementById('fo-to-date').value || null;
    const ignoreLast = document.getElementById('fo-ignore-last').checked;
    App.closeModal();
    this._startBulkFetch(ids, { max_posts: maxPosts, from_date: fromDate, to_date: toDate, ignore_last_fetched: ignoreLast });
  },

  async bulkFetchSelected() {
    this.openFetchOptionsModal('selected');
  },

  async bulkFetchAll() {
    this.openFetchOptionsModal('all');
  },

  async _startBulkFetch(ids, params = {}) {
    this._bulkFetchRunning = true;
    this._updateBulkFetchBtn();
    App.toast(`Fetching ${ids.length} creator${ids.length > 1 ? 's' : ''}…`, '');

    this._bulkProgressInterval = setInterval(async () => {
      try {
        const p = await API.get('/api/fetch/bulk/progress');
        const el = document.getElementById('bulk-fetch-progress');
        if (el && p.running) el.textContent = `Fetching… ${p.current}/${p.total}`;
      } catch {}
    }, 1500);

    try {
      const result = await API.post('/api/fetch/bulk', { creator_ids: ids, ...params });
      App.toast(`Done — ${result.total_new} new posts.`, 'success');
      if (result.stopped) App.toast('Bulk fetch was stopped early.', '');
    } catch (e) {
      if (!e.message?.includes('stopped')) App.toast('Fetch error: ' + e.message, 'error');
    } finally {
      clearInterval(this._bulkProgressInterval);
      this._bulkProgressInterval = null;
      this._bulkFetchRunning = false;
      this._updateBulkFetchBtn();
      this.load();
      App.updateBadge();
    }
  },

  async stopBulkFetch() {
    try {
      await API.post('/api/fetch/bulk/stop', {});
      App.toast('Stop signal sent…', '');
    } catch (e) {
      App.toast('Could not stop: ' + e.message, 'error');
    }
  },

  _updateBulkFetchBtn() {
    const btn = document.getElementById('bulk-fetch-all-btn');
    const stopBtn = document.getElementById('bulk-stop-btn');
    const progressEl = document.getElementById('bulk-fetch-progress');
    if (btn) {
      btn.disabled = this._bulkFetchRunning;
      btn.textContent = this._bulkFetchRunning ? 'Fetching…' : 'Fetch All';
    }
    if (stopBtn) stopBtn.style.display = this._bulkFetchRunning ? '' : 'none';
    if (progressEl) {
      progressEl.style.display = this._bulkFetchRunning ? '' : 'none';
      if (!this._bulkFetchRunning) progressEl.textContent = '';
    }
  },

  bindFilters() {
    ['', 'competitor', 'inspiration'].forEach(cat => {
      const suffix = cat === '' ? 'all' : cat.replace('competitor','comp').replace('inspiration','insp');
      const chip = document.getElementById('creator-filter-' + suffix);
      if (!chip) return;
      chip.onclick = () => {
        document.querySelectorAll('#screen-creators .toolbar .filter-chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        this.categoryFilter = cat;
        this.renderList();
      };
    });
  },

  // ── Filter bar ──

  _toggleFilterBar() {
    const bar = document.getElementById('creators-filter-bar');
    const btn = document.getElementById('creators-filter-toggle');
    if (!bar) return;
    const visible = bar.style.display !== 'none';
    bar.style.display = visible ? 'none' : 'flex';
    if (btn) btn.textContent = visible ? 'Filters ▾' : 'Filters ▴';
  },

  _populateFilterBar() {
    const sel = document.getElementById('filter-country');
    if (sel) {
      const countries = [...new Set(this.data.map(c => c.country).filter(Boolean))].sort();
      const cur = sel.value;
      sel.innerHTML = '<option value="">All countries</option>' +
        countries.map(c => `<option value="${App.escape(c)}" ${c === cur ? 'selected' : ''}>${App.escape(c)}</option>`).join('');
    }
    const tagChips = document.getElementById('filter-tag-chips');
    if (tagChips) {
      tagChips.innerHTML = this.allTags.map(t =>
        `<span class="filter-chip ${this.tagFilters.has(t) ? 'active' : ''}" onclick="Creators._toggleTagFilter('${App.escape(t)}',this)">${App.escape(t)}</span>`
      ).join('') || '<span style="font-size:11px;color:var(--text3)">No tags yet</span>';
    }
  },

  _applyCountryFilter(val) { this.countryFilter = val; this.renderList(); },
  _togglePlatformFilter(platform, checked) {
    if (checked) this.platformFilters.add(platform); else this.platformFilters.delete(platform);
    this.renderList();
  },
  _applyPriorityFilter(val, chipEl) {
    this.priorityFilter = val;
    document.querySelectorAll('#filter-priority-chips .filter-chip').forEach(c => c.classList.remove('active'));
    if (chipEl) chipEl.classList.add('active');
    this.renderList();
  },
  _toggleTagFilter(tag, chipEl) {
    if (this.tagFilters.has(tag)) { this.tagFilters.delete(tag); chipEl?.classList.remove('active'); }
    else { this.tagFilters.add(tag); chipEl?.classList.add('active'); }
    this.renderList();
  },
  _applySort(val) { this.sortBy = val; this.renderList(); },

  _resetFilters() {
    this.categoryFilter = '';
    this.countryFilter = '';
    this.priorityFilter = null;
    this.platformFilters = new Set();
    this.tagFilters = new Set();
    const countrySel = document.getElementById('filter-country');
    if (countrySel) countrySel.value = '';
    document.querySelectorAll('#creators-filter-bar input[type=checkbox]').forEach(cb => { cb.checked = false; });
    document.querySelectorAll('#filter-priority-chips .filter-chip').forEach((c, i) => c.classList.toggle('active', i === 0));
    document.querySelectorAll('.filter-chip[data-category]').forEach(c => c.classList.toggle('active', c.dataset.category === ''));
    this.renderList();
  },

  // ── Inline priority ──

  _inlineEditPriority(creatorId, badgeEl) {
    const existing = document.getElementById('inline-priority-picker');
    if (existing) { existing.remove(); return; }
    const picker = document.createElement('div');
    picker.id = 'inline-priority-picker';
    picker.className = 'bulk-popover';
    picker.style.cssText = 'display:flex;gap:4px;position:fixed;z-index:500;padding:8px';
    picker.innerHTML = [1,2,3,4,5].map(n =>
      `<button class="btn btn-ghost btn-sm" onclick="Creators._setPriority(${creatorId},${n});document.getElementById('inline-priority-picker')?.remove()">${n}</button>`
    ).join('') +
      `<button class="btn btn-ghost btn-sm" style="color:var(--text3)" onclick="Creators._setPriority(${creatorId},null);document.getElementById('inline-priority-picker')?.remove()">✕</button>`;
    const rect = badgeEl.getBoundingClientRect();
    picker.style.top = (rect.bottom + 4) + 'px';
    picker.style.left = rect.left + 'px';
    document.body.appendChild(picker);
    setTimeout(() => document.addEventListener('click', function h(e) {
      if (!picker.contains(e.target) && e.target !== badgeEl) { picker.remove(); document.removeEventListener('click', h); }
    }), 0);
  },

  async _setPriority(creatorId, priority) {
    const c = this.data.find(x => x.id === creatorId);
    if (!c) return;
    try {
      await API.put(`/api/creators/${creatorId}`, { ...c, priority });
      c.priority = priority;
      this.renderList();
    } catch(e) { App.toast(e.message, 'error'); }
  },

  // ── Bulk actions ──

  async bulkSetPriority(priority) {
    const ids = [...this._selectedIds];
    if (!ids.length) return;
    this._closeBulkPopovers();
    try {
      await API.post('/api/creators/bulk-set-priority', { ids, priority });
      ids.forEach(id => { const c = this.data.find(x => x.id === id); if (c) c.priority = priority; });
      this.renderList();
      App.toast(`Priority updated for ${ids.length} creator${ids.length > 1 ? 's' : ''}.`, 'success');
    } catch(e) { App.toast(e.message, 'error'); }
  },

  async bulkSetCategory(category) {
    const ids = [...this._selectedIds];
    if (!ids.length) return;
    this._closeBulkPopovers();
    try {
      await API.post('/api/creators/bulk-set-category', { ids, category });
      ids.forEach(id => { const c = this.data.find(x => x.id === id); if (c) c.category = category; });
      this.renderList();
      App.toast(`Category set to "${category}" for ${ids.length} creator${ids.length > 1 ? 's' : ''}.`, 'success');
    } catch(e) { App.toast(e.message, 'error'); }
  },

  async bulkAddTag() {
    const ids = [...this._selectedIds];
    if (!ids.length) return;
    const input = document.getElementById('bulk-new-tag-input');
    const tag_name = (input?.value || '').trim();
    if (!tag_name) { App.toast('Enter a tag name', 'error'); return; }
    try {
      await API.post('/api/creators/bulk-add-tag', { ids, tag_name });
      ids.forEach(id => { const c = this.data.find(x => x.id === id); if (c && !(c.tags||[]).includes(tag_name)) { c.tags = [...(c.tags||[]), tag_name]; } });
      if (!this.allTags.includes(tag_name)) this.allTags.push(tag_name);
      this._closeBulkPopovers();
      this.renderList();
      App.toast(`Tag "${tag_name}" added to ${ids.length} creator${ids.length > 1 ? 's' : ''}.`, 'success');
    } catch(e) { App.toast(e.message, 'error'); }
  },

  async bulkRemoveTag(tag_name) {
    const ids = [...this._selectedIds];
    if (!ids.length) return;
    this._closeBulkPopovers();
    try {
      await API.post('/api/creators/bulk-remove-tag', { ids, tag_name });
      ids.forEach(id => { const c = this.data.find(x => x.id === id); if (c) c.tags = (c.tags||[]).filter(t => t !== tag_name); });
      this.renderList();
      App.toast(`Tag "${tag_name}" removed.`, 'success');
    } catch(e) { App.toast(e.message, 'error'); }
  },

  bulkExport(format) {
    const ids = [...this._selectedIds];
    if (!ids.length) return;
    this._closeBulkPopovers();
    const qs = ids.map(id => `ids=${id}`).join('&') + `&format=${format}`;
    window.open(`/api/creators/export?${qs}`, '_blank');
  },

  _toggleBulkPopover(name) {
    const allNames = ['priority', 'tag-add', 'tag-remove', 'category', 'export'];
    const target = document.getElementById(`bulk-popover-${name}`);
    const isOpen = target && target.style.display !== 'none';
    allNames.forEach(n => { const el = document.getElementById(`bulk-popover-${n}`); if (el) el.style.display = 'none'; });
    if (target && !isOpen) {
      target.style.display = '';
      if (name === 'tag-add') {
        const chips = document.getElementById('bulk-tag-add-chips');
        if (chips) chips.innerHTML = this.allTags.map(t =>
          `<span class="tag-pill" style="cursor:pointer" onclick="document.getElementById('bulk-new-tag-input').value='${App.escape(t)}'">${App.escape(t)}</span>`
        ).join('');
      }
      if (name === 'tag-remove') {
        const selectedTags = new Set();
        [...this._selectedIds].forEach(id => { const c = this.data.find(x => x.id === id); (c?.tags||[]).forEach(t => selectedTags.add(t)); });
        const chips = document.getElementById('bulk-tag-remove-chips');
        if (chips) chips.innerHTML = [...selectedTags].map(t =>
          `<span class="tag-pill tag-pill-remove" onclick="Creators.bulkRemoveTag('${App.escape(t)}')">${App.escape(t)} ✕</span>`
        ).join('') || '<span style="font-size:12px;color:var(--text3)">No tags on selected creators</span>';
      }
    }
  },

  _closeBulkPopovers() {
    ['priority', 'tag-add', 'tag-remove', 'category', 'export'].forEach(n => {
      const el = document.getElementById(`bulk-popover-${n}`);
      if (el) el.style.display = 'none';
    });
  },

  // ── Modal tag management ──

  async _modalAddTag() {
    if (!this.editingId) return;
    const input = document.getElementById('m-new-tag');
    const tag_name = (input?.value || '').trim();
    if (!tag_name) return;
    try {
      await API.post(`/api/creators/${this.editingId}/tags`, { tag_name });
      const c = this.data.find(x => x.id === this.editingId);
      if (c && !(c.tags||[]).includes(tag_name)) c.tags = [...(c.tags||[]), tag_name];
      if (!this.allTags.includes(tag_name)) this.allTags.push(tag_name);
      if (input) input.value = '';
      const tagsList = document.getElementById('m-tags-list');
      if (tagsList && c) tagsList.innerHTML = (c.tags||[]).map(t =>
        `<span class="tag-pill">${App.escape(t)} <span onclick="Creators._modalRemoveTag(${this.editingId},'${App.escape(t)}')" style="cursor:pointer;opacity:0.6;margin-left:2px">✕</span></span>`
      ).join('');
    } catch(e) { App.toast(e.message, 'error'); }
  },

  async _modalRemoveTag(creatorId, tag_name) {
    try {
      await API.del(`/api/creators/${creatorId}/tags/${encodeURIComponent(tag_name)}`);
      const c = this.data.find(x => x.id === creatorId);
      if (c) c.tags = (c.tags||[]).filter(t => t !== tag_name);
      const tagsList = document.getElementById('m-tags-list');
      if (tagsList && c) tagsList.innerHTML = (c.tags||[]).map(t =>
        `<span class="tag-pill">${App.escape(t)} <span onclick="Creators._modalRemoveTag(${creatorId},'${App.escape(t)}')" style="cursor:pointer;opacity:0.6;margin-left:2px">✕</span></span>`
      ).join('');
    } catch(e) { App.toast(e.message, 'error'); }
  },

  renderList() {
    const el = document.getElementById('creators-list');
    if (!el) return;

    let filtered = this.data;
    if (this.categoryFilter)     filtered = filtered.filter(c => c.category === this.categoryFilter);
    if (this.countryFilter)      filtered = filtered.filter(c => c.country === this.countryFilter);
    if (this.priorityFilter != null) filtered = filtered.filter(c => c.priority === this.priorityFilter);
    if (this.platformFilters.size) {
      const pf = this.platformFilters;
      filtered = filtered.filter(c =>
        (!pf.has('linkedin')  || !!c.linkedin_url) &&
        (!pf.has('twitter')   || !!c.twitter_handle) &&
        (!pf.has('instagram') || !!c.instagram_handle) &&
        (!pf.has('youtube')   || !!c.youtube_channel_id) &&
        (!pf.has('tiktok')    || !!c.tiktok_handle)
      );
    }
    if (this.tagFilters.size) {
      filtered = filtered.filter(c =>
        [...this.tagFilters].every(tag => (c.tags || []).includes(tag))
      );
    }
    if (this.sortBy === 'priority') {
      filtered = [...filtered].sort((a, b) => {
        if (a.priority == null && b.priority == null) return 0;
        if (a.priority == null) return 1;
        if (b.priority == null) return -1;
        return a.priority - b.priority;
      });
    } else if (this.sortBy === 'name') {
      filtered = [...filtered].sort((a, b) => a.name.localeCompare(b.name));
    }

    if (!filtered.length) {
      el.innerHTML = `<div class="empty-state"><div class="empty-icon"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg></div><h3>No creators match these filters</h3><p>Try adjusting or clearing the filters above, or add a new creator to your list.</p><div class="empty-actions"><button class="btn btn-secondary btn-sm" onclick="Creators._resetFilters()">Clear Filters</button><button class="btn btn-primary btn-sm" onclick="Creators.openModal()">+ Add Creator</button></div></div>`;
      this._updateBulkBar();
      this._populateFilterBar();
      return;
    }

    el.innerHTML = filtered.map(c => this.buildRow(c)).join('');
    this._updateBulkBar();
    this._populateFilterBar();
  },

  _updateBulkBar() {
    const bar = document.getElementById('creators-bulk-bar');
    if (!bar) return;
    const count = this._selectedIds.size;
    if (count === 0) {
      bar.style.display = 'none';
    } else {
      bar.style.display = 'flex';
      const label = bar.querySelector('#bulk-bar-count');
      if (label) label.textContent = `${count} selected`;
    }
    const filtered = this.categoryFilter ? this.data.filter(c => c.category === this.categoryFilter) : this.data;
    const allChecked = filtered.length > 0 && filtered.every(c => this._selectedIds.has(c.id));
    const chk = document.getElementById('bulk-select-all');
    if (chk) {
      chk.checked = allChecked;
      chk.indeterminate = !allChecked && count > 0;
    }
  },

  _toggleSelect(id, checked) {
    if (checked) this._selectedIds.add(id); else this._selectedIds.delete(id);
    this._updateBulkBar();
  },

  _toggleSelectAll(checked) {
    const filtered = this.categoryFilter ? this.data.filter(c => c.category === this.categoryFilter) : this.data;
    if (checked) filtered.forEach(c => this._selectedIds.add(c.id));
    else this._selectedIds.clear();
    filtered.forEach(c => {
      const cb = document.querySelector(`.creator-row-cb[data-id="${c.id}"]`);
      if (cb) cb.checked = checked;
    });
    this._updateBulkBar();
  },

  buildRow(c) {
    const platforms = [
      c.linkedin_url ? `<span class="platform-badge platform-li">LI</span>` : '',
      c.twitter_handle ? `<span class="platform-badge platform-tw">TW</span>` : '',
      c.instagram_handle ? `<span class="platform-badge platform-ig">IG</span>` : '',
      c.youtube_channel_id ? `<span class="platform-badge platform-yt">YT</span>` : '',
      c.tiktok_handle ? `<span class="platform-badge platform-tt">TT</span>` : '',
    ].filter(Boolean).join('');

    const initials = c.name.split(' ').map(w => w[0]).join('').substring(0, 2).toUpperCase();
    const fallbackAvatar = `<div class='creator-avatar' style='font-size:13px;font-weight:700;color:var(--accent)'>${initials}</div>`;
    const avatarSrc = c.profile_image_url
      || (c.twitter_handle ? `https://unavatar.io/twitter/${encodeURIComponent(c.twitter_handle)}` : null)
      || (c.instagram_handle ? `https://unavatar.io/instagram/${encodeURIComponent(c.instagram_handle)}` : null);
    const avatar = avatarSrc
      ? `<img src="${App.escape(App.proxyImg(avatarSrc))}" class="creator-avatar" referrerpolicy="no-referrer" onerror="this.outerHTML='${fallbackAvatar.replace(/'/g, "\\'")}">`
      : fallbackAvatar;

    const catBadge = c.category === 'competitor'
      ? `<span class="creator-cat-badge cat-competitor">Competitor</span>`
      : `<span class="creator-cat-badge cat-inspiration">Inspiration</span>`;

    const newBadge = c.new_items_count > 0
      ? `<span style="background:var(--accent);color:#fff;font-size:10px;font-weight:700;padding:1px 6px;border-radius:10px">${c.new_items_count} new</span>`
      : '';

    const maxBadge = c.scrape_max_posts
      ? `<span style="font-size:10px;color:var(--text3);background:var(--bg3);border:1px solid var(--border);border-radius:4px;padding:1px 5px" title="Max posts per fetch">max ${c.scrape_max_posts}</span>`
      : '';

    const priorityBadge = c.priority != null
      ? `<span class="priority-badge priority-${c.priority}" onclick="event.stopPropagation();Creators._inlineEditPriority(${c.id},this)" title="Priority ${c.priority} — click to change">P${c.priority}</span>`
      : '';

    const tagPills = (c.tags || []).map(t => `<span class="tag-pill">${App.escape(t)}</span>`).join('');

    const isChecked = this._selectedIds.has(c.id);

    return `
      <div class="creator-row" onclick="CreatorProfile.open(${c.id})" title="Click to view profile">
        <input type="checkbox" class="creator-row-cb" data-id="${c.id}" ${isChecked ? 'checked' : ''}
          onclick="event.stopPropagation();Creators._toggleSelect(${c.id}, this.checked)"
          style="width:16px;height:16px;cursor:pointer;flex-shrink:0;accent-color:var(--accent)" />
        ${avatar}
        <div class="creator-info" style="min-width:0">
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
            ${priorityBadge}
            <div class="creator-name">${App.escape(c.name)}</div>
            ${catBadge}
            ${newBadge}
          </div>
          <div class="creator-meta" style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:3px">
            ${platforms ? platforms : ''}
            ${c.country ? `<span>${App.escape(c.country)}</span>` : ''}
            <span>${c.total_items_count || 0} posts</span>
            ${c.last_fetched_at ? `<span>· ${App.fmtDate(c.last_fetched_at)}</span>` : ''}
            ${maxBadge}
          </div>
          ${tagPills ? `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px">${tagPills}</div>` : ''}
          ${c.notes ? `<div style="font-size:11px;color:var(--text3);margin-top:3px;font-style:italic">${App.escape(c.notes)}</div>` : ''}
        </div>
        <div class="creator-actions" style="gap:4px">
          <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();Analysis.selectCreator(${c.id});App.goTo('analysis')">Analyze</button>
          <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();Creators.openFetchModal(${c.id})" title="Fetch content">↻</button>
          ${c.linkedin_url ? `<button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();Creators.openImport(${c.id})" title="Import LinkedIn posts">Import</button>` : ''}
          <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();Creators.openModal(${c.id})">Edit</button>
          <button class="btn btn-danger btn-sm" onclick="event.stopPropagation();Creators.delete(${c.id})">Del</button>
        </div>
      </div>
    `;
  },

  openModal(id) {
    const c = id ? this.data.find(x => x.id === id) : null;
    this.editingId = id || null;

    App.openModal(`
      <div class="modal-title">${c ? 'Edit Creator' : '+ Add Creator'}</div>

      ${!c ? `
      <div class="form-group" style="background:var(--bg3);border:1px solid var(--border2);border-radius:8px;padding:12px 14px;margin-bottom:16px">
        <label style="color:var(--accent-light)">Paste profile links to auto-fill — one per line</label>
        <div style="display:flex;gap:8px;margin-top:6px;align-items:flex-start">
          <textarea id="m-link-input" rows="3" placeholder="https://linkedin.com/in/...&#10;https://x.com/...&#10;https://tiktok.com/@..." style="flex:1;resize:vertical;font-size:13px"></textarea>
          <button class="btn btn-primary btn-sm" id="m-link-btn" onclick="Creators._lookupUrl()" style="white-space:nowrap;margin-top:2px">Fill All</button>
        </div>
        <div id="m-link-status" style="font-size:12px;margin-top:6px;color:var(--text3)">Supports LinkedIn, Twitter/X, YouTube, Instagram, TikTok</div>
      </div>
      ` : ''}

      <div class="form-group"><label>Name</label><input type="text" id="m-name" value="${App.escape(c?.name || '')}" /></div>
      <div class="form-group"><label>Country / Region</label><select id="m-country" style="width:100%">
        <option value="">-- Select Country / Region --</option>
        <optgroup label="MENA">
          <option value="Egypt" ${c?.country === 'Egypt' ? 'selected' : ''}>Egypt</option>
          <option value="Saudi Arabia" ${c?.country === 'Saudi Arabia' ? 'selected' : ''}>Saudi Arabia</option>
          <option value="UAE" ${c?.country === 'UAE' ? 'selected' : ''}>UAE</option>
          <option value="Kuwait" ${c?.country === 'Kuwait' ? 'selected' : ''}>Kuwait</option>
          <option value="Qatar" ${c?.country === 'Qatar' ? 'selected' : ''}>Qatar</option>
          <option value="Bahrain" ${c?.country === 'Bahrain' ? 'selected' : ''}>Bahrain</option>
          <option value="Oman" ${c?.country === 'Oman' ? 'selected' : ''}>Oman</option>
          <option value="Jordan" ${c?.country === 'Jordan' ? 'selected' : ''}>Jordan</option>
          <option value="Lebanon" ${c?.country === 'Lebanon' ? 'selected' : ''}>Lebanon</option>
          <option value="Morocco" ${c?.country === 'Morocco' ? 'selected' : ''}>Morocco</option>
          <option value="Tunisia" ${c?.country === 'Tunisia' ? 'selected' : ''}>Tunisia</option>
          <option value="Algeria" ${c?.country === 'Algeria' ? 'selected' : ''}>Algeria</option>
          <option value="Iraq" ${c?.country === 'Iraq' ? 'selected' : ''}>Iraq</option>
          <option value="Libya" ${c?.country === 'Libya' ? 'selected' : ''}>Libya</option>
          <option value="Syria" ${c?.country === 'Syria' ? 'selected' : ''}>Syria</option>
          <option value="Yemen" ${c?.country === 'Yemen' ? 'selected' : ''}>Yemen</option>
          <option value="Palestine" ${c?.country === 'Palestine' ? 'selected' : ''}>Palestine</option>
          <option value="Sudan" ${c?.country === 'Sudan' ? 'selected' : ''}>Sudan</option>
          <option value="Turkey" ${c?.country === 'Turkey' ? 'selected' : ''}>Turkey</option>
        </optgroup>
        <optgroup label="Americas">
          <option value="USA" ${c?.country === 'USA' ? 'selected' : ''}>USA</option>
          <option value="Canada" ${c?.country === 'Canada' ? 'selected' : ''}>Canada</option>
        </optgroup>
        <optgroup label="Europe">
          <option value="UK" ${c?.country === 'UK' ? 'selected' : ''}>UK</option>
          <option value="Germany" ${c?.country === 'Germany' ? 'selected' : ''}>Germany</option>
          <option value="France" ${c?.country === 'France' ? 'selected' : ''}>France</option>
          <option value="Netherlands" ${c?.country === 'Netherlands' ? 'selected' : ''}>Netherlands</option>
          <option value="Spain" ${c?.country === 'Spain' ? 'selected' : ''}>Spain</option>
          <option value="Italy" ${c?.country === 'Italy' ? 'selected' : ''}>Italy</option>
          <option value="Sweden" ${c?.country === 'Sweden' ? 'selected' : ''}>Sweden</option>
          <option value="Norway" ${c?.country === 'Norway' ? 'selected' : ''}>Norway</option>
          <option value="Denmark" ${c?.country === 'Denmark' ? 'selected' : ''}>Denmark</option>
          <option value="Switzerland" ${c?.country === 'Switzerland' ? 'selected' : ''}>Switzerland</option>
          <option value="Poland" ${c?.country === 'Poland' ? 'selected' : ''}>Poland</option>
          <option value="Belgium" ${c?.country === 'Belgium' ? 'selected' : ''}>Belgium</option>
          <option value="Portugal" ${c?.country === 'Portugal' ? 'selected' : ''}>Portugal</option>
          <option value="Austria" ${c?.country === 'Austria' ? 'selected' : ''}>Austria</option>
        </optgroup>
        <optgroup label="Global">
          <option value="Global" ${c?.country === 'Global' ? 'selected' : ''}>Global</option>
        </optgroup>
      </select></div>
      <div class="form-group">
        <label>Category</label>
        <div class="toggle-group" id="m-category-toggle">
          <div class="toggle-option ${!c || c.category === 'competitor' ? 'active' : ''}" data-val="competitor">Competitor</div>
          <div class="toggle-option ${c?.category === 'inspiration' ? 'active' : ''}" data-val="inspiration">Inspiration</div>
        </div>
      </div>
      <div class="form-group"><label>LinkedIn URL</label><input type="url" id="m-linkedin" value="${App.escape(c?.linkedin_url || '')}" placeholder="https://linkedin.com/in/..." /></div>
      <div class="form-group"><label>Twitter Handle</label><input type="text" id="m-twitter" value="${App.escape(c?.twitter_handle || '')}" placeholder="@handle" /></div>
      <div class="form-group"><label>Instagram Handle</label><input type="text" id="m-instagram" value="${App.escape(c?.instagram_handle || '')}" placeholder="@handle" /></div>
      <div class="form-group"><label>YouTube Channel ID</label><input type="text" id="m-youtube" value="${App.escape(c?.youtube_channel_id || '')}" placeholder="UCxxx..." /></div>
      <div class="form-group"><label>TikTok Handle</label><input type="text" id="m-tiktok" value="${App.escape(c?.tiktok_handle || '')}" placeholder="@handle" /></div>
      <div class="form-group"><label>Notes</label><textarea id="m-notes" rows="2" placeholder="Posts every Sunday, targets Egypt market...">${App.escape(c?.notes || '')}</textarea></div>
      <div class="form-group">
        <label>Tags</label>
        <div id="m-tags-list" style="display:flex;gap:4px;flex-wrap:wrap;min-height:24px;margin-bottom:6px">${(c?.tags || []).map(t => `<span class="tag-pill">${App.escape(t)} <span onclick="Creators._modalRemoveTag(${c?.id || 0},'${App.escape(t)}')" style="cursor:pointer;opacity:0.6;margin-left:2px">✕</span></span>`).join('')}</div>
        <div style="display:flex;gap:6px">
          <input type="text" id="m-new-tag" placeholder="Add tag..." style="flex:1;font-size:13px" list="m-tag-suggestions" />
          <datalist id="m-tag-suggestions">${this.allTags.map(t => `<option value="${App.escape(t)}">`).join('')}</datalist>
          <button class="btn btn-ghost btn-sm" onclick="Creators._modalAddTag()">+ Add</button>
        </div>
      </div>
      <div class="form-group"><label>Rank</label><input type="text" id="m-rank" value="${c?.rank ?? 999}" style="width:80px" /></div>
      <div class="form-group">
        <label>Max posts to scrape <span style="color:var(--text3);font-weight:400">(blank = global setting)</span></label>
        <input type="number" id="m-scrape-max" value="${c?.scrape_max_posts ?? ''}" min="1" max="200" style="width:100px" placeholder="global" />
      </div>

      ${!c ? `
      <div class="form-group" style="border-top:1px solid var(--border);padding-top:12px;margin-top:4px">
        <label>Initial scrape limit <span style="color:var(--text3);font-weight:400">(for first fetch)</span></label>
        <div class="toggle-group" id="m-scrape-mode-toggle" style="margin-bottom:8px">
          <div class="toggle-option active" data-val="count">Number of posts</div>
          <div class="toggle-option" data-val="date">From date</div>
        </div>
        <div id="m-scrape-count-row">
          <input type="number" id="m-scrape-initial-max" placeholder="e.g. 30" min="1" max="500" style="width:120px" />
        </div>
        <div id="m-scrape-date-row" style="display:none">
          <input type="date" id="m-scrape-from-date" />
        </div>
      </div>
      ` : ''}
      <div class="form-group">
        <label>LinkedIn Actor <span style="color:var(--text3);font-weight:400">(blank = global setting)</span></label>
        <select id="m-li-actor-select" onchange="Creators._pickActor('li', this.value)" style="margin-bottom:6px">
          <option value="">— use global setting —</option>
          <option value="apify/linkedin-profile-scraper">apify/linkedin-profile-scraper (official)</option>
          <option value="2SyF0bVxmgGr8IVCZ">2SyF0bVxmgGr8IVCZ (profile v2)</option>
          <option value="bebity/linkedin-premium-profile-scraper">bebity/linkedin-premium-profile-scraper</option>
          <option value="custom">Custom ID...</option>
        </select>
        <input type="text" id="m-li-actor" value="${App.escape(c?.scrape_linkedin_actor || '')}" placeholder="apify/actor-id or hash" />
      </div>
      <div class="form-group">
        <label>Twitter Actor <span style="color:var(--text3);font-weight:400">(blank = global setting)</span></label>
        <select id="m-tw-actor-select" onchange="Creators._pickActor('tw', this.value)" style="margin-bottom:6px">
          <option value="">— use global setting —</option>
          <option value="apidojo/twitter-user-scraper">apidojo/twitter-user-scraper (user profile)</option>
          <option value="apidojo/tweet-scraper">apidojo/tweet-scraper (search/keyword)</option>
          <option value="apidojo/twitter-scraper-lite">apidojo/twitter-scraper-lite (lightweight)</option>
          <option value="epctex/twitter-profile-scraper">epctex/twitter-profile-scraper</option>
          <option value="u6ppkMWAx2E2MpEuF">u6ppkMWAx2E2MpEuF (Twitter v1)</option>
          <option value="custom">Custom ID...</option>
        </select>
        <input type="text" id="m-tw-actor" value="${App.escape(c?.scrape_twitter_actor || '')}" placeholder="apify/actor-id or hash" />
      </div>
      <div class="form-group">
        <label>Include Replies <span style="color:var(--text3);font-weight:400">(per-creator override)</span></label>
        <div class="toggle-group" id="m-replies-toggle">
          <div class="toggle-option ${c?.scrape_include_replies === true ? 'active' : ''}" data-val="true">Yes</div>
          <div class="toggle-option ${c?.scrape_include_replies === false ? 'active' : ''}" data-val="false">No</div>
          <div class="toggle-option ${c?.scrape_include_replies == null ? 'active' : ''}" data-val="global">Global</div>
        </div>
      </div>
      <div class="form-group">
        <label>Include Retweets <span style="color:var(--text3);font-weight:400">(per-creator override)</span></label>
        <div class="toggle-group" id="m-retweets-toggle">
          <div class="toggle-option ${c?.scrape_include_retweets === true ? 'active' : ''}" data-val="true">Yes</div>
          <div class="toggle-option ${c?.scrape_include_retweets === false ? 'active' : ''}" data-val="false">No</div>
          <div class="toggle-option ${c?.scrape_include_retweets == null ? 'active' : ''}" data-val="global">Global</div>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="Creators.save()">Save${!c ? ' & Fetch Posts' : ''}</button>
      </div>
    `);

    document.querySelectorAll('#m-category-toggle .toggle-option').forEach(opt => {
      opt.onclick = () => {
        document.querySelectorAll('#m-category-toggle .toggle-option').forEach(o => o.classList.remove('active'));
        opt.classList.add('active');
      };
    });

    // Ctrl/Cmd+Enter in the link textarea triggers Fill All
    const linkInput = document.getElementById('m-link-input');
    if (linkInput) {
      linkInput.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); Creators._lookupUrl(); } });
    }

    // Pre-select actor dropdowns for existing creator
    if (c) {
      this._preselectActor('m-li-actor-select', 'm-li-actor', c.scrape_linkedin_actor);
      this._preselectActor('m-tw-actor-select', 'm-tw-actor', c.scrape_twitter_actor);
    }

    // Wire 3-way toggles (replies, retweets)
    ['m-replies-toggle', 'm-retweets-toggle'].forEach(groupId => {
      document.querySelectorAll(`#${groupId} .toggle-option`).forEach(opt => {
        opt.onclick = () => {
          document.querySelectorAll(`#${groupId} .toggle-option`).forEach(o => o.classList.remove('active'));
          opt.classList.add('active');
        };
      });
    });

    // Wire scrape mode toggle (count vs date) — only present when adding a new creator
    document.querySelectorAll('#m-scrape-mode-toggle .toggle-option').forEach(opt => {
      opt.onclick = () => {
        document.querySelectorAll('#m-scrape-mode-toggle .toggle-option').forEach(o => o.classList.remove('active'));
        opt.classList.add('active');
        const isDate = opt.dataset.val === 'date';
        const countRow = document.getElementById('m-scrape-count-row');
        const dateRow = document.getElementById('m-scrape-date-row');
        if (countRow) countRow.style.display = isDate ? 'none' : '';
        if (dateRow) dateRow.style.display = isDate ? '' : 'none';
      };
    });
  },

  async _lookupUrl() {
    const input = document.getElementById('m-link-input');
    const btn = document.getElementById('m-link-btn');
    const status = document.getElementById('m-link-status');
    const raw = input?.value?.trim();
    if (!raw) return;

    const urls = raw.split(/[\n\r]+/).map(u => u.trim()).filter(Boolean);
    btn.disabled = true;
    btn.textContent = '...';
    if (status) { status.style.color = 'var(--text3)'; status.textContent = `Checking ${urls.length} link${urls.length > 1 ? 's' : ''}...`; }

    const LABELS = { youtube: 'YouTube', linkedin: 'LinkedIn', twitter: 'Twitter/X', instagram: 'Instagram', tiktok: 'TikTok' };
    const detected = [];
    for (const url of urls) {
      try {
        const info = await API.post('/api/creators/lookup', { url });
        if (info.name && !document.getElementById('m-name').value) document.getElementById('m-name').value = info.name;
        if (info.country && !document.getElementById('m-country').value) document.getElementById('m-country').value = info.country;
        if (info.linkedin_url) document.getElementById('m-linkedin').value = info.linkedin_url;
        if (info.twitter_handle) document.getElementById('m-twitter').value = '@' + info.twitter_handle;
        if (info.instagram_handle) document.getElementById('m-instagram').value = '@' + info.instagram_handle;
        if (info.youtube_channel_id) document.getElementById('m-youtube').value = info.youtube_channel_id;
        if (info.tiktok_handle) document.getElementById('m-tiktok').value = '@' + info.tiktok_handle;
        if (info.platform) detected.push(LABELS[info.platform] || info.platform);
      } catch (e) {
        // skip unrecognised URLs silently
      }
    }

    btn.disabled = false;
    btn.textContent = 'Fill All';
    if (status) {
      if (detected.length) {
        status.style.color = 'var(--green)';
        status.textContent = `✓ Detected: ${detected.join(', ')}`;
      } else {
        status.style.color = 'var(--red)';
        status.textContent = 'Could not detect any platform from the pasted links';
      }
    }
  },

  _readTriToggle(groupId) {
    const active = document.querySelector(`#${groupId} .toggle-option.active`)?.dataset.val;
    if (active === 'true') return true;
    if (active === 'false') return false;
    return null; // 'global' = use global setting
  },

  _pickActor(platform, val) {
    const inputId = platform === 'li' ? 'm-li-actor' : 'm-tw-actor';
    const input = document.getElementById(inputId);
    if (!input) return;
    if (val !== 'custom' && val !== '') input.value = val;
    if (val === '') input.value = '';
    input.focus();
  },

  _preselectActor(selectId, inputId, currentVal) {
    const sel = document.getElementById(selectId);
    const input = document.getElementById(inputId);
    if (!sel || !input || !currentVal) return;
    const match = Array.from(sel.options).find(o => o.value === currentVal);
    sel.value = match ? currentVal : 'custom';
  },

  async save() {
    const name = document.getElementById('m-name')?.value?.trim();
    if (!name) { App.toast('Name is required', 'error'); return; }

    const category = document.querySelector('#m-category-toggle .toggle-option.active')?.dataset.val || 'competitor';
    const c = this.editingId ? this.data.find(x => x.id === this.editingId) : null;
    const data = {
      name,
      country: document.getElementById('m-country')?.value?.trim() || null,
      category,
      rank: parseInt(document.getElementById('m-rank')?.value) || 999,
      priority: c?.priority ?? null,
      linkedin_url: document.getElementById('m-linkedin')?.value?.trim() || null,
      twitter_handle: document.getElementById('m-twitter')?.value?.trim().replace('@', '') || null,
      instagram_handle: document.getElementById('m-instagram')?.value?.trim().replace('@', '') || null,
      youtube_channel_id: document.getElementById('m-youtube')?.value?.trim() || null,
      tiktok_handle: document.getElementById('m-tiktok')?.value?.trim().replace('@', '') || null,
      notes: document.getElementById('m-notes')?.value?.trim() || null,
      scrape_max_posts: parseInt(document.getElementById('m-scrape-max')?.value) || null,
      scrape_linkedin_actor: document.getElementById('m-li-actor')?.value?.trim() || null,
      scrape_twitter_actor: document.getElementById('m-tw-actor')?.value?.trim() || null,
      scrape_include_replies: Creators._readTriToggle('m-replies-toggle'),
      scrape_include_retweets: Creators._readTriToggle('m-retweets-toggle'),
    };

    try {
      let savedId;
      if (this.editingId) {
        await API.put(`/api/creators/${this.editingId}`, data);
        savedId = this.editingId;
      } else {
        const created = await API.post('/api/creators', data);
        savedId = created.id;
      }
      App.closeModal();
      App.toast(this.editingId ? 'Creator updated!' : 'Creator added!', 'success');
      await this.load();

      if (savedId) {
        this.openFetchModal(savedId);
      }
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  async delete(id) {
    if (!confirm('Delete this creator and all their content?')) return;
    try {
      await API.del(`/api/creators/${id}`);
      App.toast('Deleted', 'success');
      this.load();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  async openFetchModal(id) {
    let creator;
    try {
      creator = await API.get(`/api/creators/${id}`);
    } catch (e) {
      App.toast(e.message, 'error');
      return;
    }

    const hasPlatforms = {
      youtube: !!creator.youtube_channel_id,
      twitter: !!creator.twitter_handle,
      linkedin: !!creator.linkedin_url,
      instagram: !!creator.instagram_handle,
      tiktok: !!creator.tiktok_handle,
    };
    const platformLabels = { youtube: 'YouTube', twitter: 'Twitter/X', linkedin: 'LinkedIn', instagram: 'Instagram', tiktok: 'TikTok' };
    const platformsHtml = Object.entries(hasPlatforms)
      .filter(([, has]) => has)
      .map(([key, ]) => `
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer;user-select:none">
          <input type="checkbox" id="fp-plat-${key}" checked style="cursor:pointer" />
          ${platformLabels[key]}
        </label>`)
      .join('');

    const oldestDate = creator.oldest_post_date ? creator.oldest_post_date.split('T')[0] : null;
    const newestDate = creator.newest_post_date ? creator.newest_post_date.split('T')[0] : null;
    const olderHint = oldestDate
      ? `<span style="font-size:11px;color:var(--text3)">Will fetch posts before ${oldestDate}</span>`
      : `<span style="font-size:11px;color:var(--text3)">No posts stored yet — fetches from scratch</span>`;

    App.openModal(`
      <div class="modal-title">↻ Fetch — ${App.escape(creator.name)}</div>

      ${platformsHtml ? `
      <div class="form-group">
        <label>Platforms</label>
        <div style="display:flex;flex-wrap:wrap;gap:12px;margin-top:4px">${platformsHtml}</div>
      </div>` : ''}

      <div class="form-group">
        <label>Mode</label>
        <div class="toggle-group" id="fp-mode-toggle" style="margin-top:4px">
          <div class="toggle-option active" data-val="newer">Get Newer Posts</div>
          <div class="toggle-option" data-val="range">Custom Date Range</div>
          <div class="toggle-option" data-val="older">Older Posts</div>
        </div>
      </div>

      <div id="fp-range-row" style="display:none">
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
          <div class="form-group" style="margin:0;flex:1;min-width:120px">
            <label>From</label>
            <input type="date" id="fp-from-date" style="width:100%" />
          </div>
          <div class="form-group" style="margin:0;flex:1;min-width:120px">
            <label>To</label>
            <input type="date" id="fp-to-date" style="width:100%" />
          </div>
        </div>
      </div>

      <div id="fp-older-hint" style="display:none;margin-bottom:12px">${olderHint}</div>

      <div class="form-group">
        <label>Max posts per platform</label>
        <input type="number" id="fp-max-posts" value="50" min="1" max="500" style="width:100px" />
      </div>

      <div class="modal-footer">
        <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="Creators._doFetchModal(${id}, ${JSON.stringify(oldestDate)})">Fetch Now</button>
      </div>
    `);

    // Wire mode toggle
    document.querySelectorAll('#fp-mode-toggle .toggle-option').forEach(opt => {
      opt.onclick = () => {
        document.querySelectorAll('#fp-mode-toggle .toggle-option').forEach(o => o.classList.remove('active'));
        opt.classList.add('active');
        const mode = opt.dataset.val;
        const rangeRow = document.getElementById('fp-range-row');
        const olderHintEl = document.getElementById('fp-older-hint');
        if (rangeRow) rangeRow.style.display = mode === 'range' ? '' : 'none';
        if (olderHintEl) olderHintEl.style.display = mode === 'older' ? '' : 'none';
      };
    });
  },

  _doFetchModal(id, oldestDate) {
    const mode = document.querySelector('#fp-mode-toggle .toggle-option.active')?.dataset.val || 'newer';
    const maxPosts = parseInt(document.getElementById('fp-max-posts')?.value) || 50;

    // Collect selected platforms
    const platformKeys = ['youtube', 'twitter', 'linkedin', 'instagram', 'tiktok'];
    const selectedPlatforms = platformKeys.filter(key => {
      const cb = document.getElementById(`fp-plat-${key}`);
      return cb && cb.checked;
    });

    const params = { max_posts: maxPosts };

    if (selectedPlatforms.length > 0) {
      params.platforms = selectedPlatforms;
    }

    if (mode === 'newer') {
      params.ignore_last_fetched = false;
    } else if (mode === 'range') {
      params.ignore_last_fetched = true;
      const from = document.getElementById('fp-from-date')?.value;
      const to = document.getElementById('fp-to-date')?.value;
      if (from) params.from_date = from;
      if (to) params.to_date = to;
    } else if (mode === 'older') {
      params.ignore_last_fetched = true;
      // Fetch posts before the oldest stored post
      if (oldestDate) {
        // Subtract one day so we don't re-fetch the boundary post
        const d = new Date(oldestDate);
        d.setDate(d.getDate() - 1);
        params.to_date = d.toISOString().split('T')[0];
      }
    }

    App.closeModal();
    this.fetchOne(id, params);
  },

  async fetchOne(id, extraParams = {}) {
    App.toast('Fetching content...', '');
    try {
      const result = await API.post(`/api/fetch/creator/${id}`, extraParams);
      App.toast(`Done! ${result.new_items} new posts.`, 'success');
      if (result.errors?.length) {
        const first = String(result.errors[0] || '').slice(0, 120);
        const extra = result.errors.length > 1 ? ` (+${result.errors.length - 1} more)` : '';
        App.toast(`Posts fetch had errors (creator was saved). ${first}${extra} — Check Settings → API keys.`, 'error');
      }
      this.load();
      App.updateBadge();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  async viewPosts(id) {
    const creator = this.data.find(c => c.id === id);
    if (!creator) return;

    App.openModal(`
      <div class="modal-title">📋 ${App.escape(creator.name)}'s Posts</div>
      <div style="font-size:12px;color:var(--text3);margin-bottom:12px">${creator.total_items_count || 0} posts stored · <a href="#" onclick="event.preventDefault();App.closeModal();Creators.openFetchModal(${id})" style="color:var(--accent-light)">↻ Fetch</a></div>
      <div id="creator-posts-content">
        <div class="loading-overlay"><div class="spinner"></div> Loading...</div>
      </div>
    `);

    try {
      const result = await API.get(`/api/creators/${id}/posts?limit=25`);
      const el = document.getElementById('creator-posts-content');
      if (!el) return;

      if (!result.items.length) {
        el.innerHTML = '<div class="empty-state"><div class="empty-icon">📭</div><h3>No posts yet</h3><p>Click "↻ Fetch new" above to import this creator\'s content.</p></div>';
        return;
      }

      el.innerHTML = result.items.map(item => {
        const dir = App.detectArabic(item.body || item.title || '') ? 'rtl' : 'ltr';
        const platformClass = { linkedin: 'platform-li', twitter: 'platform-tw', youtube: 'platform-yt', instagram: 'platform-ig', blog: 'platform-blog' }[item.platform] || '';
        const platformLabel = { linkedin: 'LinkedIn', twitter: 'Twitter', youtube: 'YouTube', instagram: 'Instagram', blog: 'Blog' }[item.platform] || item.platform;
        const stats = [
          item.likes ? `♥ ${item.likes}` : '',
          item.comments_count ? `💬 ${item.comments_count}` : '',
          item.shares ? `↗ ${item.shares}` : '',
        ].filter(Boolean).join('  ');

        return `
          <div class="feed-item" style="margin-bottom:10px">
            <div class="feed-item-header">
              <span class="platform-badge ${platformClass}">${platformLabel}</span>
              <span>${item.published_at ? App.fmtDate(item.published_at) : 'Unknown date'}</span>
              ${stats ? `<span style="margin-left:auto;color:var(--text3)">${stats}</span>` : ''}
            </div>
            ${item.title ? `<div style="font-weight:600;font-size:13px;margin-bottom:4px">${App.escape(item.title)}</div>` : ''}
            ${item.body ? `<div style="font-size:13px;line-height:1.6;color:var(--text2);max-height:90px;overflow:hidden" dir="${dir}">${App.escape(item.body.slice(0, 300))}${item.body.length > 300 ? '…' : ''}</div>` : ''}
            ${item.url ? `<a href="${App.escape(item.url)}" target="_blank" style="font-size:12px;color:var(--accent-light);display:inline-block;margin-top:6px">View original ↗</a>` : ''}
          </div>
        `;
      }).join('') + (result.total > 25 ? `<div style="font-size:12px;color:var(--text3);text-align:center;padding:8px 0">${result.total} total posts · showing latest 25</div>` : '');
    } catch (e) {
      const el = document.getElementById('creator-posts-content');
      if (el) el.innerHTML = `<div style="color:var(--red);padding:12px">${App.escape(e.message)}</div>`;
    }
  },

  openImport(id) {
    const creator = this.data.find(c => c.id === id);
    if (!creator) return;
    App.openModal(`
      <div class="modal-title">⬆ Import LinkedIn Posts — ${App.escape(creator.name)}</div>
      <p style="font-size:13px;color:var(--text2);margin-bottom:12px">
        Export posts from <strong>BeReach</strong> or <strong>Synscribe</strong>, then paste the JSON here.
        Also accepts any JSON array with fields like <code>text</code>, <code>date</code>, <code>url</code>, <code>likes</code>.
      </p>
      <div class="form-group">
        <label>Paste JSON export</label>
        <textarea id="import-json" rows="10" placeholder='[{"text":"Post content...","date":"2025-01-15","likes":42},...]' style="font-family:monospace;font-size:12px"></textarea>
      </div>
      <div id="import-status" style="font-size:12px;color:var(--text3);min-height:18px"></div>
      <div class="modal-footer">
        <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="Creators._doImport(${id})">Import Posts</button>
      </div>
    `);
  },

  openBulkModal() {
    App.openModal(`
      <div class="modal-title">+ Bulk Add Creators</div>
      <p style="font-size:13px;color:var(--text2);margin-bottom:14px">Paste one profile URL per line — each line becomes a separate creator.</p>
      <div class="form-group">
        <label>Profile URLs <span style="color:var(--text3);font-weight:400">(one per line)</span></label>
        <textarea id="bulk-urls" rows="7" placeholder="https://linkedin.com/in/satyanadella&#10;https://x.com/billgates&#10;https://youtube.com/@mkbhd" style="resize:vertical;font-size:13px"></textarea>
      </div>
      <div class="form-group">
        <label>Category <span style="color:var(--text3);font-weight:400">(applied to all)</span></label>
        <div class="toggle-group" id="bulk-cat-toggle">
          <div class="toggle-option active" data-val="competitor">Competitor</div>
          <div class="toggle-option" data-val="inspiration">Inspiration</div>
        </div>
      </div>
      <div id="bulk-preview"></div>
      <div class="modal-footer">
        <button class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
        <button class="btn btn-primary" id="bulk-action-btn" onclick="Creators._bulkLookup()">Lookup All</button>
      </div>
    `);

    document.querySelectorAll('#bulk-cat-toggle .toggle-option').forEach(opt => {
      opt.onclick = () => {
        document.querySelectorAll('#bulk-cat-toggle .toggle-option').forEach(o => o.classList.remove('active'));
        opt.classList.add('active');
      };
    });
  },

  _renderBulkPreview() {
    const preview = document.getElementById('bulk-preview');
    const btn = document.getElementById('bulk-action-btn');
    if (!preview || !Creators._bulkPending) return;

    const items = Creators._bulkPending;
    const valid = items.filter(c => c && !c.failed && c.platform);
    const skipped = items.filter(c => !c || c.failed || !c.platform).length;

    preview.innerHTML = `
      <div style="border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-bottom:6px;max-height:220px;overflow-y:auto">
        ${items.map((c, i) => {
          if (!c) return '';
          const ok = !c.failed && c.platform;
          const platforms = [
            c.linkedin_url ? '<span class="platform-badge platform-li">LI</span>' : '',
            c.twitter_handle ? '<span class="platform-badge platform-tw">TW</span>' : '',
            c.instagram_handle ? '<span class="platform-badge platform-ig">IG</span>' : '',
            c.youtube_channel_id ? '<span class="platform-badge platform-yt">YT</span>' : '',
            c.tiktok_handle ? '<span class="platform-badge platform-tt">TT</span>' : '',
          ].filter(Boolean).join('');
          const displayName = c.name
            || (c.linkedin_url ? c.linkedin_url.split('/in/')[1]?.replace(/\/$/, '') : null)
            || c.twitter_handle || c.tiktok_handle || c.instagram_handle || c.youtube_channel_id || c.url;
          return `
            <div style="display:flex;align-items:center;gap:10px;padding:8px 12px;border-bottom:1px solid var(--border);font-size:13px">
              <span style="color:${ok ? 'var(--green)' : 'var(--red)'}">✓</span>
              <div style="flex:1;min-width:0">
                <div style="font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${App.escape(displayName || '?')}</div>
                <div style="margin-top:2px">${ok ? platforms || '<span style="color:var(--text3);font-size:11px">No platform detected</span>' : '<span style="color:var(--red);font-size:11px">Not recognised — will be skipped</span>'}</div>
              </div>
              <button class="btn btn-ghost btn-sm" onclick="Creators._bulkRemove(${i})" style="padding:2px 6px;font-size:11px">✕</button>
            </div>
          `;
        }).join('')}
      </div>
      ${skipped ? `<div style="font-size:12px;color:var(--text3);margin-bottom:4px">${skipped} not recognised — will be skipped.</div>` : ''}
    `;

    if (btn) {
      if (valid.length === 0) {
        btn.textContent = 'No valid creators';
        btn.disabled = true;
        btn.onclick = null;
      } else {
        btn.textContent = `Add ${valid.length} Creator${valid.length !== 1 ? 's' : ''}`;
        btn.disabled = false;
        btn.onclick = () => Creators._saveBulk();
      }
    }
  },

  _bulkRemove(index) {
    if (!Creators._bulkPending) return;
    Creators._bulkPending[index] = null;
    Creators._renderBulkPreview();
  },

  async _bulkLookup() {
    const raw = document.getElementById('bulk-urls')?.value?.trim();
    if (!raw) { App.toast('Paste some URLs first', 'error'); return; }

    const urls = raw.split(/[\n\r]+/).map(u => u.trim()).filter(Boolean);
    if (!urls.length) return;

    const btn = document.getElementById('bulk-action-btn');
    btn.disabled = true;
    btn.textContent = `Looking up ${urls.length}…`;
    btn.onclick = null;

    const settled = await Promise.allSettled(
      urls.map(url => API.post('/api/creators/lookup', { url }).then(info => ({ url, ...info })))
    );

    Creators._bulkPending = settled.map((r, i) =>
      r.status === 'fulfilled' ? r.value : { url: urls[i], failed: true }
    );

    btn.disabled = false;
    Creators._renderBulkPreview();
  },

  async _saveBulk() {
    const category = document.querySelector('#bulk-cat-toggle .toggle-option.active')?.dataset.val || 'competitor';
    const toCreate = (Creators._bulkPending || []).filter(c => c && !c.failed && c.platform);
    if (!toCreate.length) return;

    const btn = document.getElementById('bulk-action-btn');
    btn.disabled = true;
    btn.textContent = 'Adding…';

    const createdIds = [];
    let added = 0, failed = 0;
    for (const c of toCreate) {
      try {
        const payload = {
          name: c.name || c.twitter_handle || c.tiktok_handle || c.instagram_handle || c.youtube_channel_id || c.url,
          category,
          country: c.country || null,
          profile_image_url: c.profile_image_url || null,
          linkedin_url: c.linkedin_url || null,
          twitter_handle: c.twitter_handle ? c.twitter_handle.replace('@', '') : null,
          instagram_handle: c.instagram_handle ? c.instagram_handle.replace('@', '') : null,
          youtube_channel_id: c.youtube_channel_id || null,
          tiktok_handle: c.tiktok_handle ? c.tiktok_handle.replace('@', '') : null,
          rank: 999,
        };
        const created = await API.post('/api/creators', payload);
        createdIds.push(created.id);
        added++;
      } catch {
        failed++;
      }
    }

    Creators._bulkPending = null;
    App.closeModal();
    App.toast(`Added ${added} creator${added !== 1 ? 's' : ''}${failed ? `, ${failed} failed` : ''}. Fetching posts sequentially…`, 'success');
    await this.load();

    if (createdIds.length) {
      API.post('/api/fetch/bulk', { creator_ids: createdIds })
        .then(result => {
          App.toast(`Fetch done — ${result.total_new} new posts across ${createdIds.length} creator${createdIds.length !== 1 ? 's' : ''}.`, 'success');
          Creators.load();
          App.updateBadge();
        })
        .catch(() => {});
    }
  },

  async _doImport(id) {
    const raw = document.getElementById('import-json')?.value?.trim();
    const status = document.getElementById('import-status');
    if (!raw) { if (status) { status.style.color = 'var(--red)'; status.textContent = 'Paste JSON first.'; } return; }

    let posts;
    try {
      const parsed = JSON.parse(raw);
      posts = Array.isArray(parsed) ? parsed : (parsed.posts || parsed.data || parsed.items || [parsed]);
    } catch {
      if (status) { status.style.color = 'var(--red)'; status.textContent = 'Invalid JSON — check the format.'; }
      return;
    }

    if (status) { status.style.color = 'var(--text3)'; status.textContent = `Importing ${posts.length} posts...`; }
    try {
      const result = await API.post(`/api/creators/${id}/import-posts`, { posts });
      App.closeModal();
      App.toast(`Imported ${result.imported} posts (${result.skipped} duplicates skipped).`, 'success');
      this.load();
    } catch (e) {
      if (status) { status.style.color = 'var(--red)'; status.textContent = e.message; }
    }
  }
};
