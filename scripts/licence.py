"""Licence + check-in with the Apricot Digital portal (apricotdigital.xyz/jarvis/admin).

What goes out: the licence key, the app version, the usage percentage, a one-way hash of this computer and the ids of
top-up codes already applied. NEVER documents, chats, file names or questions.
What comes back: active / trial / suspended / expired / unknown, signed with Apricot Digital's key (same key as the
top-up codes), so a fake server cannot pause or un-pause anyone. A paused or expired licence stops the ONLINE assistant
(files still open and search still works locally). No key set = nothing is reported and nothing is blocked.
If the portal cannot be reached, Jarvis keeps working with the last answer it verified."""
import base64, hashlib, json, platform, time, urllib.request, uuid
from pathlib import Path
from tools import tool, CTX

DATA = Path(__file__).parent.parent / "data"
FILE = DATA / "licence.json"
URL = "https://apricotdigital.xyz/jarvis/admin/api/check"
STOP = ("suspended", "expired")


def _load() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d: dict):
    DATA.mkdir(exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    tmp.replace(FILE)


def key() -> str:
    return (_load().get("key") or "").strip().upper()


def set_key(k: str) -> str:
    k = (k or "").strip().upper()
    import re
    if not re.fullmatch(r"JRV-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}", k):
        return "That doesn't look like a licence key. It looks like JRV-XXXX-XXXX-XXXX."
    d = _load()
    d.update(key=k, status="", checked=0)
    _save(d)
    return "Licence key saved."


def _machine() -> str:
    return hashlib.sha256(f"{platform.node()}|{uuid.getnode()}".encode()).hexdigest()[:32]


def _version() -> str:
    try:
        import updater
        return (updater.current() or "dev")[:12]
    except Exception:
        return "dev"


def _verify(k: str, status: str, ts: int, sig: str) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    import usage
    b64 = lambda x: base64.urlsafe_b64decode(x + "=" * (-len(x) % 4))
    try:
        Ed25519PublicKey.from_public_bytes(b64(usage._PUBLIC_KEY)).verify(b64(sig), f"licence|{k}|{status}|{ts}".encode())
    except (InvalidSignature, ValueError, TypeError):
        return False
    return abs(time.time() - ts) < 86400  # an old "active" answer cannot be replayed


def check(url: str = "") -> str:
    """Report in and learn the licence state. Returns the status ('' when nothing was checked)."""
    k = key()
    if not k:
        return ""
    import usage
    d = _load()
    body = json.dumps({"key": k, "version": _version(), "usage_pct": usage.percent(), "machine": _machine(),
                       "used_codes": list(usage._load().get("used_codes", []))[-50:]}).encode()
    url = url or (CTX.get("cfg", {}).get("licence") or {}).get("url") or URL
    try:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "Jarvis"})
        with urllib.request.urlopen(req, timeout=20) as r:
            ans = json.loads(r.read(20000))
    except Exception as e:
        print("[licence] could not reach the portal:", type(e).__name__)
        return d.get("status", "")
    if not (ans.get("ok") and _verify(k, str(ans.get("status", "")), int(ans.get("ts", 0)), str(ans.get("sig", "")))):
        print("[licence] the answer was not signed by Apricot Digital; ignored")
        return d.get("status", "")
    d.update(status=ans["status"], message=ans.get("message", ""), checked=int(time.time()),
             latest=(ans.get("latest") or {}).get("version", ""))
    _save(d)
    return d["status"]


def blocked() -> bool:
    """True when Apricot Digital has paused or ended this licence."""
    return _load().get("status") in STOP


def message() -> str:
    return _load().get("message") or "This licence is not active. Please contact Apricot Digital."


@tool("licence_set_key", "Save the licence key Apricot Digital gave the client (looks like JRV-XXXX-XXXX-XXXX).",
      {"key": {"type": "string"}}, ["key"])
def licence_set_key(key):
    msg = set_key(key)
    if msg.startswith("Licence key saved"):
        st = check()
        if st in STOP:
            return msg + " " + message()
        if st == "unknown":
            return msg + " But Apricot Digital doesn't recognise this key. Please check it."
        if st:
            return msg + f" Licence is {st}."
    return msg


@tool("licence_status", "Say whether this Jarvis's licence is active.", {}, [])
def licence_status():
    d = _load()
    if not d.get("key"):
        return "No licence key is set on this Jarvis."
    return f"Licence {d.get('status') or 'not checked yet'}" + (f" (last checked {time.strftime('%d %b %H:%M', time.localtime(d['checked']))})" if d.get("checked") else "") + "."
