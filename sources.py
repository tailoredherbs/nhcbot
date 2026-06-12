"""Fetch new items from RSS feeds. Normalised item = (source, title, url, published, summary)."""
import logging, re
import feedparser
import requests

from config import FEEDS, SITE_URL
import store

log = logging.getLogger("sources")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

def _clean(html: str, limit=1200) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()[:limit]

def fetch_feeds() -> list[int]:
    """Pull all feeds, insert unseen items, return new item ids."""
    new_ids = []
    for source, url in FEEDS.items():
        try:
            resp = requests.get(url, headers=UA, timeout=30)
            feed = feedparser.parse(resp.content)
            if not feed.entries:
                log.warning("No entries from %s (%s)", source, url)
                continue
            for e in feed.entries[:30]:
                link = getattr(e, "link", "") or ""
                title = _clean(getattr(e, "title", ""), 300)
                if not link or not title or store.seen(link):
                    continue
                published = getattr(e, "published", "") or getattr(e, "updated", "")
                summary = _clean(getattr(e, "summary", "") or getattr(e, "description", ""))
                item_id = store.add_item(source, title, link, published, summary)
                if item_id:
                    new_ids.append(item_id)
            log.info("%s: ok", source)
        except Exception as ex:
            log.error("Feed failed %s: %s", source, ex)
    return new_ids

def load_index_venues() -> list[str]:
    """Venue names from the live site, used for on-index tagging in the LLM filter."""
    try:
        data = requests.get(f"{SITE_URL}/spaces-data.json", headers=UA, timeout=20).json()
        return [s["name"] for s in data]
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
