# LinkedIn Posts Skill + Posts Screen — Design

**Date:** 2026-09-13
**Status:** Approved in brainstorming, awaiting spec review
**Approach chosen:** B — a Claude Code skill that writes the posts, plus a Posts screen in the branding app that stores, tracks and learns from them.

---

## 1. Goal

Help Shadi publish **2–3 English LinkedIn posts per day** that grow a community of business owners, marketers and AI people in the GCC and Egypt (UAE is the main market — Shadi is based in Dubai), in his own voice, without repeating articles, and getting better from his feedback over time.

He currently has no offer to promote. The goal is community growth, discussion and inbound DMs.

---

## 2. Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Language | English only |
| Goal | Grow a community |
| Offer | None yet — pure personal brand |
| Reader | Rotate equally between business owners/founders, marketers, AI people |
| Inputs | Article link · own idea/story · pick from app Sources · a post type · rewrite a post he saw (Arabic → natural English, or English → reworded so it is not a copy) |
| Tone | Direct & practical · storyteller · bold/contrarian |
| Calls to action | Question that invites comments · "DM me" · lead magnet ("Comment SHEET and I'll send it") |
| Proof | Never use results from his CV or name his clients |
| Rewrites | His own words, no credit to the original author |
| Length | Depends on post type (see §4) |
| Emojis | Yes — as accents and bullet markers, not on every line |
| Hashtags | None |
| Source link | News & interesting-fact posts: link in a ready first comment. Case study, educational, insight: source name mentioned in the post, no link. Rewrites: no source |
| Versions | 3 full versions per post by default (he can ask for 2) |
| Extras | Visual idea for every post |
| Storage | Saved to the app so ratings and comments teach the skill |
| Never touch | Politics, religion, his employer, his clients |
| Batches | Single post, daily, weekly, monthly |
| Country rule | Country-specific stories only when about the UAE; region-wide and global topics are fine |

---

## 3. How Shadi uses it

Run `/linkedin-posts` in Claude Code while the app is running at `http://localhost:8000`.

### Modes

1. **Single post** — from a link, an idea, a post type, or a pasted post to rewrite.
2. **Daily batch** (`today`) — 3 posts for one day, each a different type, from fresh articles in Sources.
3. **Weekly batch** (`week`) — the skill first shows a plan (date, slot, type, reader, topic, source) for 7 days at 3 posts/day (21 posts; Shadi can say 2/day → 14). He approves or swaps items in chat, then it writes them.
4. **Monthly batch** (`month`) — plans the whole month, he approves the plan, then it writes **one week at a time** so each week uses his latest feedback.

### Every post comes with

- 3 full versions, each with a different hook formula and angle
- A visual idea (image, infographic, or carousel with slide text)
- A ready first comment with the source link (news and fact posts only)
- A "To create" note when the call to action promises a resource

### Batch rules

- Post types rotate so each week covers all 5 types in roughly equal share; no two posts of the same type on the same day.
- The reader rotates; each day speaks to at least 2 of the 3 reader groups.
- An article is never used twice.
- At most one lead-magnet call to action per day, so Shadi is not overloaded creating resources.
- When planning a week or month, the skill asks whether he has his own ideas or stories to slot in.
- If there are not enough fresh articles, the skill fills the gap with idea-based posts, says so, and suggests fetching Sources.

---

## 4. How the skill writes each post

### Step 1 — Understand and check

- Reads the full article from its URL (falls back to the title and summary stored in the app if the site blocks fetching), or the idea, or the post to rewrite.
- Checks fit: relevant to business owners, marketers or AI people; country-specific only if about the UAE; not about politics, religion, his employer or clients; no CV results.
- If an article fails, it explains why in one line and proposes another.

### Step 2 — Pick the format

| Type | Structure | Length |
|---|---|---|
| Case study | Transformation hook → before → after → what changed → lesson → call to action | 180–280 words |
| News | What happened → why it matters to the reader → what to do now | 80–130 words |
| Educational | Problem → why it hurts → solution, or numbered steps | 150–250 words |
| Interesting fact | The number as the hook → what it means → one takeaway | 60–120 words |
| Insight | Bold take → reasoning or short story → question | 120–200 words |
| Rewrite | Same core idea and flow, new hook, new wording and examples, UAE/GCC-relevant angle; Arabic is re-created in natural English, not translated word for word | Same as the original's type |

Frameworks come from Shadi's playbook (`linkedin_content_strategy_guide-v2.pdf`): Problem-Agitate-Solution for educational, Story-Lesson-Application for insight/story posts, and the 6-step case study conversion for case studies.

### Step 3 — Write 3 versions

- Each version uses a different hook formula from the playbook: lived experience + numbers · before/after contrast · non-conventional list · topic + silent work · painful problem state · reframing question.
- Each version uses a different angle: direct/practical, story, bold.
- 1–2 sentence lines, one idea per post, emojis as accents, no hashtags.
- One call to action per version: a question for comments, "DM me", or a lead magnet.

### Step 4 — Quality gate (rewrite until it passes)

- No banned words: leverage, game changer, changed everything, tapestry, delve, unlocking potential.
- No AI patterns: "It's not X, it's Y" contrast tropes, vague smart-sounding fluff.
- Questions: a hook question is allowed only when it names a specific, real pain of the reader. Generic openers like "Have you ever wondered…?" are banned. (This resolves the playbook listing rhetorical questions as banned while also offering a reframing-question hook.)
- Passes Sarah Ohlson's two questions: *How will someone feel more productive or successful after reading this?* and *Why would someone care if they don't know me?*
- The hook works in the first 2 lines, before "see more".
- Reads naturally out loud.
- **No invented facts or numbers** — every figure must come from the source or from Shadi.

### Step 5 — Extras

- Visual idea for every post.
- First comment with the link for news and interesting-fact posts.
- Source name in the post for case study, educational and insight posts.
- No source for rewrites.

---

## 5. The Posts screen (in the app)

A new **Posts** item in the sidebar, next to Write.

### Main view — content calendar

- Posts listed by day with a slot: morning, midday, evening.
- Card shows type, source article (clickable), batch label (e.g. "Week of 15 Sep"), status.
- Filters: status, type, batch, date range.

### Statuses

`planned → draft → approved → posted`, or `skipped`.

- Weekly/monthly plans approved in chat are saved as **planned** (no versions yet).
- When written, they become **draft**.

### Post detail

- All versions side by side; **Use this version** sets the chosen version; the final text is editable.
- 👍 / 👎 and a comment box on each version.
- Visual idea; first comment with **Copy**; **Copy post** button.
- Lead-magnet "To create: …" note with a done checkbox.
- Buttons: **Approve**, **Skip**, **Mark as posted** (with a field for the LinkedIn post URL).
- Optional results after posting: reactions, comments, impressions (typed in manually).

### Articles

- Creating a post from an article adds the tag `used` to that article in Sources.
- Deleting the post removes the tag, freeing the article.

### Not included

- Editing weekly/monthly plans inside the app (plans are approved and changed in chat).
- Auto-posting to LinkedIn, best-time-to-post suggestions, importing analytics from LinkedIn.

---

## 6. Voice and learning

### Voice profile

- Stored in the app on the profile record (new `voice_profile` field), readable and editable in My Style. The skill reads it before every post or batch.
- Built on the first run when `voice_profile` is empty, from:
  - the playbook rules;
  - tone traits from 5–10 of Shadi's older **Arabic** posts, which he pastes once — the skill extracts personality, rhythm, openings and closings, not wording;
  - creators he names as style inspiration (using the app's existing creator style analysis);
  - the decisions in §2.
- The skill shows the draft profile and saves it only after Shadi approves.

### Learning loop (before every batch)

1. Reads the feedback summary: version ratings and comments, which version was chosen, how the final text differs from the chosen version, and posted results.
2. Finds patterns across the **last 30 posts** (older feedback counts less).
3. Proposes rule changes in plain language ("You shorten the ending every time — add rule 'end with one short line'?"). Only approved rules are appended to the profile's `rules`.
4. Saves hooks from 👍-rated versions and from posts with strong results to the Hook Library (`POST /api/analysis/hooks`, source `manual`, label `LinkedIn posts skill`) as inspiration, never to copy verbatim.

The skill never changes the voice profile without approval and never copies other creators' posts.

---

## 7. Technical design

### 7.1 Skill files

Source lives in the repo and is symlinked into Claude Code:

```
shadi-branding/claude-skills/linkedin-posts/
  SKILL.md                      # trigger, modes, workflow, API calls, app-running check
  references/playbook.md        # formats per type, hook formulas, banned words/patterns, quality gate
  references/rules.md           # audience, country rule, avoid list, CTA & lead magnets, link placement, emojis, lengths
  references/batch-planning.md  # type/reader rotation, slots, dedupe, planning flow
~/.claude/skills/linkedin-posts -> <repo>/claude-skills/linkedin-posts   (symlink)
```

- `SKILL.md` frontmatter: `name: linkedin-posts`; description starts with "Use when…" and describes triggers only (writing, rewriting, planning or batching Shadi's LinkedIn posts).
- Article text: fetched with the WebFetch tool; fallback to `source_items.title/body` via the app API.
- Fresh articles: existing `GET /api/sources/items`, excluding IDs returned by `GET /api/posts/used-source-items`.

### 7.2 Data model

New table `post_batches`:

| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| kind | String(20) | `single` \| `daily` \| `weekly` \| `monthly` |
| label | String(200) | e.g. "Week of 15 Sep" |
| start_date | Date | |
| end_date | Date | |
| created_at | DateTime(tz) | |

New table `linkedin_posts`:

| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| batch_id | FK → post_batches.id, nullable | |
| planned_date | Date, nullable | |
| slot | String(20), nullable | `morning` \| `midday` \| `evening` |
| post_type | String(30) | `case_study` \| `news` \| `educational` \| `fact` \| `insight` (used for type rotation) |
| origin | String(20) | `article` \| `idea` \| `rewrite` \| `type_only` — what the post was made from; rewrites keep the type they are written in |
| reader | String(30) | `owners` \| `marketers` \| `ai` |
| topic | String(300) | |
| source_item_id | FK → source_items.id, nullable, unique when not null | enforces no reuse |
| source_url | String(1000), nullable | |
| input_text | Text, nullable | the idea or the original post being rewritten |
| versions | JSON | list of `{text, hook_type, angle, rating: "good"\|"bad"\|null, comment}` |
| chosen_version | Integer, nullable | index into `versions` |
| final_text | Text, nullable | |
| visual_idea | Text, nullable | |
| first_comment | Text, nullable | |
| lead_magnet | Text, nullable | what must be created |
| lead_magnet_done | Boolean, default false | |
| status | String(20), default `planned` | `planned` \| `draft` \| `approved` \| `posted` \| `skipped` |
| linkedin_url | String(1000), nullable | |
| reactions | Integer, nullable | |
| comments_count | Integer, nullable | |
| impressions | Integer, nullable | |
| created_at / updated_at | DateTime(tz) | |

Existing table change (added to the `ALTER TABLE` migration list in `backend/main.py`):

```sql
ALTER TABLE profile ADD COLUMN voice_profile TEXT
```

New tables are created by the existing `Base.metadata.create_all`. `ProfileIn`/`ProfileOut` in `backend/routes/style.py` gain `voice_profile`.

### 7.3 API — `backend/routes/posts.py`, prefix `/api/posts`

| Method & path | Purpose |
|---|---|
| `GET /api/posts` | List; filters `status`, `post_type`, `batch_id`, `date_from`, `date_to`; ordered by `planned_date`, `slot` |
| `GET /api/posts/batches` | List batches (for the filter) |
| `GET /api/posts/used-source-items` | IDs of articles already used |
| `GET /api/posts/feedback-summary?limit=30` | Compact learning data: type, reader, version ratings/comments, chosen version, whether final text was edited (and a short before/after), status, results |
| `GET /api/posts/{id}` | One post |
| `POST /api/posts/bulk` | Body `{batch?: {kind, label, start_date, end_date}, posts: [...]}`; creates the batch and posts in one transaction; adds tag `used` to each referenced source item; returns `409` listing already-used `source_item_id`s and creates nothing |
| `PUT /api/posts/{id}` | Partial update: `versions`, `chosen_version`, `final_text`, `status`, `planned_date`, `slot`, `visual_idea`, `first_comment`, `lead_magnet_done`, `linkedin_url`, `reactions`, `comments_count`, `impressions` |
| `DELETE /api/posts/{id}` | Deletes the post and removes the `used` tag from its source item |

The fixed paths (`/batches`, `/used-source-items`, `/feedback-summary`, `/bulk`) must be declared before `/{id}` so they are not captured as an ID. Router registered in `backend/main.py` with the other `include_router` calls.

### 7.4 Frontend

- `frontend/index.html`: new `nav-item` with `data-screen="posts"` after Write; new `<div class="screen" id="screen-posts">` with header, filter toolbar and list container; `<script src="/static/js/posts.js?v=20260913-1">`.
- `frontend/js/posts.js`: `Posts` object with `load()`, filter handling, list grouped by date, detail modal via `App.openModal` (versions side by side, rating/comment, choose version, edit final text, copy buttons, status buttons, lead-magnet checkbox, results fields).
- `frontend/js/app.js`: add `posts: () => Posts.load()` to the screen loaders.
- My Style → **My Profile** tab (`#tab-profile`, next to `#profile-bio`) gets a `voice_profile` textarea, loaded and saved through the existing `/api/style/profile` calls.

### 7.5 Error handling

| Situation | Behaviour |
|---|---|
| App not running | Skill stops and tells Shadi to start it (`.venv/bin/python -m backend.main` in `shadi-branding/`) |
| Article blocked or paywalled | Use stored title/summary; if too thin, say so and propose another article |
| Not enough fresh articles | Fill slots with idea-based posts, report how many, suggest fetching Sources |
| `409` on bulk create | Skill replaces the used articles and retries |
| Save fails for another reason | Posts stay in chat; skill retries once and reports the error |
| Empty voice profile | Run first-time voice setup before writing |

### 7.6 Testing

- **Backend:** add `pytest` to a new `requirements-dev.txt`; `tests/test_posts_api.py` with FastAPI `TestClient` and `app.dependency_overrides[get_db]` pointing to a temporary SQLite database (never `data/shadi.db`). Cases: bulk create with batch; list filters; partial update; `used` tag added on create and removed on delete; `409` on reused article with nothing created; feedback summary contents; profile `voice_profile` round-trip.
- **Skill (writing-skills TDD):** baseline run of each scenario without the skill, recording violations; then the same scenarios with the skill must pass the §4 quality gate:
  1. News article link → news post, link only in first comment
  2. Pasted Arabic post → English rewrite that is not a translation or copy
  3. `today` → 3 posts, 3 different types, 3 versions each, saved as drafts
  4. Saudi-focused article and a politics article → both rejected with a reason
  5. Draft containing "leverage" and a hashtag → caught and rewritten
- **Screen:** manual browser check with a real daily batch: filters, choose version, rate and comment, copy, status changes, results fields.

---

## 8. Out of scope

- Arabic output
- Hashtags
- Editing plans inside the app
- Auto-posting to LinkedIn or importing LinkedIn analytics
- Best-time-to-post recommendations
- Using the paid Claude API from the app for this feature
