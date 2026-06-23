"""Fetch publication feeds, news mentions, and venue-owned channel updates."""
import calendar, email.utils, json, logging, re, time
from urllib.parse import quote_plus
import feedparser
import requests

from config import (ENABLE_GROK_CHANNEL_SCAN, FEEDS, GROK_CHANNEL_BATCH_SIZE,
                    GROK_MODEL, SIGNAL_MAX_AGE_DAYS, SITE_URL, XAI_API_KEY)
import store

log = logging.getLogger("sources")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

def _clean(html: str, limit=1200) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _plain(value) -> str:
    return str(value or "").strip()


def _space_link(space: dict, key: str) -> str:
    """Read links from both legacy top-level fields and newer links.* fields."""
    links = space.get("links") or {}
    return _plain(space.get(key) or links.get(key))


def _instagram_url(handle: str) -> str:
    handle = _plain(handle)
    if not handle:
        return ""
    if handle.startswith("http://") or handle.startswith("https://"):
        return handle
    return "https://www.instagram.com/" + handle.lstrip("@").strip("/")


def _json_from_text(text: str):
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(text)
    except Exception:
        start, end = text.find("["), text.rfind("]")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def _published_ts(entry) -> int | None:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if parsed:
        return calendar.timegm(parsed)
    raw = getattr(entry, "published", "") or getattr(entry, "updated", "")
    if raw:
        try:
            return int(email.utils.parsedate_to_datetime(raw).timestamp())
        except Exception:
            return None
    return None


def _is_recent(entry, max_age_days: int = SIGNAL_MAX_AGE_DAYS) -> bool:
    ts = _published_ts(entry)
    if not ts:
        # If a feed gives no date, keep it; the LLM/editor can still judge it.
        return True
    return ts >= int(time.time()) - int(max_age_days * 86400)


def _is_obvious_nonvenue_noise(title: str, summary: str = "") -> bool:
    text = f"{title} {summary}".lower()
    noisy_phrases = (
        "job vacancy",
        "apprentice",
        "press release",
        "how to specify",
        "lighting design",
        "introduces",
        "equipment supplier",
        "fitness equipment",
        "spa equipment",
        "dry flotation bed",
        "trade show",
        "elevate 2026 partnership",
    )
    if any(p in text for p in noisy_phrases):
        positive = (
            "opens", "opening", "launches", "expands", "acquires", "resort",
            "retreat", "club", "clinic", "destination", "reservations",
        )
        return not any(p in text for p in positive)
    return False


def _fetch_one(source: str, url: str, limit: int = 30,
               allow_empty: bool = False) -> tuple[list[int], int, int, int]:
    """Fetch one RSS/Atom URL, insert unseen recent entries, and return ids + counts."""
    resp = requests.get(url, headers=UA, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    if not feed.entries and not allow_empty:
        raise RuntimeError("response contained no RSS/Atom entries")
    new_ids = []
    old = 0
    noise = 0
    for e in feed.entries[:limit]:
        if not _is_recent(e):
            old += 1
            continue
        link = getattr(e, "link", "") or ""
        title = _clean(getattr(e, "title", ""), 300)
        if not link or not title or store.seen(link) or store.seen_similar_title(title):
            continue
        published = getattr(e, "published", "") or getattr(e, "updated", "")
        summary = _clean(getattr(e, "summary", "") or getattr(e, "description", ""))
        if _is_obvious_nonvenue_noise(title, summary):
            noise += 1
            continue
        item_id = store.add_item(source, title, link, published, summary)
        if item_id:
            new_ids.append(item_id)
    return new_ids, len(feed.entries), old, noise


def _fetch_publications() -> list[int]:
    new_ids = []
    for source, url in FEEDS.items():
        try:
            is_news_search = "news.google.com/rss/search" in url
            ids, entries, old, noise = _fetch_one(source, url, limit=15 if is_news_search else 30,
                                                  allow_empty=is_news_search)
            new_ids.extend(ids)
            detail = f"ok; skipped {old} older than {SIGNAL_MAX_AGE_DAYS}d; {noise} obvious noise"
            store.record_source_health(source, url, True, entries, len(ids), detail)
            log.info("%s: ok (%d entries, %d new, %d old, %d noise)",
                     source, entries, len(ids), old, noise)
        except Exception as ex:
            store.record_source_health(source, url, False, 0, 0, str(ex))
            log.error("Feed failed %s: %s", source, ex)
    return new_ids


def load_index_spaces() -> list[dict]:
    """Full venue records from the live map export."""
    resp = requests.get(f"{SITE_URL}/spaces-data.json", headers=UA, timeout=20)
    resp.raise_for_status()
    return resp.json()


def load_index_channels() -> list[dict]:
    """Venue names plus owned web/social channels from the live map export."""
    channels = []
    for s in load_index_spaces():
        name = _plain(s.get("name") or s.get("title"))
        website = _space_link(s, "website")
        instagram = _space_link(s, "instagram")
        if name and (website or instagram):
            channels.append({
                "name": name,
                "area": _plain(s.get("area")),
                "region": _plain(s.get("region")),
                "category": _plain(s.get("category")),
                "website": website,
                "instagram": instagram,
                "instagram_url": _instagram_url(instagram),
            })
    return channels


def _fetch_index_news(batch_size: int = 8) -> list[int]:
    """Search recent news for every venue on the live index in small batches."""
    try:
        names = [s.get("name", "").strip() for s in load_index_spaces() if s.get("name")]
    except Exception as ex:
        store.record_source_health("Index venue news", SITE_URL, False, 0, 0, str(ex))
        log.error("Could not load index venues for news watch: %s", ex)
        return []

    new_ids, total_entries, old_entries, noise_entries, failures = [], 0, 0, 0, []
    change_terms = '(opening OR opens OR launch OR expansion OR partnership OR membership OR program OR retreat OR acquisition)'
    for start in range(0, len(names), batch_size):
        batch = names[start:start + batch_size]
        venue_terms = " OR ".join(f'"{name}"' for name in batch)
        query = f"({venue_terms}) {change_terms}"
        url = ("https://news.google.com/rss/search?q=" + quote_plus(query)
               + "&hl=en-US&gl=US&ceid=US:en")
        try:
            ids, entries, old, noise = _fetch_one("Index venue news", url, limit=8, allow_empty=True)
            new_ids.extend(ids)
            total_entries += entries
            old_entries += old
            noise_entries += noise
        except Exception as ex:
            failures.append(str(ex))
    ok = not failures
    detail = f"skipped {old_entries} older than {SIGNAL_MAX_AGE_DAYS}d; {noise_entries} obvious noise"
    if failures:
        detail += f"; {len(failures)} batch(es) failed: {failures[0]}"
    store.record_source_health("Index venue news", f"{SITE_URL}/spaces-data.json",
                               ok, total_entries, len(new_ids), detail)
    log.info("Index venue news: %d venues, %d results, %d new, %d old, %d noise, %d failed batches",
             len(names), total_entries, len(new_ids), old_entries, noise_entries, len(failures))
    return new_ids


def _fetch_grok_channel_scan(batch_size: int = GROK_CHANNEL_BATCH_SIZE) -> list[int]:
    """Ask Grok to search public venue-owned channels for recent signal-worthy updates.

    This is intentionally optional. Grok can browse/search public web pages, but it is
    not a guaranteed Instagram data pipe; private/blocked Instagram content may not be
    reachable. Returned candidates still go through the normal editorial LLM filter.
    """
    source = "Grok venue channel scan"
    if not ENABLE_GROK_CHANNEL_SCAN:
        store.record_source_health(source, "xAI disabled", True, 0, 0, "disabled")
        return []
    if not XAI_API_KEY:
        store.record_source_health(source, "xAI", False, 0, 0, "missing XAI_API_KEY")
        return []

    try:
        channels = load_index_channels()
    except Exception as ex:
        store.record_source_health(source, SITE_URL, False, 0, 0, str(ex))
        log.error("Could not load index channels for Grok scan: %s", ex)
        return []

    if not channels:
        store.record_source_health(source, f"{SITE_URL}/spaces-data.json", True, 0, 0,
                                   "no website/instagram links exposed")
        return []

    new_ids, found, duplicates, parse_empty, failures = [], 0, 0, 0, []
    for start in range(0, len(channels), batch_size):
        batch = channels[start:start + batch_size]
        prompt = (
            "You are a discovery scout for The New Health Club Signals feed.\n"
            "Use web search for this batch. Search the venue names, websites, and "
            "Instagram handles below for recent or newly surfaced updates. Prioritize "
            "official venue websites and Instagram pages, but credible public sources "
            "are acceptable when official pages are blocked or undated.\n\n"
            "Return candidate leads that might change the map: openings, reservations "
            "opening, expansions, new locations, new retreats/programs, memberships, "
            "partnerships, closures, leadership/medical-director moves, acquisitions, "
            "or pricing/model changes. Avoid generic evergreen service pages, product "
            "supplier news, job posts, and trend articles.\n\n"
            f"Prefer evidence from the last {SIGNAL_MAX_AGE_DAYS} days, but include a "
            "lead with published='unknown' if the source is an official announcement, "
            "booking page, Instagram post, or credible article that looks current. "
            "Do not invent dates. Return only a JSON array. Each item must have: "
            "title, url, published, summary, venue, confidence. confidence is high, "
            "medium, or low. If nothing at all is found after searching, return [].\n\n"
            "VENUES:\n"
            + json.dumps(batch, ensure_ascii=False)
        )
        try:
            r = requests.post(
                "https://api.x.ai/v1/responses",
                headers={"Authorization": f"Bearer {XAI_API_KEY}",
                         "Content-Type": "application/json"},
                json={
                    "model": GROK_MODEL,
                    "input": [{"role": "user", "content": prompt}],
                    "tools": [{"type": "web_search", "enable_image_understanding": True}],
                    "tool_choice": "required",
                    "max_tool_calls": 8,
                },
                timeout=120,
            )
            if r.status_code >= 400:
                raise RuntimeError(f"xAI API {r.status_code}: {r.text[:300]}")
            data = r.json()
            text = data.get("output_text") or ""
            if not text:
                parts = []
                for out in data.get("output", []):
                    for content in out.get("content", []):
                        if content.get("type") in ("output_text", "text"):
                            parts.append(content.get("text", ""))
                text = "\n".join(parts)
            if not text.strip():
                parse_empty += 1
                continue
            candidates = _json_from_text(text)
            if isinstance(candidates, dict):
                candidates = candidates.get("items", [])
            for cand in candidates or []:
                title = _clean(cand.get("title"), 300)
                url = _plain(cand.get("url"))
                if not title or not url:
                    continue
                if store.seen(url) or store.seen_similar_title(title):
                    duplicates += 1
                    continue
                venue = _plain(cand.get("venue"))
                confidence = _plain(cand.get("confidence"))
                summary = _clean(
                    "Venue: %s. Confidence: %s. %s" % (
                        venue, confidence or "unknown", cand.get("summary") or ""),
                    1600,
                )
                item_id = store.add_item(source, title, url, _plain(cand.get("published")), summary)
                if item_id:
                    new_ids.append(item_id)
            found += len(candidates or [])
        except Exception as ex:
            failures.append(str(ex))

    ok = not failures
    detail = (f"scanned {len(channels)} venues; candidates {found}; "
              f"duplicates {duplicates}; empty {parse_empty}")
    if failures:
        detail += f"; {len(failures)} failed: {failures[0]}"
    store.record_source_health(source, "xAI web_search over venue websites/Instagram",
                               ok, found, len(new_ids), detail)
    log.info("Grok venue channel scan: %d venues, %d candidates, %d new, %d failed batches",
             len(channels), found, len(new_ids), len(failures))
    return new_ids


def fetch_feeds() -> list[int]:
    """Pull publication feeds and all-index venue news; return newly inserted ids."""
    return _fetch_publications() + _fetch_index_news()


def fetch_grok_channels() -> list[int]:
    """Run the slower optional Grok scan over venue websites/social channels."""
    return _fetch_grok_channel_scan()

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
