"""Private radar: longevity science, therapy evidence, and regulatory shifts.
Telegram-only — never published to the site."""
import logging, re, sqlite3, time
import feedparser, requests

from config import RADAR_FEEDS, DB_PATH
from filter_llm import _call_llm, _parse
from store import _conn, hash_url

log = logging.getLogger("radar")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

RADAR_BRIEF = """You filter science and policy news for the founder of a private wellness
placement desk (premium clients -> longevity clinics, retreats, practitioners). He needs
to stay conversant — the feed is private awareness, not publishing.

INCLUDE only items a high-end wellness concierge should know about:
- Human trial results for major interventions (GLP-1s beyond weight, rapamycin,
  senolytics, reprogramming, hormone therapies, notable peptides)
- Regulatory shifts: approvals, bans, psychedelic medicine access (FDA, state programs,
  international), rules touching clinic offerings (stem cells, plasmapheresis, IV)
- Diagnostics entering clinical practice: biological-age clocks, multi-omics,
  imaging-based screening
- Meaningful evidence shifts on venue-relevant modalities: sauna, cold exposure, HBOT,
  red light, cryotherapy
- Major credibility events: retractions, fraud, safety signals around prominent
  therapies or figures

EXCLUDE: mouse/cell-only incremental studies, supplement marketing, lifestyle listicles,
routine biotech funding, opinion pieces without new facts.

For included items, write why_it_matters in ONE sentence aimed at the desk: what a
client might ask about, or what changes for venues.

Respond ONLY with JSON, no fences:
{"include": true/false, "headline": "plain restatement, max 14 words",
 "why_it_matters": "one sentence"}"""


def init():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS radar_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url_hash TEXT UNIQUE, source TEXT, title TEXT, url TEXT,
            headline TEXT, why TEXT,
            status TEXT DEFAULT 'pending',  -- pending|sent|excluded
            created_at INTEGER)""")


def _clean(html, limit=900):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()[:limit]


def fetch_and_filter() -> int:
    """Pull radar feeds, filter, store. Returns number of new pending items."""
    kept = 0
    for source, url in RADAR_FEEDS.items():
        try:
            feed = feedparser.parse(requests.get(url, headers=UA, timeout=30).content)
            for e in feed.entries[:20]:
                link = getattr(e, "link", "")
                title = _clean(getattr(e, "title", ""), 300)
                if not link or not title:
                    continue
                h = hash_url("radar:" + link)
                with _conn() as c:
                    if c.execute("SELECT 1 FROM radar_items WHERE url_hash=?", (h,)).fetchone():
                        continue
                summary = _clean(getattr(e, "summary", "") or getattr(e, "description", ""))
                verdict = None
                try:
                    verdict = _parse(_call_llm(RADAR_BRIEF,
                        f"Source: {source}\nTitle: {title}\nSummary: {summary}",
                        max_tokens=400, temperature=0.2))
                except Exception as ex:
                    log.error("Radar filter failed: %s", ex)
                status = "pending" if (verdict and verdict.get("include")) else "excluded"
                with _conn() as c:
                    c.execute("""INSERT INTO radar_items
                        (url_hash, source, title, url, headline, why, status, created_at)
                        VALUES (?,?,?,?,?,?,?,?)""",
                        (h, source, title, link,
                         (verdict or {}).get("headline", title),
                         (verdict or {}).get("why_it_matters", ""),
                         status, int(time.time())))
                if status == "pending":
                    kept += 1
            log.info("Radar %s: ok", source)
        except Exception as ex:
            log.error("Radar feed failed %s: %s", source, ex)
    return kept


def pending(limit=20):
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM radar_items WHERE status='pending' ORDER BY id ASC LIMIT ?", (limit,))]


def mark_sent(ids):
    with _conn() as c:
        c.executemany("UPDATE radar_items SET status='sent' WHERE id=?", [(i,) for i in ids])
