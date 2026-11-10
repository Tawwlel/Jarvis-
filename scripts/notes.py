"""
Meeting notes.

While notes are being taken Jarvis only listens and stores text: no model calls,
so it costs nothing in tokens. One Haiku call at the end writes the summary.

States: idle -> offered (meeting starting, "want notes?") -> active -> summary_offered -> idle
"""
import datetime as dt
import re
import time

from tools import CTX, tool

YES = re.compile(r"\b(yes|yeah|yep|yup|sure|please|go ahead|ok|okay|do it|ہاں|جی|جی ہاں|ٹھیک ہے|بالکل|کریں|کر دو)\b", re.I)
NO = re.compile(r"\b(no|nope|nah|not now|skip|don'?t|نہیں|نہ|رہنے دو|ابھی نہیں)\b", re.I)
START = re.compile(r"\b(take|start|begin)\b.*\bnotes?\b|\bnote (this|that) down\b", re.I)
STOP = re.compile(r"\b(stop|end|finish)\b.*\bnotes?\b|\bmeeting (is )?(over|ended|finished)\b", re.I)
NOISE = {"", "you", "thank you", "thanks", "thanks for watching", "bye", "okay", "uh", "um"}
OFFER_TTL = 600  # seconds an offer stays open


def looks_like_noise(text: str) -> bool:
    t = re.sub(r"[^a-z ]", "", text.lower()).strip()
    return t in NOISE or len(t.split()) < 2


class NotesSession:
    def __init__(self, memory, summarize):
        self.mem, self.summarize = memory, summarize
        self.state, self.title, self.key, self.count = "idle", "", "", 0
        self._since = 0.0

    # --- helpers ---
    def _set(self, state, title=None):
        self.state, self._since = state, time.time()
        if title is not None:
            self.title = title

    def _expire(self):
        if self.state in ("offered", "summary_offered") and time.time() - self._since > OFFER_TTL:
            self.state = "idle"

    def offer(self, title: str):
        """Called by the scheduler when a meeting starts."""
        if self.state == "idle":
            self._set("offered", title)

    def _start(self, title: str) -> str:
        title = title or "Untitled note"
        self.key = f"{title} ({dt.date.today().isoformat()})"
        self.count = 0
        self._set("active", title)
        return (f"Okay, taking notes for {title}. I'll stay quiet and just listen. "
                "Say stop notes when you're done.")

    def add(self, text: str):
        self.mem.add_note(self.key, text)
        self.count += 1

    def stop(self) -> str:
        if self.count == 0:
            self._set("idle")
            return "I didn't catch any notes."
        self._set("summary_offered")
        return f"Notes saved, {self.count} entries. Would you like a summary?"

    # --- command handling (before the brain, so it costs no tokens) ---
    def handle(self, text: str):
        """Returns a reply string if this was a notes command, else None."""
        self._expire()
        if self.state == "offered":
            if YES.search(text) or START.search(text):
                return self._start(self.title)
            if NO.search(text):
                self._set("idle")
                return "No problem."
        elif self.state == "summary_offered":
            if YES.search(text):
                self._set("idle")
                return self.summarize(self.key)
            if NO.search(text):
                self._set("idle")
                return "Okay, the notes are saved if you want them later."
        if START.search(text):
            return self._start(self.title if self.state == "offered" else "")
        return None


# --- tools the brain can call ("what did we decide in Tuesday's meeting?") ---
@tool("notes_search", "Look up saved meeting notes and summaries. Optional query matches the "
      "meeting title; days = how far back (default 14).",
      {"query": {"type": "string"}, "days": {"type": "integer"}})
def notes_search(query="", days=14):
    return CTX["memory"].notes_search(query, int(days)) or "No notes found."


@tool("note_add", "Save a quick note the user dictates (not during a meeting session).",
      {"text": {"type": "string"}, "topic": {"type": "string"}}, ["text"])
def note_add(text, topic="General"):
    CTX["memory"].add_note(f"{topic} ({dt.date.today().isoformat()})", text)
    return "Noted."
