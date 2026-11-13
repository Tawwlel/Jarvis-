"""Usage meter: how much of this month's AI budget has been used, 0-100%.

Every call to Claude is counted (tokens in/out) and priced; the owner sets a monthly budget in dollars. Jarvis warns at
80%, and at 100% stops using the online model until the budget is raised or the month turns (local answers and file
search keep working, since those cost nothing). Prices are per million tokens and can be overridden in config.json under
"usage": {"prices": {...}}. Counts come from the token numbers the service reports for every request.
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
                note(f"Heads up: usage is at {lvl} out of 100 this month." if lvl == 80 else
                     "This month's usage has reached 100 out of 100, so I'll answer only from your files until it's raised. "
                     "Ask Apricot Digital for a top-up code to continue.")


def percent(d: dict | None = None) -> float:
    d = d or _load()
    return min(100.0, round(100 * d["cost"] / d["budget"], 1)) if d["budget"] > 0 else 0.0


def label(p: float) -> str:
    """'0.4' for small values (so the first requests show up), '12' above 10."""
    return f"{p:.1f}".rstrip("0").rstrip(".") if 0 < p < 10 else f"{p:.0f}"


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


@tool("usage_status", "Show how much of this month's usage allowance has been used, out of 100.", {}, [])
def usage_status():
    s = snapshot()
    return (f"Usage this month: {label(s['percent'])} out of 100 ({s['calls']} requests). "
            "It starts again from zero each month.")


# Only Apricot Digital can raise the allowance: top-up codes are signed with a private key that never leaves the owner.
# The public key below can check a code but cannot make one.
_PUBLIC_KEY = "r1mc9K7igtaaT8dvwvTrsjlVX-P0u8kAN_lur6hsVJA="


def _set_budget(v: float):
    with _lock:
        d = _load()
        d["budget"] = float(v)
        _save(d)
    _warned.clear()


def redeem(code: str) -> str:
    import base64
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    b64 = lambda x: base64.urlsafe_b64decode(x + "=" * (-len(x) % 4))
    try:
        body, sig = (code or "").strip().removeprefix("JV-").split(".")
        Ed25519PublicKey.from_public_bytes(b64(_PUBLIC_KEY)).verify(b64(sig), b64(body))
        info = json.loads(b64(body))
        amount, cid = float(info["a"]), str(info["id"])
    except (InvalidSignature, ValueError, KeyError, TypeError):
        return "That code isn't valid. Please check it, or ask Apricot Digital for a new one."
    with _lock:
        d = _load()
        if cid in d.setdefault("used_codes", []):
            return "That code has already been used."
        d["used_codes"].append(cid)
        d["budget"] = amount
        _save(d)
    _warned.clear()
    return f"Done. Your monthly usage allowance is increased. You've used {label(percent())} out of 100 so far."


@tool("usage_redeem_code", "Apply a usage top-up code that Apricot Digital gave the client (starts with JV-).",
      {"code": {"type": "string"}}, ["code"])
def usage_redeem_code(code):
    return redeem(code)
