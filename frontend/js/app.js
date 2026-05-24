const App = {
  currentScreen: 'dashboard',
  _lastFocusBeforeModal: null,

  init() {
    // Navigation — keyboard-activatable
    document.querySelectorAll('.nav-item').forEach(el => {
      if (!el.hasAttribute('role')) el.setAttribute('role', 'button');
      if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0');
      el.addEventListener('click', () => this.goTo(el.dataset.screen));
      el.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.goTo(el.dataset.screen); }
      });
    });

    // Keyboard a11y for chips / tabs / toggle-options across the app
    this._wireKeyboardActivation();
    this._associateLabels();
    const mo = new MutationObserver(() => { this._wireKeyboardActivation(); this._associateLabels(); });
    mo.observe(document.body, { childList: true, subtree: true });

    // Global error surfaces — without this, async bugs die silently in the console
    window.addEventListener('unhandledrejection', (ev) => {
      const msg = (ev.reason && ev.reason.message) ? ev.reason.message : String(ev.reason);
      App.toast('Unexpected error: ' + msg, 'error');
      console.error('Unhandled rejection:', ev.reason);
    });
    window.addEventListener('error', (ev) => {
      if (ev.error) console.error('Window error:', ev.error);
    });

    // Modal: Escape + focus trap
    document.addEventListener('keydown', (e) => {
      const overlay = document.getElementById('modal-overlay');
      if (!overlay || overlay.style.display !== 'flex') return;
      if (e.key === 'Escape') { e.preventDefault(); this.closeModal(); return; }
      if (e.key === 'Tab') this._trapFocus(e, overlay);
    });

    // Mobile sidebar toggle
    const ham = document.getElementById('sidebar-toggle');
    if (ham) ham.addEventListener('click', () => document.body.classList.toggle('sidebar-open'));
    document.querySelectorAll('.nav-item').forEach(el => {
      el.addEventListener('click', () => document.body.classList.remove('sidebar-open'));
    });

    // Greeting
    const hr = new Date().getHours();
    const greeting = hr < 12 ? 'Good morning' : hr < 17 ? 'Good afternoon' : 'Good evening';
    const el = document.getElementById('greeting');
    if (el) el.textContent = `${greeting}, Shadi`;

    // Load unread badge — only poll when tab is visible to avoid background traffic
    this.updateBadge();
    setInterval(() => {
      if (document.visibilityState === 'visible') this.updateBadge();
    }, 60000);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') this.updateBadge();
    });

    // Load dashboard
    Dashboard.load();
  },

  /** Auto-associate labels with the first input/textarea/select in their .form-group. */
  _associateLabels() {
    let auto = 0;
    document.querySelectorAll('.form-group').forEach(group => {
      const label = group.querySelector(':scope > label');
      if (!label || label.htmlFor) return;
      const target = group.querySelector('input, textarea, select');
      if (!target) return;
      if (!target.id) target.id = `auto-input-${++auto}-${Date.now().toString(36)}`;
      label.htmlFor = target.id;
    });
  },

  _wireKeyboardActivation() {
    document.querySelectorAll('.filter-chip, .tab, .toggle-option').forEach(el => {
      if (el.dataset._kbWired) return;
      el.dataset._kbWired = '1';
      if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0');
      const role = el.classList.contains('tab') ? 'tab' : 'button';
      if (!el.hasAttribute('role')) el.setAttribute('role', role);
      el.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); el.click(); }
      });
    });
  },

  _trapFocus(e, overlay) {
    const focusables = overlay.querySelectorAll(
      'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  },

  /** Run an async fn while disabling/labeling a button; restores on completion. */
  async withBusy(btn, busyLabel, fn) {
    if (!btn) return fn();
    const wasHTML = btn.innerHTML;
    btn.disabled = true;
    if (busyLabel) btn.textContent = busyLabel;
    try { return await fn(); }
    finally { btn.disabled = false; btn.innerHTML = wasHTML; }
  },

  goTo(screen) {
    this.currentScreen = screen;
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

    const screenEl = document.getElementById('screen-' + screen);
    const navEl = document.querySelector(`.nav-item[data-screen="${screen}"]`);
    if (screenEl) screenEl.classList.add('active');
    if (navEl) navEl.classList.add('active');

    // Lazy-load each screen
    const loaders = {
      feed: () => Feed.load(),
      creators: () => Creators.load(),
      sources: () => Sources.load(),
      analysis: () => Analysis.load(),
      intelligence: () => Intelligence.load(),
      write: () => Write.load(),
      mystyle: () => MyStyle.load(),
      settings: () => Settings.load(),
      dashboard: () => Dashboard.load(),
      'creator-profile': () => CreatorProfile.load(),
      youtube: () => YouTube.init(),
      trends: () => Trends.load(),
      engage: () => Engage.load(),
    };
    loaders[screen]?.();
  },

  navigate(screen) { this.goTo(screen); },

  async updateBadge() {
    try {
      const data = await API.get('/api/content/unread-count');
      const badge = document.getElementById('nav-feed-badge');
      if (badge) {
        badge.textContent = data.count;
        badge.style.display = data.count > 0 ? '' : 'none';
      }
    } catch {}
  },

  openModal(html) {
    this._lastFocusBeforeModal = document.activeElement;
    document.getElementById('modal-content').innerHTML = html;
    const overlay = document.getElementById('modal-overlay');
    overlay.style.display = 'flex';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    // Focus first focusable after content is in the DOM
    setTimeout(() => {
      const first = overlay.querySelector(
        'input:not([type="hidden"]):not([disabled]), textarea:not([disabled]), select:not([disabled]), button:not([disabled])'
      );
      if (first) first.focus();
    }, 50);
  },

  closeModal(e) {
    const overlay = document.getElementById('modal-overlay');
    overlay.style.display = 'none';
    document.getElementById('modal-content').innerHTML = '';
    const box = document.getElementById('modal-box');
    if (box) box.style.width = '';
    // Restore previous focus
    if (this._lastFocusBeforeModal && typeof this._lastFocusBeforeModal.focus === 'function') {
      this._lastFocusBeforeModal.focus();
    }
    this._lastFocusBeforeModal = null;
  },

  toast(msg, type = '') {
    const container = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = 'toast ' + type;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  },

  loading(el, msg = 'Loading...') {
    el.innerHTML = `<div class="loading-overlay"><div class="spinner"></div>${msg}</div>`;
  },

  fmtDate(dt) {
    if (!dt) return '';
    const d = new Date(dt);
    const diff = (Date.now() - d) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    if (diff < 86400 * 7) return `${Math.floor(diff / 86400)}d ago`;
    return d.toLocaleDateString();
  },

  platformBadge(platform) {
    const map = { linkedin: 'LI', twitter: 'TW', youtube: 'YT' };
    const cls = { linkedin: 'platform-li', twitter: 'platform-tw', youtube: 'platform-yt' };
    return `<span class="platform-badge ${cls[platform] || ''}">${map[platform] || platform}</span>`;
  },

  escape(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  },

  // Route CDN images that send Cross-Origin-Resource-Policy: same-origin
  // through our backend proxy so the browser will display them.
  proxyImg(url) {
    if (!url) return '';
    try {
      const u = new URL(url, window.location.origin);
      if (u.protocol !== 'https:') return url;
      const host = u.hostname.toLowerCase();
      const blocked = ['.fbcdn.net', '.cdninstagram.com', '.tiktokcdn.com', '.tiktokcdn-us.com', '.twimg.com'];
      if (blocked.some(s => host === s.slice(1) || host.endsWith(s))) {
        return '/api/img-proxy?url=' + encodeURIComponent(url);
      }
      return url;
    } catch (_e) {
      return url;
    }
  },

  detectArabic(text) {
    if (!text) return false;
    return /[؀-ۿ]/.test(text);
  }
};


const Dashboard = {
  async load() {
    await Promise.all([
      this.loadStats(),
      this.loadCompetitors(),
      this.loadNews(),
    ]);
  },

  async loadStats() {
    const el = document.getElementById('dashboard-stats');
    if (!el) return;
    try {
      const [unread, creators, sources] = await Promise.all([
        API.get('/api/content/unread-count'),
        API.get('/api/creators'),
        API.get('/api/sources'),
      ]);

      const updatedCreators = creators.filter(c => c.new_items_count > 0).length;
      const updatedSources = sources.filter(s => s.unread_count > 0).length;

      el.innerHTML = `
        <div class="stat-card" style="cursor:pointer" onclick="App.goTo('feed')">
          <div class="stat-card-header">
            <div class="stat-card-icon stat-icon-blue">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8h1a4 4 0 010 8h-1"/><path d="M2 8h16v9a4 4 0 01-4 4H6a4 4 0 01-4-4V8z"/><line x1="6" y1="1" x2="6" y2="4"/><line x1="10" y1="1" x2="10" y2="4"/><line x1="14" y1="1" x2="14" y2="4"/></svg>
            </div>
          </div>
          <div class="stat-num">${unread.count}</div>
          <div class="stat-label">New Content</div>
          <div class="stat-sub">Unread items in feed</div>
        </div>
        <div class="stat-card" style="cursor:pointer" onclick="App.goTo('creators')">
          <div class="stat-card-header">
            <div class="stat-card-icon stat-icon-green">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg>
            </div>
          </div>
          <div class="stat-num">${creators.length}</div>
          <div class="stat-label">Creators</div>
          <div class="stat-sub">${updatedCreators} with new posts</div>
        </div>
        <div class="stat-card" style="cursor:pointer" onclick="App.goTo('sources')">
          <div class="stat-card-header">
            <div class="stat-card-icon stat-icon-yellow">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 22h16a2 2 0 002-2V4a2 2 0 00-2-2H8a2 2 0 00-2 2v16a2 2 0 01-2 2zm0 0a2 2 0 01-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8"/><path d="M15 18h-5"/><path d="M10 6h8v4h-8z"/></svg>
            </div>
          </div>
          <div class="stat-num">${sources.length}</div>
          <div class="stat-label">News Sources</div>
          <div class="stat-sub">${updatedSources} with updates</div>
        </div>
        <div class="stat-card" style="cursor:pointer" onclick="App.goTo('write')">
          <div class="stat-card-header">
            <div class="stat-card-icon stat-icon-red">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
            </div>
          </div>
          <div class="stat-num" style="font-size:20px;padding-top:4px">Write</div>
          <div class="stat-label">Create Post</div>
          <div class="stat-sub">AI-powered drafts</div>
        </div>
      `;
    } catch (e) {
      el.innerHTML = '<div style="color:var(--text3);font-size:13px">Stats unavailable</div>';
    }
  },

  async loadCompetitors() {
    const el = document.getElementById('dashboard-competitors');
    if (!el) return;
    try {
      const landscape = await API.get('/api/analysis/landscape');
      if (!landscape.length) {
        el.innerHTML = '<div style="color:var(--text3);font-size:13px;padding:16px 0">No competitor data yet. Add creators and refresh.</div>';
        return;
      }
      el.innerHTML = landscape.slice(0, 4).map((c, i) => {
        const avatarSrc = c.profile_image_url
          || (c.instagram_handle ? `https://unavatar.io/instagram/${encodeURIComponent(c.instagram_handle)}` : null)
          || (c.twitter_handle ? `https://unavatar.io/twitter/${encodeURIComponent(c.twitter_handle)}` : null);
        const avatar = avatarSrc
          ? `<img src="${App.escape(App.proxyImg(avatarSrc))}" class="creator-avatar" referrerpolicy="no-referrer" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'creator-avatar creator-avatar-fallback',textContent:''}))">`
          : `<div class="creator-avatar creator-avatar-fallback"></div>`;
        return `
        <div class="creator-row" onclick="CreatorProfile.open(${c.id})" title="View profile">
          <div class="creator-rank-badge">${i + 1}</div>
          ${avatar}
          <div class="creator-info">
            <div class="creator-name">${App.escape(c.name)}</div>
            <div class="creator-meta">${c.post_count} posts · ${c.avg_engagement} avg eng.</div>
          </div>
          <button class="btn btn-ghost btn-sm">View →</button>
        </div>`;
      }).join('');
    } catch {
      el.innerHTML = '<div style="color:var(--text3);font-size:13px;padding:16px 0">No data yet</div>';
    }
  },

  async loadNews() {
    const el = document.getElementById('dashboard-news');
    if (!el) return;
    try {
      const items = await API.get('/api/sources/items?limit=5');
      if (!items.length) {
        el.innerHTML = '<div style="color:var(--text3);font-size:13px;padding:16px 0">No news yet. Add sources and refresh.</div>';
        return;
      }
      el.innerHTML = items.map(item => `
        <div class="news-card">
          <div class="news-card-dot"></div>
          <div class="news-card-body">
            <div class="news-card-title">
              ${item.url ? `<a href="${App.escape(item.url)}" target="_blank">${App.escape(item.title)}</a>` : App.escape(item.title)}
            </div>
            <div class="news-card-meta">${App.escape(item.source_name || '')} · ${App.fmtDate(item.published_at)}</div>
          </div>
        </div>
      `).join('') + `<div style="margin-top:10px"><a href="#" onclick="App.goTo('sources');return false" style="font-size:12px;color:var(--accent)">See all news →</a></div>`;
    } catch {
      el.innerHTML = '<div style="color:var(--text3);font-size:13px;padding:16px 0">No news yet</div>';
    }
  }
};

window.addEventListener('DOMContentLoaded', () => App.init());
