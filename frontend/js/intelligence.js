const Intelligence = {
  sessions: [],
  currentSessionId: null,

  async load() {
    await this.loadSessions();
  },

  async loadSessions() {
    const el = document.getElementById('intelligence-sessions');
    if (!el) return;
    try {
      this.sessions = await API.get('/api/intelligence/sessions');
      el.innerHTML = this.sessions.length ? this.sessions.map(s => `
        <div class="chat-session ${this.currentSessionId === s.id ? 'active' : ''}" onclick="Intelligence.openSession(${s.id})">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;opacity:0.5"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
          <span class="chat-session-title">${App.escape(s.title || 'New Chat')}</span>
          <button class="btn btn-ghost chat-session-del" onclick="event.stopPropagation();Intelligence.deleteSession(${s.id})">×</button>
        </div>
      `).join('') : '<div style="color:var(--text3);font-size:12px;padding:6px 10px">No chats yet</div>';
    } catch {}
  },

  async newSession() {
    try {
      const session = await API.post('/api/intelligence/sessions', {});
      this.currentSessionId = session.id;
      await this.loadSessions();
      this.clearMessages();
      document.getElementById('intelligence-input')?.focus();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  async openSession(id) {
    this.currentSessionId = id;
    this.loadSessions();
    this.clearMessages();
    try {
      const msgs = await API.get(`/api/intelligence/sessions/${id}/messages`);
      const container = document.getElementById('intelligence-messages');
      if (!container) return;
      container.innerHTML = '';
      msgs.forEach(m => this.appendMessage(m.role, m.content));
      container.scrollTop = container.scrollHeight;
    } catch {}
  },

  async deleteSession(id) {
    try {
      await API.del(`/api/intelligence/sessions/${id}`);
      if (this.currentSessionId === id) {
        this.currentSessionId = null;
        this.clearMessages();
      }
      this.loadSessions();
    } catch {}
  },

  clearMessages() {
    const el = document.getElementById('intelligence-messages');
    if (el) el.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🧠</div>
        <h3>Intelligence</h3>
        <p>Ask anything about your creators, news, and market data.</p>
      </div>
    `;
  },

  async send() {
    const input = document.getElementById('intelligence-input');
    const msg = input?.value?.trim();
    if (!msg) return;

    // Create session if none
    if (!this.currentSessionId) {
      const session = await API.post('/api/intelligence/sessions', {});
      this.currentSessionId = session.id;
    }

    input.value = '';
    this.appendMessage('user', msg);

    const btn = document.getElementById('intelligence-send-btn');
    if (btn) btn.disabled = true;

    // Typing indicator
    const typingId = 'typing-' + Date.now();
    this.appendRaw(`<div id="${typingId}" class="chat-bubble assistant"><div class="spinner"></div></div>`);

    try {
      const data = await API.post(`/api/intelligence/sessions/${this.currentSessionId}/chat`, { content: msg });
      document.getElementById(typingId)?.remove();
      this.appendMessage('assistant', data.answer);
      this.loadSessions();
    } catch (e) {
      document.getElementById(typingId)?.remove();
      this.appendMessage('assistant', '⚠️ ' + e.message);
    } finally {
      if (btn) btn.disabled = false;
    }
  },

  appendMessage(role, content) {
    const isAr = App.detectArabic(content);
    const container = document.getElementById('intelligence-messages');
    if (!container) return;

    // Remove empty state
    const empty = container.querySelector('.empty-state');
    if (empty) empty.remove();

    const el = document.createElement('div');
    el.className = `chat-bubble ${role}`;
    if (isAr) el.style.fontFamily = 'var(--font-ar)';
    el.textContent = content;
    container.appendChild(el);
    container.scrollTop = container.scrollHeight;
  },

  appendRaw(html) {
    const container = document.getElementById('intelligence-messages');
    if (!container) return;
    const empty = container.querySelector('.empty-state');
    if (empty) empty.remove();
    container.insertAdjacentHTML('beforeend', html);
    container.scrollTop = container.scrollHeight;
  },

  onKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      this.send();
    }
  }
};
