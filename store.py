import sqlite3, hashlib, json, os, time

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

def reset_unpublished_items() -> int:
    """Clear scanner memory for testing while preserving published signals."""
    with _conn() as c:
        cur = c.execute("DELETE FROM items WHERE status!='published'")
        return cur.rowcount

def counts():
    with _conn() as c:
        return {r["status"]: r["n"] for r in c.execute(
            "SELECT status, COUNT(*) n FROM items GROUP BY status")}


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
