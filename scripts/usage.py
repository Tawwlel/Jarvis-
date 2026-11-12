"""Usage meter: how much of this month's AI budget has been used, 0-100%.

Every call to Claude is counted (tokens in/out) and priced; the owner sets a monthly budget in dollars. Jarvis warns at
80%, and at 100% stops using the online model until the budget is raised or the month turns (local answers and file
search keep working, since those cost nothing). Prices are per million tokens and can be overridden in config.json under
"usage": {"prices": {...}}. Numbers are estimates: the real bill is the Anthropic Console.
"""
import json
import threading
import time
from pathlib import Path

from tools import CTX, tool

DATA = Path(__file__).parent.parent / "data"
FILE = DATA / "usage.json"
DEFAULT_BUDGET = 5.0  # USD per month, until the owner changes it
# model family -> (input, output, cache-read) USD per million tokens, for prompts up to 100K tokens
PRICES = {"haiku": (0.10, 0.50, 0.01), "sonnet": (3.00, 15.00, 0.30), "opus": (15.00, 75.00, 1.50)}
OVER_100K = 5  # Haiku 5.5: every rate is multiplied by five for a prompt over 100K tokens
_lock = threading.Lock()
_warned: set = set()


def _month() -> str:
    return time.strftime("%Y-%m")


def _load() -> dict:
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        d = {}
    d.setdefault("budget", DEFAULT_BUDGET)
    if d.get("month") != _month():  # a new month starts from zero
        d.update(month=_month(), cost=0.0, input=0, output=0, calls=0, by_model={})
    return d


def _save(d: dict):
    DATA.mkdir(exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    tmp.replace(FILE)


def price_of(model: str, inp: int, out: int, cached: int = 0) -> float:
    over = {}
    try:
        over = (CTX.get("cfg", {}).get("usage") or {}).get("prices", {})
    except Exception:
        pass
    fam = next((f for f in ("haiku", "sonnet", "opus") if f in (model or "").lower()), "haiku")
    pi, po, pc = over.get(fam) or PRICES[fam]
    k = OVER_100K if (fam == "haiku" and inp + cached > 100_000) else 1
    return k * (max(inp - cached, 0) * pi + cached * pc + out * po) / 1_000_000


def record(model: str, inp: int, out: int, cached: int = 0):
    """Called after every Claude request."""
    with _lock:
        d = _load()
        c = price_of(model, inp, out, cached)
        d["cost"] += c
        d["input"] += inp
        d["output"] += out
        d["calls"] += 1
        m = d["by_model"].setdefault(model, {"calls": 0, "cost": 0.0})
        m["calls"] += 1
        m["cost"] += c
        _save(d)
        pct = percent(d)
    for lvl in (80, 100):
        if pct >= lvl and (d["month"], lvl) not in _warned:
            _warned.add((d["month"], lvl))
            note = CTX.get("notify")
            if note:
                note(f"Heads up: {lvl}% of this month's AI budget is used." if lvl == 80 else
                     "This month's AI budget is used up, so I'll answer only from your files until it's raised. "
                     "Say 'set my budget to 10 dollars' to continue.")


def percent(d: dict | None = None) -> float:
    d = d or _load()
    return min(100.0, round(100 * d["cost"] / d["budget"], 1)) if d["budget"] > 0 else 0.0


def blocked() -> bool:
    """True when the monthly budget is used up (the online model should not be called)."""
    try:
        return percent() >= 100 and _load()["budget"] > 0
    except Exception:
        return False


def snapshot() -> dict:
    d = _load()
    return {"percent": percent(d), "cost": round(d["cost"], 4), "budget": d["budget"], "calls": d["calls"],
            "input": d["input"], "output": d["output"], "month": d["month"]}


@tool("usage_status", "Show how much of this month's AI budget has been used (0-100%), the cost so far and the "
                      "number of requests.", {}, [])
def usage_status():
    s = snapshot()
    return (f"{s['percent']:.0f}% of this month's AI budget is used: about ${s['cost']:.2f} of ${s['budget']:.2f} "
            f"({s['calls']} requests). This is an estimate; the exact bill is in the Anthropic Console.")


@tool("usage_set_budget", "Set this month's and every month's AI budget in US dollars (e.g. 10). The owner asks for it.",
      {"dollars": {"type": "number"}}, ["dollars"])
def usage_set_budget(dollars):
    try:
        v = float(dollars)
    except (TypeError, ValueError):
        return "Tell me the budget as a number of dollars, for example 10."
    if not 0 < v <= 10000:
        return "That budget doesn't look right. Give me an amount between 1 and 10000 dollars."
    with _lock:
        d = _load()
        d["budget"] = v
        _save(d)
    _warned.clear()
    return f"Done. Your monthly AI budget is ${v:.2f}. You've used {percent():.0f}% so far."
