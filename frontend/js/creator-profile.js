const CreatorProfile = {
  currentId: null,
  _creator: null,
  _postsOffset: 0,
  _postsTotal: 0,
  _filterPlatform: null,
  _filterFormat: null,
  _fromDate: '',
  _toDate: '',
  _minLikes: 0,
  _hasMedia: false,
  _sortBy: 'published_at',
  _sortDir: 'desc',
  _search: '',
  _searchTimer: null,
  _notes: [],

  open(id) {
    this.currentId = id;
    this._creator = null;
    this._notes = [];
    this._postsOffset = 0;
    this._postsTotal = 0;
    this._filterPlatform = null;
    this._filterFormat = null;
    this._fromDate = '';
    this._toDate = '';
    this._minLikes = 0;
    this._hasMedia = false;
    this._sortBy = 'published_at';
    this._sortDir = 'desc';
    this._search = '';
    App.goTo('creator-profile');
  },

  load() {
    if (!this.currentId) { App.goTo('creators'); return; }
    this._render();
  },

  _postsQueryParams(offset = 0) {
    const p = new URLSearchParams({ limit: 30, offset });
    if (this._filterPlatform) p.set('platform', this._filterPlatform);
    if (this._filterFormat) p.set('format', this._filterFormat);
    if (this._fromDate) p.set('from_date', this._fromDate);
    if (this._toDate) p.set('to_date', this._toDate);
    if (this._minLikes > 0) p.set('min_likes', this._minLikes);
    if (this._hasMedia) p.set('has_media', 'true');
    if (this._sortBy) p.set('sort_by', this._sortBy);
    if (this._sortDir) p.set('sort_dir', this._sortDir);
    if (this._search) p.set('search', this._search);
    return p.toString();
  },

  /* SVG icon helpers */
  _iconPerson: `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>`,
  _iconBulb: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0018 8 6 6 0 006 8c0 1 .23 2.23 1.5 3.5A4.61 4.61 0 018.91 14"/></svg>`,
  _iconClose: `<svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
  _iconNote: `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`,

  async _render() {
    const el = document.getElementById('profile-content');
    if (!el) return;
    App.loading(el, 'Loading profile...');
    try {
      const [creator, postsResult, insights, notes] = await Promise.all([
        API.get(`/api/creators/${this.currentId}`),
        API.get(`/api/creators/${this.currentId}/posts?${this._postsQueryParams()}`),
        API.get(`/api/analysis/insights/${this.currentId}`),
        API.get(`/api/creators/${this.currentId}/notes`),
      ]);
      this._creator = creator;
      this._notes = notes;
      this._postsOffset = postsResult.items.length;
      this._postsTotal = postsResult.total;

      document.getElementById('profile-title').textContent = creator.name;

      const avatarSrc = creator.profile_image_url
        || (creator.twitter_handle ? `https://unavatar.io/twitter/${encodeURIComponent(creator.twitter_handle)}` : null)
        || (creator.instagram_handle ? `https://unavatar.io/instagram/${encodeURIComponent(creator.instagram_handle)}` : null);
      const avatar = avatarSrc
        ? `<img src="${App.escape(App.proxyImg(avatarSrc))}" class="profile-avatar" referrerpolicy="no-referrer" onerror="this.onerror=null;this.style.display='none';this.insertAdjacentHTML('afterend','<div class=\\'profile-avatar profile-avatar-fallback\\'></div>')">`
        : `<div class="profile-avatar profile-avatar-fallback">${this._iconPerson}</div>`;

      const catIsCompetitor = creator.category === 'competitor';
      const catColor = catIsCompetitor ? 'var(--red)' : 'var(--green)';
      const catBg    = catIsCompetitor ? 'rgba(244,63,94,0.12)' : 'rgba(16,185,129,0.12)';
      const catLabel = catIsCompetitor ? 'Competitor' : 'Inspiration';

      const platforms = [
        creator.linkedin_url    ? `<a href="${App.escape(creator.linkedin_url)}" target="_blank" class="platform-badge platform-li" style="text-decoration:none">LinkedIn</a>` : '',
        creator.twitter_handle  ? `<span class="platform-badge platform-tw">@${App.escape(creator.twitter_handle.replace(/^@/, ''))}</span>` : '',
        creator.instagram_handle ? `<a href="https://instagram.com/${App.escape(creator.instagram_handle.replace(/^@/, ''))}" target="_blank" class="platform-badge platform-ig" style="text-decoration:none">@${App.escape(creator.instagram_handle.replace(/^@/, ''))}</a>` : '',
        creator.youtube_channel_id ? `<span class="platform-badge platform-yt">YouTube</span>` : '',
        creator.tiktok_handle   ? `<a href="https://tiktok.com/@${App.escape(creator.tiktok_handle.replace(/^@/, ''))}" target="_blank" class="platform-badge platform-tt" style="text-decoration:none">@${App.escape(creator.tiktok_handle.replace(/^@/, ''))}</a>` : '',
      ].filter(Boolean).join('');

      const lastFetched = creator.last_fetched_at
        ? `Last fetched ${App.fmtDate(creator.last_fetched_at)}`
        : 'Never fetched';

      el.innerHTML = `
        <div class="profile-hero">
          <div class="profile-hero-cover"></div>
          <div class="profile-hero-body">
            ${avatar}
            <div class="profile-info">
              <div class="profile-name">${App.escape(creator.name)}</div>
              <div class="profile-meta" style="margin-top:6px;gap:8px">
                <span style="color:${catColor};background:${catBg};font-size:11px;font-weight:700;padding:2px 9px;border-radius:20px;letter-spacing:0.03em;text-transform:uppercase">${catLabel}</span>
                ${platforms}
                ${creator.country ? `<span style="font-size:12px;color:var(--text3)">${App.escape(creator.country)}</span>` : ''}
              </div>
              <div style="display:flex;gap:16px;margin-top:8px">
                <span style="display:flex;align-items:center;gap:5px;font-size:12px;color:var(--text3)">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                  <strong style="color:var(--text2)">${postsResult.total}</strong>&nbsp;posts
                </span>
                <span style="display:flex;align-items:center;gap:5px;font-size:12px;color:var(--text3)">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                  ${lastFetched}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div class="profile-section">
          <div class="section-title" style="display:flex;align-items:center;gap:8px">
            ${this._iconNote} Notes
            <button onclick="CreatorProfile.showAddNoteForm()" style="margin-left:auto;font-size:11px;font-weight:600;color:var(--accent-light);background:none;border:none;cursor:pointer;padding:0;display:flex;align-items:center;gap:4px">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              Add note
            </button>
          </div>
          <div id="add-note-form" style="display:none;margin-bottom:12px">
            <textarea id="new-note-input" rows="3" placeholder="Write a note about this creator…"
              onkeydown="if((event.ctrlKey||event.metaKey)&&event.key==='Enter'){event.preventDefault();CreatorProfile.saveNewNote()}"
            ></textarea>
            <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:8px">
              <button class="btn btn-ghost btn-sm" onclick="CreatorProfile.cancelAddNote()">Cancel</button>
              <button class="btn btn-primary btn-sm" onclick="CreatorProfile.saveNewNote()">Save note</button>
            </div>
          </div>
          <div id="notes-list">
            ${this._renderNotes(notes)}
          </div>
        </div>

        <div class="profile-section">
          <div class="section-title" style="display:flex;align-items:center;gap:8px">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polygon points="13,2 3,14 12,14 11,22 21,10 12,10 13,2"/></svg>
            Insights <span style="color:var(--text3);font-weight:400">(${insights.length})</span>
            <a href="#" onclick="event.preventDefault();Analysis.selectCreator(${this.currentId});App.goTo('analysis')" style="font-size:11px;font-weight:600;color:var(--accent-light);margin-left:auto;text-decoration:none;display:flex;align-items:center;gap:3px">
              Ask in Analysis
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
            </a>
          </div>
          <div id="profile-insights-list">
            ${this._renderInsights(insights)}
          </div>
        </div>

        <div class="profile-section">
          <div class="section-title" style="display:flex;align-items:center;gap:8px">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
            <span id="profile-posts-title">Posts (${postsResult.total})</span>
          </div>
          ${this._renderFilterBar()}
          <div id="profile-posts-list" class="posts-grid">
            ${this._renderPostItems(postsResult.items)}
          </div>
          ${postsResult.total > 30 ? `<div id="profile-load-more" style="text-align:center;padding:16px"><button class="btn btn-ghost" onclick="CreatorProfile.loadMore()">Load more (${postsResult.total - this._postsOffset} remaining)</button></div>` : ''}
        </div>
      `;
    } catch (e) {
      el.innerHTML = `<div style="color:var(--red);padding:20px">${App.escape(e.message)}</div>`;
    }
  },

  _renderSkeletonPosts(count = 5) {
    const titleWidths = ['78%', '92%', '65%', '85%', '72%'];
    return Array.from({ length: count }, (_, i) => `
      <div class="post-skel">
        <div class="skeleton" style="height:3px"></div>
        <div class="post-skel-body">
          <div class="post-skel-header">
            <span class="skeleton" style="width:54px;height:18px;border-radius:4px"></span>
            <span class="skeleton" style="width:70px;height:11px"></span>
          </div>
          <div class="skeleton" style="width:${titleWidths[i % titleWidths.length]};height:14px"></div>
          <div class="skeleton" style="width:100%;height:12px"></div>
          <div class="skeleton" style="width:88%;height:12px"></div>
          <div class="skeleton" style="width:60%;height:12px"></div>
        </div>
        <div class="post-skel-footer">
          <span class="skeleton" style="width:46px;height:11px"></span>
          <span class="skeleton" style="width:46px;height:11px"></span>
        </div>
      </div>`).join('');
  },

  _renderPostItems(items) {
    if (!items.length) {
      const iconSearch = `<svg xmlns="http://www.w3.org/2000/svg" width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>`;
      const iconInbox  = `<svg xmlns="http://www.w3.org/2000/svg" width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.45-6.89A2 2 0 0016.76 4H7.24a2 2 0 00-1.79 1.11z"/></svg>`;
      const hasFilter = this._filterPlatform || this._filterFormat || this._fromDate || this._toDate || this._minLikes > 0 || this._hasMedia || this._search;
      return hasFilter
        ? `<div class="empty-state"><div class="empty-icon">${iconSearch}</div><h3>No matching posts</h3><p>Try a different filter or search term.</p></div>`
        : `<div class="empty-state"><div class="empty-icon">${iconInbox}</div><h3>No posts yet</h3><p>Click ↻ Refresh to import posts for this creator.</p></div>`;
    }
    return items.map(item => this._renderOnePost(item)).join('');
  },

  _renderOnePost(item) {
    const dir = App.detectArabic(item.body || item.title || '') ? 'rtl' : 'ltr';
    const platformClass = { linkedin: 'platform-li', twitter: 'platform-tw', youtube: 'platform-yt', instagram: 'platform-ig', tiktok: 'platform-tt' }[item.platform] || '';
    const platformLabel = { linkedin: 'LinkedIn', twitter: 'Twitter', youtube: 'YouTube', instagram: 'Instagram', tiktok: 'TikTok' }[item.platform] || item.platform;

    const iconHeart   = `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" style="vertical-align:middle"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>`;
    const iconComment = `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:middle"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>`;
    const iconShare   = `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:middle"><path d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg>`;

    const stats = [
      item.likes          ? `${iconHeart} ${item.likes.toLocaleString()}`           : '',
      item.comments_count ? `${iconComment} ${item.comments_count.toLocaleString()}` : '',
      item.shares         ? `${iconShare} ${item.shares.toLocaleString()}`           : '',
    ].filter(Boolean).join(' · ');

    const iconPlay = `<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>`;
    const iconDownload = `<svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`;

    if (item.platform === 'youtube') {
      const thumbContent = item.image_url
        ? `<img src="${App.escape(App.proxyImg(item.image_url))}" loading="lazy" referrerpolicy="no-referrer" alt="${App.escape(item.title || 'Video thumbnail')}">`
        : `<div class="post-card-video-thumb-placeholder">${iconPlay}</div>`;

      const transcriptHtml = item.transcript
        ? `<details style="margin-top:10px">
            <summary style="font-size:11px;color:var(--text3);cursor:pointer;user-select:none">Transcript · ${item.transcript.split(' ').length} words</summary>
            <div style="font-size:12px;line-height:1.7;color:var(--text2);margin-top:8px;max-height:200px;overflow-y:auto;white-space:pre-wrap;background:rgba(255,255,255,0.03);padding:10px;border-radius:8px;border:1px solid var(--glass-border)" dir="${dir}">${App.escape(item.transcript)}</div>
           </details>`
        : '';

      const viewLink = item.url ? `<a href="${App.escape(item.url)}" target="_blank" rel="noopener" class="btn btn-ghost btn-sm" style="font-size:11px">View on YouTube ↗</a>` : '';

      return `
        <div class="post-card" data-item-id="${item.id}" data-platform="${item.platform}">
          <div class="post-card-video-thumb">
            ${thumbContent}
            ${item.image_url ? `<div class="post-card-video-play"><div class="post-card-video-play-btn">${iconPlay}</div></div>` : ''}
          </div>
          <div class="post-card-header">
            <span class="platform-badge ${platformClass}">${platformLabel}</span>
            ${item.published_at ? `<span class="post-card-header-date">${App.fmtDate(item.published_at)}</span>` : ''}
            ${stats ? `<span style="margin-left:auto;font-size:11px;color:var(--text3)">${stats}</span>` : ''}
          </div>
          <div class="post-card-inner" style="padding-bottom:14px">
            ${item.title ? `<div class="post-card-title" dir="${dir}">${App.escape(item.title)}</div>` : ''}
            ${item.body ? `<div class="post-card-body clipped" dir="${dir}">${App.escape(item.body)}</div>` : ''}
            ${transcriptHtml}
            <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
              <button class="btn btn-ghost btn-sm" onclick="CreatorProfile.fetchDetails(${item.id}, this)" style="font-size:11px;gap:5px">${iconDownload} Fetch details</button>
              ${viewLink}
            </div>
          </div>
        </div>`;
    }

    const platformColors = { linkedin: '#4F6EF7', twitter: '#38BDF8', instagram: '#F472B6' };
    const accentColor = platformColors[item.platform] || 'var(--iris-2)';
    const body = item.body || '';
    const hasImage = !!item.image_url;

    const imageTopHtml = hasImage
      ? `<div class="post-card-image-wrap"><img src="${App.escape(App.proxyImg(item.image_url))}" loading="lazy" referrerpolicy="no-referrer" alt="" class="post-card-image" onerror="this.closest('.post-card-image-wrap').remove()"></div>`
      : '';

    const footerStats = [
      item.likes          ? `<span class="post-card-stat"><span class="post-card-stat-icon">${iconHeart}</span>${item.likes.toLocaleString()}</span>`          : '',
      item.comments_count ? `<span class="post-card-stat"><span class="post-card-stat-icon">${iconComment}</span>${item.comments_count.toLocaleString()}</span>` : '',
      item.shares         ? `<span class="post-card-stat"><span class="post-card-stat-icon">${iconShare}</span>${item.shares.toLocaleString()}</span>`           : '',
    ].filter(Boolean).join('');
    const hasFooter = footerStats || item.url;

    return `
      <div class="post-card" data-item-id="${item.id}" data-platform="${item.platform}">
        ${hasImage ? imageTopHtml : `<div class="post-card-accent" style="background:${accentColor}"></div>`}
        <div class="post-card-header">
          <span class="platform-badge ${platformClass}">${platformLabel}</span>
          ${item.published_at ? `<span class="post-card-header-date">${App.fmtDate(item.published_at)}</span>` : ''}
          ${item.format && item.format !== 'text' ? `<span style="margin-left:auto;font-size:10px;background:var(--glass-bg);border:1px solid var(--glass-border);border-radius:5px;padding:1px 7px;color:var(--text3);text-transform:uppercase;letter-spacing:0.04em">${App.escape(item.format)}</span>` : ''}
        </div>
        <div class="post-card-inner" style="padding-bottom:14px">
          ${item.title ? `<div class="post-card-title" dir="${dir}">${App.escape(item.title)}</div>` : ''}
          ${body ? `<div class="post-card-body${dir === 'rtl' ? ' rtl' : ''} clipped" dir="${dir}">${App.escape(body)}</div>` : ''}
        </div>
        ${hasFooter ? `<div class="post-card-footer">
          ${footerStats}
          ${item.url ? `<a href="${App.escape(item.url)}" target="_blank" class="post-card-footer-link">View original →</a>` : ''}
        </div>` : ''}
      </div>`;
  },

  _renderInsights(insights) {
    if (!insights.length) {
      return `<div style="display:flex;align-items:center;gap:12px;padding:16px;background:var(--glass-bg);border-radius:10px;border:1px dashed rgba(255,255,255,0.1)">
        <span style="color:var(--text3);flex-shrink:0">${this._iconBulb}</span>
        <span style="font-size:13px;color:var(--text3);line-height:1.5">No insights saved yet. Go to <strong style="color:var(--text2);font-weight:600">Analysis</strong> to ask questions about this creator and save answers here.</span>
      </div>`;
    }
    return insights.map(ins => `
      <div class="insight-row" data-insight-id="${ins.id}">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
          <span style="font-size:13px;font-weight:600;color:var(--text)">${App.escape(ins.title || 'Insight')}</span>
          <span style="font-size:11px;color:var(--text3);margin-left:auto">${App.fmtDate(ins.created_at)}</span>
          <button class="btn btn-ghost btn-sm" style="color:var(--red);border-color:transparent;padding:3px 6px;flex-shrink:0" onclick="CreatorProfile.deleteInsight(${ins.id})" title="Delete insight">${this._iconClose}</button>
        </div>
        ${ins.question ? `<div style="font-size:12px;color:var(--text3);margin-bottom:6px;font-style:italic">${App.escape(ins.question)}</div>` : ''}
        <div style="font-size:13px;line-height:1.7;color:var(--text2);white-space:pre-wrap">${App.escape(ins.answer || '')}</div>
        ${ins.posts_analyzed ? `<div style="font-size:11px;color:var(--text3);margin-top:6px">Based on ${ins.posts_analyzed} posts</div>` : ''}
      </div>
    `).join('');
  },

  _renderFilterBar() {
    const c = this._creator;
    if (!c) return '';

    const platforms = [];
    if (c.linkedin_url)        platforms.push('linkedin');
    if (c.twitter_handle)      platforms.push('twitter');
    if (c.youtube_channel_id)  platforms.push('youtube');
    if (c.instagram_handle)    platforms.push('instagram');
    if (c.tiktok_handle)       platforms.push('tiktok');

    const labels = { linkedin: 'LinkedIn', twitter: 'Twitter', youtube: 'YouTube', instagram: 'Instagram', tiktok: 'TikTok' };

    const platformTabs = platforms.length > 0 ? `
      <div class="platform-tabs" style="flex-shrink:0">
        <button class="platform-tab${!this._filterPlatform ? ' active' : ''}" onclick="CreatorProfile._setPlatform(null, this)">All</button>
        ${platforms.map(p => `<button class="platform-tab${this._filterPlatform === p ? ' active' : ''}" onclick="CreatorProfile._setPlatform('${p}', this)">${labels[p] || p}</button>`).join('')}
      </div>` : '';

    const sortOptions = [
      { val: 'published_at|desc',   label: 'Newest first' },
      { val: 'published_at|asc',    label: 'Oldest first' },
      { val: 'likes|desc',          label: 'Most likes' },
      { val: 'comments_count|desc', label: 'Most comments' },
      { val: 'shares|desc',         label: 'Most shares' },
    ];
    const currentSortVal = `${this._sortBy}|${this._sortDir}`;

    const hasExtra = this._fromDate || this._toDate || this._filterFormat || this._minLikes > 0 || this._hasMedia;
    const clearBtn = hasExtra
      ? `<button onclick="CreatorProfile._clearExtraFilters()" style="font-size:11px;color:var(--red);background:none;border:none;cursor:pointer;padding:2px 6px;border-radius:6px;white-space:nowrap;flex-shrink:0;display:flex;align-items:center;gap:4px">${this._iconClose} Clear</button>`
      : '';

    return `
      <div id="profile-filter-bar" style="display:flex;flex-direction:column;gap:10px;margin-bottom:16px">
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
          ${platformTabs}
          <div style="margin-left:auto;display:flex;align-items:center;gap:8px;flex-shrink:0">
            <input type="search" id="profile-posts-search" placeholder="Search posts…" value="${App.escape(this._search)}"
              oninput="CreatorProfile._onSearch(this.value)" class="profile-filter-input" style="width:160px" />
            <select id="profile-posts-sort" onchange="CreatorProfile._onSort(this.value)" class="profile-filter-input" style="cursor:pointer">
              ${sortOptions.map(o => `<option value="${o.val}"${currentSortVal === o.val ? ' selected' : ''}>${o.label}</option>`).join('')}
            </select>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span style="font-size:11px;color:var(--text3);font-weight:500;flex-shrink:0">Filter:</span>
          <input type="date" id="profile-from-date" title="From date" value="${this._fromDate}"
            onchange="CreatorProfile._onFromDate(this.value)" class="profile-filter-input" style="width:138px" />
          <span style="font-size:11px;color:var(--text3)">–</span>
          <input type="date" id="profile-to-date" title="To date" value="${this._toDate}"
            onchange="CreatorProfile._onToDate(this.value)" class="profile-filter-input" style="width:138px" />
          <select id="profile-format-filter" onchange="CreatorProfile._onFormat(this.value)" class="profile-filter-input" style="cursor:pointer" title="Content type">
            <option value=""${!this._filterFormat ? ' selected' : ''}>All types</option>
            <option value="text"${this._filterFormat === 'text' ? ' selected' : ''}>Text</option>
            <option value="image"${this._filterFormat === 'image' ? ' selected' : ''}>Image</option>
            <option value="carousel"${this._filterFormat === 'carousel' ? ' selected' : ''}>Carousel</option>
            <option value="video"${this._filterFormat === 'video' ? ' selected' : ''}>Video</option>
            <option value="article"${this._filterFormat === 'article' ? ' selected' : ''}>Article</option>
          </select>
          <div style="display:flex;align-items:center;gap:6px;flex-shrink:0">
            <span style="font-size:11px;color:var(--text3)">Min likes</span>
            <input type="number" id="profile-min-likes" min="0" step="10" placeholder="0" value="${this._minLikes || ''}"
              onchange="CreatorProfile._onMinLikes(this.value)" class="profile-filter-input" style="width:70px;text-align:center" />
          </div>
          <button onclick="CreatorProfile._toggleHasMedia()" class="filter-chip${this._hasMedia ? ' active' : ''}" title="Show only posts with images">Has media</button>
          ${clearBtn}
        </div>
      </div>`;
  },

  _setPlatform(platform, btn) {
    this._filterPlatform = platform;
    document.querySelectorAll('.platform-tab').forEach(t => t.classList.remove('active'));
    if (btn) btn.classList.add('active');
    this._reloadPosts();
  },

  _onSort(val) {
    const [sortBy, sortDir] = val.split('|');
    this._sortBy = sortBy;
    this._sortDir = sortDir;
    this._reloadPosts();
  },

  _onSearch(val) {
    this._search = val;
    clearTimeout(this._searchTimer);
    this._searchTimer = setTimeout(() => this._reloadPosts(), 350);
  },

  _onFromDate(val) { this._fromDate = val; this._reloadPosts(); },
  _onToDate(val)   { this._toDate = val;   this._reloadPosts(); },

  _onFormat(val) {
    this._filterFormat = val || null;
    this._reloadPosts();
  },

  _onMinLikes(val) {
    this._minLikes = parseInt(val, 10) || 0;
    this._reloadPosts();
  },

  _toggleHasMedia() {
    this._hasMedia = !this._hasMedia;
    const btn = document.querySelector('#profile-content button[title="Show only posts with images"]');
    if (btn) btn.classList.toggle('active', this._hasMedia);
    this._reloadPosts();
  },

  _clearExtraFilters() {
    this._fromDate = '';
    this._toDate = '';
    this._filterFormat = null;
    this._minLikes = 0;
    this._hasMedia = false;
    this._reloadAndRefreshFilterBar();
  },

  _reloadAndRefreshFilterBar() {
    const bar = document.getElementById('profile-filter-bar');
    if (bar) bar.outerHTML = this._renderFilterBar();
    this._reloadPosts();
  },

  async _reloadPosts() {
    this._postsOffset = 0;
    const list = document.getElementById('profile-posts-list');
    const loadMore = document.getElementById('profile-load-more');
    if (!list) return;
    list.className = 'posts-grid';
    list.innerHTML = this._renderSkeletonPosts(4);
    if (loadMore) loadMore.remove();
    try {
      const result = await API.get(`/api/creators/${this.currentId}/posts?${this._postsQueryParams()}`);
      this._postsOffset = result.items.length;
      this._postsTotal = result.total;
      list.innerHTML = this._renderPostItems(result.items);
      const titleEl = document.getElementById('profile-posts-title');
      if (titleEl) titleEl.textContent = `Posts (${result.total})`;
      if (result.total > 30) {
        list.insertAdjacentHTML('afterend', `<div id="profile-load-more" style="text-align:center;padding:16px"><button class="btn btn-ghost" onclick="CreatorProfile.loadMore()">Load more (${result.total - this._postsOffset} remaining)</button></div>`);
      }
    } catch (e) {
      list.innerHTML = `<div style="color:var(--red);padding:20px">${App.escape(e.message)}</div>`;
    }
  },

  filterPosts(platform, btn) { this._setPlatform(platform, btn); },

  async deleteInsight(insightId) {
    try {
      await API.del(`/api/analysis/insights/${insightId}`);
      const el = document.querySelector(`[data-insight-id="${insightId}"]`);
      if (el) el.remove();
      const list = document.getElementById('profile-insights-list');
      const remaining = list ? list.querySelectorAll('[data-insight-id]').length : 0;
      document.querySelectorAll('#profile-content .profile-section .section-title').forEach(t => {
        if (t.textContent.includes('Insights')) {
          const link = t.querySelector('a');
          t.innerHTML = `Insights (${remaining}) `;
          if (link) t.appendChild(link);
        }
      });
      App.toast('Insight deleted', 'success');
    } catch (e) {
      App.toast('Failed to delete: ' + e.message, 'error');
    }
  },

  _renderNotes(notes) {
    if (!notes.length) {
      return `<div style="display:flex;align-items:center;gap:10px;padding:14px;background:var(--glass-bg);border-radius:9px;border:1px dashed rgba(255,255,255,0.08)">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true" style="color:var(--text3);flex-shrink:0"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
        <span style="font-size:13px;color:var(--text3)">No notes yet. Click <strong style="color:var(--text2);font-weight:600">+ Add note</strong> to start.</span>
      </div>`;
    }
    return notes.map(note => `
      <div class="note-item" data-note-id="${note.id}">
        <div style="display:flex;align-items:flex-start;gap:10px">
          <span style="font-size:11px;color:var(--text3);white-space:nowrap;padding-top:2px;min-width:72px">${App.fmtDate(note.created_at)}</span>
          <div style="flex:1;font-size:13px;line-height:1.7;color:var(--text2);white-space:pre-wrap">${App.escape(note.content)}</div>
          <button class="btn btn-ghost btn-sm" style="color:var(--red);border-color:transparent;padding:3px 6px;flex-shrink:0" onclick="CreatorProfile.deleteNote(${note.id})" title="Delete note">${this._iconClose}</button>
        </div>
      </div>
    `).join('');
  },

  showAddNoteForm() {
    const form = document.getElementById('add-note-form');
    if (form) { form.style.display = 'block'; document.getElementById('new-note-input')?.focus(); }
  },

  cancelAddNote() {
    const form = document.getElementById('add-note-form');
    if (form) form.style.display = 'none';
    const input = document.getElementById('new-note-input');
    if (input) input.value = '';
  },

  async saveNewNote() {
    const input = document.getElementById('new-note-input');
    const content = input?.value?.trim();
    if (!content) return;
    try {
      const note = await API.post(`/api/creators/${this.currentId}/notes`, { content });
      this._notes.unshift(note);
      this.cancelAddNote();
      const list = document.getElementById('notes-list');
      if (list) list.innerHTML = this._renderNotes(this._notes);
      App.toast('Note saved', 'success');
    } catch (e) {
      App.toast('Failed to save note: ' + e.message, 'error');
    }
  },

  async deleteNote(noteId) {
    try {
      await API.del(`/api/creators/${this.currentId}/notes/${noteId}`);
      this._notes = this._notes.filter(n => n.id !== noteId);
      const list = document.getElementById('notes-list');
      if (list) list.innerHTML = this._renderNotes(this._notes);
      App.toast('Note deleted', 'success');
    } catch (e) {
      App.toast('Failed to delete note: ' + e.message, 'error');
    }
  },

  async loadMore() {
    const btn = document.getElementById('profile-load-more');
    if (btn) btn.innerHTML = '<div class="spinner" style="display:inline-block;width:16px;height:16px"></div>';
    try {
      const result = await API.get(`/api/creators/${this.currentId}/posts?${this._postsQueryParams(this._postsOffset)}`);
      this._postsOffset += result.items.length;
      const list = document.getElementById('profile-posts-list');
      if (list) list.insertAdjacentHTML('beforeend', this._renderPostItems(result.items));
      if (btn) {
        const remaining = this._postsTotal - this._postsOffset;
        if (remaining > 0) {
          btn.innerHTML = `<button class="btn btn-ghost" onclick="CreatorProfile.loadMore()">Load more (${remaining} remaining)</button>`;
        } else {
          btn.remove();
        }
      }
    } catch (e) {
      App.toast('Failed to load more: ' + e.message, 'error');
      if (btn) btn.innerHTML = `<button class="btn btn-ghost" onclick="CreatorProfile.loadMore()">Retry</button>`;
    }
  },

  openEdit() {
    if (!this._creator) return;
    if (!Creators.data.find(x => x.id === this._creator.id)) {
      Creators.data = [this._creator, ...Creators.data];
    }
    Creators.openModal(this._creator.id);
  },

  async refresh() {
    if (!this.currentId) return;
    const btn = document.getElementById('profile-refresh-btn');
    if (btn) { btn.disabled = true; btn.textContent = '...'; }
    try {
      await API.post(`/api/fetch/creator/${this.currentId}`, {});
      App.toast('Posts refreshed!', 'success');
      this._render();
    } catch (e) {
      App.toast('Refresh failed: ' + e.message, 'error');
      if (btn) { btn.disabled = false; btn.textContent = '↻ Refresh'; }
    }
  },

  async fetchDetails(itemId, btn) {
    btn.disabled = true;
    const original = btn.innerHTML;
    btn.textContent = '...';
    try {
      const updated = await API.post(`/api/content/${itemId}/fetch-details`, {});
      const card = document.querySelector(`[data-item-id="${itemId}"]`);
      if (card) {
        card.outerHTML = this._renderOnePost(updated);
      } else {
        this._render();
      }
      App.toast('Details fetched!', 'success');
    } catch (e) {
      App.toast('Failed: ' + e.message, 'error');
      btn.disabled = false;
      btn.innerHTML = original;
    }
  },

  async deleteCurrent() {
    if (!this.currentId) return;
    const nameEl = document.getElementById('profile-title');
    const name = nameEl?.textContent || 'this creator';
    if (!confirm(`Delete ${name} and all their content? This cannot be undone.`)) return;
    try {
      await API.del(`/api/creators/${this.currentId}`);
      App.toast('Creator deleted', 'success');
      this.currentId = null;
      App.goTo('creators');
      if (typeof Creators !== 'undefined' && Creators.load) Creators.load();
    } catch (e) {
      App.toast('Delete failed: ' + e.message, 'error');
    }
  },
};
