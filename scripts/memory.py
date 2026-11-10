"""Tiny SQLite memory: conversation history + facts + reminders. Local, free."""
import sqlite3
import time
from pathlib import Path

DB = Path(__file__).parent.parent / "jarvis_memory.db"


class Memory:
    def __init__(self):
        # Shared with the background scheduler thread, so allow cross-thread use.
        self.db = sqlite3.connect(DB, check_same_thread=False)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages(ts REAL, role TEXT, content TEXT);
            CREATE TABLE IF NOT EXISTS facts(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY, due REAL, text TEXT, done INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS notes(ts REAL, meeting TEXT, kind TEXT, text TEXT);
            """
        )

    # ---- meeting notes ----
    def add_note(self, meeting: str, text: str, kind: str = "note"):
        self.db.execute("INSERT INTO notes VALUES(?,?,?,?)", (time.time(), meeting, kind, text))
        self.db.commit()

    def notes_text(self, meeting: str, kind: str = "note") -> str:
        rows = self.db.execute(
            "SELECT text FROM notes WHERE meeting=? AND kind=? ORDER BY ts", (meeting, kind)
        ).fetchall()
        return "\n".join(r[0] for r in rows)

    def notes_search(self, query: str = "", days: int = 14) -> str:
        since = time.time() - days * 86400
        rows = self.db.execute(
            "SELECT meeting, kind, text FROM notes WHERE ts>=? AND meeting LIKE ? ORDER BY ts",
            (since, f"%{query}%"),
        ).fetchall()
        return "\n".join(f"[{m} | {k}] {t}" for m, k, t in rows)

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
