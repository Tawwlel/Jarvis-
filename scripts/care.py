"""Jarvis's care team: six small helpers that look after Jarvis every 30 minutes, on the customer's own PC.

  1. Error watcher   - reads Jarvis's own log for crashes and failures and groups them
  2. Backend doctor  - checks the file index, WhatsApp, email, licence and disk, and repairs what it safely can
  3. Screen watcher  - looks for slow answers, unanswered messages and window (UI) problems
  4. Updater         - checks for a new version and installs it while the customer is not using Jarvis
  5. Issue keeper    - lists what went wrong for the customer (nothing found, errors, "this is wrong")
  6. Question spotter- finds questions the customer asks again and again (candidates for one-tap buttons)

Everything they find is written to data/care_report.json on this PC. Only anonymous COUNTS (how many errors,
which kind, how many slow answers - never a file, chat, name or question) go to Apricot Digital with the
licence check-in, so problems can be fixed in the next update. Customers are told only what they must act on.
"""
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
LOG = ROOT / "jarvis.log"
REPORT = DATA / "care_report.json"
STATE = DATA / "care_state.json"
EVERY = 30 * 60


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(p: Path, d: dict):
    try:
        DATA.mkdir(exist_ok=True)
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        print("[care] could not save:", e)


def _new_log_lines(st: dict) -> list[str]:
    """Only the log written since the last round."""
    try:
        size = LOG.stat().st_size
        start = st.get("log_pos", 0)
        if start > size:  # the log was cleared
            start = 0
        with open(LOG, "rb") as f:
            f.seek(start)
            chunk = f.read(4_000_000)
        st["log_pos"] = start + len(chunk)
        return chunk.decode("utf-8", "replace").splitlines()
    except Exception:
        return []


# ---------------- 1. error watcher ----------------
ERR = re.compile(r"Traceback|Error\b|Exception|\[llm\]|skipped \(|couldn't|could not|failed", re.I)


def error_watcher(lines: list[str]) -> dict:
    sigs = Counter()
    for i, ln in enumerate(lines):
        if not ERR.search(ln):
            continue
        if "Traceback" in ln:  # the useful line is the last one of the traceback
            for nxt in lines[i + 1:i + 40]:
                if re.match(r"^(\d\d:\d\d:\d\d )?\w*(Error|Exception)\b", nxt):
                    ln = nxt
                    break
        tag = re.sub(r"^\d\d:\d\d:\d\d ", "", ln)
        tag = re.sub(r"\d+", "#", tag)[:90]
        tag = re.sub(r"\[wa\] .*?: skipped", "[wa] <chat>: skipped", tag)
        sigs[tag] += 1
    return {"errors": sum(sigs.values()), "top": sigs.most_common(8)}


# ---------------- 2. backend doctor ----------------
def backend_doctor(cfg: dict, fix=True) -> dict:
    found, fixed = [], []
    try:
        import docsearch
        db = docsearch._db()
        ok = db.execute("PRAGMA quick_check").fetchone()[0]
        n = db.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        db.close()
        if ok != "ok":
            found.append("file index damaged")
        if n == 0:
            found.append("file index empty")
            if fix:
                docsearch.background_index(cfg)
                fixed.append("started building the file index")
    except Exception as e:
        found.append(f"file index unreadable ({type(e).__name__})")
    wa = _load(DATA / "wa_agent.json")
    if (DATA / "wa_profile").exists():
        age = time.time() - float(wa.get("last_sync", 0) or 0)
        if age > 24 * 3600:
            found.append("WhatsApp not synced for over a day")
            if False:  # the WhatsApp agent's own loop syncs; a second starter here opened the browser twice
                try:
                    pass
                except Exception:
                    pass
    else:
        found.append("WhatsApp not linked")
    try:
        import licence
        st = licence._load()
        if not st.get("key"):
            found.append("no licence key")
        elif licence.blocked():
            found.append("licence paused")
    except Exception:
        pass
    try:
        free = shutil.disk_usage(str(ROOT)).free / 1e9
        if free < 1:
            found.append(f"disk almost full ({free:.1f} GB free)")
    except Exception:
        pass
    return {"problems": found, "fixed": fixed}


# ---------------- 3. screen (UI) watcher ----------------
def screen_watcher(lines: list[str], memory=None) -> dict:
    slow, ui = [], 0
    for ln in lines:
        m = re.search(r"\[timing\].*?(?:answer|reply|total)[^\d]*([\d.]+)s", ln)
        if m and float(m.group(1)) > 20:
            slow.append(float(m.group(1)))
        if re.search(r"QWidget|QPainter|QTextCursor|QObject::|Qt\w*Warning", ln):
            ui += 1
    unanswered = 0
    if memory is not None:
        try:
            rows = memory.chat_recent(60)
            for (t, r, _), nxt in zip(rows, rows[1:] + [(time.time(), "", "")]):
                if r == "user" and nxt[1] != "assistant" and nxt[0] - t > 60:
                    unanswered += 1
        except Exception:
            pass
    return {"slow_answers": len(slow), "slowest_s": max(slow) if slow else 0, "ui_warnings": ui,
            "unanswered": unanswered}


# ---------------- 4. updater ----------------
def updater_bot(idle: bool, restart=None) -> dict:
    if not idle:
        return {"checked": False, "why": "customer is using Jarvis"}
    try:
        import updater
        if updater.enabled():  # zip installs
            r = updater.check_and_update(print)
            if r == "updated" and restart:
                restart(updater.whats_new())
            return {"checked": True, "result": r}
        if (ROOT / ".git").exists():  # git installs (Apricot Digital's own laptops)
            flags = 0x08000000 if sys.platform == "win32" else 0
            before = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                                    creationflags=flags, timeout=30).stdout.strip()
            p = subprocess.run(["git", "-C", str(ROOT), "pull", "--ff-only", "-q"], capture_output=True, text=True,
                               creationflags=flags, timeout=180)
            after = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                                   creationflags=flags, timeout=30).stdout.strip()
            if p.returncode == 0 and before and after and before != after:
                if restart:
                    restart("a newer version")
                return {"checked": True, "result": "updated"}
            return {"checked": True, "result": "none" if p.returncode == 0 else "failed"}
    except Exception as e:
        return {"checked": True, "result": f"failed ({type(e).__name__})"}
    return {"checked": False}


# ---------------- 5 & 6. issue keeper and question spotter ----------------
FAILED = re.compile(r"couldn't|could not|can't|cannot|not found|no (matching|file|files)|nothing (matched|found)|"
                    r"isn't working|went wrong|plan .*used up|not activated|نہیں مل|نہیں ملی", re.I)
UNHAPPY = re.compile(r"\b(wrong|not working|doesn'?t work|useless|bakwas|ghalat|galat|kaam nahi|nahi chal|"
                     r"not what i|that'?s not|still not|again\?)\b|غلط|کام نہیں", re.I)
STOP = set("the a an and or to of for me my please plz jarvis can you i is it in on from with mujhe mera meri ki ka ke "
           "ko se do de dein dikhao batao".split())


def _shape(q: str) -> str:
    words = [w for w in re.findall(r"[\w']+", q.lower()) if w not in STOP and not w.isdigit()]
    return " ".join(sorted(set(words)))


def issue_keeper(memory, since: float) -> dict:
    issues = Counter()
    if memory is None:
        return {"issues": []}
    try:
        rows = [r for r in memory.chat_recent(400) if r[0] > since]
    except Exception:
        rows = []
    for (t, role, text) in rows:
        if role == "assistant" and FAILED.search(text):
            kind = ("plan" if re.search(r"plan|bill", text, re.I) else "nothing found" if re.search(
                r"not found|no (matching|file)|nothing|نہیں مل", text, re.I) else "could not do it")
            issues[kind] += 1
        elif role == "user" and UNHAPPY.search(text):
            issues["customer said the answer was wrong"] += 1
    return {"issues": issues.most_common()}


def question_spotter(memory, top=10) -> dict:
    if memory is None:
        return {"repeated": []}
    try:
        rows = [x for (t, role, x) in memory.chat_recent(1000) if role == "user" and len(x) < 300]
    except Exception:
        rows = []
    groups, sample = Counter(), {}
    shapes = []
    for q in rows:
        s = _shape(q)
        if not s:
            continue
        sw = set(s.split())
        key = next((k for k in shapes if len(sw & set(k.split())) / max(1, len(sw | set(k.split()))) >= 0.6), s)
        if key == s and s not in shapes:
            shapes.append(s)
        groups[key] += 1
        sample.setdefault(key, q)
    rep = [(sample[k], n) for k, n in groups.most_common(top) if n >= 3]
    return {"repeated": rep}


# ---------------- the team ----------------
def run_round(cfg: dict, memory=None, notify=None, restart=None, idle=True) -> dict:
    st = _load(STATE)
    since = st.get("last_round", time.time() - 86400)
    lines = _new_log_lines(st)
    rep = {"ts": time.time(), "errors": error_watcher(lines), "backend": backend_doctor(cfg),
           "screen": screen_watcher(lines, memory), "update": updater_bot(idle, restart),
           "issues": issue_keeper(memory, since), "questions": question_spotter(memory)}
    _save(REPORT, rep)
    # tell the customer only what THEY must do, and not more than once a day per thing
    told = st.setdefault("told", {})
    for problem in rep["backend"]["problems"]:
        msg = {"WhatsApp not linked": "WhatsApp isn't linked yet, so I can't find files from your chats. Say 'link WhatsApp' when you're ready.",
               "no licence key": "Jarvis isn't activated yet. Please contact Apricot Digital to finish your setup."}.get(problem)
        if msg and notify and time.time() - told.get(problem, 0) > 86400:
            told[problem] = time.time()
            notify(msg)
    st["last_round"] = time.time()
    _save(STATE, st)
    print(f"[care] round done: {rep['errors']['errors']} error line(s), problems {rep['backend']['problems']}, "
          f"fixed {rep['backend']['fixed']}, slow answers {rep['screen']['slow_answers']}, update {rep['update']}")
    return rep


def anonymous_counts() -> dict:
    """What may leave this PC: numbers and error KINDS only. No names, files, chats or questions."""
    r = _load(REPORT)
    if not r:
        return {}
    kinds = Counter()
    for tag, n in r.get("errors", {}).get("top", []):
        k = ("whatsapp" if "[wa]" in tag else "language model" if "[llm]" in tag else "voice" if re.search(
            r"audio|voice|stt|tts|whisper", tag, re.I) else "email" if "mail" in tag.lower() else "search" if re.search(
            r"docs|search|index", tag, re.I) else "other")
        kinds[k] += n
    return {"errors": r.get("errors", {}).get("errors", 0), "error_kinds": dict(kinds),
            "problems": r.get("backend", {}).get("problems", []),
            "slow_answers": r.get("screen", {}).get("slow_answers", 0),
            "unanswered": r.get("screen", {}).get("unanswered", 0),
            "issues": dict(r.get("issues", {}).get("issues", [])),
            "repeated_questions": len(r.get("questions", {}).get("repeated", []))}


class CareTeam(threading.Thread):
    def __init__(self, cfg, memory=None, notify=None, restart=None, last_activity=None):
        super().__init__(daemon=True, name="care-team")
        self.cfg, self.memory, self.notify, self.restart = cfg, memory, notify, restart
        self.last_activity = last_activity or (lambda: 0)

    def run(self):
        time.sleep(180)  # let Jarvis finish starting
        while True:
            try:
                idle = time.time() - self.last_activity() > 10 * 60
                run_round(self.cfg, self.memory, self.notify, self.restart, idle)
            except Exception as e:
                print("[care] round failed:", e)
            time.sleep(EVERY)


from tools import tool  # noqa: E402


@tool("care_report", "Show what Jarvis's care team (error watcher, backend doctor, screen watcher, updater, issue "
      "keeper, question spotter) found in its last check. They run every 30 minutes.", {}, [])
def care_report():
    r = _load(REPORT)
    if not r:
        return "The care team hasn't finished its first check yet (it runs every 30 minutes)."
    b, s, q = r["backend"], r["screen"], r["questions"]["repeated"]
    parts = [f"Last check {time.strftime('%H:%M', time.localtime(r['ts']))}."]
    parts.append("Everything looks healthy." if not b["problems"] and not r["errors"]["errors"] else
                 f"Problems: {', '.join(b['problems']) or 'none'}; {r['errors']['errors']} error line(s) in the log.")
    if b["fixed"]:
        parts.append("Fixed: " + ", ".join(b["fixed"]) + ".")
    if s["slow_answers"]:
        parts.append(f"{s['slow_answers']} slow answer(s).")
    if r["issues"]["issues"]:
        parts.append("What went wrong for you: " + ", ".join(f"{k} ({n})" for k, n in r["issues"]["issues"]) + ".")
    if q:
        parts.append("You often ask: " + "; ".join(f"'{t[:60]}' ({n} times)" for t, n in q[:3]) + ".")
    return " ".join(parts)
