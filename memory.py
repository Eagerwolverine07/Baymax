"""
Baymax Memory Layer — SQLite with FTS5 full-text search
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "baymax.db"

def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            remind_at TEXT,
            done INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE,
            value TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    c.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts
        USING fts5(content, content=conversations, content_rowid=id)
    """)
    c.execute("""
        CREATE TRIGGER IF NOT EXISTS conversations_ai AFTER INSERT ON conversations BEGIN
            INSERT INTO conversations_fts(rowid, content) VALUES (new.id, new.content);
        END
    """)
    conn.commit()
    conn.close()

def add_task(task: str) -> int:
    conn = get_conn()
    cur = conn.execute("INSERT INTO tasks (task) VALUES (?)", (task,))
    conn.commit()
    task_id = cur.lastrowid
    conn.close()
    return task_id

def list_tasks(status: str = "pending") -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, task, status, created_at FROM tasks WHERE status=? ORDER BY created_at DESC",
        (status,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def complete_task(task_name: str) -> bool:
    conn = get_conn()
    cur = conn.execute(
        "UPDATE tasks SET status='done' WHERE task LIKE ? AND status='pending'",
        (f"%{task_name}%",)
    )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed

def add_reminder(text: str, remind_at: str = None) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO reminders (text, remind_at) VALUES (?, ?)",
        (text, remind_at)
    )
    conn.commit()
    reminder_id = cur.lastrowid
    conn.close()
    return reminder_id

def list_reminders(done: bool = False) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, text, remind_at, created_at FROM reminders WHERE done=? ORDER BY created_at DESC",
        (1 if done else 0,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def set_memory(key: str, value: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO memory (key, value, updated_at) VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value)
    )
    conn.commit()
    conn.close()

def get_memory(key: str):
    conn = get_conn()
    row = conn.execute("SELECT value FROM memory WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None

def log_message(role: str, content: str):
    conn = get_conn()
    conn.execute("INSERT INTO conversations (role, content) VALUES (?, ?)", (role, content))
    conn.commit()
    conn.close()

def recent_conversations(limit: int = 10) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT role, content FROM conversations ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]
