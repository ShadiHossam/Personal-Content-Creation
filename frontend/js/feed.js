const Feed = {
  offset: 0,
  limit: 20,
  filter: { type: null, platform: null, category: null, saved: null, tag: null, from_date: null, to_date: null },
  items: [],

  async load() {
    this.offset = 0;
    this.items = [];
    this.render();
    this.bindFilters();
    await Promise.all([this.populateRefreshDropdown(), this.loadWebsiteTags()]);
  },

  bindFilters() {
    // Type filter (All / Creators / Websites)
    document.querySelectorAll('#feed-type-filters .filter-chip').forEach(chip => {
      chip.onclick = () => {
        document.querySelectorAll('#feed-type-filters .filter-chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        this.filter.type = chip.dataset.type || null;
        // Reset sub-filters when switching type
        this.filter = { type: this.filter.type, platform: null, category: null, saved: null, tag: null, from_date: this.filter.from_date, to_date: this.filter.to_date };
        document.querySelectorAll('#feed-filters .filter-chip').forEach(c => c.classList.remove('active'));
        const allChip = document.querySelector('#feed-filters .filter-chip[data-filter=""]');
        if (allChip) allChip.classList.add('active');
        document.querySelectorAll('#feed-website-filters .filter-chip').forEach(c => c.classList.remove('active'));
        const allTagChip = document.querySelector('#feed-website-filters .filter-chip[data-tag=""]');
        if (allTagChip) allTagChip.classList.add('active');

        // Show creator sub-filters only when viewing creators only
        const subBar = document.getElementById('feed-filters');
        if (subBar) subBar.style.display = this.filter.type === 'creator' ? '' : 'none';
        // Show tag filter bar when viewing websites or all
        const tagBar = document.getElementById('feed-website-filters');
        if (tagBar) tagBar.style.display = this.filter.type === 'creator' ? 'none' : '';

        this.offset = 0;
        this.items = [];
        this.render();
      };
    });

    // Sub-filters (platform / category / saved) — only applies to creator content
    document.querySelectorAll('#feed-filters .filter-chip').forEach(chip => {
      chip.onclick = () => {
        document.querySelectorAll('#feed-filters .filter-chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        const f = chip.dataset.filter || '';
        this.filter.platform = null;
        this.filter.category = null;
        this.filter.saved = null;
        if (f.startsWith('platform:')) this.filter.platform = f.split(':')[1];
        if (f.startsWith('category:')) this.filter.category = f.split(':')[1];
        if (f === 'saved:true') this.filter.saved = true;
        this.offset = 0;
        this.items = [];
        this.render();
      };
    });

    // Date range filters
    const fromEl = document.getElementById('feed-from-date');
    const toEl = document.getElementById('feed-to-date');
    if (fromEl) {
      fromEl.addEventListener('change', () => {
        this.filter.from_date = fromEl.value || null;
        this.offset = 0;
        this.items = [];
        this.render();
      });
    }
    if (toEl) {
      toEl.addEventListener('change', () => {
        this.filter.to_date = toEl.value || null;
        this.offset = 0;
        this.items = [];
        this.render();
      });
    }

    // Initial visibility of sub-filter bars
    const subBar = document.getElementById('feed-filters');
    if (subBar) subBar.style.display = this.filter.type === 'creator' ? '' : 'none';
    const tagBar = document.getElementById('feed-website-filters');
    if (tagBar) tagBar.style.display = this.filter.type === 'creator' ? 'none' : '';
  },

  async loadWebsiteTags() {
    const bar = document.getElementById('feed-website-filters');
    if (!bar) return;
    try {
      const meta = await API.get('/api/sources/meta');
      const tags = meta.tags || [];
      if (!tags.length) return;
      bar.innerHTML = `<span class="filter-chip active" data-tag="">All topics</span>` +
        tags.map(t => `<span class="filter-chip" data-tag="${App.escape(t)}">${App.escape(t)}</span>`).join('');
      bar.querySelectorAll('.filter-chip').forEach(chip => {
        chip.onclick = () => {
          bar.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
          chip.classList.add('active');
          this.filter.tag = chip.dataset.tag || null;
          this.offset = 0;
          this.items = [];
          this.render();
        };
      });
    } catch {}
  },

  async render() {
    const el = document.getElementById('feed-list');
    if (!el) return;
    if (this.offset === 0) App.loading(el, 'Loading feed...');

    try {
      if (this.filter.type === 'website') {
        await this.renderWebsites(el);
      } else if (this.filter.type === 'creator') {
        await this.renderCreators(el);
      } else {
        // All: websites first, then creators below
        await this.renderWebsites(el);
        await this.renderCreators(el, true);
        const more = document.getElementById('feed-load-more');
        if (more) more.style.display = 'none';
      }
    } catch (e) {
      el.innerHTML = `<div class="empty-state"><p style="color:var(--red)">${App.escape(e.message)}</p></div>`;
    }
  },

  async renderCreators(el, append = false) {
    const params = new URLSearchParams({ limit: this.limit, offset: this.offset });
    if (this.filter.platform) params.set('platform', this.filter.platform);
    if (this.filter.category) params.set('category', this.filter.category);
    if (this.filter.saved) params.set('saved', 'true');
    if (this.filter.from_date) params.set('from_date', this.filter.from_date);
    if (this.filter.to_date) params.set('to_date', this.filter.to_date);

    const data = await API.get('/api/content?' + params);
    if (!append && this.offset === 0) el.innerHTML = '';

    if (!data.length && this.offset === 0 && !append) {
      el.innerHTML = `<div class="empty-state"><div class="empty-icon">📡</div><h3>No content yet</h3><p>Add creators and click Refresh to start tracking content.</p></div>`;
      return;
    }

    this.items.push(...data);
    data.forEach(item => el.appendChild(this.buildCard(item)));

    const more = document.getElementById('feed-load-more');
    if (more) more.style.display = data.length >= this.limit ? '' : 'none';
  },

  async renderWebsites(el, append = false) {
    const params = new URLSearchParams({ limit: this.limit, offset: this.offset });
    if (this.filter.tag) params.set('tags', this.filter.tag);
    if (this.filter.from_date) params.set('from_date', this.filter.from_date);
    if (this.filter.to_date) params.set('to_date', this.filter.to_date);

    const data = await API.get('/api/sources/items?' + params);
    if (!append && this.offset === 0) el.innerHTML = '';

    if (!data.length && this.offset === 0 && !append) {
      el.innerHTML = `<div class="empty-state"><div class="empty-icon">📰</div><h3>No articles yet</h3><p>Add sources and click Refresh to get news.</p></div>`;
      return;
    }

    this.items.push(...data);
    data.forEach(item => el.appendChild(this.buildWebsiteCard(item)));

    const more = document.getElementById('feed-load-more');
    if (more) more.style.display = data.length >= this.limit ? '' : 'none';
  },

  buildCard(item) {
    const isAr = App.detectArabic(item.body || '');
    const el = document.createElement('div');
    el.className = 'feed-item feed-card';
    el.dataset.id = item.id;
    if (item.is_read) el.classList.add('is-read');

    const platformColor = { linkedin: '#0a66c2', twitter: '#1d9bf0', youtube: '#ff0000' }[item.platform] || 'var(--accent)';
    const body = (item.body || '').length > 300 ? item.body.substring(0, 300) + '...' : item.body;
    // Force a single ASCII char for the fallback initial — guarantees no HTML/quote injection.
    const rawInitial = ((item.creator_name || '?')[0] || '?').toUpperCase();
    const initial = /[A-Z0-9]/.test(rawInitial) ? rawInitial : '?';

    const avatarHtml = item.creator_image_url
      ? `<img src="${App.escape(App.proxyImg(item.creator_image_url))}" class="feed-item-avatar" referrerpolicy="no-referrer" data-fallback-initial="${initial}" onerror="this.outerHTML='<div class=\\'feed-item-avatar-fallback\\'>'+this.dataset.fallbackInitial+'</div>'">`
      : `<div class="feed-item-avatar-fallback">${initial}</div>`;

    el.innerHTML = `
      ${item.image_url ? `<div class="feed-item-image-wrap"><img src="${App.escape(App.proxyImg(item.image_url))}" loading="lazy" referrerpolicy="no-referrer" alt="" class="feed-item-image" onerror="this.closest('.feed-item-image-wrap').remove()"></div>` : `<div class="feed-item-platform-bar" style="background:${platformColor}"></div>`}
      <div class="feed-item-content">
        <div class="feed-item-header">
          ${avatarHtml}
          <div class="feed-item-meta">
            <span class="feed-item-name" ${item.creator_id ? `onclick="CreatorProfile.open(${item.creator_id})"` : ''}>${App.escape(item.creator_name || '')}</span>
            <span class="feed-item-date">${App.fmtDate(item.published_at)}</span>
          </div>
          ${App.platformBadge(item.platform)}
          ${item.is_saved ? '<span class="feed-item-saved-badge">★ Saved</span>' : ''}
        </div>
        ${item.title ? `<div class="feed-item-title">${App.escape(item.title)}</div>` : ''}
        ${body ? `<div class="feed-item-body${isAr ? ' rtl' : ''}">${App.escape(body)}</div>` : ''}
        <div class="feed-item-actions">
          ${item.url ? `<a href="${App.escape(item.url)}" target="_blank" class="btn btn-ghost btn-sm">Open ↗</a>` : ''}
          ${!item.is_saved ? `<button class="btn btn-secondary btn-sm" onclick="Feed.save(${item.id}, this)">Save</button>` : ''}
          ${!item.is_read ? `<button class="btn btn-ghost btn-sm" onclick="Feed.skip(${item.id}, this)">Mark read</button>` : ''}
          <button class="btn btn-sm feed-action-write" onclick="Write.fromContent(${item.id}); App.goTo('write')">Write from this</button>
        </div>
      </div>
    `;
    return el;
  },

  buildWebsiteCard(item) {
    const el = document.createElement('div');
    el.className = 'feed-item feed-card';
    el.dataset.id = `ws-${item.id}`;

    const hostname = (() => { try { return new URL(item.url || '').hostname; } catch { return ''; } })();
    const fav = hostname ? `https://www.google.com/s2/favicons?domain=${hostname}&sz=32` : null;
    const tags = (item.topic_tags || []).map(t => `<span class="tag">${App.escape(t)}</span>`).join('');
    const body = (item.body || '').substring(0, 220);

    const avatarHtml = fav
      ? `<img src="${fav}" style="width:34px;height:34px;border-radius:8px;object-fit:contain;flex-shrink:0;background:var(--bg3);border:1.5px solid var(--border);padding:4px" onerror="this.style.display='none'">`
      : `<div class="feed-item-avatar-fallback" style="border-radius:8px">W</div>`;

    el.innerHTML = `
      <div class="feed-item-platform-bar" style="background:#6366f1"></div>
      <div class="feed-item-content">
        <div class="feed-item-header">
          ${avatarHtml}
          <div class="feed-item-meta">
            <span class="feed-item-name" style="cursor:default">${App.escape(item.source_name || '')}</span>
            <span class="feed-item-date">${App.fmtDate(item.published_at)}</span>
          </div>
          ${item.is_saved ? '<span class="feed-item-saved-badge">★ Saved</span>' : ''}
        </div>
        ${item.title ? `<div class="feed-item-title">${App.escape(item.title)}</div>` : ''}
        ${body ? `<div class="feed-item-body">${App.escape(body)}${(item.body || '').length > 220 ? '…' : ''}</div>` : ''}
        ${tags ? `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:8px">${tags}</div>` : ''}
        <div class="feed-item-actions">
          ${item.url ? `<a href="${App.escape(item.url)}" target="_blank" class="btn btn-ghost btn-sm">Open ↗</a>` : ''}
        </div>
      </div>
    `;
    return el;
  },

  loadMore() {
    this.offset += this.limit;
    this.render();
  },

  async save(id, btn) {
    try {
      await API.post(`/api/content/${id}/save`, {});
      btn.remove();
      const card = document.querySelector(`.feed-item[data-id="${id}"]`);
      if (card && !card.querySelector('.feed-item-saved-badge')) {
        const badge = document.createElement('span');
        badge.className = 'feed-item-saved-badge';
        badge.textContent = '★ Saved';
        card.querySelector('.feed-item-header')?.appendChild(badge);
      }
      App.toast('Saved!', 'success');
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  async skip(id, btn) {
    try {
      await API.post(`/api/content/${id}/skip`, {});
      const card = document.querySelector(`.feed-item[data-id="${id}"]`);
      if (card) card.classList.add('is-read');
      btn.remove();
    } catch {}
  },

  async populateRefreshDropdown() {
    const sel = document.getElementById('feed-refresh-target');
    if (!sel) return;
    while (sel.options.length > 1) sel.remove(1);
    try {
      const [creators, sources] = await Promise.all([
        API.get('/api/creators'),
        API.get('/api/sources'),
      ]);
      if (creators?.length) {
        const og = document.createElement('optgroup');
        og.label = 'Creators';
        creators.forEach(c => {
          const o = document.createElement('option');
          o.value = `creator:${c.id}`;
          o.textContent = c.name;
          og.appendChild(o);
        });
        sel.appendChild(og);
      }
      if (sources?.length) {
        const og = document.createElement('optgroup');
        og.label = 'Websites';
        sources.forEach(s => {
          const o = document.createElement('option');
          o.value = `source:${s.id}`;
          o.textContent = s.name;
          og.appendChild(o);
        });
        sel.appendChild(og);
      }
    } catch {}
  },

  async refresh() {
    const btn = document.getElementById('feed-refresh-btn');
    const sel = document.getElementById('feed-refresh-target');
    const target = sel?.value || '';
    if (btn) { btn.disabled = true; btn.textContent = 'Refreshing...'; }
    try {
      let result;
      if (!target) {
        result = await API.post('/api/fetch/all', {});
      } else if (target.startsWith('creator:')) {
        const id = target.split(':')[1];
        result = await API.post(`/api/fetch/creator/${id}`, {});
      } else if (target.startsWith('source:')) {
        const id = target.split(':')[1];
        result = await API.post(`/api/fetch/source/${id}`, {});
      }
      const newCount = result.new_items ?? result.total_new ?? 0;
      App.toast(`Done! ${newCount} new items.`, 'success');
      if (result.errors?.length) {
        result.errors.slice(0, 3).forEach(e => App.toast(e, 'error'));
      }
      this.offset = 0;
      this.items = [];
      await this.loadWebsiteTags();
      this.render();
      App.updateBadge();
    } catch (e) {
      App.toast(e.message, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 16h5v5"/></svg> Refresh`;
      }
    }
  },

  // kept as alias so any other callers don't break
  refreshAll() { return this.refresh(); }
};
