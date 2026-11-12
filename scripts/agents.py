"""
The agents: one bot per job, and no two bots share a job or a tool.

Jarvis himself is the coordinator: he hears the request and hands it to exactly ONE agent. That agent sees only
its own tools, so it cannot wander into another agent's work (and the online model gets a much shorter tool list,
which is also faster). Background work is split the same way: each agent has its own worker.

  Finder      finds and opens documents (computer + saved WhatsApp files)
  Accounts    totals and exact invoice details
  WhatsApp    the WhatsApp connection: link, fetch files, answer what is written inside them, iPhone import
  Email       the daily email digest
  Organizer   reminders, to-dos, notes, calendar
  Librarian   the big scan: learns where every file is, refreshes every 12 hours
  Clerk       changes files (write, edit, move, delete) - always asks first
  Keeper      backups and restore
  Guide       setup help and settings
  Operator    mouse-and-keyboard computer control (off unless switched on)
  Jarvis      coordinator: small talk, time, memory, and handing work to the agents above
"""
import re
import time

from tools import REGISTRY, tool

AGENTS = {
    "finder": {
        "title": "Finder", "job": "find, list and open documents and photos on the computer and from WhatsApp",
        "tools": ["doc_search", "doc_find_by_meaning", "doc_collect", "file_find", "file_open", "file_read"],
        "prompt": "You are the Finder agent. Your only job: find, list, open or gather documents. Answer from the "
                  "tools' results only. For files that came from WhatsApp use doc_search with source 'whatsapp'."},
    "accounts": {
        "title": "Accounts", "job": "totals, sums and exact invoice/receipt details",
        "tools": ["invoice_totals", "invoice_details", "learn_invoice_layout"],
        "prompt": "You are the Accounts agent. Your only job: totals and exact figures from invoices, receipts and "
                  "quotations. Give the numbers exactly as the tools return them."},
    "whatsapp": {
        "title": "WhatsApp", "job": "link WhatsApp, fetch its files, answer what is written inside WhatsApp "
                                    "documents, import old files from an iPhone backup",
        "tools": ["whatsapp_link", "whatsapp_sync", "whatsapp_docs_ask", "whatsapp_new_docs",
                  "iphone_whatsapp_import"],
        "prompt": "You are the WhatsApp agent. Read-only: you never send, reply or delete. Your only job: the "
                  "WhatsApp connection, fetching its files, and questions about what is written inside them."},
    "email": {
        "title": "Email", "job": "read new email and give the digest with ideas, questions and tips",
        "tools": ["email_digest", "email_settings"],
        "prompt": "You are the Email agent. Read-only: you never send or delete mail. Your only job: the email "
                  "digest and its settings. Offer to hand events or follow-ups to the Organizer."},
    "organizer": {
        "title": "Organizer", "job": "reminders, to-dos, notes and the calendar",
        "tools": ["set_reminder", "todo_add", "todo_done", "todo_list", "note_add", "notes_search",
                  "calendar_add", "calendar_agenda", "add_to_calendar"],
        "prompt": "You are the Organizer agent. Your only job: reminders, to-dos, notes and calendar events."},
    "librarian": {
        "title": "Librarian", "job": "scan the computer and WhatsApp so every file's location is known; refresh "
                                     "every 12 hours",
        "tools": ["scan_everything", "scan_status", "scan_settings", "scan_add_folder"],
        "prompt": "You are the Librarian agent. Your only job: the scan that learns where every file is, its "
                  "schedule and its status. Never start a scan without the owner's clear yes."},
    "clerk": {
        "title": "Clerk", "job": "change files: write, edit, move, delete (asks first)",
        "tools": ["file_write", "file_edit", "file_move", "file_delete"],
        "prompt": "You are the Clerk agent. Your only job: changing files the owner names. Every change asks the "
                  "owner first."},
    "keeper": {
        "title": "Keeper", "job": "backups and moving Jarvis to a new laptop",
        "tools": ["backup_now"],
        "prompt": "You are the Keeper agent. Your only job: backups of Jarvis."},
    "guide": {
        "title": "Guide", "job": "explain how to set up or connect anything, and change settings",
        "tools": ["setup_help", "update_settings"],
        "prompt": "You are the Guide agent. Your only job: help the owner set Jarvis up, one step at a time, and "
                  "change settings. Never ask for passwords or keys in chat."},
    "operator": {
        "title": "Operator", "job": "control the mouse and keyboard (only when switched on)",
        "tools": [], "prefix": "computer_",
        "prompt": "You are the Operator agent. Your only job: on-screen computer control."},
    "jarvis": {
        "title": "Jarvis", "job": "coordinator: small talk, time, memory, and handing work to the right agent",
        "tools": ["get_time", "remember_fact", "show_visual", "agents_status", "ask_agent"],
        "prompt": ""},
}

RULES = [  # first match wins; anything unmatched goes to the coordinator, who can hand it over
    ("guide", r"\b(set ?up|setup)\b|\bhow (do|can|to)\b.*\b(connect|link|add|install|use)\b|kaise (connect|link|"
              r"set|laga|kar)|settings?\b|سیٹ ?اپ|سیٹپ|کیسے (کنیکٹ|لنک)"),
    ("keeper", r"\bback ?up\b|\bbackup\b|\brestore\b|بیک ?اپ"),
    ("librarian", r"\bscan\b|\bscanning\b|refresh every|سکین|اسکین"),
    ("email", r"\be-?mails?\b|\binbox\b|\bdigest\b|\bmails?\b|ای ?میل|میل"),
    ("whatsapp", r"(whats ?app|واٹس ?ایپ).*\b(link|sync|check|import|new|naye|fetch|connect|linked|how much|kitn\w*|"
                 r"paid?|says?|written|likha)\b|\b(link|sync|check|import|connect|how much|kitn\w*|paid?|written|likha)\b"
                 r".*(whats ?app|واٹس ?ایپ)|\biphone\b"),
    ("accounts", r"\btotals?\b|\bkul\b|\bsum\b|\bhow much\b|\bkitn[aie]\b|\badd up\b|\bkitn[ie] sales\b|\btax\b|\blayout\b|\binvoice details\b|"
                 r"\bdetails of\b|کل رقم|ٹوٹل"),
    ("organizer", r"\bremind\w*\b|yaad dila|\bto-?dos?\b|\btasks?\b|\bnotes?\b|\bcalendar\b|\bmeetings?\b|"
                  r"\bschedule\b|\bappointments?\b|\bagenda\b|یاد دہانی|میٹنگ|نوٹ"),
    ("clerk", r"\b(delete|rename|move|copy|edit|write|create)\b.*\b(file|folder|document|pdf)\b"),
    ("finder", r"\b(find|search|look ?(up|for)|show|open|list|get|where|collect|gather|latest|oldest|dikha\w*|"
               r"nikal\w*|dh?oond\w*|dhund\w*|talash|khol\w*|kahan)\b|\b(invoices?|quotations?|quotes?|receipts?|"
               r"challans?|bills?|agreements?|contracts?|documents?|files?|photos?|pdfs?|raseed|parchi)\b|"
               r"whats ?app|فائل|انوائس|کوٹیشن|رسید|ڈھونڈ|دکھا|تلاش|کھول|واٹس ?ایپ"),
]
_RULES = [(a, re.compile(r, re.I)) for a, r in RULES]
STICKY_SECONDS = 180


def owned(agent: str) -> list[str]:
    a = AGENTS[agent]
    names = list(a["tools"])
    if a.get("prefix"):
        names += [n for n in REGISTRY if n.startswith(a["prefix"])]
    return names


def owner_of(tool_name: str) -> str | None:
    for name in AGENTS:
        if tool_name in owned(name):
            return name
    return None


def pick(text: str, last: tuple | None = None) -> str:
    """Which single agent takes this request."""
    for agent, rx in _RULES:
        if rx.search(text):
            return agent
    if last and time.time() - last[1] < STICKY_SECONDS and len(text.split()) <= 8 and last[0] != "jarvis":
        return last[0]  # "open the first one", "yes go ahead": the same agent carries on
    return "jarvis"


def tools_for(agent: str, enabled: list) -> list:
    mine = set(owned(agent))
    return [t for t in enabled if t["schema"]["name"] in mine]


def prompt_for(agent: str, enabled: list) -> str:
    if agent != "jarvis":
        return "\n" + AGENTS[agent]["prompt"] + (" If the request is not your job, say which agent it belongs to "
                                                  "in one short sentence instead of guessing.")
    have = {t["schema"]["name"] for t in enabled}
    lines = [f"- {n}: {a['job']}" for n, a in AGENTS.items()
             if n != "jarvis" and any(t in have for t in owned(n))]
    return ("\nYou are the coordinator. You do small talk, the time and remembering facts yourself. Anything else "
            "belongs to exactly one agent: hand it over with ask_agent and do not try to do it yourself.\n"
            "Agents:\n" + "\n".join(lines))


@tool("ask_agent", "Hand the owner's request to the one agent whose job it is. agent = one of: finder, accounts, "
                   "whatsapp, email, organizer, librarian, clerk, keeper, guide, operator.",
      {"agent": {"type": "string"}}, ["agent"])
def ask_agent(agent):
    return f"Handed to {agent}."  # the brain intercepts this call and switches agent


@tool("agents_status", "List Jarvis's agents: what each one does and what it is doing now.", {}, [])
def agents_status():
    from tools import CTX, _running
    cfg = CTX.get("cfg", {})
    notes = {}
    try:
        import deep_scan
        st = deep_scan._load()
        when = time.strftime("%d %b %H:%M", time.localtime(st["last_sync"])) if st.get("last_sync") else "never"
        allowed = {True: "allowed", False: "switched off", None: "waiting for permission"}[st.get("allowed")]
        notes["librarian"] = f"scan {allowed}, last {when}, every {st.get('hours', 12):g} h"
        notes["whatsapp"] = "linked" if deep_scan._wa_linked() else "not linked"
    except Exception:
        pass
    mail = (cfg.get("email") or {}).get("address")
    notes["email"] = f"connected as {mail}" if mail else "no email connected"
    notes["keeper"] = "daily backup on" if (cfg.get("backup") or {}).get("email") else "no backup email yet"
    busy = {"scan": "librarian", "whatsapp_link": "whatsapp", "whatsapp_sync": "whatsapp"}
    working = {busy[j] for j in _running if j in busy}
    rows = []
    for name, a in AGENTS.items():
        if name == "operator" and not owned(name):
            continue
        state = "WORKING NOW" if name in working else notes.get(name, "ready")
        rows.append(f"- {a['title']}: {a['job']} [{state}]")
    return "Jarvis's agents (one job each):\n" + "\n".join(rows)
