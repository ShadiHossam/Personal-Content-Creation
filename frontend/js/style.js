const MyStyle = {
  profile: { bio: '', audience: '', rules: [] },
  skills: [],
  editingSkillId: null,
  editingSkillRules: [],
  editingSamples: [],
  activeTab: 'profile',

  load() {
    this.bindTabs();
    this.loadTab(this.activeTab);
  },

  bindTabs() {
    document.querySelectorAll('#style-tabs .tab').forEach(tab => {
      tab.onclick = () => {
        document.querySelectorAll('#style-tabs .tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        const name = tab.dataset.tab;
        const panel = document.getElementById('tab-' + name);
        if (panel) panel.classList.add('active');
        this.activeTab = name;
        this.loadTab(name);
      };
    });
  },

  loadTab(name) {
    if (name === 'profile') this.loadProfile();
    else if (name === 'skills') this.loadSkills();
    else if (name === 'feedback') this.loadFeedback();
  },

  // ── PROFILE ─────────────────────────────────────────────────────────────────

  async loadProfile() {
    try {
      const p = await API.get('/api/style/profile');
      this.profile = p;
      const bio = document.getElementById('profile-bio');
      const aud = document.getElementById('profile-audience');
      if (bio) bio.value = p.bio || '';
      if (aud) aud.value = p.audience || '';
      this.renderRules(p.rules || []);
    } catch (e) {
      App.toast('Could not load profile', 'error');
    }
  },

  renderRules(rules) {
    const el = document.getElementById('profile-rules-list');
    if (!el) return;
    this.profile.rules = rules;
    if (!rules.length) {
      el.innerHTML = '<div style="color:var(--text3);font-size:13px;margin-bottom:4px">No rules yet.</div>';
      return;
    }
    el.innerHTML = rules.map((r, i) => `
      <div class="rule-item">
        <div class="rule-item-dot"></div>
        <span class="rule-item-text">${App.escape(r)}</span>
        <button class="btn btn-ghost btn-sm" style="color:var(--red);padding:2px 8px" onclick="MyStyle.removeRule(${i})">×</button>
      </div>
    `).join('');
  },

  addRule() {
    const input = document.getElementById('profile-rule-input');
    const val = input?.value?.trim();
    if (!val) return;
    this.profile.rules = [...(this.profile.rules || []), val];
    this.renderRules(this.profile.rules);
    input.value = '';
  },

  removeRule(i) {
    this.profile.rules.splice(i, 1);
    this.renderRules(this.profile.rules);
  },

  async saveProfile() {
    const bio = document.getElementById('profile-bio')?.value?.trim() || '';
    const audience = document.getElementById('profile-audience')?.value?.trim() || '';
    try {
      await API.post('/api/style/profile', { bio, audience, rules: this.profile.rules });
      App.toast('Profile saved!', 'success');
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  // ── SKILLS ──────────────────────────────────────────────────────────────────

  async loadSkills() {
    const el = document.getElementById('skills-list');
    if (!el) return;
    try {
      this.skills = await API.get('/api/style/skills');
      this.renderSkillsList();
    } catch (e) {
      App.toast('Could not load skills', 'error');
    }
  },

  renderSkillsList() {
    const el = document.getElementById('skills-list');
    if (!el) return;
    if (!this.skills.length) {
      el.innerHTML = '<div class="empty-state"><div class="empty-icon">🎨</div><h3>No skills yet</h3><p>Create a writing personality to use in the AI writer.</p></div>';
      return;
    }
    el.innerHTML = this.skills.map(s => `
      <div class="card" style="margin-bottom:10px;padding:12px 14px">
        <div style="display:flex;align-items:center;gap:10px">
          <div style="flex:1;min-width:0">
            <div style="font-weight:600;font-size:13px">${App.escape(s.name)}</div>
            <div style="font-size:11px;color:var(--text3);margin-top:2px">${s.sample_count} samples · ${s.feedback_count} feedback items</div>
          </div>
          ${s.is_active ? '<span style="font-size:11px;color:var(--accent);font-weight:700">ACTIVE</span>' : `<button class="btn btn-ghost btn-sm" onclick="MyStyle.activateSkill(${s.id})">Use</button>`}
          <button class="btn btn-ghost btn-sm" onclick="MyStyle.openSkillEdit(${s.id})">Edit</button>
          <button class="btn btn-danger btn-sm" onclick="MyStyle.deleteSkill(${s.id})">Del</button>
        </div>
        ${s.style_description ? `<div style="font-size:12px;color:var(--text2);margin-top:6px">${App.escape(s.style_description)}</div>` : ''}
      </div>
    `).join('');
  },

  openSkillModal() {
    this.openSkillEdit(null);
  },

  async openSkillEdit(id) {
    this.editingSkillId = id;
    const panel = document.getElementById('skill-edit-panel');
    if (!panel) return;
    panel.style.display = '';

    if (id) {
      const skill = this.skills.find(s => s.id === id);
      if (!skill) return;
      document.getElementById('skill-edit-name').value = skill.name || '';
      document.getElementById('skill-edit-style').value = skill.style_description || '';
      this.editingSkillRules = [...(skill.rules || [])];

      try {
        const samples = await API.get(`/api/style/skills/${id}/samples`);
        this.editingSamples = samples;
      } catch {
        this.editingSamples = [];
      }
    } else {
      document.getElementById('skill-edit-name').value = '';
      document.getElementById('skill-edit-style').value = '';
      this.editingSkillRules = [];
      this.editingSamples = [];
    }

    document.getElementById('skill-sample-input').value = '';
    this.renderSkillRules();
    this.renderSamples();
    panel.scrollIntoView({ behavior: 'smooth' });
  },

  closeSkillEdit() {
    const panel = document.getElementById('skill-edit-panel');
    if (panel) panel.style.display = 'none';
    this.editingSkillId = null;
  },

  renderSkillRules() {
    const el = document.getElementById('skill-edit-rules');
    if (!el) return;
    if (!this.editingSkillRules.length) {
      el.innerHTML = '<div style="color:var(--text3);font-size:13px;margin-bottom:4px">No rules yet.</div>';
      return;
    }
    el.innerHTML = this.editingSkillRules.map((r, i) => `
      <div style="display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--border)">
        <span style="color:var(--accent);flex-shrink:0">●</span>
        <span style="flex:1;font-size:13px">${App.escape(r)}</span>
        <button class="btn btn-danger btn-sm" onclick="MyStyle.removeSkillRule(${i})">Remove</button>
      </div>
    `).join('');
  },

  addSkillRule() {
    const input = document.getElementById('skill-rule-input');
    const val = input?.value?.trim();
    if (!val) return;
    this.editingSkillRules.push(val);
    this.renderSkillRules();
    input.value = '';
  },

  removeSkillRule(i) {
    this.editingSkillRules.splice(i, 1);
    this.renderSkillRules();
  },

  renderSamples() {
    const el = document.getElementById('skill-samples-list');
    if (!el) return;
    if (!this.editingSamples.length) {
      el.innerHTML = '<div style="color:var(--text3);font-size:13px;margin-bottom:4px">No samples yet.</div>';
      return;
    }
    el.innerHTML = this.editingSamples.map(s => `
      <div class="card" style="padding:10px 12px;margin-bottom:8px;font-size:12px;position:relative">
        <span style="position:absolute;top:8px;right:8px;font-size:10px;color:var(--text3)">${s.language === 'ar' ? 'AR' : 'EN'}</span>
        <div style="white-space:pre-wrap;line-height:1.5" dir="${s.language === 'ar' ? 'rtl' : 'ltr'}">${App.escape(s.text)}</div>
        <button class="btn btn-danger btn-sm" style="margin-top:8px" onclick="MyStyle.deleteSample(${s.id})">Remove</button>
      </div>
    `).join('');
  },

  async addSample() {
    if (!this.editingSkillId) { App.toast('Save the skill first', 'error'); return; }
    const text = document.getElementById('skill-sample-input')?.value?.trim();
    const lang = document.getElementById('skill-sample-lang')?.value || 'ar';
    if (!text) return;
    try {
      const sample = await API.post(`/api/style/skills/${this.editingSkillId}/samples`, { text, language: lang });
      this.editingSamples.push(sample);
      this.renderSamples();
      document.getElementById('skill-sample-input').value = '';
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  async deleteSample(id) {
    try {
      await API.del(`/api/samples/${id}`);
      this.editingSamples = this.editingSamples.filter(s => s.id !== id);
      this.renderSamples();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  async saveSkill() {
    const name = document.getElementById('skill-edit-name')?.value?.trim();
    if (!name) { App.toast('Skill name is required', 'error'); return; }
    const style_description = document.getElementById('skill-edit-style')?.value?.trim() || '';
    const data = { name, style_description, rules: this.editingSkillRules };

    try {
      if (this.editingSkillId) {
        await API.put(`/api/style/skills/${this.editingSkillId}`, data);
        App.toast('Skill updated!', 'success');
      } else {
        const created = await API.post('/api/style/skills', data);
        this.editingSkillId = created.id;
        App.toast('Skill created! You can now add samples below.', 'success');
      }
      await this.loadSkills();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  async activateSkill(id) {
    try {
      await API.post(`/api/style/skills/${id}/activate`, {});
      await this.loadSkills();
      App.toast('Skill activated!', 'success');
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  async deleteSkill(id) {
    if (!confirm('Delete this skill and all its samples?')) return;
    try {
      await API.del(`/api/style/skills/${id}`);
      if (this.editingSkillId === id) this.closeSkillEdit();
      await this.loadSkills();
      App.toast('Deleted', 'success');
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  // ── FEEDBACK MEMORY ──────────────────────────────────────────────────────────

  feedbackFilter: '',

  async loadFeedback() {
    const el = document.getElementById('feedback-list');
    if (!el) return;
    App.loading(el, 'Loading feedback...');

    // Bind filter chips once
    document.querySelectorAll('#tab-feedback .filter-chip').forEach(chip => {
      chip.onclick = () => {
        document.querySelectorAll('#tab-feedback .filter-chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        this.feedbackFilter = chip.dataset.rating || '';
        this.loadFeedback();
      };
    });

    try {
      const params = this.feedbackFilter ? `?rating=${this.feedbackFilter}` : '';
      const items = await API.get('/api/style/feedback' + params);
      this.renderFeedback(items);
    } catch (e) {
      el.innerHTML = `<div style="color:var(--red)">${App.escape(e.message)}</div>`;
    }
  },

  renderFeedback(items) {
    const el = document.getElementById('feedback-list');
    if (!el) return;
    if (!items.length) {
      el.innerHTML = '<div class="empty-state"><div class="empty-icon">💬</div><h3>No feedback yet</h3><p>Rate AI drafts in the Write screen to build feedback history.</p></div>';
      return;
    }
    el.innerHTML = items.map(fb => {
      const emoji = fb.rating === 'good' ? '👍' : '👎';
      const dir = App.detectArabic(fb.draft) ? 'rtl' : 'ltr';
      return `
        <div class="card" style="margin-bottom:10px;padding:12px 14px">
          <div style="display:flex;align-items:flex-start;gap:8px;margin-bottom:6px">
            <span style="font-size:16px;flex-shrink:0">${emoji}</span>
            <div style="flex:1;min-width:0">
              <div style="font-size:12px;color:var(--text3)">${fb.skill_name ? `Skill: ${App.escape(fb.skill_name)} · ` : ''}${App.fmtDate(fb.created_at)}</div>
              ${fb.note ? `<div style="font-size:13px;margin-top:4px;font-style:italic">${App.escape(fb.note)}</div>` : '<div style="font-size:12px;color:var(--text3);margin-top:2px">No note</div>'}
            </div>
          </div>
          ${fb.draft ? `<div style="font-size:12px;color:var(--text2);background:var(--bg3);padding:8px;border-radius:6px;white-space:pre-wrap;max-height:80px;overflow:hidden" dir="${dir}">${App.escape(fb.draft.slice(0, 200))}${fb.draft.length > 200 ? '…' : ''}</div>` : ''}
          <div style="display:flex;gap:8px;margin-top:8px">
            <button class="btn btn-ghost btn-sm" onclick="MyStyle.editFeedbackNote(${fb.id}, ${JSON.stringify(fb.note || '')})">Edit Note</button>
            <button class="btn btn-danger btn-sm" onclick="MyStyle.deleteFeedback(${fb.id})">Delete</button>
          </div>
        </div>
      `;
    }).join('');
  },

  editFeedbackNote(id, currentNote) {
    const note = prompt('Edit note:', currentNote);
    if (note === null) return;
    API.put(`/api/style/feedback/${id}?note=${encodeURIComponent(note)}`, {})
      .then(() => { App.toast('Note updated', 'success'); this.loadFeedback(); })
      .catch(e => App.toast(e.message, 'error'));
  },

  async deleteFeedback(id) {
    if (!confirm('Delete this feedback?')) return;
    try {
      await API.del(`/api/style/feedback/${id}`);
      App.toast('Deleted', 'success');
      this.loadFeedback();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  }
};
