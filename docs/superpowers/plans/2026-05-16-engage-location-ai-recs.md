# Engage: Location Dropdown + AI Profile Recommendations

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the free-text location input in Search LinkedIn Profiles with a preset dropdown (+ custom option), add an AI Recommendations section that generates tailored search queries using Claude, and fix the frontend error message to guide the user to Settings when no scraping method is configured.

**Architecture:** Three isolated changes — (1) HTML/JS location dropdown, (2) a new backend endpoint `/api/engage/ai-recommendations` that calls Claude to produce 5 search suggestions, (3) JS frontend that calls that endpoint, renders clickable chips, and auto-runs searches. No new files needed; all changes stay in the three existing files.

**Tech Stack:** Vanilla JS, FastAPI, SQLAlchemy, Anthropic Python SDK (already used in the same file), Jinja-less HTML template.

---

## File Map

| File | Change |
|---|---|
| `frontend/index.html` lines 1237–1263 | Replace location `<input>` with `<select>` + hidden custom `<input>`; add AI Recommendations section |
| `frontend/js/engage.js` | Add `locationPresetChange()`, update `searchProfiles()`, add `getAIRecommendations()`, `_applyRecommendation()` |
| `backend/routes/engage.py` | Add `POST /api/engage/ai-recommendations` endpoint |

---

## Task 1: Location Dropdown in HTML

**Files:**
- Modify: `frontend/index.html:1248–1255`

Replace the location text input with a `<select>` + hidden custom input. No JS yet — just the markup.

- [ ] **Step 1: Replace the location input block**

Find this block (around line 1248):
```html
<div class="form-group" style="flex:1;min-width:140px;margin-bottom:0">
  <label>Location (optional)</label>
  <input type="text" id="engage-search-location" placeholder="UAE, Saudi Arabia..." />
</div>
```

Replace with:
```html
<div class="form-group" style="flex:1;min-width:160px;margin-bottom:0">
  <label>Location (optional)</label>
  <select id="engage-search-location-preset" onchange="Engage.locationPresetChange()" style="width:100%">
    <option value="">Worldwide</option>
    <optgroup label="Gulf">
      <option value="United Arab Emirates">UAE</option>
      <option value="Dubai, United Arab Emirates">Dubai, UAE</option>
      <option value="Abu Dhabi, United Arab Emirates">Abu Dhabi, UAE</option>
      <option value="Saudi Arabia">Saudi Arabia</option>
      <option value="Riyadh, Saudi Arabia">Riyadh, KSA</option>
      <option value="Qatar">Qatar</option>
      <option value="Kuwait">Kuwait</option>
      <option value="Bahrain">Bahrain</option>
      <option value="Oman">Oman</option>
    </optgroup>
    <optgroup label="Levant &amp; North Africa">
      <option value="Egypt">Egypt</option>
      <option value="Cairo, Egypt">Cairo, Egypt</option>
      <option value="Jordan">Jordan</option>
      <option value="Lebanon">Lebanon</option>
      <option value="Morocco">Morocco</option>
    </optgroup>
    <option value="__custom__">Custom…</option>
  </select>
  <input type="text" id="engage-search-location-custom"
         placeholder="Type a location…"
         style="display:none;margin-top:6px;width:100%" />
</div>
```

- [ ] **Step 2: Visually verify in browser**

Open the Engage page → Search LinkedIn Profiles section → confirm the dropdown renders with all groups and the last option is "Custom…".

---

## Task 2: JS — Wire Up Location Dropdown

**Files:**
- Modify: `frontend/js/engage.js`

Two changes: add `locationPresetChange()` and update `searchProfiles()` to read the new elements.

- [ ] **Step 1: Add `locationPresetChange` function**

In `engage.js`, add this function **before** the `return` statement at the bottom of the IIFE:

```js
function locationPresetChange() {
  const preset = document.getElementById('engage-search-location-preset');
  const custom = document.getElementById('engage-search-location-custom');
  if (!preset || !custom) return;
  custom.style.display = preset.value === '__custom__' ? '' : 'none';
  if (preset.value !== '__custom__') custom.value = '';
}
```

- [ ] **Step 2: Update `searchProfiles()` to read from new elements**

Find the existing `searchProfiles` function. Replace this line:
```js
const location = document.getElementById('engage-search-location')?.value?.trim() || '';
```

With:
```js
const preset = document.getElementById('engage-search-location-preset');
const customInput = document.getElementById('engage-search-location-custom');
const location = preset?.value === '__custom__'
  ? (customInput?.value?.trim() || '')
  : (preset?.value || '');
```

- [ ] **Step 3: Export `locationPresetChange` in return statement**

Find the last line of the IIFE:
```js
return { load, refresh, applyFilters, markStatus, clearDone, generateReply, searchProfiles, addCreatorFromSearch };
```
Add `locationPresetChange`:
```js
return { load, refresh, applyFilters, markStatus, clearDone, generateReply, searchProfiles, addCreatorFromSearch, locationPresetChange };
```

- [ ] **Step 4: Manual test**

In browser:
1. Select "Custom…" → text input appears below dropdown.
2. Select "UAE" → text input disappears.
3. Run a search with "UAE" selected → watch Network tab, confirm request body has `location: "United Arab Emirates"`.
4. Select "Custom…", type "London", search → request body has `location: "London"`.

---

## Task 3: Better Error Message for Missing Credentials

**Files:**
- Modify: `frontend/js/engage.js` — `searchProfiles()` catch block

Currently the error renders raw HTML into `tableEl`. If the backend returns the "No scraping method available" message, surface a helpful link to Settings instead of just the text.

- [ ] **Step 1: Update the catch block in `searchProfiles()`**

Find:
```js
    } catch (e) {
      tableEl.innerHTML = `<div style="color:var(--red);font-size:13px;padding:16px">Error: ${_escHtml(e.message)}</div>`;
    }
```

Replace with:
```js
    } catch (e) {
      const isConfig = e.message && e.message.toLowerCase().includes('no scraping method');
      tableEl.innerHTML = isConfig
        ? `<div style="color:var(--red);font-size:13px;padding:16px">
             No scraping method configured.
             <a href="#" onclick="App.navigate('settings');return false" style="color:var(--accent)">
               Go to Settings → Scraping Options
             </a> to add an Apify key or LinkedIn li_at cookie.
           </div>`
        : `<div style="color:var(--red);font-size:13px;padding:16px">Error: ${_escHtml(e.message)}</div>`;
    }
```

- [ ] **Step 2: Test**

Without Apify or li_at configured, click Search People → should see the linked error message instead of the raw text.

---

## Task 4: Backend — AI Recommendations Endpoint

**Files:**
- Modify: `backend/routes/engage.py`

Add a new Pydantic schema and route. The endpoint calls Claude (same pattern as `_score_posts`) to produce 5 tailored search suggestions.

- [ ] **Step 1: Add Pydantic response schema**

After the existing `SearchProfilesRequest` class (around line 66), add:

```python
class AIRecommendationSuggestion(BaseModel):
    keywords: str
    location: str
    reason: str


class AIRecommendationsResponse(BaseModel):
    suggestions: list[AIRecommendationSuggestion]
```

- [ ] **Step 2: Add the endpoint**

At the end of the file (after `_search_via_playwright`), add:

```python
# ─── POST /api/engage/ai-recommendations ──────────────────────────────────────

@router.post("/ai-recommendations", response_model=AIRecommendationsResponse)
def get_ai_recommendations(db: Session = Depends(get_db)):
    """Use Claude to suggest LinkedIn search queries tailored to the user's niche."""
    profile = db.query(Profile).first()
    profile_text = ""
    if profile:
        parts = []
        if profile.bio:
            parts.append(f"Bio: {profile.bio}")
        if profile.audience:
            parts.append(f"Target audience: {profile.audience}")
        if profile.niche:
            parts.append(f"Niche: {profile.niche}")
        profile_text = "\n".join(parts)

    if not profile_text:
        profile_text = "Marketing consultant and AI advisor for Arab business owners in the Gulf region."

    system_prompt = (
        "You are a LinkedIn growth strategist. Based on the user's profile, "
        "generate exactly 5 LinkedIn people-search suggestions to help them find "
        "high-value connections. Each suggestion should have distinct keywords and location.\n\n"
        "Respond ONLY with a valid JSON array. No text before or after the JSON.\n"
        'Format: [{"keywords": "...", "location": "...", "reason": "..."}, ...]'
    )
    user_prompt = (
        f"User profile:\n{profile_text}\n\n"
        "Generate 5 LinkedIn search suggestions. "
        "keywords = job title / role / topic (e.g. 'CMO fintech startup'). "
        "location = city or country (e.g. 'Dubai, United Arab Emirates'). "
        "reason = one sentence why this persona is worth connecting with."
    )

    try:
        from ..ai.client import resolve_backend, get_api_key
        backend, api_key = resolve_backend(db)
    except ValueError:
        return AIRecommendationsResponse(suggestions=_default_suggestions())

    try:
        if backend == "cli":
            import subprocess
            result = subprocess.run(
                ["claude", "-p", user_prompt, "--system", system_prompt, "--output-format", "text"],
                capture_output=True, text=True, timeout=60,
            )
            raw = result.stdout.strip()
        else:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=800,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = next((b.text for b in resp.content if hasattr(b, "text")), "").strip()

        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            raise ValueError("No JSON array in response")
        data = json.loads(match.group(0))
        suggestions = [
            AIRecommendationSuggestion(
                keywords=str(item.get("keywords", "")),
                location=str(item.get("location", "")),
                reason=str(item.get("reason", "")),
            )
            for item in data[:5]
        ]
        return AIRecommendationsResponse(suggestions=suggestions)

    except Exception as e:
        log.warning("AI recommendations failed — %s", e)
        return AIRecommendationsResponse(suggestions=_default_suggestions())


def _default_suggestions() -> list[AIRecommendationSuggestion]:
    return [
        AIRecommendationSuggestion(keywords="CMO marketing director", location="United Arab Emirates", reason="Senior marketers who can refer clients or collaborate"),
        AIRecommendationSuggestion(keywords="founder CEO small business", location="Dubai, United Arab Emirates", reason="Business owners who need personal branding help"),
        AIRecommendationSuggestion(keywords="AI consultant digital transformation", location="Saudi Arabia", reason="Tech-forward professionals in Shadi's niche"),
        AIRecommendationSuggestion(keywords="marketing manager e-commerce", location="Egypt", reason="Growing market with strong demand for branding"),
        AIRecommendationSuggestion(keywords="entrepreneur startup personal brand", location="Qatar", reason="Startup founders often looking for LinkedIn presence help"),
    ]
```

- [ ] **Step 3: Check the Profile model has the right fields**

Open `backend/models.py` and confirm the `Profile` model has `bio`, `audience` columns. If it has `niche` too use it; if not, remove that line from the endpoint (the field is already guarded with `if profile.niche`).

Run the server and hit the endpoint manually:
```bash
curl -s -X POST http://localhost:8000/api/engage/ai-recommendations | python3 -m json.tool
```
Expected: JSON with `suggestions` array of 5 objects each with `keywords`, `location`, `reason`.

---

## Task 5: Frontend — AI Recommendations Section

**Files:**
- Modify: `frontend/index.html:1237–1261`
- Modify: `frontend/js/engage.js`

Add the recommendations UI above the search form, and the JS that drives it.

- [ ] **Step 1: Add recommendations section in HTML**

Find this comment in `index.html`:
```html
<!-- Search Profiles section -->
<div style="margin-top:32px">
  <div class="form-section-title" style="margin-bottom:16px">
```

Insert a new block **immediately before** that `<!-- Search Profiles section -->` comment:

```html
<!-- AI Recommendations section -->
<div style="margin-top:32px">
  <div class="form-section-title" style="margin-bottom:12px">
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
    AI-Recommended Searches
  </div>
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
    <button class="btn btn-ghost btn-sm" id="engage-ai-rec-btn" onclick="Engage.getAIRecommendations()">
      ✦ Get AI Suggestions
    </button>
    <span id="engage-ai-rec-status" style="font-size:12px;color:var(--text3)"></span>
  </div>
  <div id="engage-ai-rec-chips" style="display:flex;flex-wrap:wrap;gap:8px;min-height:0"></div>
</div>
```

- [ ] **Step 2: Add `getAIRecommendations()` to engage.js**

Add before the `return` statement:

```js
async function getAIRecommendations() {
  const btn = document.getElementById('engage-ai-rec-btn');
  const status = document.getElementById('engage-ai-rec-status');
  const chips = document.getElementById('engage-ai-rec-chips');
  if (btn) { btn.disabled = true; btn.textContent = 'Thinking…'; }
  if (status) status.textContent = '';
  if (chips) chips.innerHTML = '';

  try {
    const data = await API.post('/api/engage/ai-recommendations', {});
    const suggestions = data.suggestions || [];
    if (!suggestions.length) {
      if (status) status.textContent = 'No suggestions returned.';
      return;
    }
    if (chips) {
      chips.innerHTML = suggestions.map((s, i) => `
        <div class="engage-ai-chip" title="${_escHtml(s.reason)}"
             onclick="Engage._applyRecommendation(${JSON.stringify(_escHtml(s.keywords))}, ${JSON.stringify(_escHtml(s.location))})"
             style="cursor:pointer;background:var(--bg2);border:1px solid var(--border);border-radius:20px;
                    padding:6px 14px;font-size:12px;color:var(--text1);transition:background 0.15s"
             onmouseover="this.style.background='var(--bg3)'"
             onmouseout="this.style.background='var(--bg2)'">
          <span style="font-weight:500">${_escHtml(s.keywords)}</span>
          ${s.location ? `<span style="color:var(--text3);margin-left:4px">· ${_escHtml(s.location)}</span>` : ''}
        </div>`).join('');
    }
    if (status) status.textContent = `${suggestions.length} suggestions — click any to search`;
  } catch (e) {
    if (status) status.textContent = 'Error: ' + e.message;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '✦ Get AI Suggestions'; }
  }
}

function _applyRecommendation(keywords, location) {
  const kw = document.getElementById('engage-search-keywords');
  const preset = document.getElementById('engage-search-location-preset');
  const custom = document.getElementById('engage-search-location-custom');
  if (kw) kw.value = keywords;

  if (preset) {
    // Try to match a preset option
    const match = Array.from(preset.options).find(
      o => o.value.toLowerCase() === location.toLowerCase()
    );
    if (match) {
      preset.value = match.value;
      if (custom) { custom.style.display = 'none'; custom.value = ''; }
    } else {
      preset.value = '__custom__';
      if (custom) { custom.style.display = ''; custom.value = location; }
    }
  }

  searchProfiles();
}
```

- [ ] **Step 3: Export new functions**

Update the return statement:
```js
return {
  load, refresh, applyFilters, markStatus, clearDone, generateReply,
  searchProfiles, addCreatorFromSearch,
  locationPresetChange,
  getAIRecommendations, _applyRecommendation,
};
```

- [ ] **Step 4: Manual end-to-end test**

1. Open Engage page.
2. Click "✦ Get AI Suggestions" → button shows "Thinking…" then chips appear.
3. Hover a chip → tooltip shows `reason`.
4. Click a chip → keywords input fills, location dropdown updates, search runs automatically.
5. If location doesn't match a preset → "Custom…" is selected and text input shows with the location.

---

## Self-Review Checklist

### Spec coverage
- [x] Location dropdown with presets → Task 1 + 2
- [x] Custom location option → Task 1 + 2 (`__custom__` branch)
- [x] Search not working → Task 3 (better error with Settings link)
- [x] AI recommendation with same sources/tools → Task 4 + 5

### Placeholder scan
- No TBD or TODO in any step.
- All code blocks are complete.

### Type consistency
- `AIRecommendationSuggestion` defined in Task 4, used as-is in Task 5 (`s.keywords`, `s.location`, `s.reason`).
- `locationPresetChange` exported in Task 2 Step 3, referenced in HTML `onchange` in Task 1 Step 1.
- `_applyRecommendation` exported in Task 5 Step 3, called from chip `onclick` in Task 5 Step 2.
