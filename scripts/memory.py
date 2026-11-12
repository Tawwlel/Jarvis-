"""
Local memory in SQLite. Everything the user said or stored (messages, facts, notes,
reminders, to-dos) is encrypted at rest; meeting titles stay readable so notes
can be searched. The key lives in the OS keyring (see secrets_store.py).
"""
import sqlite3
import time
from pathlib import Path

from secrets_store import decrypt_text as D
from secrets_store import encrypt_text as E

DB = Path(__file__).parent.parent / "jarvis_memory.db"
import threading
_chat_lock = threading.Lock()
INTERNAL_FACTS = {"last_brief_date"}  # bookkeeping, not shown to the model


class Memory:
    def __init__(self):
        # Shared with the background scheduler thread, so allow cross-thread use.
        self.db = sqlite3.connect(DB, check_same_thread=False)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages(ts REAL, role TEXT, content TEXT);
            CREATE TABLE IF NOT EXISTS chat_log(ts REAL, role TEXT, content TEXT);
            CREATE INDEX IF NOT EXISTS chat_log_ts ON chat_log(ts);
            CREATE TABLE IF NOT EXISTS facts(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY, due REAL, text TEXT, done INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS notes(ts REAL, meeting TEXT, kind TEXT, text TEXT);
            CREATE TABLE IF NOT EXISTS todos(id INTEGER PRIMARY KEY, ts REAL, due REAL, text TEXT, done INTEGER DEFAULT 0);
            """
        )

    # ---- conversation ----
    def add_message(self, role: str, content: str):
        self.db.execute("INSERT INTO messages VALUES(?,?,?)", (time.time(), role, E(content)))
        self.db.commit()

    def recent(self, n: int = 8) -> list[dict]:
        rows = self.db.execute(
            "SELECT role, content FROM messages ORDER BY ts DESC LIMIT ?", (n,)).fetchall()
        return [{"role": r, "content": D(c)} for r, c in reversed(rows)]

    # ---- chat history: everything shown in the chat window, kept for good (encrypted) ----
    def add_chat(self, role: str, text: str, ts: float | None = None):
        with _chat_lock:
            self.db.execute("INSERT INTO chat_log VALUES(?,?,?)", (ts or time.time(), role, E(text)))
            self.db.commit()

    def chat_recent(self, n: int = 40) -> list[tuple]:
        rows = self.db.execute("SELECT ts, role, content FROM chat_log ORDER BY ts DESC LIMIT ?", (n,)).fetchall()
        return [(t, r, x) for t, r, c in reversed(rows) if not (x := D(c)).startswith("(unreadable")]

    def chat_days(self) -> list[tuple]:
        """[(YYYY-MM-DD, message count)], newest first."""
        rows = self.db.execute("SELECT strftime('%Y-%m-%d', ts, 'unixepoch', 'localtime') d, COUNT(*) FROM chat_log "
                               "GROUP BY d ORDER BY d DESC").fetchall()
        return [(d, n) for d, n in rows]

    def chat_on(self, day: str) -> list[tuple]:
        rows = self.db.execute("SELECT ts, role, content FROM chat_log WHERE "
                               "strftime('%Y-%m-%d', ts, 'unixepoch', 'localtime')=? ORDER BY ts", (day,)).fetchall()
        return [(t, r, D(c)) for t, r, c in rows]

    def chat_search(self, query: str, limit: int = 200) -> list[tuple]:
        """Newest first. The text is encrypted, so matching happens here, not in SQL."""
        q = query.lower().strip()
        out = []
        for t, r, c in self.db.execute("SELECT ts, role, content FROM chat_log ORDER BY ts DESC"):
            text = D(c)
            if q in text.lower():
                out.append((t, r, text))
                if len(out) >= limit:
                    break
        return out

    # ---- facts / profile ----
    def remember(self, key: str, value: str):
        self.db.execute("INSERT OR REPLACE INTO facts VALUES(?,?)", (key, E(value)))
        self.db.commit()

    def get_fact(self, key: str):
        row = self.db.execute("SELECT value FROM facts WHERE key=?", (key,)).fetchone()
        return D(row[0]) if row else None

    def facts_text(self) -> str:
        rows = self.db.execute("SELECT key, value FROM facts ORDER BY key").fetchall()
        return "\n".join(f"- {k}: {D(v)}" for k, v in rows
                         if k not in INTERNAL_FACTS and not k.startswith("_"))

    # ---- reminders ----
    def add_reminder(self, due: float, text: str):
        self.db.execute("INSERT INTO reminders(due, text) VALUES(?,?)", (due, E(text)))
        self.db.commit()

    def due_reminders(self) -> list[str]:
        rows = self.db.execute(
            "SELECT id, text FROM reminders WHERE done=0 AND due<=?", (time.time(),)).fetchall()
        for rid, _ in rows:
            self.db.execute("UPDATE reminders SET done=1 WHERE id=?", (rid,))
        self.db.commit()
        return [D(t) for _, t in rows]

    def reminders_today(self) -> list[str]:
        now = time.localtime()
        start = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, -1))
        rows = self.db.execute(
            "SELECT text FROM reminders WHERE done=0 AND due>=? AND due<? ORDER BY due",
            (start, start + 86400)).fetchall()
        return [D(r[0]) for r in rows]

    # ---- to-dos ----
    def add_todo(self, text: str, due: float | None = None) -> int:
        cur = self.db.execute("INSERT INTO todos(ts, due, text) VALUES(?,?,?)",
                              (time.time(), due, E(text)))
        self.db.commit()
        return cur.lastrowid

    def list_todos(self, include_done: bool = False) -> list[dict]:
        q = "SELECT id, text, due, done FROM todos" + ("" if include_done else " WHERE done=0")
        rows = self.db.execute(q + " ORDER BY COALESCE(due, 9e18), id").fetchall()
        return [{"id": i, "text": D(t), "due": d, "done": bool(x)} for i, t, d, x in rows]

    def complete_todo(self, ref: str) -> str | None:
        """Mark done by id or by a part of the text. Returns the todo text, or None."""
        todos = self.list_todos()
        hit = next((t for t in todos if str(t["id"]) == str(ref).strip()), None) or next(
            (t for t in todos if str(ref).lower() in t["text"].lower()), None)
        if not hit:
            return None
        self.db.execute("UPDATE todos SET done=1 WHERE id=?", (hit["id"],))
        self.db.commit()
        return hit["text"]

    # ---- meeting notes ----
    def add_note(self, meeting: str, text: str, kind: str = "note"):
        self.db.execute("INSERT INTO notes VALUES(?,?,?,?)", (time.time(), meeting, kind, E(text)))
        self.db.commit()

    def notes_text(self, meeting: str, kind: str = "note") -> str:
        rows = self.db.execute(
            "SELECT text FROM notes WHERE meeting=? AND kind=? ORDER BY ts", (meeting, kind)).fetchall()
        return "\n".join(D(r[0]) for r in rows)

    def recent_summaries(self, days: int = 2) -> list[tuple[str, str]]:
        since = time.time() - days * 86400
        rows = self.db.execute(
            "SELECT meeting, text FROM notes WHERE kind='summary' AND ts>=? ORDER BY ts",
            (since,)).fetchall()
        return [(m, D(t)) for m, t in rows]

    def last_summary(self, title: str):
        """Most recent summary of an earlier meeting with the same title (for prep)."""
        row = self.db.execute(
            "SELECT text FROM notes WHERE kind='summary' AND meeting LIKE ? ORDER BY ts DESC LIMIT 1",
            (f"{title} (%",)).fetchone()
        return D(row[0]) if row else None

    def notes_search(self, query: str = "", days: int = 14) -> str:
        """Matches the note's topic OR its text (text is stored encrypted, so it is matched after reading)."""
        since = time.time() - days * 86400
        rows = self.db.execute("SELECT meeting, kind, text FROM notes WHERE ts>=? ORDER BY ts", (since,)).fetchall()
        q = (query or "").lower().strip()
        out = []
        for m, k, t in rows:
            text = D(t)
            if not q or q in m.lower() or q in text.lower() or all(w in (m + " " + text).lower() for w in q.split()):
                out.append(f"[{m} | {k}] {text}")
        return "\n".join(out)
