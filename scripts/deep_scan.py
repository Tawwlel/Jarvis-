"""
Deep scan: with the owner's permission, Jarvis reads EVERY document and photo it can reach - the computer's
document folders and every WhatsApp chat - once, remembers where everything is, and then refreshes every 12
hours (the owner can change that). Afterwards "find the Khan Traders invoice" is answered straight from what
Jarvis already knows, with no waiting.

Permission: nothing is scanned until the owner says yes (a spoken/typed yes, or the tray's 'Scan everything').
Read-only: files are only read, WhatsApp files are only downloaded into data/whatsapp. Nothing is sent,
changed or deleted.
"""
import json
import threading
import time
from pathlib import Path

from tools import CTX, background, notify, tool

DATA = Path(__file__).parent.parent / "data"
STATE = DATA / "scan.json"
DEFAULT_HOURS = 12
_lock = threading.Lock()

ASK = ("I can learn where all your documents are. With your OK I'll read the folders on this computer "
       "(Documents, Desktop, Downloads, Pictures, OneDrive) and every WhatsApp chat once, remember where each "
       "file is, and refresh that every 12 hours. After that I can answer instantly. I only read and save files - "
       "I never send, change or delete anything. Shall I start? Say 'yes, scan everything'.")


def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"allowed": None, "hours": DEFAULT_HOURS, "last_sync": 0, "last_full": 0, "asked": 0, "folders": []}


def _save(st: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st), encoding="utf-8")
    tmp.replace(STATE)


def extra_folders() -> list[Path]:
    """Folders beyond Documents/Desktop/Downloads that the owner allowed Jarvis to read."""
    st = _load()
    if not st.get("allowed"):
        return []
    if "chosen" in st:  # picked in the welcome screen: exactly these folders, nothing automatic
        return [Path(p) for p in st["chosen"] if Path(p).is_dir()]
    import files
    home = files.HOME
    found = [home / "Pictures"] + sorted(home.glob("OneDrive*"))
    found += [Path(p) for p in st.get("folders", [])]
    return [p for p in found if p.is_dir()]


FAST_TEXT = ("Fast search: I read every file once and keep a private list on this computer of where it is and what it "
             "says. Searches are instant and use no AI credits. It uses some of the computer's power (CPU, and the "
             "graphics card if there is one) while scanning, and a little afterwards.")
LIGHT_TEXT = ("Light: I only remember where your files are. When you ask, I open the likely ones and read them then. "
              "That uses less computer power and disk space, but answers are slower and use more AI credits.")


def learn_mode() -> str:
    """'fast' (read everything once, instant searches) or 'light' (only remember locations, read files when asked)."""
    return "light" if _load().get("mode") == "light" else "fast"


def set_mode(m: str):
    st = _load()
    st["mode"] = "light" if m == "light" else "fast"
    _save(st)
    if st["mode"] == "fast":
        try:  # files remembered by name only get read on the next refresh
            import docsearch
            db = docsearch._db()
            db.execute("UPDATE docs SET mtime=0 WHERE text='' OR text IS NULL")
            db.commit()
            db.close()
        except Exception as e:
            print("[scan] mode:", e)


def grant(folders: list[str], whatsapp: bool = True, email: bool = True, scan_mode: str = "fast"):
    """The owner said yes in the welcome screen: remember which folders and sources Jarvis may read."""
    st = _load()
    st.update(allowed=True, chosen=[str(Path(f)) for f in folders], sources={"whatsapp": whatsapp, "email": email},
              granted_at=time.time(), mode="light" if scan_mode == "light" else "fast")
    _save(st)


def source_ok(name: str) -> bool:
    return _load().get("sources", {}).get(name, True)


def offer() -> str:
    """The question to put to the owner (only while they haven't answered)."""
    st = _load()
    if st.get("allowed") is None:
        st["asked"] = time.time()
        _save(st)
        return ASK
    return ""


def _wa_linked() -> bool:
    try:
        import whatsapp_reader as wa
        return wa.PROFILE.exists()
    except Exception:
        return False


def _counts() -> dict:
    import docsearch
    db = docsearch._db()
    total = db.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    by_src = dict(db.execute("SELECT source, COUNT(*) FROM docs GROUP BY source").fetchall())
    by_type = db.execute("SELECT doc_type, COUNT(*) FROM docs WHERE doc_type NOT IN ('other','') "
                         "GROUP BY doc_type ORDER BY 2 DESC").fetchall()
    db.close()
    return {"total": total, "computer": by_src.get("computer", 0), "whatsapp": by_src.get("whatsapp", 0),
            "email": by_src.get("email", 0), "types": by_type}


def _summary(prefix: str) -> str:
    c = _counts()
    types = ", ".join(f"{n} {t}{'s' if n != 1 else ''}" for t, n in c["types"][:6])
    hours = _load().get("hours", DEFAULT_HOURS)
    return (f"{prefix} I now know {c['total']} files: {c['computer']} on this computer, {c['whatsapp']} from "
            f"WhatsApp and {c['email']} from email" + (f" ({types})" if types else "") + f". Ask me for any of them and I'll answer straight "
            f"away. I'll refresh this every {hours:g} hours.")


def run_scan(cfg: dict, full: bool = True) -> str:
    """The scan itself. full=True: everything, all history. full=False: the regular refresh."""
    import docsearch
    if not _lock.acquire(blocking=False):
        return "A scan is already running."
    try:
        last = [0.0]

        def tick(msg):
            if time.time() - last[0] > 45:  # a progress line at most every 45 seconds
                last[0] = time.time()
                notify(msg)

        if full:
            notify("Scan started. First your computer's folders...")
        with docsearch._index_lock:
            docsearch.reindex(cfg, include_computer=True, include_whatsapp=False,
                              progress=lambda n: tick(f"Computer: read {n} files so far..."))
        import whatsapp_agent  # WhatsApp is the WhatsApp agent's job: ask it, don't do it here
        if _wa_linked() and full:
            notify("Now the WhatsApp agent goes through every chat (this part is slower)...")
        state = whatsapp_agent.scan(cfg, full, tick) if source_ok("whatsapp") else "skipped"
        if state == "busy":
            notify("WhatsApp was busy, so that part will be done next time.")
        elif state == "not linked" and full:
            notify("WhatsApp isn't linked yet, so I scanned the computer only. Say 'link WhatsApp' to add it.")
        try:
            import email_agent
            n = email_agent.sync_attachments(cfg, days=180 if full else 14) if source_ok("email") else None
            if n is not None:
                with docsearch._index_lock:
                    docsearch.reindex(cfg, include_computer=False, include_whatsapp=False)
                if full:
                    notify(f"Email: saved and read {n} new attachment(s).")
        except Exception as e:
            print("[scan] email:", e)
        threading.Thread(target=docsearch._vectors, daemon=True).start()
        st = _load()
        st["last_sync"] = time.time()
        if full:
            st["last_full"] = time.time()
        _save(st)
        return _summary("Scan finished." if full else "Refreshed.")
    finally:
        _lock.release()


@tool("scan_everything",
      "Read ALL the owner's documents and photos - the computer's document folders and every WhatsApp chat - so "
      "Jarvis knows where every file is and can answer instantly. Needs the owner's permission: call with "
      "confirm=true ONLY after the owner clearly said yes (e.g. 'yes, scan everything'); confirm=false if they "
      "said no; leave confirm out to just explain and ask. It runs in the background and reports when done.",
      {"confirm": {"type": "boolean"}}, [])
def scan_everything(confirm=None):
    import threading as _t
    st = _load()
    if confirm is None and getattr(_t.current_thread(), "inline", False):
        confirm = True  # the owner pressed 'Scan everything' in the tray: that is the permission
    if confirm is None:
        return ASK if st.get("allowed") is not True else "Scanning is already allowed. Say 'scan now' to run it again."
    if not confirm:
        st["allowed"] = False
        _save(st)
        return "OK, I won't scan. Say 'scan everything' any time you change your mind."
    st["allowed"] = True
    _save(st)
    return background("scan", lambda: run_scan(CTX.get("cfg", {}), full=True),
                      "Starting now. I'll read your computer's folders first, then every WhatsApp chat, and tell "
                      "you how it goes. You can keep using me meanwhile.")


@tool("scan_status", "Say what Jarvis has read so far, when it last refreshed and when it refreshes next.", {}, [])
def scan_status():
    st = _load()
    c = _counts()
    when = lambda t: time.strftime("%d %b %H:%M", time.localtime(t)) if t else "never"  # noqa: E731
    state = {True: "allowed", False: "not allowed (owner said no)", None: "not asked yet"}[st.get("allowed")]
    nxt = when(st["last_sync"] + st.get("hours", DEFAULT_HOURS) * 3600) if st.get("last_sync") else "after the first scan"
    return (f"Scanning: {state}. Known files: {c['total']} ({c['computer']} computer, {c['whatsapp']} WhatsApp). "
            f"Last refresh: {when(st.get('last_sync', 0))}. Next: {nxt}. Refreshes every "
            f"{st.get('hours', DEFAULT_HOURS):g} hours. WhatsApp {'linked' if _wa_linked() else 'not linked'}. "
            f"Extra folders: {', '.join(st.get('folders', [])) or 'none'}.")


@tool("scan_mode", "Choose how Jarvis learns the owner's files: 'fast' = read everything once and keep a private list on "
                   "this computer (instant searches, no AI credits, uses some computer power while scanning); 'light' = only "
                   "remember where files are and read them when asked (less computer power, slower, uses more AI credits). "
                   "Call without a mode to explain the two and the current choice.",
      {"mode": {"type": "string", "enum": ["fast", "light"]}}, [])
def scan_mode(mode=None):
    m = mode
    if m not in ("fast", "light"):
        return f"{FAST_TEXT}\n\n{LIGHT_TEXT}\n\nRight now: {learn_mode()}. Say 'use fast search' or 'use light mode' to change."
    set_mode(m)
    return ("Done: fast search. I'll read everything on the next refresh (say 'scan now' to start it)."
            if m == "fast" else "Done: light mode. I'll remember where files are and read them when you ask.")


@tool("scan_settings", "Change how often Jarvis refreshes what it knows (hours, 1 to 168; default 12).",
      {"hours": {"type": "number"}}, ["hours"])
def scan_settings(hours):
    h = max(1.0, min(168.0, float(hours)))
    st = _load()
    st["hours"] = h
    _save(st)
    return f"OK. I'll refresh every {h:g} hours."


@tool("scan_add_folder",
      "Also let Jarvis read documents in one more folder on this computer (e.g. 'C:\\Invoices'). Only when the "
      "owner asks and gives the folder. Read-only.", {"path": {"type": "string"}}, ["path"])
def scan_add_folder(path):
    p = Path(path).expanduser()
    if not p.is_dir():
        return f"I can't find the folder {path}. Check the spelling."
    st = _load()
    if str(p) not in st.setdefault("folders", []):
        st["folders"].append(str(p))
    if st.get("allowed") is None:
        st["allowed"] = True
    _save(st)
    return f"Added {p}. I'll read it in the next refresh (or say 'scan now')."


class ScanAgent(threading.Thread):
    """Asks once, then keeps everything fresh every N hours (default 12)."""

    def __init__(self, cfg: dict, notify_fn):
        super().__init__(daemon=True, name="scan-agent")
        self.cfg, self.notify = cfg, notify_fn

    def run(self):
        time.sleep(75)  # let Jarvis finish starting
        while True:
            try:
                self.tick()
            except Exception as e:
                print("[scan] error:", e)
            time.sleep(300)

    def tick(self):
        st = _load()
        now = time.time()
        if st.get("allowed") is None:
            if now - st.get("asked", 0) > 86400:  # ask at most once a day until they answer
                self.notify(offer())
            return
        if not st.get("allowed") or _lock.locked():  # a scan is already running: nothing to do or say
            return
        if now - st.get("last_try", 0) < 3600:  # after any attempt wait an hour before the next
            return
        due = now - st.get("last_sync", 0) >= st.get("hours", DEFAULT_HOURS) * 3600
        if not st.get("last_full") or due:
            st["last_try"] = now
            _save(st)
            try:
                msg = run_scan(self.cfg, full=not st.get("last_full"))
                if not st.get("last_full"):
                    self.notify(msg)
            except Exception as e:
                print("[scan] failed:", e)
                self.notify("The scan stopped on a problem. I'll try again in an hour.")
