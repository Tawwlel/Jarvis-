"""
WhatsApp Document Agent - a separate worker that runs beside Jarvis once WhatsApp is linked.

Job:
  1. Keep watching: every few minutes it pulls new documents/photos from WhatsApp (read-only) and reads them
     (PDF text, OCR for photos), so everything is indexed before anyone asks.
  2. Tell the owner when new invoices/quotations/receipts arrive ("2 new invoices from Talal Jazz").
  3. Answer questions about what is IN the documents ("How much did Khan Traders pay?", "Bilal Steel ki
     quotation mein total kya hai?") by handing Jarvis's brain the matching documents' text, with sources.

Safety: it never sends, replies, deletes or forwards anything in WhatsApp. It only reads and downloads.
"""
import json
import threading
import time
from pathlib import Path

import docsearch
import whatsapp_reader as wa
from tools import CTX, tool

STATE = wa.DATA / "wa_agent.json"
INTERVAL_MIN = 15
_lock = threading.Lock()


def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"known": [], "last_sync": 0}


def _save(st: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st), encoding="utf-8")


def _wa_rows():
    db = docsearch._db()
    rows = db.execute("SELECT path,chat,name,doc_type,amount,doc_date,text FROM docs WHERE source='whatsapp'").fetchall()
    db.close()
    return rows


def run_once(cfg: dict, notify=None) -> list[dict]:
    """Sync + index; returns the documents that are new since the last run."""
    with _lock:
        st = _load()
        if wa.PROFILE.exists():
            try:
                wa.sync()
            except Exception as e:
                print("[wa-agent] sync failed:", e)
        docsearch.reindex(cfg, include_computer=False, include_whatsapp=True)
        known = set(st["known"])
        new = [dict(path=p, chat=c, name=n, type=t, amount=a, date=d)
               for p, c, n, t, a, d, _ in _wa_rows() if p not in known]
        st["known"] = sorted(known | {d["path"] for d in new})
        first_run = st["last_sync"] == 0
        st["last_sync"] = time.time()
        _save(st)
    business = [d for d in new if d["type"] and d["type"] not in ("other", "photo")]
    if notify and business and not first_run:
        lines = [f"- {d['name']} ({d['type']}" + (f", Rs. {float(d['amount']):,.0f}" if d["amount"] else "")
                 + f") from {d['chat'] or 'WhatsApp'}" for d in business[:6]]
        notify(f"{len(business)} new document(s) on WhatsApp:\n" + "\n".join(lines))
    return new


class WhatsAppAgent(threading.Thread):
    def __init__(self, cfg: dict, notify):
        super().__init__(daemon=True, name="whatsapp-agent")
        self.cfg, self.notify = cfg, notify

    def run(self):
        time.sleep(60)  # let Jarvis finish starting first
        while True:
            if wa.PROFILE.exists() or (wa.WA_DIR.exists() and any(wa.WA_DIR.iterdir())):
                try:
                    run_once(self.cfg, self.notify)
                except Exception as e:
                    print("[wa-agent] error:", e)
            time.sleep(INTERVAL_MIN * 60)


@tool("whatsapp_docs_ask",
      "Answer a question about what is written INSIDE WhatsApp documents (amounts, dates, items, who paid, totals, "
      "what a quotation says). Returns the matching documents' text with file and chat names; answer only from it "
      "and say which file the answer came from. If nothing matches, say so.",
      {"question": {"type": "string"}}, ["question"])
def whatsapp_docs_ask(question):
    cfg = CTX.get("cfg", {})
    with _lock:
        docsearch.reindex(cfg, include_computer=False, include_whatsapp=True)
    r = docsearch.search(question, "whatsapp", limit=5)
    if not r["items"]:
        return "No WhatsApp documents match that."
    rows = {p: txt for p, *_rest, txt in _wa_rows()}
    out = []
    for it in r["items"][:5]:
        chats = ", ".join(it.get("also_in") or [it["chat"]])
        text = (rows.get(it["path"]) or "").strip()[:1500] or "(no readable text)"
        out.append(f"### {it['name']} (chat: {chats}; type: {it['type']}; total: {it['amount']}; date: {it['date']})\n{text}")
    note = "Closest matches only - confirm with the user.\n" if r["mode"] == "close" else ""
    return note + "\n\n".join(out)


@tool("whatsapp_new_docs",
      "List documents that arrived on WhatsApp recently. days = how far back (default 1).",
      {"days": {"type": "number"}}, [])
def whatsapp_new_docs(days=1):
    cut = time.time() - float(days) * 86400
    db = docsearch._db()
    rows = db.execute("SELECT name,chat,doc_type,amount,doc_date,mtime FROM docs WHERE source='whatsapp' AND mtime>=? "
                      "ORDER BY mtime DESC", (cut,)).fetchall()
    db.close()
    if not rows:
        return f"No new WhatsApp documents in the last {days:g} day(s)."
    return "\n".join(f"- {n} ({t}, {a or '-'}) from {c or 'WhatsApp'}" for n, c, t, a, d, _ in rows[:30])
