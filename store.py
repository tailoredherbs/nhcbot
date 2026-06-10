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
            status TEXT DEFAULT 'new',   -- new|rejected|pending|published|skipped
            llm TEXT,                    -- JSON from filter
            created_at INTEGER
        )""")

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

def counts():
    with _conn() as c:
        return {r["status"]: r["n"] for r in c.execute(
            "SELECT status, COUNT(*) n FROM items GROUP BY status")}

def rejected_recent(limit=15):
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM items WHERE status='rejected' ORDER BY id DESC LIMIT ?", (limit,))]
