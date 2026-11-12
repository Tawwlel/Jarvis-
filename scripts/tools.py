"""
Tool registry. To add a capability: write a function, decorate it with @tool.
Only tools enabled in config.local.json are sent to the model, which keeps
token usage low (unused tools cost nothing).
"""
import datetime as dt

REGISTRY: dict = {}  # name -> {"schema": {...}, "fn": callable}


def tool(name: str, description: str, properties: dict | None = None, required: list | None = None):
    def deco(fn):
        REGISTRY[name] = {
            "schema": {
                "name": name,
                "description": description,
                "input_schema": {
                    "type": "object",
                    "properties": properties or {},
                    "required": required or [],
                },
            },
            "fn": fn,
        }
        return fn
    return deco


# ---- context injected by the brain so tools can reach memory ----
CTX: dict = {}


def notify(msg: str):
    """Say something in the chat window from a background job (set by the app; silent when there is none)."""
    print(f"[notify] {msg}"[:300])  # in jarvis.log too, so a scan's progress can be checked afterwards
    f = CTX.get("notify")
    if f:
        try:
            f(msg)
        except Exception as e:
            print("[notify]", e)


_running: set = set()


def background(label: str, fn, started: str):
    """Run a long job (WhatsApp link, big scans) in its own thread so the chat never sits on 'working'.
    The result is announced in the chat when it finishes. A thread marked .inline (the tray's own worker,
    tests) just runs it and returns the result."""
    import threading
    if getattr(threading.current_thread(), "inline", False):
        return fn()
    if label in _running:
        return "That is already running. I'll tell you as soon as it finishes."

    def run():
        try:
            msg = fn()
        except Exception as e:
            msg = f"That didn't finish: {e}"
        finally:
            _running.discard(label)
        notify(str(msg))
    _running.add(label)
    threading.Thread(target=run, daemon=True, name=label).start()
    return started


@tool("get_time", "Get the current local date and time.")
def get_time():
    return dt.datetime.now().strftime("%A %d %B %Y, %I:%M %p")


@tool(
    "set_reminder",
    "Set a reminder. Provide minutes from now and the reminder text.",
    {"minutes": {"type": "number"}, "text": {"type": "string"}},
    ["minutes", "text"],
)
def set_reminder(minutes, text):
    import time
    CTX["memory"].add_reminder(time.time() + float(minutes) * 60, text)
    return f"Reminder set for {minutes} minutes from now: {text}"


@tool(
    "remember_fact",
    "Store a long-term fact about the user or their work (name, preferences, project details).",
    {"key": {"type": "string"}, "value": {"type": "string"}},
    ["key", "value"],
)
def remember_fact(key, value):
    CTX["memory"].remember(key, value)
    return "Saved."


@tool(
    "show_visual",
    "Show a small on-screen visual explanation. kind: 'bar'|'line'|'definition'. "
    "For charts give labels and values; for definition give title and body.",
    {
        "kind": {"type": "string", "enum": ["bar", "line", "definition"]},
        "title": {"type": "string"},
        "labels": {"type": "array", "items": {"type": "string"}},
        "values": {"type": "array", "items": {"type": "number"}},
        "body": {"type": "string"},
    },
    ["kind", "title"],
)
def show_visual(kind, title, labels=None, values=None, body=None):
    import importlib.util
    if importlib.util.find_spec("webview") is None:  # never claim something was shown when it wasn't
        return "The on-screen visual window isn't installed on this computer, so explain it in words instead."
    from visual import show
    show(kind, title, labels, values, body)
    return "Displayed."


def enabled_tools(cfg: dict) -> list:
    """Each feature flag in config.local.json switches a group of tools on or off."""
    flags = cfg.get("tools_enabled", {})
    CTX["cfg"] = cfg
    if flags.get("computer_control"):
        import computer  # noqa: F401  (registers computer_* tools)
    if flags.get("calendar"):
        import jcalendar  # noqa: F401  (registers calendar_* tools)
    if flags.get("notes"):
        import notes  # noqa: F401  (registers note tools)
    if flags.get("todos", True):
        import todos  # noqa: F401  (registers todo_* tools)
    if flags.get("files", True):
        import files  # noqa: F401  (registers file_* tools)
    if flags.get("documents", True):
        import docsearch  # noqa: F401  (registers doc_* tools)
        import whatsapp_reader  # noqa: F401  (registers whatsapp_* tools)
        import whatsapp_agent  # noqa: F401  (registers the WhatsApp document agent's tools)
        import iphone_backup  # noqa: F401  (registers iphone_whatsapp_import)
        import invoice_fields  # noqa: F401  (invoice_totals, invoice_details, learn_invoice_layout)
    if flags.get("email", True):
        import email_agent  # noqa: F401  (registers email_* and add_to_calendar)
    import briefing  # noqa: F401  (registers update_settings)
    import backup  # noqa: F401  (registers backup_now)
    import setup_guide  # noqa: F401  (registers setup_help)
    import agents  # noqa: F401  (registers ask_agent, agents_status)
    import phone_bridge  # noqa: F401  (registers phone_pair, phone_status, phone_forget)
    import usage  # noqa: F401  (registers usage_status, usage_set_budget)
    if flags.get("documents", True):
        import deep_scan  # noqa: F401  (registers scan_* tools)
    groups = {
        "reminders": ["set_reminder"],
        "email": [n for n in REGISTRY if n.startswith("email_") or n == "add_to_calendar"],
        "visual_explainer": ["show_visual"],
        "computer_control": [n for n in REGISTRY if n.startswith("computer_")],
        "calendar": [n for n in REGISTRY if n.startswith("calendar_")],
        "notes": ["notes_search", "note_add"],
        "todos": [n for n in REGISTRY if n.startswith("todo_")],
        "files": [n for n in REGISTRY if n.startswith("file_")],
        "documents": [n for n in REGISTRY if n.startswith("doc_") or n.startswith("whatsapp_") or n.startswith("iphone_") or n.startswith("invoice_") or n == "learn_invoice_layout"],
    }
    names = {"get_time", "remember_fact", "update_settings", "backup_now", "setup_help", "ask_agent", "agents_status", "phone_pair", "phone_status", "phone_forget", "scan_everything", "scan_status", "scan_settings", "scan_add_folder"}
    default_on = {"todos", "files", "documents", "email", "reminders"}
    for flag, tnames in groups.items():
        if flags.get(flag, flag in default_on):
            names.update(tnames)
    return [REGISTRY[n] for n in sorted(names) if n in REGISTRY]


def run_tool(name: str, args: dict):
    """Returns a string, or a dict with image_b64 for screenshots."""
    try:
        result = REGISTRY[name]["fn"](**args)
        return result if isinstance(result, dict) else str(result)
    except Exception as e:  # report to the model, don't crash the loop
        return f"Tool error: {e}"
