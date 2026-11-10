"""Tiny SQLite memory: conversation history + facts + reminders. Local, free."""
import sqlite3
import time
from pathlib import Path

DB = Path(__file__).parent.parent / "jarvis_memory.db"


class Memory:
    def __init__(self):
        self.db = sqlite3.connect(DB)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages(ts REAL, role TEXT, content TEXT);
            CREATE TABLE IF NOT EXISTS facts(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY, due REAL, text TEXT, done INTEGER DEFAULT 0);
            """
        )

    def add_message(self, role: str, content: str):
        self.db.execute("INSERT INTO messages VALUES(?,?,?)", (time.time(), role, content))
        self.db.commit()

    def recent(self, n: int = 8) -> list[dict]:
        rows = self.db.execute(
            "SELECT role, content FROM messages ORDER BY ts DESC LIMIT ?", (n,)
        ).fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    def remember(self, key: str, value: str):
        self.db.execute("INSERT OR REPLACE INTO facts VALUES(?,?)", (key, value))
        self.db.commit()

    def facts_text(self) -> str:
        rows = self.db.execute("SELECT key, value FROM facts").fetchall()
        return "\n".join(f"- {k}: {v}" for k, v in rows)

    def add_reminder(self, due: float, text: str):
        self.db.execute("INSERT INTO reminders(due, text) VALUES(?,?)", (due, text))
        self.db.commit()

    def due_reminders(self) -> list[str]:
        now = time.time()
        rows = self.db.execute(
            "SELECT id, text FROM reminders WHERE done=0 AND due<=?", (now,)
        ).fetchall()
        for rid, _ in rows:
            self.db.execute("UPDATE reminders SET done=1 WHERE id=?", (rid,))
        self.db.commit()
        return [t for _, t in rows]
