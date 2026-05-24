const Settings = {
  current: {},
  _dirty: false,
  _dirtyWired: false,

  async load() {
    try {
      this.current = await API.get('/api/settings');
      this.render();
    } catch (e) {
      App.toast('Could not load settings', 'error');
    }
    this.loadSkill();
    this.loadAIProviders();
    this._wireDirtyTracking();
    this._setDirty(false);
  },

  _wireDirtyTracking() {
    if (this._dirtyWired) return;
    this._dirtyWired = true;
    const screen = document.getElementById('screen-settings');
    if (!screen) return;
    const mark = () => this._setDirty(true);
    screen.addEventListener('input', mark);
    screen.addEventListener('change', mark);
    // Toggle clicks
    screen.addEventListener('click', (e) => {
      if (e.target.closest('.toggle-option')) mark();
    });
    window.addEventListener('beforeunload', (e) => {
      if (this._dirty && App.currentScreen === 'settings') {
        e.preventDefault();
        e.returnValue = '';
      }
    });
  },

  _setDirty(v) {
    this._dirty = v;
    const btn = document.querySelector('#screen-settings .screen-header .btn-primary');
    if (btn) {
      btn.textContent = v ? 'Save All •' : 'Save All';
      btn.classList.toggle('btn-dirty', v);
    }
  },

  render() {
    const s = this.current;

    // Claude backend toggle
    const claudeBackend = s['claude_backend'] || 'cli';
    this._setClaudeBackend(claudeBackend);

    // API key fields
    const keyMap = {
      'youtube-key': 'youtube_api_key',
      'claude-key': 'claude_api_key',
      'apify-key': 'apify_api_key',
      'twitter-auth-token': 'twitter_auth_token',
      'twitter-ct0': 'twitter_ct0',
      'linkedin-li-at': 'linkedin_li_at',
    };
    Object.keys(keyMap).forEach(f => {
      const el = document.getElementById('setting-' + f);
      if (!el) return;
      el.value = s[keyMap[f]] || '';
      el.type = 'password';
    });

    // Scraping options
    const maxEl = document.getElementById('setting-scrape-max');
    if (maxEl) maxEl.value = s['scrape_max_posts'] || '20';

    const liActor = document.getElementById('setting-linkedin-actor');
    if (liActor) liActor.value = s['apify_linkedin_actor'] || '';

    const twActor = document.getElementById('setting-twitter-actor');
    if (twActor) twActor.value = s['apify_twitter_actor'] || '';

    const liHashEl = document.getElementById('setting-linkedin-hashtags');
    if (liHashEl) liHashEl.value = s['linkedin_hashtags'] || '';

    this._bindToggle('setting-twitter-replies-toggle', s['scrape_twitter_replies'] || 'false');
    this._bindToggle('setting-twitter-retweets-toggle', s['scrape_twitter_retweets'] || 'false');
    this._bindToggle('setting-proxy-toggle', s['scrape_use_proxy'] || 'false');

    // Default language
    this._bindToggle('setting-lang-toggle', s['default_language'] || 'ar');

    // Default format
    const fmt = document.getElementById('setting-format');
    if (fmt) fmt.value = s['default_format'] || 'linkedin_post';
  },

  _bindToggle(groupId, activeVal) {
    document.querySelectorAll(`#${groupId} .toggle-option`).forEach(opt => {
      opt.classList.toggle('active', opt.dataset.val === activeVal);
      opt.onclick = () => {
        document.querySelectorAll(`#${groupId} .toggle-option`).forEach(o => o.classList.remove('active'));
        opt.classList.add('active');
      };
    });
  },

  _setClaudeBackend(val) {
    document.querySelectorAll('#setting-claude-backend-toggle .toggle-option').forEach(o => {
      o.classList.toggle('active', o.dataset.val === val);
    });
    const apiRow = document.getElementById('setting-claude-api-key-row');
    const cliHint = document.getElementById('setting-claude-cli-hint');
    if (apiRow) apiRow.style.display = val === 'api' ? '' : 'none';
    if (cliHint) cliHint.style.display = val === 'cli' ? '' : 'none';
  },

  onClaudeBackendChange(val) {
    this._setClaudeBackend(val);
  },

  toggleShow(field) {
    const el = document.getElementById('setting-' + field);
    if (!el) return;
    if (el.type === 'password') {
      // Fetch actual value to display
      const keyMap = {
        'youtube-key': 'youtube_api_key',
        'claude-key': 'claude_api_key',
        'apify-key': 'apify_api_key',
        'twitter-auth-token': 'twitter_auth_token',
        'twitter-ct0': 'twitter_ct0',
        'linkedin-li-at': 'linkedin_li_at',
      };
      const key = keyMap[field];
      API.get(`/api/settings/value/${key}`)
        .then(r => {
          el.value = r.value || '';
          el.type = 'text';
        })
        .catch(() => { el.type = 'text'; });
    } else {
      el.type = 'password';
    }
  },

  async test(service) {
    const keyMap = { youtube: 'youtube_api_key', claude: 'claude_api_key', apify: 'apify_api_key' };
    const key = keyMap[service];
    try {
      const r = await API.get(`/api/settings/value/${key}`);
      if (!r.value) { App.toast('No API key saved yet', 'error'); return; }

      if (service === 'youtube') {
        const res = await fetch(`https://www.googleapis.com/youtube/v3/search?part=id&q=test&maxResults=1&key=${encodeURIComponent(r.value)}`);
        if (res.ok) App.toast('YouTube API key is valid!', 'success');
        else { const j = await res.json(); App.toast('YouTube key error: ' + (j.error?.message || res.status), 'error'); }
      } else if (service === 'claude') {
        const res = await API.post('/api/write/generate', {
          idea: 'test',
          format: 'caption',
          language: 'en',
          angle: 'share a tip'
        });
        if (res.draft !== undefined) App.toast('Claude API key is valid!', 'success');
      } else if (service === 'apify') {
        App.toast('Testing Apify key…', 'info');
        const res = await API.get('/api/settings/test/apify');
        if (res.ok) App.toast(`Apify key valid — account: ${res.username}`, 'success');
        else App.toast('Apify key error: ' + (res.error || 'unknown'), 'error');
      }
    } catch (e) {
      App.toast('Test failed: ' + e.message, 'error');
    }
  },

  async saveAll() {
    const data = {};

    const claudeBackend = document.querySelector('#setting-claude-backend-toggle .toggle-option.active')?.dataset.val || 'cli';
    data['claude_backend'] = claudeBackend;

    // For credential fields, send empty string when user clears them so the value can be removed.
    const credField = (id, key) => {
      const el = document.getElementById(id);
      if (!el) return;
      data[key] = (el.value || '').trim();
    };
    credField('setting-youtube-key', 'youtube_api_key');
    credField('setting-claude-key', 'claude_api_key');
    credField('setting-apify-key', 'apify_api_key');
    credField('setting-twitter-auth-token', 'twitter_auth_token');
    credField('setting-twitter-ct0', 'twitter_ct0');
    credField('setting-linkedin-li-at', 'linkedin_li_at');
    const liHashtags = document.getElementById('setting-linkedin-hashtags')?.value?.trim();
    if (liHashtags !== undefined) data['linkedin_hashtags'] = liHashtags;

    // Scraping options
    const scrapeMax = document.getElementById('setting-scrape-max')?.value?.trim();
    if (scrapeMax) data['scrape_max_posts'] = scrapeMax;

    const liActor = document.getElementById('setting-linkedin-actor')?.value?.trim();
    if (liActor) data['apify_linkedin_actor'] = liActor;

    const twActor = document.getElementById('setting-twitter-actor')?.value?.trim();
    if (twActor) data['apify_twitter_actor'] = twActor;

    const replies = document.querySelector('#setting-twitter-replies-toggle .toggle-option.active')?.dataset.val;
    if (replies) data['scrape_twitter_replies'] = replies;

    const retweets = document.querySelector('#setting-twitter-retweets-toggle .toggle-option.active')?.dataset.val;
    if (retweets) data['scrape_twitter_retweets'] = retweets;

    const proxy = document.querySelector('#setting-proxy-toggle .toggle-option.active')?.dataset.val;
    if (proxy) data['scrape_use_proxy'] = proxy;

    const lang = document.querySelector('#setting-lang-toggle .toggle-option.active')?.dataset.val;
    if (lang) data['default_language'] = lang;

    const fmt = document.getElementById('setting-format')?.value;
    if (fmt) data['default_format'] = fmt;

    try {
      await API.post('/api/settings', data);
      App.toast('Settings saved!', 'success');
      this._setDirty(false);
      this.load();
    } catch (e) {
      App.toast(e.message, 'error');
    }
  },

  async loadSkill() {
    try {
      const r = await API.get('/api/settings/skill/analyze-accounts');
      const ta = document.getElementById('skill-analyze-content');
      const hint = document.getElementById('skill-path-hint');
      if (ta) ta.value = r.content || '';
      if (hint) hint.textContent = r.path || '';
    } catch {}
  },

  reloadSkill() {
    this.loadSkill();
    App.toast('Skill reloaded from disk', 'info');
  },

  editInCLI() {
    const path = document.getElementById('skill-path-hint')?.textContent?.trim();
    const cmd = path ? `claude "${path}"` : 'claude ~/.claude/skills/analyze-accounts.md';
    navigator.clipboard.writeText(cmd).then(() => {
      App.toast(`Copied: ${cmd}`, 'success');
    }).catch(() => {
      App.toast(cmd, 'info');
    });
  },

  async saveSkill() {
    const ta = document.getElementById('skill-analyze-content');
    if (!ta) return;
    try {
      await API.post('/api/settings/skill/analyze-accounts', { content: ta.value });
      App.toast('Skill saved to ~/.claude/skills/analyze-accounts.md', 'success');
    } catch (e) {
      App.toast('Save failed: ' + e.message, 'error');
    }
  },

  // ── AI Providers ──────────────────────────────────────────────────────────
  async loadAIProviders() {
    const el = document.getElementById('ai-providers-list');
    if (!el) return;
    try {
      const providers = await API.get('/api/settings/ai-providers');
      el.innerHTML = this._renderAIProviders(providers);
    } catch {
      el.innerHTML = '<p style="color:var(--text3);font-size:12px">Could not load AI providers.</p>';
    }
  },

  _renderAIProviders(providers) {
    const meta = {
      claude_cli: { label: 'Claude CLI', sublabel: 'Local claude command — no API key needed', noKey: true },
      groq: { label: 'Groq', sublabel: 'Get free key at console.groq.com', settingKey: 'ai_provider_groq_key' },
      openrouter: { label: 'OpenRouter', sublabel: 'Free tier at openrouter.ai', settingKey: 'ai_provider_openrouter_key' },
      gemini: { label: 'Google Gemini', sublabel: 'Free tier at aistudio.google.com', settingKey: 'ai_provider_gemini_key' },
    };
    return Object.entries(meta).map(([key, m]) => {
      const info = providers[key] || {};
      const models = info.models || [];
      const defaultModel = info.default_model || '';
      const modelSelector = models.length > 1 ? `
        <select id="ai-model-${key}" style="font-size:11px;padding:2px 4px;border:1px solid var(--border);background:var(--bg2);border-radius:4px;color:var(--text1)" title="Select model">
          ${models.map(m => `<option value="${m}" ${m === defaultModel ? 'selected' : ''}>${m.split('/').pop()}</option>`).join('')}
        </select>` : '';
      if (m.noKey) {
        return `
          <div class="ai-provider-row">
            <div style="flex:1">
              <div class="ai-provider-label">${m.label}</div>
              <div class="ai-provider-sublabel">${m.sublabel}</div>
            </div>
            ${modelSelector}
            <span class="ai-provider-status ok" id="ai-status-${key}"></span>
            <button class="btn btn-ghost btn-sm" onclick="Settings.testAIProvider('${key}')">Check</button>
          </div>
        `;
      }
      const hasKey = info.has_key;
      return `
        <div class="ai-provider-row">
          <div style="flex:1;min-width:0">
            <div class="ai-provider-label">${m.label}</div>
            <div class="ai-provider-sublabel">${m.sublabel}</div>
          </div>
          ${modelSelector}
          <input type="password" id="ai-key-${key}" placeholder="${hasKey ? '●●●●●●●●' : 'Paste API key...'}"
            style="width:160px;font-size:12px" />
          <span class="ai-provider-status" id="ai-status-${key}">${hasKey ? '<span style="color:var(--green)">✓</span>' : ''}</span>
          <button class="btn btn-ghost btn-sm" onclick="Settings.saveAIProviderKey('${key}', '${m.settingKey}')">Save</button>
          <button class="btn btn-ghost btn-sm" onclick="Settings.testAIProvider('${key}', document.getElementById('ai-model-${key}')?.value)">Test</button>
        </div>
      `;
    }).join('');
  },

  async saveAIProviderKey(provider, settingKey) {
    const input = document.getElementById(`ai-key-${provider}`);
    const key = input?.value?.trim();
    if (!key) { App.toast('Enter an API key first', 'error'); return; }
    try {
      await API.post('/api/settings', { [settingKey]: key });
      document.getElementById(`ai-status-${provider}`).innerHTML = '<span style="color:var(--green)">✓ Saved</span>';
      App.toast(`${provider} key saved!`, 'success');
      input.value = '';
      input.placeholder = '●●●●●●●●';
    } catch (e) {
      App.toast('Save failed: ' + e.message, 'error');
    }
  },

  async testAIProvider(provider, model) {
    const statusEl = document.getElementById(`ai-status-${provider}`);
    if (statusEl) statusEl.innerHTML = '<span style="color:var(--text3)">Testing…</span>';
    const body = { provider };
    if (model) body.model = model;
    try {
      const r = await API.post('/api/settings/test-ai-provider', body);
      if (r.ok) {
        if (statusEl) statusEl.innerHTML = '<span style="color:var(--green)">✓ Works</span>';
        App.toast(`${provider}: connection OK`, 'success');
      } else {
        const errMap = {
          token_missing: 'No API key saved',
          token_invalid: 'Invalid API key',
          cli_not_found: 'claude not found on PATH',
          rate_limit: 'Rate limited — try again',
        };
        const msg = errMap[r.error] || r.error || 'Failed';
        if (statusEl) statusEl.innerHTML = `<span style="color:var(--red)">✗ ${msg}</span>`;
        App.toast(`${provider}: ${msg}`, 'error');
      }
    } catch (e) {
      if (statusEl) statusEl.innerHTML = '<span style="color:var(--red)">✗ Error</span>';
      App.toast('Test failed: ' + e.message, 'error');
    }
  },
};
