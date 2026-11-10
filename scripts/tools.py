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
    if flags.get("email", True):
        import email_agent  # noqa: F401  (registers email_* and add_to_calendar)
    import briefing  # noqa: F401  (registers update_settings)
    groups = {
        "reminders": ["set_reminder"],
        "email": [n for n in REGISTRY if n.startswith("email_") or n == "add_to_calendar"],
        "visual_explainer": ["show_visual"],
        "computer_control": [n for n in REGISTRY if n.startswith("computer_")],
        "calendar": [n for n in REGISTRY if n.startswith("calendar_")],
        "notes": ["notes_search", "note_add"],
        "todos": [n for n in REGISTRY if n.startswith("todo_")],
        "files": [n for n in REGISTRY if n.startswith("file_")],
        "documents": [n for n in REGISTRY if n.startswith("doc_") or n.startswith("whatsapp_")],
    }
    names = {"get_time", "remember_fact", "update_settings"}
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
