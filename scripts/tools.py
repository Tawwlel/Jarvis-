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
    flags = cfg.get("tools_enabled", {})
    always = {"get_time", "remember_fact"}
    mapping = {"reminders": "set_reminder", "visual_explainer": "show_visual"}
    names = set(always)
    for flag, tname in mapping.items():
        if flags.get(flag):
            names.add(tname)
    return [REGISTRY[n] for n in names if n in REGISTRY]


def run_tool(name: str, args: dict) -> str:
    try:
        return str(REGISTRY[name]["fn"](**args))
    except Exception as e:  # report to the model, don't crash the loop
        return f"Tool error: {e}"
