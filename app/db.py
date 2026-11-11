"""Base SQLite : les contenus (items) et le fil d'échanges de chacun (messages)."""
import json
import sqlite3
import threading
import time
import uuid

from . import config

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    author TEXT NOT NULL,
    source_url TEXT,
    source_text TEXT,
    instructions TEXT,
    target_format TEXT DEFAULT 'auto',
    title TEXT,
    platform TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    progress TEXT,
    error TEXT,
    source_json TEXT,
    analysis TEXT,
    output_format TEXT,
    archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    author TEXT NOT NULL,
    role TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'done',
    meta_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_item ON messages(item_id, created_at);
CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    author TEXT,
    url TEXT,
    text TEXT,
    files_json TEXT
);
"""


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(config.DATA_DIR / "studio.db", check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA)
    return _conn


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _row(r):
    return dict(r) if r else None


def execute(sql: str, params=()):
    with _lock:
        c = conn()
        c.execute(sql, params)
        c.commit()


def query(sql: str, params=()) -> list[dict]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, params).fetchall()]


# --- items ---

def create_item(author, url, text, instructions, target_format) -> str:
    iid = new_id()
    now = time.time()
    execute(
        "INSERT INTO items (id, created_at, updated_at, author, source_url, source_text, instructions, target_format, status, progress)"
        " VALUES (?,?,?,?,?,?,?,?, 'queued', 'En attente…')",
        (iid, now, now, author, url, text, instructions, target_format or "auto"),
    )
    return iid


def get_item(iid: str) -> dict | None:
    rows = query("SELECT * FROM items WHERE id=?", (iid,))
    return rows[0] if rows else None


def update_item(iid: str, **fields):
    if not fields:
        return
    fields["updated_at"] = time.time()
    for k, v in list(fields.items()):
        if isinstance(v, (dict, list)):
            fields[k] = json.dumps(v, ensure_ascii=False)
    cols = ", ".join(f"{k}=?" for k in fields)
    execute(f"UPDATE items SET {cols} WHERE id=?", (*fields.values(), iid))


def list_items(q: str = "", author: str | None = None, limit: int = 200) -> list[dict]:
    sql = ("SELECT id, created_at, updated_at, author, source_url, title, platform, status, progress, output_format,"
           " substr(coalesce(instructions,''),1,200) AS instructions FROM items WHERE archived=0")
    params: list = []
    if author:
        sql += " AND author=?"
        params.append(author)
    if q:
        like = f"%{q}%"
        sql += (" AND (title LIKE ? OR source_url LIKE ? OR instructions LIKE ? OR source_text LIKE ?"
                " OR id IN (SELECT item_id FROM messages WHERE content LIKE ?))")
        params += [like] * 5
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return query(sql, params)


# --- messages ---

def add_message(item_id, author, role, kind, content, status="done", meta=None) -> str:
    mid = new_id()
    execute(
        "INSERT INTO messages (id, item_id, created_at, author, role, kind, content, status, meta_json) VALUES (?,?,?,?,?,?,?,?,?)",
        (mid, item_id, time.time(), author, role, kind, content, status,
         json.dumps(meta, ensure_ascii=False) if meta else None),
    )
    execute("UPDATE items SET updated_at=? WHERE id=?", (time.time(), item_id))
    return mid


def update_message(mid: str, **fields):
    if "meta" in fields:
        fields["meta_json"] = json.dumps(fields.pop("meta"), ensure_ascii=False)
    cols = ", ".join(f"{k}=?" for k in fields)
    execute(f"UPDATE messages SET {cols} WHERE id=?", (*fields.values(), mid))


def get_message(mid: str) -> dict | None:
    rows = query("SELECT * FROM messages WHERE id=?", (mid,))
    return rows[0] if rows else None


def messages_for(item_id: str) -> list[dict]:
    return query("SELECT * FROM messages WHERE item_id=? ORDER BY created_at", (item_id,))


# --- brouillons venus du bouton « Partager » d'Android ---

def create_draft(author, url, text, files) -> str:
    did = new_id()
    execute("INSERT INTO drafts (id, created_at, author, url, text, files_json) VALUES (?,?,?,?,?,?)",
            (did, time.time(), author, url, text, json.dumps(files, ensure_ascii=False)))
    return did


def get_draft(did: str) -> dict | None:
    rows = query("SELECT * FROM drafts WHERE id=?", (did,))
    return rows[0] if rows else None
