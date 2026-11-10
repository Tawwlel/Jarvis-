"""To-do list tools: "add a to-do to send the invoice", "what's on my list", "tick off the invoice"."""
import datetime as dt

from tools import CTX, tool


def _fmt_due(ts):
    return "" if not ts else " (due " + dt.datetime.fromtimestamp(ts).strftime("%a %d %b %H:%M") + ")"


@tool("todo_add", "Add an item to the user's to-do list. Optional due_iso like 2026-11-12T15:00.",
      {"text": {"type": "string"}, "due_iso": {"type": "string"}}, ["text"])
def todo_add(text, due_iso=None):
    due = dt.datetime.fromisoformat(due_iso).timestamp() if due_iso else None
    CTX["memory"].add_todo(text, due)
    return f"Added to your list: {text}"


@tool("todo_list", "Read the user's open to-do items.")
def todo_list():
    items = CTX["memory"].list_todos()
    return "\n".join(f"{t['id']}. {t['text']}{_fmt_due(t['due'])}" for t in items) or "Your list is empty."


@tool("todo_done", "Tick off a to-do by its number or part of its text.",
      {"item": {"type": "string"}}, ["item"])
def todo_done(item):
    done = CTX["memory"].complete_todo(item)
    return f"Done: {done}" if done else "I couldn't find that item."
