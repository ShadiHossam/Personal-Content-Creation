const Write = {
  refs: { content: [], source: [] },
  format: 'linkedin_post',
  language: 'ar',
  currentDraft: null,

  async load() {
    this.loadSkills();
    this.bindToggles();
  },

  bindToggles() {
    // Format toggle
    document.querySelectorAll('#write-format-toggle .toggle-option').forEach(opt => {
      opt.onclick = () => {
        document.querySelectorAll('#write-format-toggle .toggle-option').forEach(o => o.classList.remove('active'));
        opt.classList.add('active');
        this.format = opt.dataset.val;
      };
    });

    // Language toggle
    document.querySelectorAll('#write-lang-toggle .toggle-option').forEach(opt => {
      opt.onclick = () => {
        document.querySelectorAll('#write-lang-toggle .toggle-option').forEach(o => o.classList.remove('active'));
        opt.classList.add('active');
        this.language = opt.dataset.val;
      };
    });
  },

  async loadSkills() {
    const sel = document.getElementById('write-skill-select');
    if (!sel) return;
    try {
      const skills = await API.get('/api/style/skills');
      sel.innerHTML = '<option value="">— Default (no skill) —</option>' +
        skills.map(s => `<option value="${s.id}" ${s.is_active ? 'selected' : ''}>${App.escape(s.name)}</option>`).join('');
    } catch {}
  },

  async generate() {
    const idea = document.getElementById('write-idea')?.value?.trim();
    if (!idea) { App.toast('Enter your idea first', 'error'); return; }

    const btn = document.getElementById('write-generate-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Generating...'; }

    const placeholder = document.getElementById('draft-placeholder');
    const output = document.getElementById('draft-output');
    const feedbackBar = document.getElementById('write-feedback-bar');

    if (placeholder) placeholder.style.display = 'none';
    if (output) { output.style.display = 'block'; output.textContent = ''; }

    // Spinner
    if (output) output.innerHTML = '<div class="spinner" style="margin:20px auto;display:block;width:20px;height:20px"></div>';

    const angle = document.getElementById('write-angle')?.value;
    const skillId = parseInt(document.getElementById('write-skill-select')?.value) || null;

    try {
      const data = await API.post('/api/write/generate', {
        idea,
        angle,
        format: this.format,
        language: this.language,
        skill_id: skillId,
        reference_content_ids: this.refs.content,
        reference_source_ids: this.refs.source,
      });

      this.currentDraft = data.draft;
      if (output) {
        output.textContent = data.draft;
        const isAr = App.detectArabic(data.draft);
        output.dir = isAr ? 'rtl' : 'ltr';
        if (isAr) output.style.fontFamily = 'var(--font-ar)';
        else output.style.fontFamily = '';
      }
      if (feedbackBar) feedbackBar.style.display = '';
    } catch (e) {
      if (output) output.textContent = '';
      if (placeholder) { placeholder.style.display = ''; placeholder.textContent = e.message; placeholder.style.color = 'var(--red)'; }
      App.toast(e.message, 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '✨ Generate Draft'; }
    }
  },

  regenerate() {
    this.generate();
  },

  rateDraft(rating) {
    document.querySelectorAll('#write-feedback-bar .btn-green, #write-feedback-bar .btn-ghost').forEach(b => {
      b.style.opacity = '0.5';
    });
    this._pendingRating = rating;
    App.toast(rating === 'good' ? '👍 Marked as good' : '👎 Marked for improvement', '');
  },

  async saveFeedback() {
    const note = document.getElementById('write-feedback-note')?.value?.trim() || null;
    const rating = this._pendingRating || 'good';
    const draft = document.getElementById('draft-output')?.textContent || this.currentDraft || '';
    if (!draft) { App.toast('No draft to save feedback for', 'error'); return; }

    const skillId = parseInt(document.getElementById('write-skill-select')?.value) || null;
    try {
      await API.post('/api/write/feedback', {
        idea: document.getElementById('write-idea')?.value || '',
        angle: document.getElementById('write-angle')?.value || null,
        format: this.format,
        language: this.language,
        skill_id: skillId,
        draft,
        rating,
        note,
      });
      App.toast('Feedback saved!', 'success');
      if (document.getElementById('write-feedback-note')) document.getElementById('write-feedback-note').value = '';
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  copyDraft() {
    const text = document.getElementById('draft-output')?.textContent || '';
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => App.toast('Copied to clipboard!', 'success'));
  },

  // ── Local drafts (localStorage) ───────────────────────────────────────────

  _DRAFTS_KEY: 'write.drafts.v1',

  _readDrafts() {
    try { return JSON.parse(localStorage.getItem(this._DRAFTS_KEY) || '[]'); } catch { return []; }
  },
  _writeDrafts(list) {
    localStorage.setItem(this._DRAFTS_KEY, JSON.stringify(list.slice(0, 100)));
  },

  saveDraft() {
    const text = document.getElementById('draft-output')?.textContent?.trim() || '';
    if (!text) { App.toast('Nothing to save yet', 'error'); return; }
    const idea = document.getElementById('write-idea')?.value?.trim() || '';
    const list = this._readDrafts();
    list.unshift({
      id: 'd-' + Date.now(),
      created_at: new Date().toISOString(),
      idea,
      format: this.format,
      language: this.language,
      text,
    });
    this._writeDrafts(list);
    App.toast('Draft saved locally', 'success');
  },

  exportDraft() {
    const text = document.getElementById('draft-output')?.textContent || '';
    if (!text) { App.toast('Nothing to export', 'error'); return; }
    const idea = document.getElementById('write-idea')?.value?.trim() || 'draft';
    const safe = idea.replace(/[^a-z0-9-_]+/gi, '_').substring(0, 40) || 'draft';
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `${safe}-${Date.now()}.txt`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },

  openDraftsList() {
    const drafts = this._readDrafts();
    const rows = drafts.length ? drafts.map(d => {
      const dt = new Date(d.created_at).toLocaleString();
      const preview = App.escape((d.text || '').substring(0, 140));
      return `
        <div style="padding:10px 4px;border-bottom:1px solid var(--border);display:flex;gap:8px;align-items:flex-start">
          <div style="flex:1;min-width:0">
            <div style="font-size:11px;color:var(--text3);margin-bottom:4px">${dt} · ${App.escape(d.format || '')} · ${App.escape(d.language || '')}</div>
            <div style="font-size:13px;color:var(--text2);white-space:pre-wrap;word-break:break-word">${preview}${(d.text||'').length>140?'…':''}</div>
          </div>
          <div style="display:flex;flex-direction:column;gap:4px;flex-shrink:0">
            <button class="btn btn-secondary btn-sm" onclick="Write.loadDraft('${d.id}')">Load</button>
            <button class="btn btn-ghost btn-sm" style="color:var(--red)" onclick="Write.deleteDraft('${d.id}')">Delete</button>
          </div>
        </div>`;
    }).join('') : '<div style="color:var(--text3);font-size:13px;padding:20px;text-align:center">No saved drafts yet.</div>';

    App.openModal(`
      <div class="modal-title">Saved Drafts</div>
      <div style="max-height:50vh;overflow-y:auto">${rows}</div>
      <div class="modal-footer">
        <button class="btn btn-ghost" onclick="App.closeModal()">Close</button>
      </div>
    `);
  },

  loadDraft(id) {
    const drafts = this._readDrafts();
    const d = drafts.find(x => x.id === id);
    if (!d) return;
    document.getElementById('write-idea').value = d.idea || '';
    const output = document.getElementById('draft-output');
    const placeholder = document.getElementById('draft-placeholder');
    const feedbackBar = document.getElementById('write-feedback-bar');
    if (output) { output.textContent = d.text; output.style.display = 'block'; output.dir = App.detectArabic(d.text) ? 'rtl' : 'ltr'; }
    if (placeholder) placeholder.style.display = 'none';
    if (feedbackBar) feedbackBar.style.display = '';
    this.currentDraft = d.text;
    App.closeModal();
    App.toast('Draft loaded', 'success');
  },

  deleteDraft(id) {
    if (!confirm('Delete this draft?')) return;
    const drafts = this._readDrafts().filter(x => x.id !== id);
    this._writeDrafts(drafts);
    this.openDraftsList();
  },

  openRefPicker() {
    App.openModal(`
      <div class="modal-title">Add Reference</div>
      <div class="tabs" style="margin-bottom:14px">
        <div class="tab active" data-tab="ref-saved-content">Saved Posts</div>
        <div class="tab" data-tab="ref-saved-articles">Saved Articles</div>
      </div>
      <div id="ref-saved-content" class="tab-content active" style="max-height:300px;overflow-y:auto">
        <div class="loading-overlay"><div class="spinner"></div></div>
      </div>
      <div id="ref-saved-articles" class="tab-content" style="max-height:300px;overflow-y:auto">
        <div class="loading-overlay"><div class="spinner"></div></div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-ghost" onclick="App.closeModal()">Close</button>
      </div>
    `);

    // Bind tabs
    document.querySelectorAll('.modal .tab').forEach(tab => {
      tab.onclick = () => {
        document.querySelectorAll('.modal .tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.modal .tab-content').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const target = document.getElementById(tab.dataset.tab);
        if (target) target.classList.add('active');
      };
    });

    this.loadRefContent();
    this.loadRefArticles();
  },

  async loadRefContent() {
    const el = document.getElementById('ref-saved-content');
    if (!el) return;
    try {
      const items = await API.get('/api/content?saved=true&limit=30');
      if (!items.length) { el.innerHTML = '<div style="color:var(--text3);font-size:13px;padding:12px">No saved posts yet.</div>'; return; }
      el.innerHTML = items.map(item => `
        <div style="display:flex;align-items:center;gap:8px;padding:8px;border-bottom:1px solid var(--border);cursor:pointer" onclick="Write.addRef('content', ${item.id}, this)">
          ${App.platformBadge(item.platform)}
          <span style="font-size:12px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${App.escape(item.creator_name)} — ${App.escape((item.body || '').substring(0, 60))}</span>
          <span style="font-size:11px;color:var(--text3)">${App.fmtDate(item.published_at)}</span>
        </div>
      `).join('');
    } catch (e) {
      el.textContent = '';
      const errEl = document.createElement('div');
      errEl.style.cssText = 'color:var(--red);font-size:12px;padding:12px';
      errEl.textContent = e.message;
      el.appendChild(errEl);
    }
  },

  async loadRefArticles() {
    const el = document.getElementById('ref-saved-articles');
    if (!el) return;
    try {
      const items = await API.get('/api/sources/items?saved=true&limit=30');
      if (!items.length) { el.innerHTML = '<div style="color:var(--text3);font-size:13px;padding:12px">No saved articles yet.</div>'; return; }
      el.innerHTML = items.map(item => `
        <div style="display:flex;align-items:center;gap:8px;padding:8px;border-bottom:1px solid var(--border);cursor:pointer" onclick="Write.addRef('source', ${item.id}, this)">
          <span style="font-size:18px">📰</span>
          <span style="font-size:12px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${App.escape(item.source_name)} — ${App.escape(item.title.substring(0, 60))}</span>
        </div>
      `).join('');
    } catch (e) {
      el.textContent = '';
      const errEl = document.createElement('div');
      errEl.style.cssText = 'color:var(--red);font-size:12px;padding:12px';
      errEl.textContent = e.message;
      el.appendChild(errEl);
    }
  },

  addRef(type, id, el) {
    if (type === 'content' && !this.refs.content.includes(id)) this.refs.content.push(id);
    if (type === 'source' && !this.refs.source.includes(id)) this.refs.source.push(id);
    el.style.background = 'rgba(79,126,247,0.1)';
    el.style.borderColor = 'var(--accent)';
    this.renderRefs();
  },

  renderRefs() {
    const el = document.getElementById('write-refs-list');
    if (!el) return;
    const total = this.refs.content.length + this.refs.source.length;
    el.innerHTML = total ? `<div style="font-size:12px;color:var(--text2)">${total} reference(s) selected <a href="#" onclick="Write.clearRefs();return false" style="color:var(--text3)">Clear</a></div>` : '';
  },

  clearRefs() {
    this.refs = { content: [], source: [] };
    this.renderRefs();
  },

  async fromContent(contentId) {
    // Pre-fill write screen with a saved content item as reference
    this.refs.content = [contentId];
    this.renderRefs();
    document.getElementById('write-idea')?.focus();
  },

  async fromSourceItem(sourceItemId) {
    try {
      const items = await API.get(`/api/sources/items?limit=200`);
      const item = items.find(i => i.id === sourceItemId);
      if (item) {
        const idea = document.getElementById('write-idea');
        if (idea) idea.value = `React to this article: "${item.title}"`;
        const angleEl = document.querySelector('#write-angle option[value="share insight"]');
        if (angleEl) angleEl.selected = true;
        this.refs.source = [sourceItemId];
        this.renderRefs();
      }
    } catch {}
  },

  async fromSourceItems(sourceItemIds) {
    try {
      const idsParam = sourceItemIds.join(',');
      const items = await API.get(`/api/sources/items?source_ids=${idsParam}&limit=200`);
      const matched = items.filter(i => sourceItemIds.includes(i.id));
      if (matched.length) {
        const titles = matched.map(i => `"${i.title}"`).join(', ');
        const idea = document.getElementById('write-idea');
        if (idea) idea.value = `Write a post combining insights from these articles: ${titles}`;
        this.refs.source = sourceItemIds;
        this.renderRefs();
      }
    } catch {}
  },

  setIdea(text) {
    const idea = document.getElementById('write-idea');
    if (idea) { idea.value = text; idea.focus(); }
  },
};
