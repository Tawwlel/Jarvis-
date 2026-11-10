"""
Calendar tools.

Read: any calendar that can publish a private iCal (.ics) link works - Google
Calendar ("Secret address in iCal format"), Outlook/Microsoft 365 ("Publish
calendar"), Apple, etc. No OAuth or passwords. Set integrations.calendar_ics_url
in config.local.json (an https URL or a local .ics file path).

Write: events Jarvis adds are stored locally (calendar_local.json) and merged into
the agenda. Writing back to Google/Outlook needs OAuth and is a later step.
"""
import datetime as dt
import json
import time
import urllib.request
from pathlib import Path

from tools import CTX, tool

LOCAL = Path(__file__).parent.parent / "calendar_local.json"
_cache = {"t": 0.0, "text": ""}


def _cfg():
    return CTX.get("cfg", {})


def _local_tz():
    return dt.datetime.now().astimezone().tzinfo


def _ics_text() -> str:
    src = _cfg().get("integrations", {}).get("calendar_ics_url")
    if not src:
        return ""
    if time.time() - _cache["t"] < 300 and _cache["text"]:
        return _cache["text"]
    if src.startswith("http"):
        with urllib.request.urlopen(src, timeout=20) as r:
            text = r.read().decode("utf-8", "replace")
    else:
        text = Path(src).read_text(encoding="utf-8")
    _cache.update(t=time.time(), text=text)
    return text


def _norm(d) -> dt.datetime:
    if isinstance(d, dt.datetime):
        return d.astimezone(_local_tz()) if d.tzinfo else d.replace(tzinfo=_local_tz())
    return dt.datetime.combine(d, dt.time.min, tzinfo=_local_tz())  # all-day


def events_between(start: dt.datetime, end: dt.datetime) -> list[dict]:
    out = []
    text = _ics_text()
    if text:
        import icalendar
        import recurring_ical_events

        cal = icalendar.Calendar.from_ical(text)
        for ev in recurring_ical_events.of(cal).between(start, end):
            s = _norm(ev["DTSTART"].dt)
            e = _norm(ev["DTEND"].dt) if "DTEND" in ev else s
            out.append({"title": str(ev.get("SUMMARY", "(no title)")), "start": s, "end": e,
                        "all_day": not isinstance(ev["DTSTART"].dt, dt.datetime)})
    if LOCAL.exists():
        for ev in json.loads(LOCAL.read_text(encoding="utf-8")):
            s = dt.datetime.fromisoformat(ev["start"])
            s = s if s.tzinfo else s.replace(tzinfo=_local_tz())
            if start <= s <= end:
                out.append({"title": ev["title"], "start": s,
                            "end": s + dt.timedelta(minutes=ev.get("minutes", 30)), "all_day": False})
    return sorted(out, key=lambda e: e["start"])


def _fmt(ev) -> str:
    when = "all day" if ev["all_day"] else ev["start"].strftime("%I:%M %p").lstrip("0")
    return f"{ev['start'].strftime('%a %d %b')} {when} - {ev['title']}"


@tool("calendar_agenda", "List calendar events for the next N days (default 1 = today and tomorrow "
      "morning). Use for 'what's on my calendar', meeting prep, and daily briefings.",
      {"days": {"type": "integer"}})
def calendar_agenda(days=1):
    now = dt.datetime.now(_local_tz())
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    evs = events_between(start, start + dt.timedelta(days=max(1, int(days))))
    return "\n".join(_fmt(e) for e in evs) or "No events."


@tool("calendar_add", "Add an event to the local calendar. start_iso like 2026-11-12T15:00.",
      {"title": {"type": "string"}, "start_iso": {"type": "string"}, "minutes": {"type": "integer"}},
      ["title", "start_iso"])
def calendar_add(title, start_iso, minutes=30):
    dt.datetime.fromisoformat(start_iso)  # validate
    items = json.loads(LOCAL.read_text(encoding="utf-8")) if LOCAL.exists() else []
    items.append({"title": title, "start": start_iso, "minutes": minutes})
    LOCAL.write_text(json.dumps(items, indent=1), encoding="utf-8")
    return f"Added '{title}' at {start_iso}."


def starting_now(window_seconds: int = 90) -> list[dict]:
    """Meetings that began within the last window (or start in the next 30s)."""
    now = dt.datetime.now(_local_tz())
    lo, hi = now - dt.timedelta(seconds=window_seconds), now + dt.timedelta(seconds=30)
    return [e for e in events_between(lo, hi) if not e["all_day"] and lo <= e["start"] <= hi]


def upcoming_within(minutes: int) -> list[dict]:
    """Used by the background scheduler for meeting reminders."""
    now = dt.datetime.now(_local_tz())
    return [e for e in events_between(now, now + dt.timedelta(minutes=minutes)) if not e["all_day"]]
