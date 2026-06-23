import datetime, email.utils, re, sqlite3, hashlib, json, os, time

from config import DB_PATH

def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url_hash TEXT UNIQUE,
            source TEXT, title TEXT, url TEXT, published TEXT,
            raw_summary TEXT,
            status TEXT DEFAULT 'new',   -- new|rejected|pending|published|skipped|archived
            llm TEXT,                    -- JSON from filter
            created_at INTEGER
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS source_health (
            source TEXT PRIMARY KEY,
            url TEXT,
            ok INTEGER,
            entries INTEGER,
            new_items INTEGER,
            detail TEXT,
            checked_at INTEGER
        )""")


def requeue_failed() -> int:
    """Recover items rejected only because classification never completed."""
    with _conn() as c:
        cur = c.execute("""UPDATE items SET status='new'
            WHERE status='rejected' AND (llm IS NULL OR llm='')""")
        return cur.rowcount

def hash_url(url: str) -> str:
    return hashlib.sha256(url.strip().lower().encode()).hexdigest()[:24]

def seen(url: str) -> bool:
    with _conn() as c:
        return c.execute("SELECT 1 FROM items WHERE url_hash=?", (hash_url(url),)).fetchone() is not None

_STOPWORDS = {
    "a", "an", "and", "at", "for", "from", "in", "into", "its", "new", "of",
    "on", "the", "to", "under", "with", "by", "as", "is", "will", "opens",
    "open", "opening", "launch", "launches", "adds", "sets", "targets",
}

def _title_tokens(title: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (title or "").lower())
            if len(t) > 2 and t not in _STOPWORDS}

def _similarity(a: str, b: str) -> float:
    ta, tb = _title_tokens(a), _title_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, min(len(ta), len(tb)))

def seen_similar_title(title: str, max_age_days=45, threshold=0.40) -> bool:
    cutoff = int(time.time()) - int(max_age_days * 86400)
    with _conn() as c:
        rows = c.execute(
            "SELECT title FROM items WHERE created_at>=? ORDER BY id DESC LIMIT 500",
            (cutoff,)).fetchall()
    return any(_similarity(title, r["title"]) >= threshold for r in rows)

def add_item(source, title, url, published, raw_summary) -> int | None:
    try:
        with _conn() as c:
            cur = c.execute(
                "INSERT INTO items (url_hash, source, title, url, published, raw_summary, created_at) VALUES (?,?,?,?,?,?,?)",
                (hash_url(url), source, title, url, published, raw_summary, int(time.time())))
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None

def set_status(item_id, status):
    with _conn() as c:
        c.execute("UPDATE items SET status=? WHERE id=?", (status, item_id))

def set_llm(item_id, llm: dict, status):
    with _conn() as c:
        c.execute("UPDATE items SET llm=?, status=? WHERE id=?", (json.dumps(llm), status, item_id))

def get(item_id):
    with _conn() as c:
        r = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        return dict(r) if r else None

def by_status(status, limit=50):
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM items WHERE status=? ORDER BY id ASC LIMIT ?", (status, limit))]

def pending_fresh(limit=50, max_age_days=28):
    cutoff = int(time.time()) - int(max_age_days * 86400)
    with _conn() as c:
        return [dict(r) for r in c.execute(
            """SELECT * FROM items
               WHERE status='pending' AND created_at>=?
               ORDER BY id DESC LIMIT ?""", (cutoff, limit))]

def archive_old_pending(max_age_days=28) -> int:
    cutoff = int(time.time()) - int(max_age_days * 86400)
    with _conn() as c:
        cur = c.execute(
            "UPDATE items SET status='archived' WHERE status='pending' AND created_at<?",
            (cutoff,))
        return cur.rowcount

def archived_recent(limit=25, max_age_days=28):
    cutoff = int(time.time()) - int(max_age_days * 86400)
    with _conn() as c:
        return [dict(r) for r in c.execute(
            """SELECT * FROM items
               WHERE status='archived' AND created_at>=?
               ORDER BY created_at DESC, id DESC LIMIT ?""", (cutoff, limit))]

def archive_all_pending() -> int:
    with _conn() as c:
        cur = c.execute("UPDATE items SET status='archived' WHERE status='pending'")
        return cur.rowcount

def _published_text_ts(raw: str) -> int | None:
    raw = (raw or "").strip()
    if not raw or raw.lower() in {"unknown", "n/a", "none", "recent"}:
        return None
    try:
        return int(email.utils.parsedate_to_datetime(raw).timestamp())
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return int(datetime.datetime.strptime(raw, fmt).replace(tzinfo=datetime.timezone.utc).timestamp())
        except Exception:
            pass
    return None

_MONTH_RE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?\s+(\d{1,2},?\s+)?(20\d{2})\b",
    re.I,
)
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7,
    "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12,
    "december": 12,
}

def _text_date_ts(text: str) -> int | None:
    matches = list(_MONTH_RE.finditer(text or ""))
    if not matches:
        return None
    latest = None
    for m in matches:
        month = _MONTHS.get(m.group(1).lower().rstrip("."))
        day_text = (m.group(2) or "1").replace(",", "").strip()
        year = int(m.group(3))
        try:
            day = int(day_text) if day_text else 1
            ts = int(datetime.datetime(year, month, day, tzinfo=datetime.timezone.utc).timestamp())
            latest = max(latest or ts, ts)
        except Exception:
            continue
    return latest

def item_is_stale(item: dict, max_age_days=45, archive_unknown=False) -> bool:
    cutoff = int(time.time()) - int(max_age_days * 86400)
    published_ts = _published_text_ts(item.get("published") or "")
    text_ts = _text_date_ts(" ".join([
        item.get("title") or "",
        item.get("raw_summary") or "",
    ]))
    # If the story text itself says March/April/etc, trust that over a fresh
    # Google News RSS timestamp.
    evidence_ts = text_ts or published_ts
    if evidence_ts is None:
        return bool(archive_unknown)
    return evidence_ts < cutoff

def archive_stale_pending(max_age_days=45, archive_unknown=True) -> int:
    cutoff = int(time.time()) - int(max_age_days * 86400)
    with _conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT id, title, published, raw_summary FROM items WHERE status='pending'")]
        archive_ids = []
        for row in rows:
            if item_is_stale(row, max_age_days, archive_unknown):
                archive_ids.append(row["id"])
        if archive_ids:
            c.executemany("UPDATE items SET status='archived' WHERE id=?",
                          [(i,) for i in archive_ids])
        return len(archive_ids)

def reset_unpublished_items() -> int:
    """Clear scanner memory for testing while preserving published signals."""
    with _conn() as c:
        cur = c.execute("DELETE FROM items WHERE status!='published'")
        return cur.rowcount

def counts():
    with _conn() as c:
        return {r["status"]: r["n"] for r in c.execute(
            "SELECT status, COUNT(*) n FROM items GROUP BY status")}

def recent_by_status(status: str, limit=20, source_query: str = ""):
    with _conn() as c:
        if source_query:
            return [dict(r) for r in c.execute(
                """SELECT * FROM items
                   WHERE status=? AND lower(source) LIKE ?
                   ORDER BY created_at DESC, id DESC LIMIT ?""",
                (status, f"%{source_query.lower()}%", limit))]
        return [dict(r) for r in c.execute(
            """SELECT * FROM items
               WHERE status=?
               ORDER BY created_at DESC, id DESC LIMIT ?""", (status, limit))]

def recent_by_source(source_query: str, limit=20):
    with _conn() as c:
        return [dict(r) for r in c.execute(
            """SELECT * FROM items
               WHERE lower(source) LIKE ?
               ORDER BY created_at DESC, id DESC LIMIT ?""",
            (f"%{source_query.lower()}%", limit))]

def requeue_pending_source(source_query: str) -> int:
    with _conn() as c:
        cur = c.execute(
            """UPDATE items SET status='new'
               WHERE status='pending' AND lower(source) LIKE ?""",
            (f"%{source_query.lower()}%",))
        return cur.rowcount

def archive_pending_source(source_query: str) -> int:
    with _conn() as c:
        cur = c.execute(
            """UPDATE items SET status='archived'
               WHERE status='pending' AND lower(source) LIKE ?""",
            (f"%{source_query.lower()}%",))
        return cur.rowcount

def dedupe_pending(threshold=0.40) -> int:
    with _conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT id, title, llm FROM items WHERE status='pending' ORDER BY id DESC")]
        keep = []
        archive_ids = []
        for row in rows:
            try:
                llm = json.loads(row["llm"]) if row.get("llm") else {}
            except Exception:
                llm = {}
            title = llm.get("title") or row["title"]
            if any(_similarity(title, kept) >= threshold for kept in keep):
                archive_ids.append(row["id"])
            else:
                keep.append(title)
        if archive_ids:
            c.executemany("UPDATE items SET status='archived' WHERE id=?",
                          [(i,) for i in archive_ids])
        return len(archive_ids)


def record_source_health(source: str, url: str, ok: bool, entries: int,
                         new_items: int, detail: str = ""):
    with _conn() as c:
        c.execute("""INSERT INTO source_health
            (source, url, ok, entries, new_items, detail, checked_at)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(source) DO UPDATE SET
                url=excluded.url, ok=excluded.ok, entries=excluded.entries,
                new_items=excluded.new_items, detail=excluded.detail,
                checked_at=excluded.checked_at""",
            (source, url, int(ok), entries, new_items, detail[:300], int(time.time())))


def source_health() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM source_health ORDER BY ok ASC, source ASC")]

def rejected_recent(limit=15):
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM items WHERE status='rejected' ORDER BY id DESC LIMIT ?", (limit,))]

def init_insights():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS insights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, post TEXT, transcript TEXT,
            status TEXT DEFAULT 'draft',  -- draft|saved|used|discarded
            created_at INTEGER
        )""")

def add_insight(title, post, transcript) -> int:
    import time as _t
    with _conn() as c:
        cur = c.execute("INSERT INTO insights (title, post, transcript, created_at) VALUES (?,?,?,?)",
                        (title, post, transcript, int(_t.time())))
        return cur.lastrowid

def set_insight_status(iid, status):
    with _conn() as c:
        c.execute("UPDATE insights SET status=? WHERE id=?", (status, iid))

def get_insight(iid):
    with _conn() as c:
        r = c.execute("SELECT * FROM insights WHERE id=?", (iid,)).fetchone()
        return dict(r) if r else None

def saved_insights(limit=25):
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM insights WHERE status='saved' ORDER BY id DESC LIMIT ?", (limit,))]

def get_by_url(url: str):
    with _conn() as c:
        r = c.execute("SELECT * FROM items WHERE url_hash=?", (hash_url(url),)).fetchone()
        return dict(r) if r else None
