const Trends = (() => {
  let _region = 'AE';
  let _timeframe = '30d';
  let _loaded = false;

  // ── Public ──────────────────────────────────────────────────────────────

  async function load() {
    if (_loaded) return;
    _bindTimeframeChips();
    await Promise.all([loadGoogleTrending(), loadYouTubeTrending()]);
    _loaded = true;
  }

  async function refresh() {
    _loaded = false;
    await load();
  }

  function switchTab(tab) {
    document.querySelectorAll('#trends-tabs .tab').forEach(t => {
      t.classList.toggle('active', t.dataset.tab === tab);
    });
    document.querySelectorAll('#screen-trends .tab-content').forEach(c => {
      c.classList.toggle('active', c.id === `trends-tab-${tab}`);
      c.style.display = c.id === `trends-tab-${tab}` ? '' : 'none';
    });
  }

  function setRegion(el, code) {
    _region = code;
    document.querySelectorAll('#trends-region-chips .filter-chip').forEach(c => c.classList.remove('active'));
    el.classList.add('active');
    Promise.all([loadGoogleTrending(), loadYouTubeTrending()]);
  }

  // ── Tab 1: Trending Now ──────────────────────────────────────────────────

  async function loadGoogleTrending() {
    const el = document.getElementById('trends-google-chips');
    if (!el) return;
    App.loading(el, 'Loading Google Trends…');
    try {
      const data = await API.post(`/api/trends/google/trending?region=${_region}`, {});
      if (!data.keywords || !data.keywords.length) {
        el.innerHTML = '<div style="color:var(--text3);font-size:13px">No trending data available for this region.</div>';
      } else {
        el.innerHTML = `<div style="display:flex;flex-direction:column;gap:2px">${
          data.keywords.slice(0, 15).map((kw, i) => `
            <div onclick="Trends.searchKeyword('${kw.replace(/'/g, "\\'")}')"
              style="display:flex;align-items:center;gap:10px;padding:7px 10px;border-radius:8px;cursor:pointer;transition:background .15s"
              onmouseover="this.style.background='rgba(255,255,255,0.06)'"
              onmouseout="this.style.background='transparent'">
              <span style="font-size:11px;font-weight:700;color:var(--text3);min-width:18px;text-align:right">${i + 1}</span>
              <span style="font-size:13px;color:var(--text);flex:1;direction:auto">${App.escape(kw)}</span>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="var(--text3)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            </div>`
          ).join('')
        }</div>`;
      }
      _updateCacheIndicator(data);
    } catch (e) {
      el.innerHTML = `<div style="color:var(--text3);font-size:13px">${App.escape(e.message || 'Error loading Google Trends')}</div>`;
    }
  }

  function searchKeyword(kw) {
    switchTab('keywords');
    const input = document.querySelector('.trends-kw-input');
    if (input) input.value = kw;
    fetchKeywordInterest();
  }

  async function loadYouTubeTrending() {
    const el = document.getElementById('trends-yt-list');
    if (!el) return;
    App.loading(el, 'Loading YouTube trending…');
    const catEl = document.getElementById('trends-yt-category');
    const cat = catEl ? catEl.value : '';
    try {
      const data = await API.get(`/api/trends/youtube?region=${_region}&category_id=${cat}&max_results=20`);
      if (!data.videos || !data.videos.length) {
        el.innerHTML = '<div style="color:var(--text3);font-size:13px">No trending videos found for this region/category.</div>';
      } else {
        el.innerHTML = data.videos.map(_renderVideoCard).join('');
      }
    } catch (e) {
      el.innerHTML = `<div style="color:var(--text3);font-size:13px">${App.escape(e.message || 'Error loading YouTube trending')}</div>`;
    }
  }

  function _renderVideoCard(v) {
    const views = _fmtNum(v.views);
    return `
      <div style="display:flex;gap:10px;margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid rgba(255,255,255,0.05)">
        <a href="${App.escape(v.url)}" target="_blank" style="flex-shrink:0;display:block;width:112px;height:63px;border-radius:6px;overflow:hidden;background:rgba(255,255,255,0.05)">
          ${v.thumbnail
            ? `<img src="${App.escape(v.thumbnail)}" alt="" loading="lazy" style="width:100%;height:100%;object-fit:cover">`
            : '<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:var(--text3);font-size:18px">▶</div>'
          }
        </a>
        <div style="flex:1;min-width:0">
          <a href="${App.escape(v.url)}" target="_blank" style="font-size:12px;font-weight:500;color:var(--text);line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;text-decoration:none">${App.escape(v.title)}</a>
          <div style="font-size:11px;color:var(--text3);margin-top:4px">${App.escape(v.channel)}</div>
          <div style="font-size:11px;color:var(--text3)">${views} views</div>
        </div>
      </div>`;
  }

  // ── Tab 2: Keyword Tracker ───────────────────────────────────────────────

  function addKeywordInput() {
    const container = document.getElementById('trends-kw-inputs');
    const inputs = container.querySelectorAll('.trends-kw-input');
    if (inputs.length >= 5) { App.toast('Max 5 keywords', 'error'); return; }
    const div = document.createElement('div');
    div.style.cssText = 'display:flex;gap:8px';
    div.innerHTML = `<input type="text" class="trends-kw-input" placeholder="Keyword ${inputs.length + 1}" style="flex:1" onkeydown="if(event.key==='Enter')Trends.fetchKeywordInterest()" />
      <button class="btn btn-ghost btn-sm" onclick="this.parentElement.remove()" style="color:var(--red,#f87171)">×</button>`;
    container.appendChild(div);
  }

  async function fetchKeywordInterest() {
    const inputs = document.querySelectorAll('.trends-kw-input');
    const keywords = [...inputs].map(i => i.value.trim()).filter(Boolean);
    if (!keywords.length) { App.toast('Enter at least one keyword', 'error'); return; }

    const region = document.getElementById('trends-kw-region').value;
    const el = document.getElementById('trends-kw-results');
    App.loading(el, 'Fetching keyword trends…');

    try {
      const data = await API.post('/api/trends/google/keywords', { keywords, region, timeframe: _timeframe });
      el.innerHTML = _renderKeywordResults(data);
    } catch (e) {
      el.innerHTML = `<div style="color:var(--text3);font-size:13px">${App.escape(e.message || 'Error fetching trends')}</div>`;
    }
  }

  function _renderKeywordResults(data) {
    const { keywords, interest_over_time, related_topics } = data;
    if (!interest_over_time || !interest_over_time.length) {
      return '<div style="color:var(--text3);font-size:13px;padding:12px 0">No interest data found. Try different keywords or a broader timeframe.</div>';
    }

    const colors = ['var(--accent)', '#22d3ee', '#4ade80', '#fb923c', '#f472b6'];
    const allVals = interest_over_time.flatMap(r => keywords.map(k => r[k] || 0));
    const maxVal = Math.max(...allVals, 1);
    const hasAnyData = allVals.some(v => v > 0);
    if (!hasAnyData) {
      return '<div style="color:var(--text3);font-size:13px;padding:12px 0">Google Trends returned no interest data for this keyword/region. Try a different keyword or broader timeframe.</div>';
    }

    // Legend
    const legend = keywords.map((kw, i) =>
      `<span style="display:inline-flex;align-items:center;gap:5px;margin-right:12px;font-size:12px;color:var(--text2)">
        <span style="width:10px;height:10px;border-radius:2px;background:${colors[i % colors.length]};display:inline-block"></span>
        ${App.escape(kw)}
      </span>`
    ).join('');

    // Bar chart
    const bars = interest_over_time.map((row, idx) => {
      const showLabel = idx % Math.max(1, Math.floor(interest_over_time.length / 8)) === 0;
      const date = String(row.date || '').slice(5); // MM-DD
      const barsHtml = keywords.map((kw, i) => {
        const val = row[kw] || 0;
        const h = maxVal > 0 ? Math.max(2, Math.round((val / maxVal) * 100)) : 2;
        return `<div title="${kw}: ${val}" style="flex:1;height:${h}%;background:${colors[i % colors.length]};border-radius:2px 2px 0 0;min-height:2px"></div>`;
      }).join('');
      return `
        <div style="flex:1;display:flex;flex-direction:column;align-items:stretch;gap:1px">
          <div style="flex:1;display:flex;align-items:flex-end;gap:1px">${barsHtml}</div>
          <div style="font-size:9px;color:var(--text3);text-align:center;overflow:hidden;white-space:nowrap;padding-top:2px">${showLabel ? App.escape(date) : ''}</div>
        </div>`;
    }).join('');

    let html = `
      <div style="margin-bottom:8px">${legend}</div>
      <div style="display:flex;align-items:flex-end;height:130px;gap:2px;padding-bottom:18px;border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:20px">${bars}</div>
    `;

    // Related topics
    const hasTopics = keywords.some(kw => (related_topics[kw] || []).length > 0);
    if (hasTopics) {
      html += `<div style="font-size:12px;font-weight:600;color:var(--text2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px">Related Topics</div>`;
      html += `<div class="grid-2" style="gap:16px">`;
      keywords.forEach((kw, i) => {
        const topics = related_topics[kw] || [];
        if (!topics.length) return;
        html += `
          <div>
            <div style="font-size:12px;color:${colors[i % colors.length]};font-weight:600;margin-bottom:6px">${App.escape(kw)}</div>
            <div>${topics.map(t => `<span class="filter-chip" style="margin:2px 3px 2px 0;cursor:default;font-size:11px">${App.escape(t)}</span>`).join('')}</div>
          </div>`;
      });
      html += `</div>`;
    }

    return html;
  }

  // ── Helpers ──────────────────────────────────────────────────────────────

  function _bindTimeframeChips() {
    document.querySelectorAll('#trends-kw-timeframe .filter-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        document.querySelectorAll('#trends-kw-timeframe .filter-chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        _timeframe = chip.dataset.tf;
      });
    });
  }

  function _updateCacheIndicator(data) {
    const el = document.getElementById('trends-cache-indicator');
    if (!el) return;
    if (data.cached && data.cache_age_seconds != null) {
      const mins = Math.round(data.cache_age_seconds / 60);
      el.textContent = `Cached ${mins}m ago`;
    } else {
      el.textContent = 'Fresh data';
    }
  }

  function _fmtNum(n) {
    if (!n) return '0';
    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return String(n);
  }

  return { load, refresh, switchTab, setRegion, addKeywordInput, fetchKeywordInterest, loadYouTubeTrending, searchKeyword };
})();
