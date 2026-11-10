"""
Daily brief: today's meetings, what to prepare (from earlier notes on the same
meetings), yesterday's summaries and today's reminders - written as a short
spoken message. One cheap Haiku call, and none at all on an empty day.
"""
import datetime as dt

import tools


def gather(mem, cfg: dict) -> dict:
    now = dt.datetime.now()
    out = {"meetings": [], "prep": [], "reminders": mem.reminders_today(),
           "yesterday": [f"{m}: {t}" for m, t in mem.recent_summaries(2)],
           "todos": [t["text"] for t in mem.list_todos()][:10],
           "working_on": mem.get_fact("currently_working_on")}
    if cfg.get("tools_enabled", {}).get("calendar"):
        import jcalendar

        start = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        for ev in jcalendar.events_between(start, start + dt.timedelta(days=1)):
            when = "all day" if ev["all_day"] else ev["start"].strftime("%I:%M %p").lstrip("0")
            out["meetings"].append(f"{when} - {ev['title']}")
            last = mem.last_summary(ev["title"])
            if last:
                out["prep"].append(f"Last time in '{ev['title']}': {last}")
    return out


def generate(brain, cfg: dict) -> str:
    name = cfg.get("owner_name") or "there"
    parts = gather(brain.mem, cfg)
    if not (parts["meetings"] or parts["reminders"] or parts["yesterday"] or parts["todos"]):
        return f"Good morning {name}. Your calendar and reminders are clear today."
    raw = "\n".join(f"{k.upper()}:\n" + ("\n".join(v) if isinstance(v, list) else str(v or "-"))
                    for k, v in parts.items())
    return brain.ask(
        f"You are {brain.assistant_name}, a personal assistant giving {name} a spoken "
        "morning brief. Plain sentences only, no markdown or lists, because it is read "
        "aloud. Under 130 words. Start with a short greeting, give today's meetings in "
        "time order, then what to prepare (use PREP and YESTERDAY, mention open action "
        "items and open to-dos), then reminders. Do not invent anything.", raw, 400)


# ---- settings Jarvis may change by voice ("brief me at 7:30") ----
@tools.tool(
    "update_settings",
    "Change an assistant setting. briefing_time is 24h 'HH:MM'; briefing_enabled true/false; "
    "assistant_names is the list of names the user can call the assistant (e.g. ['Jarvis','Friday']).",
    {"briefing_time": {"type": "string"}, "briefing_enabled": {"type": "boolean"},
     "assistant_names": {"type": "array", "items": {"type": "string"}},
     "meeting_reminder_minutes": {"type": "integer"}})
def update_settings(briefing_time=None, briefing_enabled=None, assistant_names=None,
                    meeting_reminder_minutes=None):
    cfg = tools.CTX["cfg"]
    changed = []
    if briefing_time is not None:
        dt.datetime.strptime(briefing_time, "%H:%M")  # raises on bad input
        cfg["briefing_time"] = briefing_time
        changed.append(f"daily brief at {briefing_time}")
    if briefing_enabled is not None:
        cfg["briefing_enabled"] = bool(briefing_enabled)
        changed.append("daily brief " + ("on" if briefing_enabled else "off"))
    if assistant_names:
        cfg["assistant_names"] = [str(n).strip() for n in assistant_names if str(n).strip()][:6]
        changed.append("names: " + ", ".join(cfg["assistant_names"]))
    if meeting_reminder_minutes is not None:
        cfg["meeting_reminder_minutes"] = max(1, int(meeting_reminder_minutes))
        changed.append(f"meeting reminders {cfg['meeting_reminder_minutes']} minutes ahead")
    if not changed:
        return "Nothing to change."
    from config import save_config

    save_config(cfg)
    return "Updated: " + "; ".join(changed)
