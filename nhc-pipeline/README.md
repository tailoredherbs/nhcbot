# NHC Signals Pipeline

Automated news pipeline for thenewhealthclubs.com:
RSS feeds → LLM filter (EDITORIAL criteria) → daily Telegram review digest
→ one-tap publish → GitHub commit to _signals/ → Netlify deploy.

## Setup (Railway, ~15 min)

1. **Telegram bot**: message @BotFather → /newbot → copy the token.
   Message your new bot once, then open
   https://api.telegram.org/bot<TOKEN>/getUpdates and copy your chat `id`.

2. **GitHub token**: github.com → Settings → Developer settings →
   Personal access tokens (classic) → generate with `repo` scope.

3. **Railway**: New Project → Deploy from GitHub repo (push this folder to a
   new private repo first) or `railway up` from this folder.
   - Attach a **Volume** mounted at `/data` (keeps the SQLite DB across deploys).
   - Set environment variables:
     - TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
     - GITHUB_TOKEN  (GITHUB_REPO defaults to tailoredherbs/new-health-club)
     - OPENAI_API_KEY  *or*  ANTHROPIC_API_KEY
     - optional: DIGEST_HOUR (default 8), FETCH_EVERY_HOURS (default 6), TZ (default Asia/Makassar)

4. **Verify the feed URLs** (one-time): in Railway's shell or locally run
   `python discover_feeds.py` — it probes each publication for a working RSS URL.
   Update `FEEDS` in config.py with any corrections and redeploy.
   If a site reports NOT FOUND, tell Claude — it gets an HTML-scraper fetcher instead.

## Daily use
- Digest arrives at 08:00 Bali time with candidate cards: ✅ Publish / ✏️ Edit / ❌ Skip.
- ✅ commits the formatted markdown to _signals/ on main; Netlify deploys automatically.
- ✏️ then reply with an instruction ("shorten, lead with the funding number") for an
  AI revision, or reply `TEXT: <your text>` to replace the body verbatim.
- Commands: /fetch (pull feeds now), /digest (resend pending), /stats.

## Notes
- Dedupe is by URL hash in SQLite — items never resurface once seen.
- ⭐ ON INDEX marks news about venues already on the map (pulled live from spaces-data.json).
- Venue Instagram/website monitoring is the planned phase 2; the venue list with
  handles already lives in the site repo's _spaces collection.
