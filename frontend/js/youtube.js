const YouTube = (() => {
  let keywords = [];

  function init() {
    renderKeywords();
  }

  // ── Keywords ────────────────────────────────────────────────────────────

  function addKeyword() {
    const input = document.getElementById('yt-kw-input');
    const priority = document.getElementById('yt-kw-priority').value;
    const term = (input.value || '').trim();
    if (!term) return;
    keywords.push({ term, priority });
    input.value = '';
    renderKeywords();
  }

  function removeKeyword(i) {
    keywords.splice(i, 1);
    renderKeywords();
  }

  function renderKeywords() {
    const el = document.getElementById('yt-keywords-list');
    if (!el) return;
    if (!keywords.length) {
      el.innerHTML = '<span style="color:var(--text3);font-size:12px">No keywords added yet</span>';
      return;
    }
    el.innerHTML = keywords.map((kw, i) => `
      <span class="filter-chip active" style="display:inline-flex;align-items:center;gap:6px;margin:2px">
        <span style="font-size:10px;color:var(--text3)">[${kw.priority}]</span>
        ${kw.term}
        <span style="cursor:pointer;opacity:0.6" onclick="YouTube.removeKeyword(${i})">×</span>
      </span>`).join('');
  }

  // ── Source toggle ────────────────────────────────────────────────────────

  function toggleSource(mode) {
    document.getElementById('yt-source-text').style.display = mode === 'text' ? '' : 'none';
    document.getElementById('yt-source-url').style.display = mode === 'url' ? '' : 'none';
    document.querySelectorAll('#yt-source-toggle .toggle-option').forEach(el => {
      el.classList.toggle('active', el.dataset.val === mode);
    });
  }

  // ── Generate ─────────────────────────────────────────────────────────────

  async function generate() {
    const btn = document.getElementById('yt-generate-btn');
    const outputEl = document.getElementById('yt-output');
    const placeholderEl = document.getElementById('yt-placeholder');

    const mode = document.querySelector('#yt-source-toggle .toggle-option.active')?.dataset.val || 'text';
    const transcriptText = mode === 'text' ? (document.getElementById('yt-transcript').value || '').trim() : null;
    const transcriptUrl = mode === 'url' ? (document.getElementById('yt-url').value || '').trim() : null;

    if (!transcriptText && !transcriptUrl) {
      App.toast('Paste a transcript or enter a YouTube URL', 'error'); return;
    }

    const projectName = (document.getElementById('yt-project-name').value || '').trim() || 'My Channel';
    const projectDesc = (document.getElementById('yt-project-desc').value || '').trim();
    const projectLang = document.querySelector('#yt-lang-toggle .toggle-option.active')?.dataset.val || 'en';
    const arabicDialect = document.getElementById('yt-dialect').value || '';

    btn.disabled = true;
    btn.textContent = '⏳ Generating…';
    outputEl.style.display = 'none';
    placeholderEl.style.display = '';
    placeholderEl.textContent = 'Calling Claude…';

    try {
      const res = await fetch('/api/youtube/generate-pack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          transcript_text: transcriptText || null,
          transcript_url: transcriptUrl || null,
          project_name: projectName,
          project_description: projectDesc,
          project_language: projectLang,
          arabic_dialect: arabicDialect || null,
          keywords,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Generation failed');
      renderPack(data.pack, data.usage);
      placeholderEl.style.display = 'none';
      outputEl.style.display = '';
    } catch (e) {
      placeholderEl.textContent = '❌ ' + e.message;
      App.toast(e.message, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = '✨ Generate Content Pack';
    }
  }

  // ── Render output ─────────────────────────────────────────────────────────

  function renderPack(pack, usage) {
    const el = document.getElementById('yt-output');

    const section = (title, content) => `
      <div style="margin-bottom:20px">
        <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:var(--text3);margin-bottom:8px">${title}</div>
        ${content}
      </div>`;

    const copyBtn = (text, label) => {
      const id = 'yt-copy-' + Math.random().toString(36).slice(2);
      // Store text in a data attribute to avoid escaping issues
      return `<button class="btn btn-ghost btn-sm" style="margin-top:6px" onclick="navigator.clipboard.writeText(document.getElementById('${id}').dataset.v);App.toast('Copied!')">📋 Copy ${label}</button><span id="${id}" data-v="${text.replace(/"/g,'&quot;')}" style="display:none"></span>`;
    };

    let html = '';

    // Description
    if (pack.description) {
      html += section('Description', `
        <div style="white-space:pre-wrap;font-size:13px;line-height:1.6;background:var(--bg2);padding:12px 14px;border-radius:8px;border:1px solid var(--border)">${escHtml(pack.description)}</div>
        ${copyBtn(pack.description, 'description')}`);
    }

    // Chapters
    if (pack.chapters?.length) {
      const chapText = pack.chapters.map(c => `${c.t} – ${c.title}`).join('\n');
      html += section('Chapters', `
        <div style="font-size:13px;font-family:monospace;background:var(--bg2);padding:12px 14px;border-radius:8px;border:1px solid var(--border)">
          ${pack.chapters.map(c => `<div><b>${escHtml(c.t)}</b> — ${escHtml(c.title)}</div>`).join('')}
        </div>
        ${copyBtn(chapText, 'chapters')}`);
    }

    // Title variants
    if (pack.title_variants?.length) {
      const titlesText = pack.title_variants.join('\n');
      html += section('Title Variants', `
        <div style="display:flex;flex-direction:column;gap:6px">
          ${pack.title_variants.map((t, i) => `
            <div style="display:flex;align-items:center;gap:8px;background:var(--bg2);padding:8px 12px;border-radius:6px;border:1px solid var(--border)">
              <span style="font-size:11px;color:var(--text3);min-width:16px">${i + 1}.</span>
              <span style="font-size:13px;flex:1">${escHtml(t)}</span>
              <button class="btn btn-ghost btn-sm" style="flex-shrink:0;padding:2px 8px" onclick="navigator.clipboard.writeText(${JSON.stringify(t)});App.toast('Copied!')">📋</button>
            </div>`).join('')}
        </div>`);
    }

    // Thumbnail texts
    if (pack.thumbnail_text_options?.length) {
      html += section('Thumbnail Text Options', `
        <div style="display:flex;flex-wrap:wrap;gap:8px">
          ${pack.thumbnail_text_options.map(t => `
            <div style="background:var(--accent);color:#fff;padding:6px 12px;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer"
                 onclick="navigator.clipboard.writeText(${JSON.stringify(t)});App.toast('Copied!')">${escHtml(t)}</div>`).join('')}
        </div>`);
    }

    // Tags
    if (pack.tags?.length) {
      const tagsText = pack.tags.join(', ');
      html += section('Tags', `
        <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px">
          ${pack.tags.map(t => `<span class="filter-chip">${escHtml(t)}</span>`).join('')}
        </div>
        ${copyBtn(tagsText, 'tags')}`);
    }

    // Hashtags
    if (pack.hashtags?.length) {
      html += section('Hashtags', `
        <div style="display:flex;flex-wrap:wrap;gap:6px">
          ${pack.hashtags.map(h => `
            <span style="background:var(--bg2);border:1px solid var(--border);padding:4px 10px;border-radius:20px;font-size:13px;color:var(--accent)">${escHtml(h)}</span>`).join('')}
        </div>`);
    }

    // Shorts clips
    if (pack.shorts_clips?.length) {
      html += section('Shorts / Reels Clips', `
        <div style="display:flex;flex-direction:column;gap:10px">
          ${pack.shorts_clips.map((c, i) => `
            <div style="background:var(--bg2);padding:12px 14px;border-radius:8px;border:1px solid var(--border)">
              <div style="font-size:11px;color:var(--text3);margin-bottom:4px">Clip ${i + 1} · ${escHtml(c.start)} → ${escHtml(c.end)}</div>
              <div style="font-size:13px;font-weight:600;margin-bottom:4px">Hook: ${escHtml(c.hook)}</div>
              <div style="font-size:12px;color:var(--text2)">${escHtml(c.caption)}</div>
            </div>`).join('')}
        </div>`);
    }

    if (usage) {
      html += `<div style="font-size:11px;color:var(--text3);margin-top:8px">Tokens used: ${usage.input_tokens} in + ${usage.output_tokens} out</div>`;
    }

    el.innerHTML = html;
  }

  function escHtml(s) {
    return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function copyAll() {
    const pack = document.getElementById('yt-output');
    navigator.clipboard.writeText(pack?.innerText || '');
    App.toast('Copied all');
  }

  return { init, addKeyword, removeKeyword, toggleSource, generate, copyAll };
})();
