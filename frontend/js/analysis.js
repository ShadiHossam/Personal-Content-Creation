const Analysis = {
  creators: [],
  selectedId: null,

  _friendlyError(e) {
    const m = e?.message || '';
    if (m.includes('502') || m.includes('not configured') || m.includes('Claude')) return 'Claude is not configured — add an API key in Settings → API Keys.';
    // Only call it "Creator not found" when the failing endpoint is the creator lookup itself.
    if (m.includes('404') && /\/api\/creators\/\d+(?:\s|$|")/.test(m) && !/\/(stats|insights|notes|posts)\b/.test(m)) return 'Creator not found.';
    if (m.includes('404')) return 'A required endpoint was unavailable for a moment — please retry.';
    if (m.includes('422')) return 'Could not extract hooks from this document.';
    if (m.includes('400')) return 'Invalid request — check your inputs.';
    if (m.includes('500')) return 'Server error — try again in a moment.';
    return m || 'Something went wrong. Please try again.';
  },

  renderMarkdown(text) {
    if (!text) return '';
    let html = App.escape(text);
    // Headers
    html = html.replace(/^### (.+)$/gm, '<h4 style="font-size:13px;font-weight:700;color:var(--text);margin:14px 0 4px">$1</h4>');
    html = html.replace(/^## (.+)$/gm, '<h3 style="font-size:14px;font-weight:700;color:var(--text);margin:16px 0 6px">$1</h3>');
    html = html.replace(/^# (.+)$/gm, '<h2 style="font-size:15px;font-weight:700;color:var(--text);margin:18px 0 8px">$1</h2>');
    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Italic
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    // Bullet lists (- or *)
    html = html.replace(/^[•\-\*] (.+)$/gm, '<li style="margin:2px 0;padding-left:2px">$1</li>');
    html = html.replace(/(<li[^>]*>.*<\/li>\n?)+/g, '<ul style="margin:6px 0 8px;padding-left:18px;list-style:disc">$&</ul>');
    // Numbered lists
    html = html.replace(/^\d+\. (.+)$/gm, '<li style="margin:2px 0">$1</li>');
    // Line breaks
    html = html.replace(/\n{2,}/g, '</p><p style="margin:8px 0">');
    html = html.replace(/\n/g, '<br>');
    return `<p style="margin:0">${html}</p>`;
  },
  _landscapeSessionId: null,
  _lastQuestion: null,
  _lastAnswer: null,
  _lastAnswerPosts: null,
  _lastIsFullAnalysis: false,
  _lastDimensions: null,
  _lastMultiAnalysis: null,
  _compareSelectedIds: new Set(),
  _bulkMode: false,
  _bulkSelectedIds: new Set(),
  _activePeriod: 'all',
  _customFrom: null,
  _customTo: null,

  async load() {
    try {
      this.creators = await API.get('/api/creators');
      const sel = document.getElementById('analysis-creator-select');
      if (sel) {
        sel.innerHTML = '<option value="">Select a creator...</option>' +
          this.creators.map(c => `<option value="${c.id}">${App.escape(c.name)} (${c.category})</option>`).join('');
        sel.onchange = () => { const id = parseInt(sel.value); if (id) this.selectCreator(id); };
        if (this.selectedId) {
          sel.value = this.selectedId;
          this.selectCreator(this.selectedId);
        } else {
          this.loadCreatorView(null);
        }
      }
    } catch {}
  },

  switchTab(tab) {
    document.querySelectorAll('#analysis-tabs .tab').forEach(t => {
      t.classList.toggle('active', t.dataset.tab === tab);
    });
    ['single', 'compare', 'hooks', 'style', 'linkedin'].forEach(t => {
      const el = document.getElementById(`analysis-tab-${t}`);
      if (el) el.style.display = t === tab ? 'block' : 'none';
    });
    if (tab === 'single') {
      if (this.selectedId) this.selectCreator(this.selectedId);
      else this.loadCreatorView(null);
    }
    if (tab === 'compare') this.loadCompareTab();
    if (tab === 'hooks') this.loadHooksTab();
    if (tab === 'style') this.loadStyleTab();
    if (tab === 'linkedin') this.loadLinkedInTab();
  },

  selectCreator(id) {
    this.selectedId = id;
    this._activePeriod = 'all';
    this._customFrom = null;
    this._customTo = null;
    const sel = document.getElementById('analysis-creator-select');
    if (sel) sel.value = id;
    document.getElementById('analysis-landscape-view').style.display = 'none';
    document.getElementById('analysis-creator-view').style.display = '';
    this.loadCreatorView(id);
  },

  _periodDates() {
    if (this._activePeriod === 'custom') {
      return { start_date: this._customFrom || undefined, end_date: this._customTo || undefined };
    }
    if (this._activePeriod === 'all') return {};
    const months = parseInt(this._activePeriod);
    const end = new Date();
    const start = new Date();
    start.setMonth(start.getMonth() - months);
    return {
      start_date: start.toISOString().slice(0, 10),
      end_date: end.toISOString().slice(0, 10),
    };
  },

  setPeriod(period, id) {
    this._activePeriod = period;
    if (period !== 'custom') {
      this._customFrom = null;
      this._customTo = null;
      this.reloadStats(id);
    }
    document.querySelectorAll('.period-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.period === period);
    });
    const customRange = document.getElementById('period-custom-range');
    if (customRange) customRange.style.display = period === 'custom' ? 'flex' : 'none';
  },

  async reloadStats(id) {
    const { start_date, end_date } = this._periodDates();
    const params = new URLSearchParams();
    if (start_date) params.set('start_date', start_date);
    if (end_date) params.set('end_date', end_date);
    const qs = params.toString();
    const stats = await API.get(`/api/creators/${id}/stats${qs ? '?' + qs : ''}`);
    const statsEl = document.getElementById('analysis-stats-block');
    if (statsEl) statsEl.innerHTML = this.buildStatsBlock(stats, id);
  },

  buildStatsBlock(stats, id) {
    if (!stats.total) return `<div class="card" style="margin-bottom:20px;color:var(--text3);text-align:center;padding:32px 20px">
      <div style="font-size:32px;margin-bottom:8px">📭</div>
      <div style="font-size:13px">No content in this period.</div>
      <button class="btn btn-primary btn-sm" style="margin-top:12px" onclick="Creators.fetchOne(${id})">Fetch Posts Now</button>
    </div>`;
    return `
    <div class="grid-2" style="gap:16px;margin-bottom:20px">
      <div class="card">
        <div style="font-size:12px;font-weight:600;color:var(--text);margin-bottom:14px">Posting Behavior</div>
        <div class="metric-strip">
          <div class="metric-pill"><div class="metric-pill-value">${stats.frequency}</div><div class="metric-pill-label">Frequency</div></div>
          <div class="metric-pill"><div class="metric-pill-value">${stats.best_day}</div><div class="metric-pill-label">Best Day</div></div>
          <div class="metric-pill"><div class="metric-pill-value">${stats.total}</div><div class="metric-pill-label">Total Posts</div></div>
        </div>
      </div>
      <div class="card">
        <div style="font-size:12px;font-weight:600;color:var(--text);margin-bottom:14px">Engagement</div>
        ${this.buildBar('Likes', stats.engagement?.avg_likes, stats.engagement?.avg_total)}
        ${this.buildBar('Comments', stats.engagement?.avg_comments, stats.engagement?.avg_total)}
        ${this.buildBar('Shares', stats.engagement?.avg_shares, stats.engagement?.avg_total)}
        <div style="font-size:12px;color:var(--text3);margin-top:10px">Avg per post: <strong style="color:var(--text)">${stats.engagement?.avg_total}</strong></div>
      </div>
    </div>
    <div class="card" style="margin-bottom:20px">
      <div style="font-size:12px;font-weight:600;color:var(--text);margin-bottom:14px">Format Breakdown</div>
      <div class="bar-chart">
        ${Object.entries(stats.formats || {}).map(([fmt, count]) =>
          `${this.buildBar(fmt, count, Math.max(...Object.values(stats.formats)))}`
        ).join('')}
      </div>
    </div>`;
  },

  async loadCreatorView(id) {
    const el = document.getElementById('analysis-creator-view');
    if (!el) return;
    if (!id) {
      el.innerHTML = `<div class="empty-state" style="margin-top:40px"><div class="empty-icon">📊</div><h3>Select a creator to begin</h3><p>Choose a creator from the dropdown above to see their posting stats, ask Claude about their strategy, and save insights.</p></div>`;
      return;
    }
    App.loading(el, 'Loading analysis...');

    const { start_date, end_date } = this._periodDates();
    const params = new URLSearchParams();
    if (start_date) params.set('start_date', start_date);
    if (end_date) params.set('end_date', end_date);
    const qs = params.toString();

    const fetchAll = () => Promise.all([
      API.get(`/api/creators/${id}`),
      API.get(`/api/creators/${id}/stats${qs ? '?' + qs : ''}`),
      API.get(`/api/analysis/insights/${id}`),
    ]);

    try {
      let creator, stats, insights;
      try {
        [creator, stats, insights] = await fetchAll();
      } catch (firstErr) {
        // Dev server uvicorn --reload can return a single transient 404 during restart.
        // Retry once after a brief delay before surfacing the error.
        const msg = firstErr?.message || '';
        if (msg.includes('404') || msg.includes('Failed to fetch')) {
          await new Promise(r => setTimeout(r, 1200));
          [creator, stats, insights] = await fetchAll();
        } else {
          throw firstErr;
        }
      }

      el.innerHTML = `
        <div class="analysis-creator-header">
          <div style="flex:1;min-width:0">
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:4px">
              <span style="font-size:18px;font-weight:700;color:var(--text);letter-spacing:-0.3px">${App.escape(creator.name)}</span>
              <span class="creator-cat-badge ${creator.category === 'competitor' ? 'cat-competitor' : 'cat-inspiration'}">${creator.category}</span>
            </div>
            <div style="font-size:12px;color:var(--text3);display:flex;gap:8px;align-items:center;flex-wrap:wrap">
              ${creator.country ? `<span>${App.escape(creator.country)}</span>` : ''}
              <span>${stats.total} posts tracked</span>
            </div>
          </div>
          <div style="display:flex;gap:8px;flex-shrink:0">
            <button class="btn btn-ghost btn-sm" onclick="CreatorProfile.open(${id})">View Profile</button>
            <button class="btn btn-ghost btn-sm" onclick="Creators.fetchOne(${id})">↻ Refresh</button>
          </div>
        </div>

        <div class="period-selector">
          ${['all','1','3','6','9','12','custom'].map(p => {
            const label = p === 'all' ? 'All' : p === 'custom' ? 'Custom' : `${p}M`;
            const active = this._activePeriod === p ? ' active' : '';
            return `<button class="period-btn${active}" data-period="${p}" onclick="Analysis.setPeriod('${p}', ${id})">${label}</button>`;
          }).join('')}
          <div id="period-custom-range" class="period-custom-range" style="display:${this._activePeriod === 'custom' ? 'flex' : 'none'}">
            <input type="date" id="period-from" value="${this._customFrom || ''}" onchange="Analysis._customFrom=this.value">
            <span style="color:var(--text3);font-size:12px">to</span>
            <input type="date" id="period-to" value="${this._customTo || ''}" onchange="Analysis._customTo=this.value">
            <button class="btn btn-primary btn-sm" onclick="Analysis.reloadStats(${id})">Apply</button>
          </div>
        </div>

        <div id="analysis-stats-block">
          ${this.buildStatsBlock(stats, id)}
        </div>

        <div class="card" style="margin-bottom:20px">
          <div style="font-size:12px;font-weight:600;color:var(--text);margin-bottom:14px">Ask Claude About This Creator</div>
          <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap">
            <select id="ask-limit" style="width:auto">
              <option value="10">Last 10 posts</option>
              <option value="20" selected>Last 20 posts</option>
              <option value="50">Last 50 posts</option>
            </select>
            <select id="ask-platform" style="width:auto">
              <option value="">All platforms</option>
              <option value="linkedin">LinkedIn</option>
              <option value="twitter">Twitter</option>
              <option value="youtube">YouTube</option>
            </select>
            <button class="btn btn-primary btn-sm" onclick="Analysis.runFullAnalysis(${id})">Full Analysis</button>
          </div>
          <textarea id="ask-question" rows="3" placeholder="What is their content strategy and what can I learn from them?&#10;What topics perform best for them?"></textarea>
          <div style="margin-top:8px;display:flex;gap:8px">
            <button class="btn btn-primary" onclick="Analysis.ask(${id})">Ask Claude</button>
          </div>
          <div id="ask-answer" style="margin-top:12px;display:none">
            <div class="divider"></div>
            <div id="ask-answer-text" style="font-size:13.5px;line-height:1.7;color:var(--text)"></div>
            <div id="ask-posts-meta" style="display:none;font-size:11px;color:var(--text3);margin-top:8px"></div>
            <div id="save-answer-actions" style="margin-top:10px;display:flex;gap:8px">
              <button class="btn btn-secondary btn-sm" id="save-answer-btn" onclick="Analysis.saveCurrentAnswer(${id})">Save Insight</button>
              <button class="btn btn-ghost btn-sm" onclick="document.getElementById('ask-answer').style.display='none'">Discard</button>
            </div>
          </div>
        </div>

        <div class="card">
          <div style="font-size:12px;font-weight:600;color:var(--text);margin-bottom:14px">Saved Insights</div>
          <div id="insights-list-${id}">
            ${insights.length ? insights.map(ins => {
              const full = ins.answer || '';
              const preview = full.substring(0, 200);
              const hasMore = full.length > 200;
              return `
              <div class="insight-item" data-insight-id="${ins.id}">
                <div class="insight-item-header">
                  <svg class="insight-item-pin" width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/></svg>
                  <div class="insight-item-title">${App.escape(ins.title || 'Insight')}</div>
                  <div class="insight-item-date">${App.fmtDate(ins.created_at)}</div>
                  <button class="btn btn-ghost btn-sm" style="padding:2px 8px" onclick="Analysis.deleteInsight(${ins.id}, ${id})">×</button>
                </div>
                <div class="insight-item-body" id="insight-body-${ins.id}">${App.escape(preview)}${hasMore ? '...' : ''}</div>
                ${hasMore ? `<button class="btn btn-ghost btn-sm" style="padding:2px 6px;font-size:11px;margin-top:4px" onclick="Analysis.toggleInsight(${ins.id}, ${JSON.stringify(full).replace(/</g,'\\u003c')})">Show more ▾</button>` : ''}
              </div>`;
            }).join('') : '<div style="color:var(--text3);font-size:13px;padding:8px 0">No insights saved yet.</div>'}
          </div>
        </div>
      `;
    } catch (e) {
      el.innerHTML = `<div class="empty-state"><p style="color:var(--red)">${App.escape(this._friendlyError(e))}</p></div>`;
    }
  },

  buildBar(label, value, max) {
    const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
    return `
      <div class="bar-row">
        <div class="bar-label">${App.escape(label)}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
        <div class="bar-value">${value}</div>
      </div>
    `;
  },

  async ask(creatorId) {
    const q = document.getElementById('ask-question')?.value?.trim();
    if (!q) { App.toast('Enter a question first', 'error'); return; }
    const limit = parseInt(document.getElementById('ask-limit')?.value) || 20;
    const platform = document.getElementById('ask-platform')?.value || null;

    const answerEl = document.getElementById('ask-answer');
    const textEl = document.getElementById('ask-answer-text');
    if (!answerEl || !textEl) return;
    answerEl.style.display = 'block';
    textEl.innerHTML = '<div style="display:flex;align-items:center;gap:10px;padding:12px 0"><div class="spinner" style="width:18px;height:18px;flex-shrink:0"></div><span style="font-size:12.5px;color:var(--text3)">Claude is thinking… this can take 10–30 seconds</span></div>';

    this._lastQuestion = q;
    this._lastAnswerPosts = limit;
    this._lastIsFullAnalysis = false;

    try {
      const data = await API.post('/api/analysis/ask', { creator_id: creatorId, question: q, limit, platform });
      textEl.innerHTML = this.renderMarkdown(data.answer);
      this._lastAnswer = data.answer;
      const metaEl = document.getElementById('ask-posts-meta');
      if (metaEl) { metaEl.textContent = `Analyzed ${data.posts_analyzed} post${data.posts_analyzed !== 1 ? 's' : ''}`; metaEl.style.display = ''; }
      const saveBtn = document.getElementById('save-answer-btn');
      if (saveBtn) saveBtn.textContent = 'Save Insight';
    } catch (e) {
      textEl.innerHTML = `<span style="color:var(--red)">${App.escape(this._friendlyError(e))}</span>`;
    }
  },

  async runFullAnalysis(creatorId) {
    const limit = parseInt(document.getElementById('ask-limit')?.value) || 20;
    const answerEl = document.getElementById('ask-answer');
    const textEl = document.getElementById('ask-answer-text');
    if (!answerEl || !textEl) return;
    answerEl.style.display = 'block';
    textEl.innerHTML = '<div style="display:flex;align-items:center;gap:10px;padding:12px 0"><div class="spinner" style="width:18px;height:18px;flex-shrink:0"></div><span style="font-size:12.5px;color:var(--text3)">Running 7-dimension analysis… this can take 20–40 seconds</span></div>';
    this._lastQuestion = 'Full Analysis';
    this._lastAnswerPosts = limit;
    this._lastIsFullAnalysis = true;
    this._lastDimensions = null;

    try {
      const data = await API.postQuery('/api/analysis/full-analysis', { creator_id: creatorId, limit });
      const metaEl = document.getElementById('ask-posts-meta');
      if (metaEl) { metaEl.textContent = `Analyzed ${data.posts_analyzed} post${data.posts_analyzed !== 1 ? 's' : ''}`; metaEl.style.display = ''; }

      if (data.structured && data.dimensions) {
        this._lastDimensions = data.dimensions;
        this._lastAnswer = JSON.stringify(data.dimensions);
        textEl.innerHTML = this._renderDimensionCards(data.dimensions, creatorId);
        const actionsEl = document.getElementById('save-answer-actions');
        if (actionsEl) actionsEl.style.display = 'none';
      } else {
        // Fallback: render as markdown
        this._lastAnswer = data.analysis_text || '';
        textEl.innerHTML = this.renderMarkdown(this._lastAnswer);
        const actionsEl = document.getElementById('save-answer-actions');
        if (actionsEl) { actionsEl.style.display = ''; }
        const saveBtn = document.getElementById('save-answer-btn');
        if (saveBtn) saveBtn.textContent = 'Save Analysis';
      }
    } catch (e) {
      textEl.innerHTML = `<span style="color:var(--red)">${App.escape(this._friendlyError(e))}</span>`;
    }
  },

  _dimensionConfig() {
    return [
      { key: 'pillars',     icon: '🏛', label: 'Content Pillars',       desc: 'Core topics + the emotion/pain each targets' },
      { key: 'formats',     icon: '📐', label: 'Format & Structure',     desc: 'How they structure their posts' },
      { key: 'hooks',       icon: '🪝', label: 'Hook Analysis',          desc: 'Opening lines that grab attention' },
      { key: 'ctas',        icon: '📣', label: 'CTA Patterns',           desc: 'How they close their posts' },
      { key: 'engagement',  icon: '📈', label: 'Engagement Insights',    desc: 'What performs best and why' },
      { key: 'tone',        icon: '🎙', label: 'Tone & Voice',           desc: 'Writing personality with examples' },
      { key: 'positioning', icon: '🎯', label: 'Strategic Positioning',  desc: 'Unique angle + what Shadi can adapt' },
    ];
  },

  _renderDimensionCards(dims, creatorId) {
    const configs = this._dimensionConfig();
    return configs.map(cfg => {
      const raw = dims[cfg.key];
      if (!raw) return '';
      const bodyHtml = this._renderDimensionBody(cfg.key, raw);
      const cardId = `dim-card-${cfg.key}`;
      const bodyId = `dim-body-${cfg.key}`;
      return `
        <div class="card" id="${cardId}" style="margin-bottom:10px;padding:0;overflow:hidden">
          <div style="display:flex;align-items:center;gap:10px;padding:12px 14px;cursor:pointer;user-select:none"
               onclick="Analysis._toggleDimCard('${bodyId}')">
            <span style="font-size:18px">${cfg.icon}</span>
            <div style="flex:1;min-width:0">
              <div style="font-size:13px;font-weight:700;color:var(--text)">${cfg.label}</div>
              <div style="font-size:11px;color:var(--text3)">${cfg.desc}</div>
            </div>
            <div style="display:flex;gap:6px;align-items:center">
              <button class="btn btn-secondary btn-sm" style="font-size:11px;padding:3px 10px"
                onclick="event.stopPropagation();Analysis.saveDimensionInsight(${creatorId},'${cfg.key}','${cfg.label}',${JSON.stringify(JSON.stringify(raw)).replace(/</g,'\\u003c')})">
                Save
              </button>
              <span id="dim-chevron-${cfg.key}" style="color:var(--text3);font-size:12px;transition:transform 0.2s">▾</span>
            </div>
          </div>
          <div id="${bodyId}" style="padding:0 14px 14px;border-top:1px solid var(--border)">
            ${bodyHtml}
          </div>
        </div>`;
    }).join('');
  },

  _toggleDimCard(bodyId) {
    const body = document.getElementById(bodyId);
    if (!body) return;
    const key = bodyId.replace('dim-body-', '');
    const chevron = document.getElementById(`dim-chevron-${key}`);
    const hidden = body.style.display === 'none';
    body.style.display = hidden ? '' : 'none';
    if (chevron) chevron.style.transform = hidden ? 'rotate(180deg)' : '';
  },

  _renderDimensionBody(key, data) {
    if (key === 'pillars' && Array.isArray(data)) {
      return `<div style="display:flex;flex-direction:column;gap:8px;padding-top:10px">` +
        data.map(p => `
          <div style="background:var(--bg3);border-radius:8px;padding:10px 12px">
            <div style="font-size:13px;font-weight:700;color:var(--text);margin-bottom:2px">${App.escape(p.topic || '')}</div>
            <div style="font-size:12px;color:var(--text2)">Targets: <em>${App.escape(p.emotion || '')}</em></div>
            ${p.share ? `<div style="font-size:11px;color:var(--text3);margin-top:2px">${App.escape(p.share)} of posts</div>` : ''}
          </div>`).join('') + `</div>`;
    }
    if (key === 'formats' && Array.isArray(data)) {
      return `<div style="display:flex;flex-direction:column;gap:8px;padding-top:10px">` +
        data.map(f => `
          <div style="background:var(--bg3);border-radius:8px;padding:10px 12px">
            <div style="font-size:13px;font-weight:700;color:var(--text);margin-bottom:3px">${App.escape(f.type || '')}</div>
            <div style="font-size:12px;color:var(--text2);margin-bottom:4px">${App.escape(f.description || '')}</div>
            ${f.example ? `<div style="font-size:11px;color:var(--text3);font-style:italic">"${App.escape(f.example)}"</div>` : ''}
          </div>`).join('') + `</div>`;
    }
    if (key === 'hooks' && Array.isArray(data)) {
      const typeColors = { question:'#3b82f6',stat:'#10b981',story:'#f59e0b',bold_claim:'#ef4444',pain_point:'#8b5cf6',curiosity_gap:'#06b6d4',other:'#6b7280' };
      return `<div style="display:flex;flex-direction:column;gap:8px;padding-top:10px">` +
        data.map(h => {
          const col = typeColors[h.type] || '#6b7280';
          return `
          <div style="background:var(--bg3);border-radius:8px;padding:10px 12px">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
              <span style="font-size:10px;font-weight:700;padding:2px 7px;border-radius:20px;background:${col}22;color:${col}">${App.escape(h.type || 'other').replace(/_/g,' ')}</span>
            </div>
            <div style="font-size:13px;color:var(--text);font-style:italic;margin-bottom:4px">"${App.escape(h.example || '')}"</div>
            <div style="font-size:12px;color:var(--text3)">${App.escape(h.why_it_works || '')}</div>
          </div>`;
        }).join('') + `</div>`;
    }
    if (key === 'ctas' && Array.isArray(data)) {
      return `<div style="display:flex;flex-direction:column;gap:6px;padding-top:10px">` +
        data.map(c => `
          <div style="background:var(--bg3);border-radius:8px;padding:9px 12px;display:flex;justify-content:space-between;align-items:center;gap:8px">
            <div style="font-size:13px;color:var(--text);font-style:italic">"${App.escape(c.pattern || '')}"</div>
            ${c.frequency ? `<div style="font-size:11px;color:var(--text3);flex-shrink:0">${App.escape(c.frequency)}</div>` : ''}
          </div>`).join('') + `</div>`;
    }
    if (key === 'engagement' && typeof data === 'object') {
      const best = (data.best_posts || []).map(p => `
        <div style="background:#10b98111;border-radius:6px;padding:8px 10px;margin-bottom:6px">
          <div style="font-size:12px;font-weight:600;color:#10b981;margin-bottom:2px">✓ ${App.escape(p.summary || '')}</div>
          <div style="font-size:11px;color:var(--text2)">${App.escape(p.why || '')}</div>
        </div>`).join('');
      const worst = (data.worst_posts || []).map(p => `
        <div style="background:#ef444411;border-radius:6px;padding:8px 10px;margin-bottom:6px">
          <div style="font-size:12px;font-weight:600;color:#ef4444;margin-bottom:2px">✗ ${App.escape(p.summary || '')}</div>
          <div style="font-size:11px;color:var(--text2)">${App.escape(p.why || '')}</div>
        </div>`).join('');
      return `<div style="padding-top:10px">
        ${data.key_insight ? `<div style="background:var(--accent-dim);border-radius:8px;padding:10px 12px;margin-bottom:12px;font-size:13px;color:var(--accent);font-weight:600">${App.escape(data.key_insight)}</div>` : ''}
        ${best ? `<div style="font-size:11px;font-weight:700;color:var(--text3);margin-bottom:6px">BEST POSTS</div>${best}` : ''}
        ${worst ? `<div style="font-size:11px;font-weight:700;color:var(--text3);margin:10px 0 6px">NEEDS WORK</div>${worst}` : ''}
      </div>`;
    }
    if (key === 'tone' && Array.isArray(data)) {
      return `<div style="display:flex;flex-direction:column;gap:8px;padding-top:10px">` +
        data.map(t => `
          <div style="display:flex;align-items:flex-start;gap:10px">
            <span style="font-size:13px;font-weight:700;color:var(--accent);min-width:80px">${App.escape(t.adjective || '')}</span>
            <span style="font-size:12px;color:var(--text2);font-style:italic">"${App.escape(t.evidence || '')}"</span>
          </div>`).join('') + `</div>`;
    }
    if (key === 'positioning' && typeof data === 'object') {
      return `<div style="display:flex;flex-direction:column;gap:10px;padding-top:10px">
        ${data.unique_angle ? `<div style="background:var(--bg3);border-radius:8px;padding:10px 12px"><div style="font-size:11px;font-weight:700;color:var(--text3);margin-bottom:4px">UNIQUE ANGLE</div><div style="font-size:13px;color:var(--text)">${App.escape(data.unique_angle)}</div></div>` : ''}
        ${data.gap_for_shadi ? `<div style="background:var(--accent-dim);border-radius:8px;padding:10px 12px;border:1px solid var(--accent)44"><div style="font-size:11px;font-weight:700;color:var(--accent);margin-bottom:4px">OPPORTUNITY FOR SHADI</div><div style="font-size:13px;color:var(--text)">${App.escape(data.gap_for_shadi)}</div></div>` : ''}
        ${data.key_lesson ? `<div style="background:var(--bg3);border-radius:8px;padding:10px 12px"><div style="font-size:11px;font-weight:700;color:var(--text3);margin-bottom:4px">KEY LESSON</div><div style="font-size:13px;color:var(--text)">${App.escape(data.key_lesson)}</div></div>` : ''}
      </div>`;
    }
    // Generic fallback
    return `<div style="padding-top:10px;font-size:13px;color:var(--text);white-space:pre-wrap">${App.escape(JSON.stringify(data, null, 2))}</div>`;
  },

  async saveDimensionInsight(creatorId, dimension, dimensionLabel, rawJson) {
    let content;
    try {
      const parsed = JSON.parse(rawJson);
      content = JSON.stringify(parsed, null, 2);
    } catch { content = rawJson; }
    const today = new Date().toISOString().slice(0, 10);
    const title = `${dimensionLabel} — ${today}`;
    try {
      await API.post('/api/analysis/insights', {
        creator_id: creatorId,
        title,
        question: `Full Analysis: ${dimensionLabel}`,
        answer: content,
        posts_analyzed: this._lastAnswerPosts || 0,
      });
      App.toast(`${dimensionLabel} saved!`, 'success');
      this.loadCreatorView(creatorId);
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  async saveInsight(creatorId) {
    if (!this._lastAnswer) return;
    const title = prompt('Title for this insight:', this._lastQuestion?.substring(0, 50) || 'Analysis');
    if (!title) return;
    try {
      await API.post('/api/analysis/insights', {
        creator_id: creatorId,
        title,
        question: this._lastQuestion || '',
        answer: this._lastAnswer,
        posts_analyzed: this._lastAnswerPosts || 0,
      });
      App.toast('Insight saved!', 'success');
      this.loadCreatorView(creatorId);
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  async saveCurrentAnswer(creatorId) {
    if (!this._lastAnswer) return;
    if (this._lastIsFullAnalysis && this._lastDimensions) {
      // Structured analysis — user should use per-dimension save buttons
      App.toast('Use the Save buttons on each dimension card above.', 'error');
      return;
    }
    if (this._lastIsFullAnalysis) {
      const today = new Date().toISOString().slice(0, 10);
      const title = `Full Analysis — ${today}`;
      try {
        await API.post('/api/analysis/insights', {
          creator_id: creatorId,
          title,
          question: 'Full Analysis',
          answer: this._lastAnswer,
          posts_analyzed: this._lastAnswerPosts || 0,
        });
        App.toast('Analysis saved!', 'success');
        this.loadCreatorView(creatorId);
      } catch (e) {
        App.toast(e.message, 'error');
      }
    } else {
      await this.saveInsight(creatorId);
    }
  },

  async deleteInsight(insightId, creatorId) {
    try {
      await API.del(`/api/analysis/insights/${insightId}`);
      App.toast('Deleted', 'success');
      this.loadCreatorView(creatorId);
    } catch {}
  },

  toggleInsight(id, fullText) {
    const body = document.getElementById(`insight-body-${id}`);
    const btn = body?.nextElementSibling;
    if (!body || !btn) return;
    const expanded = btn.textContent.includes('▴');
    if (expanded) {
      body.textContent = fullText.substring(0, 200) + '...';
      btn.textContent = 'Show more ▾';
    } else {
      body.textContent = fullText;
      btn.textContent = 'Show less ▴';
    }
  },

  _landscapeFilter: 'all',

  async showLandscape(filter) {
    if (filter) this._landscapeFilter = filter;
    document.getElementById('analysis-creator-view').style.display = 'none';
    const el = document.getElementById('analysis-landscape-view');
    el.style.display = '';
    App.loading(el, 'Loading creators overview...');

    try {
      const param = this._landscapeFilter !== 'all' ? `?category=${this._landscapeFilter}` : '';
      const data = await API.get(`/api/analysis/landscape${param}`);

      if (!data.length) {
        el.innerHTML = `
          ${this._landscapeFilterPills()}
          <div class="empty-state"><div class="empty-icon">📊</div><h3>No creators found</h3><p>Add creators and fetch their content first.</p></div>`;
        return;
      }

      const maxEng = Math.max(...data.map(d => d.avg_engagement)) || 1;
      const catLabel = this._landscapeFilter === 'all' ? 'All' : (this._landscapeFilter === 'competitor' ? 'Competitor' : 'Inspiration');

      el.innerHTML = `
        ${this._landscapeFilterPills()}
        <div class="section-title">${data.length} ${catLabel} Creator${data.length !== 1 ? 's' : ''} — Engagement Overview</div>
        <div class="card" style="margin-bottom:16px">
          <div class="bar-chart">
            ${data.map(c => {
              const catColor = c.category === 'competitor' ? 'var(--red)' : 'var(--accent)';
              const platforms = (c.platforms || []).join(' · ').toUpperCase();
              return `
              <div class="bar-row">
                <div class="bar-label" style="display:flex;flex-direction:column;gap:2px;min-width:130px">
                  <span style="font-weight:600">${App.escape(c.name)}</span>
                  <span style="font-size:10px;color:var(--text3)">${platforms || '—'} · ${c.post_count} posts</span>
                </div>
                <div class="bar-track" style="flex:1">
                  <div class="bar-fill" style="width:${Math.round((c.avg_engagement/maxEng)*100)}%;background:linear-gradient(90deg,${catColor},var(--accent))"></div>
                </div>
                <div class="bar-value" style="min-width:70px;text-align:right">${c.avg_engagement} avg</div>
                <div style="display:flex;gap:4px;margin-left:8px;flex-shrink:0">
                  <button class="btn btn-ghost btn-sm" style="padding:2px 8px;font-size:11px" onclick="Analysis.selectCreator(${c.id})">View →</button>
                  <button class="btn btn-ghost btn-sm" style="padding:2px 8px;font-size:11px" onclick="Analysis._openCompareWith(${c.id})">Compare</button>
                </div>
              </div>`;
            }).join('')}
          </div>
        </div>
        <div class="section-title">Ask Claude About All Creators</div>
        <div class="card">
          <textarea id="landscape-question" rows="3" placeholder="Who has the strongest content strategy and why?&#10;What topics are all creators covering?&#10;Where are the content gaps I could fill?"></textarea>
          <div style="margin-top:8px">
            <button class="btn btn-primary" onclick="Analysis.askLandscape()">Ask Claude</button>
          </div>
          <div id="landscape-answer" style="margin-top:12px;display:none">
            <div class="divider"></div>
            <div id="landscape-answer-text" style="font-size:13.5px;line-height:1.7;color:var(--text)"></div>
          </div>
        </div>
      `;
    } catch (e) {
      el.innerHTML = `<div class="empty-state"><p style="color:var(--red)">${App.escape(e.message)}</p></div>`;
    }
  },

  _landscapeFilterPills() {
    const filters = [
      { key: 'all', label: 'All' },
      { key: 'competitor', label: 'Competitors' },
      { key: 'inspiration', label: 'Inspirations' },
    ];
    return `
      <div style="display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap">
        ${filters.map(f => `
          <button onclick="Analysis.showLandscape('${f.key}')"
            style="padding:5px 14px;border-radius:20px;border:1px solid ${this._landscapeFilter === f.key ? 'var(--accent)' : 'var(--border)'};background:${this._landscapeFilter === f.key ? 'var(--accent-dim)' : 'transparent'};color:${this._landscapeFilter === f.key ? 'var(--accent)' : 'var(--text2)'};font-size:12px;font-weight:600;cursor:pointer">
            ${f.label}
          </button>
        `).join('')}
      </div>`;
  },

  _openCompareWith(creatorId) {
    this._compareSelectedIds.add(creatorId);
    this.switchTab('compare');
  },

  async askLandscape() {
    const q = document.getElementById('landscape-question')?.value?.trim();
    if (!q) return;
    const answerEl = document.getElementById('landscape-answer');
    const textEl = document.getElementById('landscape-answer-text');
    if (!answerEl || !textEl) return;
    answerEl.style.display = 'block';
    textEl.innerHTML = '<div style="display:flex;align-items:center;gap:10px;padding:12px 0"><div class="spinner" style="width:18px;height:18px;flex-shrink:0"></div><span style="font-size:12.5px;color:var(--text3)">Claude is thinking… this can take 10–30 seconds</span></div>';
    try {
      if (!this._landscapeSessionId) {
        const session = await API.post('/api/intelligence/sessions', {});
        this._landscapeSessionId = session.id;
      }
      const data = await API.post(`/api/intelligence/sessions/${this._landscapeSessionId}/chat`, { content: q });
      textEl.innerHTML = this.renderMarkdown(data.answer);
    } catch (e) {
      this._landscapeSessionId = null;
      textEl.innerHTML = `<span style="color:var(--red)">${App.escape(e.message)}</span>`;
    }
  },

  // ─── Compare Tab ────────────────────────────────────────────────────────────

  async loadCompareTab() {
    const el = document.getElementById('analysis-compare-view');
    if (!el) return;
    try {
      if (!this.creators.length) await this.load();
      if (!this.creators.length) {
        el.innerHTML = `<div class="empty-state"><h3>No creators yet</h3><p>Add creators first in the Creators section.</p></div>`;
        return;
      }
      const checkboxes = this.creators.map(c => `
        <label style="display:flex;align-items:center;gap:8px;padding:6px 0;cursor:pointer;font-size:13px">
          <input type="checkbox" class="compare-creator-check" value="${c.id}"
            style="accent-color:var(--accent)"
            ${this._compareSelectedIds.has(c.id) ? 'checked' : ''}
            onchange="Analysis._onCompareCheck(${c.id}, this.checked)">
          <span>${App.escape(c.name)}</span>
          <span style="color:var(--text3);font-size:11px">${App.escape(c.category)}</span>
        </label>
      `).join('');

      el.innerHTML = `
        <div class="card" style="margin-bottom:16px">
          <div style="font-size:12px;font-weight:600;color:var(--text);margin-bottom:12px">Select Creators to Compare (2–10)</div>
          <div style="column-count:2;column-gap:16px">${checkboxes}</div>
          <div style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn btn-primary btn-sm" onclick="Analysis.runMultiAnalysis()">Cross-Account Analysis</button>
            <button class="btn btn-secondary btn-sm" onclick="Analysis.runExtractHooksCompare()">Extract Hooks</button>
            <button class="btn btn-secondary btn-sm" onclick="Analysis.runExtractStyleCompare()">Extract Style DNA</button>
          </div>
        </div>
        <div class="card" style="margin-bottom:16px">
          <div style="font-size:12px;font-weight:600;color:var(--text);margin-bottom:8px">Custom Question (optional)</div>
          <textarea id="compare-question" rows="2" placeholder="Which creator should I model my content after and why?"></textarea>
        </div>
        <div id="compare-result"></div>
        <div id="compare-saved-list"></div>
      `;
      this.loadSavedBulkAnalyses();
    } catch (e) {
      el.innerHTML = `<div class="empty-state"><p style="color:var(--red)">${App.escape(e.message || 'Failed to load Compare tab')}</p></div>`;
    }
  },

  _onCompareCheck(id, checked) {
    if (checked) this._compareSelectedIds.add(id);
    else this._compareSelectedIds.delete(id);
  },

  _getCheckedCreatorIds() {
    const fromDom = Array.from(document.querySelectorAll('.compare-creator-check:checked')).map(cb => parseInt(cb.value));
    return fromDom.length ? fromDom : Array.from(this._compareSelectedIds);
  },

  async runMultiAnalysis() {
    const ids = this._getCheckedCreatorIds();
    if (ids.length < 2) { App.toast('Select at least 2 creators', 'error'); return; }
    const question = document.getElementById('compare-question')?.value?.trim() || null;
    const el = document.getElementById('compare-result');
    App.loading(el, 'Running cross-account analysis… this can take 20–40 seconds');
    try {
      const data = await API.post('/api/analysis/multi-analysis', { creator_ids: ids, question, limit: 20 });
      this._lastMultiAnalysis = data;
      const names = data.creators_analyzed.map(c => c.name).join(', ');
      el.innerHTML = `
        <div class="card">
          <div style="font-size:12px;font-weight:600;color:var(--text);margin-bottom:4px">Cross-Account Analysis</div>
          <div style="font-size:11px;color:var(--text3);margin-bottom:14px">${App.escape(names)}</div>
          <div style="font-size:13.5px;line-height:1.8;color:var(--text)">${this.renderMarkdown(data.analysis)}</div>
          <div style="margin-top:12px;display:flex;gap:8px">
            <button class="btn btn-secondary btn-sm" onclick="Analysis.saveBulkAnalysis()">Save Analysis</button>
          </div>
        </div>
      `;
    } catch (e) {
      el.innerHTML = `<div class="empty-state"><p style="color:var(--red)">${App.escape(e.message)}</p></div>`;
    }
  },

  async saveBulkAnalysis() {
    const data = this._lastMultiAnalysis;
    if (!data) return;
    const today = new Date().toISOString().slice(0, 10);
    const names = data.creators_analyzed.map(c => c.name).join(', ');
    const title = `Cross-Account: ${names} — ${today}`;
    try {
      await API.post('/api/analysis/bulk-analyses', {
        title,
        creator_ids: data.creators_analyzed.map(c => c.id),
        creator_names: data.creators_analyzed.map(c => c.name),
        question: document.getElementById('compare-question')?.value?.trim() || null,
        analysis_text: data.analysis,
        posts_per_creator: data.posts_per_creator,
      });
      App.toast('Analysis saved!', 'success');
      this.loadSavedBulkAnalyses();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  async loadSavedBulkAnalyses() {
    const el = document.getElementById('compare-saved-list');
    if (!el) return;
    try {
      const items = await API.get('/api/analysis/bulk-analyses');
      if (!items.length) {
        el.innerHTML = '';
        return;
      }
      el.innerHTML = `
        <div style="font-size:12px;font-weight:600;color:var(--text);margin:20px 0 10px">Saved Analyses</div>
        <div style="display:flex;flex-direction:column;gap:10px">
          ${items.map(item => `
            <div class="card" style="padding:12px 14px">
              <div style="display:flex;align-items:flex-start;gap:8px">
                <div style="flex:1;min-width:0">
                  <div style="font-size:13px;font-weight:600;color:var(--text);margin-bottom:3px">${App.escape(item.title)}</div>
                  <div style="font-size:11px;color:var(--text3);margin-bottom:8px">${App.fmtDate(item.created_at)} · ${item.posts_per_creator} posts/creator</div>
                  <div id="bulk-body-${item.id}" style="font-size:12.5px;line-height:1.7;color:var(--text2);white-space:pre-wrap;display:none">${App.escape(item.analysis_text)}</div>
                  <button class="btn btn-ghost btn-sm" style="padding:2px 8px;font-size:11px" onclick="Analysis._toggleBulkBody(${item.id})">Show ▾</button>
                </div>
                <button class="btn btn-ghost btn-sm" style="padding:2px 8px;flex-shrink:0" onclick="Analysis.deleteBulkAnalysis(${item.id})">×</button>
              </div>
            </div>
          `).join('')}
        </div>
      `;
    } catch {}
  },

  _toggleBulkBody(id) {
    const body = document.getElementById(`bulk-body-${id}`);
    const btn = body?.nextElementSibling;
    if (!body) return;
    const shown = body.style.display !== 'none';
    body.style.display = shown ? 'none' : '';
    if (btn) btn.textContent = shown ? 'Show ▾' : 'Hide ▴';
  },

  async deleteBulkAnalysis(id) {
    try {
      await API.del(`/api/analysis/bulk-analyses/${id}`);
      App.toast('Deleted', 'success');
      this.loadSavedBulkAnalyses();
    } catch {}
  },

  async runExtractHooksCompare() {
    const ids = this._getCheckedCreatorIds();
    if (!ids.length) { App.toast('Select at least 1 creator', 'error'); return; }
    const el = document.getElementById('compare-result');
    App.loading(el, 'Extracting hooks...');
    try {
      const data = await API.post('/api/analysis/extract-hooks', { creator_ids: ids, limit: 30 });
      App.toast(`Extracted ${data.total} hooks — see Hook Library tab`, 'success');
      el.innerHTML = this._renderHooksList(data.hooks.slice(0, 20));
    } catch (e) {
      el.innerHTML = `<div class="empty-state"><p style="color:var(--red)">${App.escape(e.message)}</p></div>`;
    }
  },

  async runExtractStyleCompare() {
    const ids = this._getCheckedCreatorIds();
    if (!ids.length) { App.toast('Select at least 1 creator', 'error'); return; }
    const el = document.getElementById('compare-result');
    App.loading(el, 'Extracting style DNA...');
    try {
      const data = await API.post('/api/analysis/extract-style', { creator_ids: ids, limit: 40 });
      App.toast('Style DNA extracted — see Style DNA tab', 'success');
      el.innerHTML = `<div style="display:flex;flex-direction:column;gap:12px">${data.styles.map(s => this._renderStyleCard(s)).join('')}</div>`;
    } catch (e) {
      el.innerHTML = `<div class="empty-state"><p style="color:var(--red)">${App.escape(e.message)}</p></div>`;
    }
  },

  // ─── Hooks Tab ──────────────────────────────────────────────────────────────

  async loadHooksTab() {
    const el = document.getElementById('analysis-hooks-view');
    if (!el) return;
    try {
    if (!this.creators.length) await this.load();

    const creatorOptions = this.creators.map(c =>
      `<option value="${c.id}">${App.escape(c.name)}</option>`
    ).join('');

    el.innerHTML = `
      <div class="toolbar" style="margin-bottom:8px;flex-wrap:wrap;gap:6px">
        <select id="hooks-filter-creator" style="width:auto" onchange="Analysis.refreshHooks()">
          <option value="">All Creators</option>
          ${creatorOptions}
        </select>
        <select id="hooks-filter-type" style="width:auto" onchange="Analysis.refreshHooks()">
          <option value="">All Types</option>
          <option value="question">Question</option>
          <option value="stat">Stat / Number</option>
          <option value="story">Story</option>
          <option value="bold_claim">Bold Claim</option>
          <option value="pain_point">Pain Point</option>
          <option value="curiosity_gap">Curiosity Gap</option>
          <option value="other">Other</option>
        </select>
        <input type="text" id="hooks-search" placeholder="Search hooks…" style="width:160px;font-size:12px" oninput="Analysis._onHookSearch(this.value)">
        <div class="spacer"></div>
        <button class="btn btn-secondary btn-sm" onclick="Analysis.showAddHookForm()">+ Add Hook</button>
        <button class="btn btn-secondary btn-sm" onclick="Analysis.showUploadDocumentPanel()">Upload Doc</button>
        <button class="btn btn-secondary btn-sm" onclick="Analysis.showExtractPanel()">Extract from Creator</button>
        <button id="hooks-bulk-toggle" class="btn btn-ghost btn-sm" onclick="Analysis.toggleBulkMode()">Select</button>
      </div>
      <div id="hooks-extract-panel" style="display:none">
        <div class="card" style="margin-bottom:10px;padding:12px 14px">
          <div style="font-size:12px;font-weight:600;color:var(--text);margin-bottom:8px">Extract Hooks From Creator</div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <select id="hooks-extract-creator" style="flex:1;min-width:140px">
              <option value="">Select creator...</option>
              ${creatorOptions}
            </select>
            <button class="btn btn-primary btn-sm" onclick="Analysis.extractHooksInline()">Extract Hooks</button>
            <button class="btn btn-ghost btn-sm" onclick="Analysis.showExtractPanel()">×</button>
          </div>
          <div id="hooks-extract-status" style="margin-top:6px;font-size:12px;color:var(--text3)"></div>
        </div>
      </div>
      <div id="hooks-add-panel" style="display:none"></div>
      <div id="hooks-upload-panel" style="display:none"></div>
      <div id="hooks-bulk-bar" style="display:none;background:var(--bg2);border:1px solid var(--border);padding:10px 14px;align-items:center;gap:10px;border-radius:8px;margin-bottom:8px">
        <span id="hooks-bulk-count" style="font-size:12px;font-weight:600;color:var(--text)">0 selected</span>
        <button class="btn btn-sm" style="background:#ef444422;color:#ef4444;border:1px solid #ef444444" onclick="Analysis.bulkDeleteHooks()">Delete Selected</button>
        <button class="btn btn-secondary btn-sm" onclick="Analysis.bulkCopyHooks()">Copy to Clipboard</button>
        <button class="btn btn-ghost btn-sm" style="margin-left:auto" onclick="Analysis.clearBulkSelection()">Deselect All</button>
      </div>
      <div id="hooks-list"></div>
    `;
    await this.refreshHooks();
    } catch (e) {
      el.innerHTML = `<div class="empty-state"><p style="color:var(--red)">${App.escape(e.message || 'Failed to load Hook Library tab')}</p></div>`;
    }
  },

  showExtractPanel() {
    const p = document.getElementById('hooks-extract-panel');
    if (p) p.style.display = p.style.display === 'none' ? '' : 'none';
  },

  async extractHooksInline() {
    const creatorId = parseInt(document.getElementById('hooks-extract-creator')?.value);
    if (!creatorId) { App.toast('Select a creator first', 'error'); return; }
    const status = document.getElementById('hooks-extract-status');
    if (status) status.textContent = 'Extracting…';
    try {
      const data = await API.post('/api/analysis/extract-hooks', { creator_ids: [creatorId], limit: 30 });
      App.toast(`Extracted ${data.total} hooks`, 'success');
      if (status) status.textContent = `Done — ${data.total} hooks extracted`;
      await this.refreshHooks();
    } catch (e) {
      App.toast(e.message, 'error');
      if (status) status.textContent = '';
    }
  },

  _hookTypeOptions(selected) {
    const types = ['question', 'stat', 'story', 'bold_claim', 'pain_point', 'curiosity_gap', 'other'];
    return types.map(t =>
      `<option value="${t}" ${selected === t ? 'selected' : ''}>${t.replace(/_/g, ' ')}</option>`
    ).join('');
  },

  showAddHookForm() {
    const panel = document.getElementById('hooks-add-panel');
    if (!panel) return;
    if (panel.style.display !== 'none') { panel.style.display = 'none'; return; }
    const creatorOptions = this.creators.map(c =>
      `<option value="${c.id}">${App.escape(c.name)}</option>`
    ).join('');
    panel.style.display = '';
    panel.innerHTML = `
      <div class="card" style="margin-bottom:10px;padding:14px">
        <div style="font-size:12px;font-weight:600;color:var(--text);margin-bottom:10px">Add Hook Manually</div>
        <textarea id="add-hook-text" rows="3" placeholder="Enter your hook here…" style="margin-bottom:8px"></textarea>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">
          <select id="add-hook-type" style="flex:1;min-width:130px">${this._hookTypeOptions('other')}</select>
          <select id="add-hook-creator" style="flex:1;min-width:130px">
            <option value="">No creator (manual)</option>
            ${creatorOptions}
          </select>
        </div>
        <div style="display:flex;gap:8px">
          <button class="btn btn-primary btn-sm" onclick="Analysis.saveAddHook()">Add to Library</button>
          <button class="btn btn-ghost btn-sm" onclick="document.getElementById('hooks-add-panel').style.display='none'">Cancel</button>
        </div>
      </div>`;
  },

  async saveAddHook() {
    const text = document.getElementById('add-hook-text')?.value?.trim();
    const type = document.getElementById('add-hook-type')?.value || 'other';
    const creatorId = parseInt(document.getElementById('add-hook-creator')?.value) || null;
    if (!text) { App.toast('Hook text is required', 'error'); return; }
    try {
      await API.post('/api/analysis/hooks', { hook_text: text, hook_type: type, creator_id: creatorId });
      App.toast('Hook added!', 'success');
      document.getElementById('hooks-add-panel').style.display = 'none';
      await this.refreshHooks();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  showUploadDocumentPanel() {
    const panel = document.getElementById('hooks-upload-panel');
    if (!panel) return;
    if (panel.style.display !== 'none') { panel.style.display = 'none'; return; }
    const creatorOptions = this.creators.map(c =>
      `<option value="${c.id}">${App.escape(c.name)}</option>`
    ).join('');
    panel.style.display = '';
    panel.innerHTML = `
      <div class="card" style="margin-bottom:10px;padding:14px">
        <div style="font-size:12px;font-weight:600;color:var(--text);margin-bottom:4px">Upload Document → Extract Hooks</div>
        <div style="font-size:11px;color:var(--text3);margin-bottom:10px">Claude reads the document and extracts all opening hooks. Supports .txt, .pdf, .docx</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px">
          <input type="file" id="upload-hook-file" accept=".txt,.pdf,.docx" style="flex:1;min-width:180px;font-size:12px">
          <select id="upload-hook-creator" style="flex:1;min-width:130px">
            <option value="">No creator (document)</option>
            ${creatorOptions}
          </select>
        </div>
        <div style="display:flex;gap:8px">
          <button class="btn btn-primary btn-sm" onclick="Analysis.uploadDocumentHooks()">Upload &amp; Extract</button>
          <button class="btn btn-ghost btn-sm" onclick="document.getElementById('hooks-upload-panel').style.display='none'">Cancel</button>
        </div>
        <div id="upload-hook-status" style="margin-top:6px;font-size:12px;color:var(--text3)"></div>
      </div>`;
  },

  async uploadDocumentHooks() {
    const fileInput = document.getElementById('upload-hook-file');
    const creatorId = parseInt(document.getElementById('upload-hook-creator')?.value) || null;
    const status = document.getElementById('upload-hook-status');
    if (!fileInput?.files?.length) { App.toast('Select a file first', 'error'); return; }
    const file = fileInput.files[0];
    if (status) status.textContent = 'Uploading and extracting…';
    const formData = new FormData();
    formData.append('file', file);
    if (creatorId) formData.append('creator_id', String(creatorId));
    try {
      const resp = await fetch('/api/analysis/hooks/upload-document', { method: 'POST', body: formData });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Upload failed');
      }
      const data = await resp.json();
      App.toast(`Extracted ${data.total} hooks from "${data.filename}"`, 'success');
      document.getElementById('hooks-upload-panel').style.display = 'none';
      await this.refreshHooks();
    } catch (e) {
      App.toast(e.message, 'error');
      if (status) status.textContent = '';
    }
  },

  _hooksSearchTimer: null,
  _allHooksCache: [],

  _onHookSearch(val) {
    clearTimeout(this._hooksSearchTimer);
    this._hooksSearchTimer = setTimeout(() => this._filterHooksBySearch(val), 280);
  },

  _filterHooksBySearch(query) {
    const el = document.getElementById('hooks-list');
    if (!el || !this._allHooksCache.length) return;
    const q = query.trim().toLowerCase();
    const filtered = q ? this._allHooksCache.filter(h => (h.hook_text || '').toLowerCase().includes(q)) : this._allHooksCache;
    if (!filtered.length) {
      el.innerHTML = `<div class="empty-state"><p style="color:var(--text3)">No hooks match "${App.escape(query)}"</p></div>`;
      return;
    }
    el.innerHTML = `<div style="display:flex;flex-direction:column;gap:8px">${filtered.map(h => this._renderHookCard(h)).join('')}</div>`;
    this._updateBulkBar();
  },

  async refreshHooks() {
    const el = document.getElementById('hooks-list');
    if (!el) return;
    App.loading(el, 'Loading hooks...');

    const creatorId = document.getElementById('hooks-filter-creator')?.value;
    const hookType = document.getElementById('hooks-filter-type')?.value;

    let url = '/api/analysis/hooks?limit=200';
    if (creatorId) url += `&creator_ids=${creatorId}`;
    if (hookType) url += `&hook_type=${encodeURIComponent(hookType)}`;

    try {
      const hooks = await API.get(url);
      this._allHooksCache = hooks;
      const searchVal = document.getElementById('hooks-search')?.value?.trim() || '';
      const toRender = searchVal ? hooks.filter(h => (h.hook_text || '').toLowerCase().includes(searchVal.toLowerCase())) : hooks;
      if (!toRender.length) {
        el.innerHTML = `<div class="empty-state"><div class="empty-icon">🪝</div><h3>No hooks yet</h3><p>Add hooks manually, upload a document, or use "Extract from Creator" to pull from a creator's content.</p></div>`;
        return;
      }
      el.innerHTML = `<div style="display:flex;flex-direction:column;gap:8px">${toRender.map(h => this._renderHookCard(h)).join('')}</div>`;
      this._updateBulkBar();
    } catch (e) {
      el.innerHTML = `<div class="empty-state"><p style="color:var(--red)">${App.escape(this._friendlyError(e))}</p></div>`;
    }
  },

  toggleBulkMode() {
    this._bulkMode = !this._bulkMode;
    if (!this._bulkMode) this._bulkSelectedIds.clear();
    const btn = document.getElementById('hooks-bulk-toggle');
    if (btn) btn.textContent = this._bulkMode ? 'Done' : 'Select';
    this.refreshHooks();
  },

  _updateBulkBar() {
    const bar = document.getElementById('hooks-bulk-bar');
    const count = document.getElementById('hooks-bulk-count');
    if (!bar) return;
    const n = this._bulkSelectedIds.size;
    bar.style.display = (this._bulkMode && n > 0) ? 'flex' : 'none';
    if (count) count.textContent = `${n} hook${n !== 1 ? 's' : ''} selected`;
  },

  _toggleBulkHook(id, checked) {
    if (checked) this._bulkSelectedIds.add(id);
    else this._bulkSelectedIds.delete(id);
    this._updateBulkBar();
  },

  clearBulkSelection() {
    this._bulkSelectedIds.clear();
    document.querySelectorAll('.hook-bulk-check').forEach(cb => { cb.checked = false; });
    this._updateBulkBar();
  },

  async bulkDeleteHooks() {
    const ids = Array.from(this._bulkSelectedIds);
    if (!ids.length) return;
    if (!confirm(`Delete ${ids.length} hook${ids.length !== 1 ? 's' : ''}?`)) return;
    try {
      await API.post('/api/analysis/hooks/bulk-delete', { ids });
      this._bulkSelectedIds.clear();
      App.toast(`Deleted ${ids.length} hooks`, 'success');
      await this.refreshHooks();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  async bulkCopyHooks() {
    const ids = Array.from(this._bulkSelectedIds);
    if (!ids.length) return;
    const texts = [];
    document.querySelectorAll('[data-hook-id]').forEach(cardEl => {
      if (ids.includes(parseInt(cardEl.dataset.hookId))) {
        const textEl = cardEl.querySelector('[data-hook-text]');
        if (textEl) texts.push(textEl.textContent.trim().replace(/^"|"$/g, ''));
      }
    });
    try {
      await navigator.clipboard.writeText(texts.join('\n\n'));
      App.toast(`Copied ${texts.length} hooks to clipboard`, 'success');
    } catch {
      App.toast('Could not access clipboard', 'error');
    }
  },

  async deleteHook(id) {
    if (!confirm('Delete this hook?')) return;
    try {
      await API.del(`/api/analysis/hooks/${id}`);
      App.toast('Hook deleted', 'success');
      await this.refreshHooks();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  editHook(id) {
    const card = document.querySelector(`[data-hook-id="${id}"]`);
    if (!card) return;
    card.querySelector('[data-hook-view]').style.display = 'none';
    card.querySelector('[data-hook-edit]').style.display = '';
  },

  cancelEditHook(id) {
    const card = document.querySelector(`[data-hook-id="${id}"]`);
    if (!card) return;
    card.querySelector('[data-hook-view]').style.display = '';
    card.querySelector('[data-hook-edit]').style.display = 'none';
  },

  async saveEditHook(id) {
    const card = document.querySelector(`[data-hook-id="${id}"]`);
    if (!card) return;
    const text = card.querySelector(`#hook-edit-text-${id}`)?.value?.trim();
    const type = card.querySelector(`#hook-edit-type-${id}`)?.value || 'other';
    if (!text) { App.toast('Hook text cannot be empty', 'error'); return; }
    try {
      await API.put(`/api/analysis/hooks/${id}`, { hook_text: text, hook_type: type });
      App.toast('Hook updated', 'success');
      await this.refreshHooks();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  _hookTypeBadgeColor(type) {
    const map = {
      question: '#3b82f6', stat: '#10b981', story: '#f59e0b',
      bold_claim: '#ef4444', pain_point: '#8b5cf6', curiosity_gap: '#06b6d4', other: '#6b7280',
    };
    return map[type] || '#6b7280';
  },

  _sourceBadge(h) {
    if (h.source === 'manual') return `<span style="font-size:10px;padding:1px 6px;border-radius:10px;background:#f59e0b22;color:#f59e0b;font-weight:600">Manual</span>`;
    if (h.source === 'document') {
      const label = (h.source_label || 'Doc').split('/').pop().substring(0, 20);
      return `<span style="font-size:10px;padding:1px 6px;border-radius:10px;background:#10b98122;color:#10b981;font-weight:600" title="${App.escape(h.source_label || '')}">Doc: ${App.escape(label)}</span>`;
    }
    return '';
  },

  _renderHookCard(h) {
    const color = this._hookTypeBadgeColor(h.hook_type);
    const score = h.engagement_score ? h.engagement_score.toFixed(1) : '—';
    const bulkCheckbox = this._bulkMode
      ? `<input type="checkbox" class="hook-bulk-check" ${this._bulkSelectedIds.has(h.id) ? 'checked' : ''} onchange="Analysis._toggleBulkHook(${h.id}, this.checked)" style="accent-color:var(--accent);margin-right:4px">`
      : '';
    return `
      <div class="card" style="padding:12px 14px" data-hook-id="${h.id}">
        <div data-hook-view>
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap">
            ${bulkCheckbox}
            <span style="font-size:11px;font-weight:600;color:var(--text3)">${App.escape(h.creator_name)}</span>
            <span style="font-size:10px;color:var(--text3)">${(h.platform || '').toUpperCase()}</span>
            <span data-hook-type data-type="${h.hook_type || 'other'}" style="font-size:10px;font-weight:700;padding:2px 7px;border-radius:20px;background:${color}22;color:${color}">${(h.hook_type || 'other').replace(/_/g, ' ')}</span>
            ${this._sourceBadge(h)}
            <span style="margin-left:auto;font-size:11px;color:var(--text3)">Score: <strong style="color:var(--accent)">${score}</strong></span>
          </div>
          <div data-hook-text style="font-size:13.5px;color:var(--text);line-height:1.6;font-style:italic">"${App.escape(h.hook_text)}"</div>
          <div style="display:flex;gap:12px;margin-top:8px;font-size:11px;color:var(--text3);align-items:center">
            <span>❤ ${h.likes || 0}</span>
            <span>💬 ${h.comments_count || 0}</span>
            <span>↗ ${h.shares || 0}</span>
            <span style="margin-left:auto;display:flex;gap:4px">
              <button class="btn btn-ghost btn-sm" style="padding:2px 8px;font-size:11px" onclick="Analysis.editHook(${h.id})">Edit</button>
              <button class="btn btn-ghost btn-sm" style="padding:2px 8px;font-size:11px;color:var(--red)" onclick="Analysis.deleteHook(${h.id})">×</button>
            </span>
          </div>
        </div>
        <div data-hook-edit style="display:none">
          <textarea id="hook-edit-text-${h.id}" rows="3" style="margin-bottom:8px">${App.escape(h.hook_text)}</textarea>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <select id="hook-edit-type-${h.id}" style="width:auto">${this._hookTypeOptions(h.hook_type)}</select>
            <button class="btn btn-primary btn-sm" onclick="Analysis.saveEditHook(${h.id})">Save</button>
            <button class="btn btn-ghost btn-sm" onclick="Analysis.cancelEditHook(${h.id})">Cancel</button>
          </div>
        </div>
      </div>
    `;
  },

  _renderHooksList(hooks) {
    if (!hooks.length) return '<div class="empty-state"><p>No hooks found.</p></div>';
    return `<div style="display:flex;flex-direction:column;gap:8px">${hooks.map(h => this._renderHookCard(h)).join('')}</div>`;
  },

  // ─── Style DNA Tab ──────────────────────────────────────────────────────────

  async loadStyleTab() {
    const el = document.getElementById('analysis-style-view');
    if (!el) return;
    try {
      if (!this.creators.length) await this.load();

      const creatorOptions = this.creators.map(c =>
        `<option value="${c.id}">${App.escape(c.name)}</option>`
      ).join('');

      el.innerHTML = `
        <div class="toolbar" style="margin-bottom:12px">
          <select id="style-filter-creator" style="width:auto" onchange="Analysis.refreshStyles()">
            <option value="">All Creators</option>
            ${creatorOptions}
          </select>
          <div class="spacer"></div>
          <button class="btn btn-secondary btn-sm" onclick="Analysis.switchTab('compare')">Extract More →</button>
        </div>
        <div id="style-list"></div>
      `;
      await this.refreshStyles();
    } catch (e) {
      el.innerHTML = `<div class="empty-state"><p style="color:var(--red)">${App.escape(e.message || 'Failed to load Style DNA tab')}</p></div>`;
    }
  },

  async refreshStyles() {
    const el = document.getElementById('style-list');
    if (!el) return;
    App.loading(el, 'Loading style profiles...');

    const creatorId = document.getElementById('style-filter-creator')?.value;
    let url = '/api/analysis/styles';
    if (creatorId) url += `?creator_ids=${creatorId}`;

    try {
      const styles = await API.get(url);
      if (!styles.length) {
        el.innerHTML = `<div class="empty-state"><div class="empty-icon">🧬</div><h3>No style profiles yet</h3><p>Go to the Compare tab, select creators, and click "Extract Style DNA".</p></div>`;
        return;
      }
      el.innerHTML = `<div style="display:flex;flex-direction:column;gap:14px">${styles.map(s => this._renderStyleCard(s)).join('')}</div>`;
    } catch (e) {
      el.innerHTML = `<div class="empty-state"><p style="color:var(--red)">${App.escape(e.message)}</p></div>`;
    }
  },

  // ─── LinkedIn AI Tab ────────────────────────────────────────────────────────

  _liSkill: 'content_analyzer',
  _liResult: null,
  _liRunning: false,

  _skillMeta: {
    content_analyzer: {
      icon: '📊',
      label: 'Content Analyzer',
      desc: 'Find engagement patterns, gaps, and 10 ranked content ideas from a creator\'s LinkedIn posts.',
      needsCreator: true,
    },
    profile_optimizer: {
      icon: '✦',
      label: 'Profile Optimizer',
      desc: 'Audit and rewrite a LinkedIn profile headline, about section, and featured section.',
      needsCreator: true,
    },
    content_writer: {
      icon: '✍',
      label: 'Content Writer',
      desc: 'Turn a raw idea or topic into a high-performing LinkedIn post with hook, body, and CTA.',
      needsCreator: false,
    },
    dm_writer: {
      icon: '✉',
      label: 'DM Writer',
      desc: 'Write a full 4-message outbound DM sequence for a target audience segment.',
      needsCreator: false,
    },
  },

  async loadLinkedInTab() {
    const el = document.getElementById('analysis-linkedin-view');
    if (!el) return;
    try {
    if (!this.creators.length) await this.load();

    const creatorOptions = this.creators.map(c =>
      `<option value="${c.id}">${App.escape(c.name)} (${c.category})</option>`
    ).join('');

    const skillCards = Object.entries(this._skillMeta).map(([key, m]) => `
      <div class="card li-skill-card" data-skill="${key}"
        onclick="Analysis.selectLinkedInSkill('${key}')"
        style="cursor:pointer;padding:16px;flex:1;min-width:180px;border:2px solid ${this._liSkill === key ? 'var(--accent)' : 'transparent'}">
        <div style="font-size:22px;margin-bottom:6px">${m.icon}</div>
        <div style="font-size:13px;font-weight:700;color:var(--text);margin-bottom:4px">${m.label}</div>
        <div style="font-size:11px;color:var(--text3);line-height:1.5">${m.desc}</div>
      </div>
    `).join('');

    const currentMeta = this._skillMeta[this._liSkill];

    el.innerHTML = `
      <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px">${skillCards}</div>

      <div class="card" style="margin-bottom:20px;padding:20px" id="li-input-panel">
        <div style="font-size:13px;font-weight:700;color:var(--text);margin-bottom:14px">
          ${currentMeta.icon} ${currentMeta.label}
        </div>
        ${currentMeta.needsCreator ? `
          <div style="margin-bottom:12px">
            <label style="font-size:11px;font-weight:600;color:var(--text3);display:block;margin-bottom:5px">CREATOR</label>
            <select id="li-creator-select" style="width:100%;max-width:360px">
              <option value="">Select a creator...</option>
              ${creatorOptions}
            </select>
          </div>
          <div style="margin-bottom:14px">
            <label style="font-size:11px;font-weight:600;color:var(--text3);display:block;margin-bottom:5px">EXTRA CONTEXT <span style="font-weight:400">(optional)</span></label>
            <textarea id="li-context-input" rows="2" placeholder="e.g. Focus on their top 5 posts, or competitor to compare against..." style="width:100%;max-width:600px;resize:vertical"></textarea>
          </div>
        ` : `
          <div style="margin-bottom:14px">
            <label style="font-size:11px;font-weight:600;color:var(--text3);display:block;margin-bottom:5px">
              ${this._liSkill === 'content_writer' ? 'RAW IDEA OR TOPIC' : 'TARGET SEGMENT DESCRIPTION'}
            </label>
            <textarea id="li-context-input" rows="4"
              placeholder="${this._liSkill === 'content_writer'
                ? 'e.g. How I used to grind 16-hour days at my corporate job, now I work 4 hours from Southeast Asia...'
                : 'e.g. AI startup founders, 11-50 employees, US/Canada, trying to build personal brand on LinkedIn to get inbound deals...'}"
              style="width:100%;max-width:600px;resize:vertical"></textarea>
          </div>
        `}
        <button class="btn btn-primary btn-sm" onclick="Analysis.runLinkedInSkill()" id="li-run-btn">
          ▶ Run ${currentMeta.label}
        </button>
      </div>

      <div id="li-result-panel" style="display:none;margin-bottom:20px"></div>

      <div>
        <div style="font-size:12px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:0.8px;margin-bottom:10px">Saved Results</div>
        <div id="li-history-list"></div>
      </div>
    `;

    await this.loadLinkedInHistory();
    } catch (e) {
      el.innerHTML = `<div class="empty-state"><p style="color:var(--red)">${App.escape(e.message || 'Failed to load LinkedIn AI tab')}</p></div>`;
    }
  },

  selectLinkedInSkill(skill) {
    this._liSkill = skill;
    this._liResult = null;
    this.loadLinkedInTab();
  },

  async runLinkedInSkill() {
    if (this._liRunning) return;
    const meta = this._skillMeta[this._liSkill];
    const btn = document.getElementById('li-run-btn');
    const resultPanel = document.getElementById('li-result-panel');
    if (!resultPanel) return;

    let creatorId = null;
    let creatorName = null;
    const context = document.getElementById('li-context-input')?.value?.trim() || '';

    if (meta.needsCreator) {
      const sel = document.getElementById('li-creator-select');
      creatorId = sel ? parseInt(sel.value) || null : null;
      if (!creatorId) { App.toast('Select a creator first', 'error'); return; }
      creatorName = this.creators.find(c => c.id === creatorId)?.name || null;
    } else {
      if (!context) { App.toast('Enter a description or idea first', 'error'); return; }
    }

    this._liRunning = true;
    if (btn) { btn.disabled = true; btn.textContent = 'Running...'; }
    resultPanel.style.display = 'block';
    App.loading(resultPanel, `Running ${meta.label}...`);

    try {
      const body = { skill: this._liSkill };
      if (creatorId) body.creator_id = creatorId;
      if (context) body.user_context = context;

      const data = await API.post('/api/analysis/linkedin-skill', body);
      this._liResult = { skill: this._liSkill, creator_id: creatorId, creator_name: creatorName, user_context: context, result_text: data.result };

      resultPanel.innerHTML = `
        <div class="card" style="padding:20px">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap">
            <span style="font-size:13px;font-weight:700;color:var(--text)">${meta.icon} ${meta.label} Result</span>
            ${creatorName ? `<span style="font-size:11px;color:var(--text3)">· ${App.escape(creatorName)}</span>` : ''}
            <button class="btn btn-primary btn-sm" style="margin-left:auto" onclick="Analysis.saveLinkedInResult()">Save Result</button>
          </div>
          <div style="font-size:13px;line-height:1.7;color:var(--text)">${this.renderMarkdown(data.result)}</div>
        </div>
      `;
    } catch (e) {
      resultPanel.innerHTML = `<div class="card" style="padding:16px;color:var(--red)">${App.escape(this._friendlyError(e))}</div>`;
    } finally {
      this._liRunning = false;
      if (btn) { btn.disabled = false; btn.textContent = `▶ Run ${meta.label}`; }
    }
  },

  async saveLinkedInResult() {
    if (!this._liResult) return;
    try {
      await API.post('/api/analysis/linkedin-results', this._liResult);
      App.toast('Result saved', 'success');
      this._liResult = null;
      document.querySelector('#li-result-panel .btn')?.remove();
      await this.loadLinkedInHistory();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  async loadLinkedInHistory() {
    const el = document.getElementById('li-history-list');
    if (!el) return;

    try {
      const results = await API.get('/api/analysis/linkedin-results');
      if (!results.length) {
        el.innerHTML = `<div style="font-size:12px;color:var(--text3);padding:16px 0">No saved results yet. Run a skill above and save the output.</div>`;
        return;
      }
      el.innerHTML = results.map(r => this._renderLinkedInHistoryCard(r)).join('');
    } catch (e) {
      el.innerHTML = `<div style="font-size:12px;color:var(--red)">${App.escape(e.message)}</div>`;
    }
  },

  _renderLinkedInHistoryCard(r) {
    const meta = this._skillMeta[r.skill] || { icon: '◆', label: r.skill };
    const date = r.created_at ? new Date(r.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '';
    const subtitle = r.creator_name || (r.user_context ? r.user_context.slice(0, 60) + (r.user_context.length > 60 ? '...' : '') : '');
    const previewId = `li-hist-${r.id}`;
    return `
      <div class="card" style="margin-bottom:10px;padding:14px 16px">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span style="font-size:13px">${meta.icon}</span>
          <span style="font-size:13px;font-weight:600;color:var(--text)">${meta.label}</span>
          ${subtitle ? `<span style="font-size:11px;color:var(--text3)">· ${App.escape(subtitle)}</span>` : ''}
          <span style="font-size:11px;color:var(--text3);margin-left:auto">${date}</span>
          <button class="btn btn-ghost btn-sm" style="padding:2px 8px;font-size:11px" onclick="Analysis.toggleLinkedInResult('${previewId}')">Expand</button>
          <button class="btn btn-ghost btn-sm" style="padding:2px 8px;font-size:11px;color:var(--red)" onclick="Analysis.deleteLinkedInResult(${r.id})">×</button>
        </div>
        <div id="${previewId}" style="display:none;margin-top:12px;font-size:13px;line-height:1.7;color:var(--text)">
          ${this.renderMarkdown(r.result_text)}
        </div>
      </div>
    `;
  },

  toggleLinkedInResult(id) {
    const el = document.getElementById(id);
    if (!el) return;
    const isHidden = el.style.display === 'none';
    el.style.display = isHidden ? 'block' : 'none';
    const card = el.closest('.card');
    if (card) {
      const expandBtn = card.querySelector(`button[onclick*="toggleLinkedInResult"]`);
      if (expandBtn) expandBtn.textContent = isHidden ? 'Collapse' : 'Expand';
    }
  },

  async deleteLinkedInResult(id) {
    if (!confirm('Delete this saved result?')) return;
    try {
      await API.del(`/api/analysis/linkedin-results/${id}`);
      App.toast('Deleted', 'success');
      await this.loadLinkedInHistory();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  _renderStyleCard(s) {
    const toneChips = (s.tone || []).map(t =>
      `<span style="font-size:10px;padding:2px 8px;border-radius:20px;background:var(--accent-dim);color:var(--accent);font-weight:600">${App.escape(t)}</span>`
    ).join('');

    const fmtChips = (s.formats_used || []).map(f =>
      `<span style="font-size:10px;padding:2px 8px;border-radius:20px;background:var(--bg3);color:var(--text2)">${App.escape(f)}</span>`
    ).join('');

    const ctaList = (s.cta_patterns || []).map(c =>
      `<li style="font-size:12px;color:var(--text2)">"${App.escape(c)}"</li>`
    ).join('');

    const phraseList = (s.key_phrases || []).map(p =>
      `<span style="font-size:11px;padding:2px 8px;border-radius:4px;background:var(--bg3);color:var(--text2)">${App.escape(p)}</span>`
    ).join('');

    return `
      <div class="card">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap">
          <span style="font-size:15px;font-weight:700;color:var(--text)">${App.escape(s.creator_name)}</span>
          <span style="font-size:11px;color:var(--text3)">${s.posts_analyzed || 0} posts analyzed</span>
          ${s.vocabulary_level ? `<span style="font-size:11px;padding:2px 8px;border-radius:4px;background:var(--bg3);color:var(--text2)">${App.escape(s.vocabulary_level)}</span>` : ''}
          ${s.avg_sentence_length ? `<span style="font-size:11px;padding:2px 8px;border-radius:4px;background:var(--bg3);color:var(--text2)">${App.escape(s.avg_sentence_length)} sentences</span>` : ''}
        </div>

        ${toneChips ? `<div style="margin-bottom:10px"><div style="font-size:11px;color:var(--text3);margin-bottom:5px;font-weight:600">TONE</div><div style="display:flex;gap:5px;flex-wrap:wrap">${toneChips}</div></div>` : ''}
        ${fmtChips ? `<div style="margin-bottom:10px"><div style="font-size:11px;color:var(--text3);margin-bottom:5px;font-weight:600">FORMATS</div><div style="display:flex;gap:5px;flex-wrap:wrap">${fmtChips}</div></div>` : ''}
        ${ctaList ? `<div style="margin-bottom:10px"><div style="font-size:11px;color:var(--text3);margin-bottom:5px;font-weight:600">CALL-TO-ACTION PATTERNS</div><ul style="margin:0;padding-left:16px">${ctaList}</ul></div>` : ''}
        ${phraseList ? `<div style="margin-bottom:10px"><div style="font-size:11px;color:var(--text3);margin-bottom:5px;font-weight:600">KEY PHRASES</div><div style="display:flex;gap:5px;flex-wrap:wrap">${phraseList}</div></div>` : ''}
        ${s.posting_rhythm ? `<div style="margin-bottom:10px"><div style="font-size:11px;color:var(--text3);margin-bottom:2px;font-weight:600">POSTING RHYTHM</div><div style="font-size:12px;color:var(--text2)">${App.escape(s.posting_rhythm)}</div></div>` : ''}
        ${s.analysis_text ? `<div class="divider"></div><div style="font-size:13px;line-height:1.7;color:var(--text);white-space:pre-wrap">${App.escape(s.analysis_text)}</div>` : ''}
      </div>
    `;
  },
};
