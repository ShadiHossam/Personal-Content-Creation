const App = {
  currentScreen: 'dashboard',

  init() {
    // Navigation
    document.querySelectorAll('.nav-item').forEach(el => {
      el.addEventListener('click', () => this.goTo(el.dataset.screen));
    });

    // Greeting
    const hr = new Date().getHours();
    const greeting = hr < 12 ? 'Good morning' : hr < 17 ? 'Good afternoon' : 'Good evening';
    const el = document.getElementById('greeting');
    if (el) el.textContent = `${greeting}, Shadi`;

    // Load unread badge
    this.updateBadge();
    setInterval(() => this.updateBadge(), 60000);

    // Load dashboard
    Dashboard.load();
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
    document.getElementById('modal-content').innerHTML = html;
    document.getElementById('modal-overlay').style.display = 'flex';
  },

  closeModal(e) {
    document.getElementById('modal-overlay').style.display = 'none';
    document.getElementById('modal-content').innerHTML = '';
    const box = document.getElementById('modal-box');
    if (box) box.style.width = '';
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
      el.innerHTML = landscape.slice(0, 4).map((c, i) => `
        <div class="creator-row" onclick="CreatorProfile.open(${c.id})" title="View profile">
          <div class="creator-avatar" style="font-size:13px;font-weight:700;color:var(--accent)">${i + 1}</div>
          <div class="creator-info">
            <div class="creator-name">${App.escape(c.name)}</div>
            <div class="creator-meta">${c.post_count} posts · ${c.avg_engagement} avg eng.</div>
          </div>
          <button class="btn btn-ghost btn-sm">View →</button>
        </div>
      `).join('');
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
