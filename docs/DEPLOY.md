# Deploying the Social Media Scrapper

This app runs as a single FastAPI process that also serves the vanilla-JS
frontend. Below are the realistic deployment scenarios and concrete steps for
each.

The fastest path to a live server is **Scenario A + Docker** (≈ 10 min on any
Linux VPS).

---

## TL;DR — which scenario fits me?

| You have… | Use scenario |
|---|---|
| An Anthropic API key, want everything to work | **A** |
| No Anthropic key, OK paying nothing for AI | **B** (free providers) |
| A Claude subscription you want to reuse on the server | **D** (CLI + OAuth copy) — fragile |
| A mix: Anthropic for Writing, free for everything else | **E** |
| Want the `claude` CLI on the server using an API key | **C** |

All scenarios run inside the same Docker image — only environment vars and
the in-app Settings page change.

---

## Prerequisites

- A Linux VPS with **≥ 2 GB RAM** (Playwright Chromium is hungry).
- Docker + Docker Compose installed.
- A domain or just the public IP (for HTTPS, put Caddy/Nginx in front).
- For scraping: a logged-in `storage_state.json` (see "Scraping on a server" below).

---

## One-time setup (all scenarios)

```bash
git clone <this-repo>
cd "Social Media Scrapper"
cp .env.example .env
# (edit .env if needed)

docker compose build
docker compose up -d
```

Open `http://<server-ip>:8000`. The app comes up empty; configure AI in
**Settings → AI Providers**.

To update later: `git pull && docker compose build && docker compose up -d`.

---

## Scenario A — Anthropic API key (everything works)

1. In the running app, open **Settings**.
2. Paste your Anthropic API key into the **Claude API Key** field. Save.
3. Under **AI Providers**, leave **Default provider = Anthropic**. No
   per-feature overrides needed.
4. Done. Writing uses the agentic tool-use loop; every other feature uses the
   same key.

**Cost:** pay-as-you-go to Anthropic.

---

## Scenario B — Free providers only (no Anthropic bill)

For users running on a tight budget or where Anthropic isn't available.

1. Get a free API key from one of:
   - **Groq** — <https://console.groq.com> (fast, good quality)
   - **OpenRouter** — <https://openrouter.ai> (many free models)
   - **Google Gemini** — <https://aistudio.google.com>
2. In **Settings → AI Providers**, paste the key into the matching card and hit **Save**, then **Test**.
3. Set **Default provider** to the one you picked.
4. The yellow banner under "Writing" appears — that's expected. Drafts still
   work via the single-shot inline path; only the agentic tool-use loop is
   skipped (it's Anthropic-only).

**Cost:** $0 within free tier limits.

---

## Scenario C — Claude CLI inside the container, using an API key

Useful if a future feature relies on CLI-only flags.

1. Add to `.env`: `ANTHROPIC_API_KEY=sk-ant-...`
2. Uncomment the `ANTHROPIC_API_KEY` line in `docker-compose.yml`.
3. Rebuild the container with the CLI installed — add this line to
   `Dockerfile` before `COPY . .`:
   ```dockerfile
   RUN curl -fsSL https://claude.ai/install.sh | bash
   ```
   (or whatever the current CLI install command is — see <https://claude.ai/code>)
4. `docker compose up -d --build`
5. In Settings, set **Default provider** = **Claude CLI**.

Functionally equivalent to Scenario A — same Anthropic billing.

---

## Scenario D — Claude CLI with subscription OAuth (fragile)

Only use this if you already pay for a Claude subscription and refuse to use
the API.

1. On your local machine, log into the CLI: `claude login`.
2. Tar your credentials: `tar czf claude-auth.tgz ~/.claude/`
3. Scp to the server: `scp claude-auth.tgz user@server:~/`
4. On the server: extract into the container's home dir. Easiest way is a
   bind mount in `docker-compose.yml`:
   ```yaml
   volumes:
     - ./data:/app/data
     - ~/.claude:/root/.claude
   ```
5. Restart: `docker compose up -d`

**Caveat:** OAuth refresh tokens expire (usually weeks). When the CLI starts
failing, re-do steps 1–3.

---

## Scenario E — Hybrid (Anthropic Writing + free for the rest)

The cheapest "everything works" option.

1. Paste both your Anthropic key and a Groq/Gemini key in Settings.
2. **Default provider** → Groq (or Gemini).
3. **Writing override** → Anthropic.
4. Leave Analysis / Intelligence on "Use global default".

Result: Writing keeps the agentic loop on Anthropic (the expensive feature
you actually want quality on), everything else costs $0.

---

## Scraping on a server (Playwright + LinkedIn / Instagram / X)

The Chromium browser runs headless on the server, but the social platforms
require an **authenticated session**. You can't log in interactively from a
headless box, so:

### Option 1: Bake a session locally, upload it (simplest)

1. On your local laptop:
   ```bash
   python open_login_browser.py
   ```
   This opens Chromium. Log into LinkedIn (and any other platforms).
2. Close the browser. A `storage_state.json` is written under `data/`.
3. Upload to the server: `scp data/storage_state.json user@server:/path/to/app/data/`
4. The container picks it up automatically via the bind-mounted `./data`.

Sessions expire (LinkedIn ≈ 1–4 weeks). When scraping stops working, repeat.

### Option 2: Paste the `li_at` cookie

For LinkedIn specifically, the settings table already supports `linkedin_li_at`.
1. In your browser DevTools, copy the `li_at` cookie from linkedin.com.
2. Paste it into **Settings → LinkedIn auth token**.

### Option 3: Headed via Xvfb (most complex)

Run a virtual display on the server so `open_login_browser.py` can pop a real
window over VNC. Doable but adds moving parts — only worth it if you refresh
sessions frequently.

---

## Putting HTTPS in front

The container listens on port 8000 over plain HTTP. For a public deploy add
a reverse proxy:

### Caddy (easiest — auto-HTTPS)

```caddy
your-domain.com {
  reverse_proxy localhost:8000
}
```

### Nginx + certbot

Standard reverse_proxy block to `127.0.0.1:8000` + `certbot --nginx`.

---

## Backups

Everything mutable is under `./data/`:
- `shadi.db` — SQLite (creators, posts, settings, API keys)
- `scraper_chrome_profile/` — Playwright profile
- `scraper_tokens/` — third-party scraper tokens

Daily tarball:
```bash
tar czf "backup-$(date +%F).tgz" data/
```

Restore: stop the container, replace `data/`, start again.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Writing fails with "Anthropic API key required" | Default provider is Anthropic but no key saved | Add the key, or change the Writing provider in Settings |
| AI calls fail with "provider has no API key configured" | You set a default provider but forgot to save its key | Save the key in the matching card under AI Providers |
| Scrapers return empty / "login required" | `storage_state.json` expired | Re-bake locally and re-upload |
| Chromium fails to launch in container | Missing system libs | Rebuild — the Dockerfile runs `playwright install --with-deps` |
| Port 8000 already in use | Another service is bound | Change the `ports:` mapping in `docker-compose.yml` |
| `docker compose build` very slow first time | Playwright + Chromium download (~200 MB) | Normal; subsequent builds are cached |
