"""Fetch publication feeds and news mentions for venues on the live index."""
import logging, re
from urllib.parse import quote_plus
import feedparser
import requests

from config import FEEDS, SITE_URL
import store

log = logging.getLogger("sources")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

def _clean(html: str, limit=1200) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _fetch_one(source: str, url: str, limit: int = 30,
               allow_empty: bool = False) -> tuple[list[int], int]:
    """Fetch one RSS/Atom URL, insert unseen entries, and return ids + feed size."""
    resp = requests.get(url, headers=UA, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    if not feed.entries and not allow_empty:
        raise RuntimeError("response contained no RSS/Atom entries")
    new_ids = []
    for e in feed.entries[:limit]:
        link = getattr(e, "link", "") or ""
        title = _clean(getattr(e, "title", ""), 300)
        if not link or not title or store.seen(link):
            continue
        published = getattr(e, "published", "") or getattr(e, "updated", "")
        summary = _clean(getattr(e, "summary", "") or getattr(e, "description", ""))
        item_id = store.add_item(source, title, link, published, summary)
        if item_id:
            new_ids.append(item_id)
    return new_ids, len(feed.entries)


def _fetch_publications() -> list[int]:
    new_ids = []
    for source, url in FEEDS.items():
        try:
            is_news_search = "news.google.com/rss/search" in url
            ids, entries = _fetch_one(source, url, limit=15 if is_news_search else 30,
                                      allow_empty=is_news_search)
            new_ids.extend(ids)
            store.record_source_health(source, url, True, entries, len(ids), "ok")
            log.info("%s: ok (%d entries, %d new)", source, entries, len(ids))
        except Exception as ex:
            store.record_source_health(source, url, False, 0, 0, str(ex))
            log.error("Feed failed %s: %s", source, ex)
    return new_ids


def load_index_spaces() -> list[dict]:
    """Full venue records from the live map export."""
    resp = requests.get(f"{SITE_URL}/spaces-data.json", headers=UA, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _fetch_index_news(batch_size: int = 8) -> list[int]:
    """Search recent news for every venue on the live index in small batches."""
    try:
        names = [s.get("name", "").strip() for s in load_index_spaces() if s.get("name")]
    except Exception as ex:
        store.record_source_health("Index venue news", SITE_URL, False, 0, 0, str(ex))
        log.error("Could not load index venues for news watch: %s", ex)
        return []

    new_ids, total_entries, failures = [], 0, []
    change_terms = '(opening OR opens OR launch OR expansion OR partnership OR membership OR program OR retreat OR acquisition)'
    for start in range(0, len(names), batch_size):
        batch = names[start:start + batch_size]
        venue_terms = " OR ".join(f'"{name}"' for name in batch)
        query = f"({venue_terms}) {change_terms}"
        url = ("https://news.google.com/rss/search?q=" + quote_plus(query)
               + "&hl=en-US&gl=US&ceid=US:en")
        try:
            ids, entries = _fetch_one("Index venue news", url, limit=8, allow_empty=True)
            new_ids.extend(ids)
            total_entries += entries
        except Exception as ex:
            failures.append(str(ex))
    ok = not failures
    detail = "ok" if ok else f"{len(failures)} batch(es) failed: {failures[0]}"
    store.record_source_health("Index venue news", f"{SITE_URL}/spaces-data.json",
                               ok, total_entries, len(new_ids), detail)
    log.info("Index venue news: %d venues, %d results, %d new, %d failed batches",
             len(names), total_entries, len(new_ids), len(failures))
    return new_ids


def fetch_feeds() -> list[int]:
    """Pull publication feeds and all-index venue news; return newly inserted ids."""
    return _fetch_publications() + _fetch_index_news()

def load_index_venues() -> list[str]:
    """Venue names from the live site, used for on-index tagging in the LLM filter."""
    try:
        return [s["name"] for s in load_index_spaces()]
    except Exception as ex:
        log.warning("Could not load spaces-data.json: %s", ex)
        return []

def fetch_page_text(url: str, limit=1800) -> str:
    """Fetch a page and return readable text — used for manual /signal suggestions."""
    try:
        resp = requests.get(url, headers=UA, timeout=20)
        text = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", resp.text)
        return _clean(text, limit)
    except Exception as ex:
        log.warning("Page fetch failed %s: %s", url, ex)
        return ""
