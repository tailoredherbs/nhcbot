"""Private radar: longevity science, therapy evidence, and regulatory shifts.
Telegram-only — never published to the site."""
import logging, re, sqlite3, time
import feedparser, requests

from config import RADAR_FEEDS, RADAR_MAX_AGE_DAYS, DB_PATH
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
- RETREAT SAFETY (high priority): facilitator misconduct allegations, deaths or serious
  incidents at retreats, lawsuits against retreat operators, jurisdiction crackdowns
  or legalizations affecting retreat operations, adverse-effects research on intensive
  meditation or psychedelic programs
- Notable retreat-world moves: a major program/teacher launching a new format or
  location (Hoffman, Esalen, Modern Elder Academy, Buchinger Wilhelmi tier)

EXCLUDE: mouse/cell-only incremental studies, supplement marketing, lifestyle listicles,
routine biotech funding, opinion pieces without new facts.

For included items, write "detail": 1-2 sentences of CONCRETE SUBSTANCE pulled from the
item itself — the specific finding, numbers, names, location, ruling, or outcome. What
actually happened, with the facts that make it useful. NEVER write generic relevance
statements like "clients may ask about safety" — the reader already knows why it is
relevant; he needs the substance so he can speak about it without opening the link.

Bad:  "Clients may inquire about safety and legal risks of psychedelic retreats."
Good: "Peruvian facilitator charged with negligent homicide after a 34-year-old US
client died from combined kambo and ayahuasca at an Iquitos retreat; the venue had
no medical screening protocol."

Respond ONLY with JSON, no fences:
{"include": true/false, "headline": "plain restatement, max 14 words",
 "detail": "1-2 sentences of concrete substance"}"""


def init():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS radar_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url_hash TEXT UNIQUE, source TEXT, title TEXT, url TEXT,
            headline TEXT, why TEXT,
            status TEXT DEFAULT 'pending',  -- pending|sent|excluded
            created_at INTEGER)""")


def reset() -> int:
    """Wipe all radar items so the next scan re-fetches and re-filters everything."""
    with _conn() as c:
        n = c.execute("SELECT COUNT(*) FROM radar_items").fetchone()[0]
        c.execute("DELETE FROM radar_items")
    return n


def _clean(html, limit=900):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()[:limit]


def _entry_ts(e):
    """Best-effort published timestamp from a feed entry, else None."""
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(e, attr, None)
        if t:
            try:
                return int(time.mktime(t))
            except Exception:
                pass
    return None


def fetch_and_filter() -> dict:
    """Pull radar feeds, filter, store. Returns counts for diagnostics."""
    stats = {"scanned": 0, "kept": 0, "excluded": 0, "old": 0, "errors": 0, "feed_fail": 0}
    cutoff = int(time.time()) - RADAR_MAX_AGE_DAYS * 86400
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
                ts = _entry_ts(e)
                if ts and ts < cutoff:
                    # Too old: remember it (so it never re-scans) but skip the LLM entirely.
                    with _conn() as c:
                        c.execute("""INSERT INTO radar_items
                            (url_hash, source, title, url, headline, why, status, created_at)
                            VALUES (?,?,?,?,?,?,?,?)""",
                            (h, source, title, link, title, "skipped: older than cutoff",
                             "old", int(time.time())))
                    stats["old"] += 1
                    continue
                stats["scanned"] += 1
                summary = _clean(getattr(e, "summary", "") or getattr(e, "description", ""))
                try:
                    verdict = _parse(_call_llm(RADAR_BRIEF,
                        f"Source: {source}\nTitle: {title}\nSummary: {summary}",
                        max_tokens=400, temperature=0.2))
                except Exception as ex:
                    log.error("Radar filter failed (will retry next run): %s", ex)
                    stats["errors"] += 1
                    continue  # do NOT store — item stays unseen and retries next scan
                if verdict is None:
                    log.warning("Radar verdict unparseable for: %s", title[:60])
                    stats["errors"] += 1
                    continue
                import time as _t; _t.sleep(0.6)  # be gentle with API rate limits
                status = "pending" if verdict.get("include") else "excluded"
                with _conn() as c:
                    c.execute("""INSERT INTO radar_items
                        (url_hash, source, title, url, headline, why, status, created_at)
                        VALUES (?,?,?,?,?,?,?,?)""",
                        (h, source, title, link,
                         (verdict or {}).get("headline", title),
                         (verdict or {}).get("detail") or (verdict or {}).get("why_it_matters", ""),
                         status, int(time.time())))
                stats["kept" if status == "pending" else "excluded"] += 1
            log.info("Radar %s: ok", source)
        except Exception as ex:
            log.error("Radar feed failed %s: %s", source, ex)
            stats["feed_fail"] += 1
    log.info("Radar scan done: %s", stats)
    return stats


def pending(limit=20):
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM radar_items WHERE status='pending' ORDER BY id ASC LIMIT ?", (limit,))]


def mark_sent(ids):
    with _conn() as c:
        c.executemany("UPDATE radar_items SET status='sent' WHERE id=?", [(i,) for i in ids])


def get(rid: int):
    with _conn() as c:
        r = c.execute("SELECT * FROM radar_items WHERE id=?", (rid,)).fetchone()
        return dict(r) if r else None
