"""
Phone link: the client talks to Jarvis from a PHONE; this laptop stays at home, plugged in, as the server.

The laptop connects OUT to the Apricot relay (relay/server.py). The phone opens a web page (an installable app) and
talks to the same relay. Everything between phone and laptop is END-TO-END ENCRYPTED (AES-256-GCM) with a key that
lives only on the laptop and in the phone's browser - it travels inside the pairing QR code's '#' part, which is
never sent to any server - so the relay cannot read questions, answers or documents.

What a phone may do: ask Jarvis questions (read-only agents only), see and open the documents an answer is about,
read recent chat. What it may NOT do: change or delete files, run backups, link accounts, change settings, or open
anything on the laptop. Files are sent only if they are in Jarvis's own index (never an arbitrary path).
"""
import asyncio
import base64
import hashlib
import json
import mimetypes
import secrets
import threading
import time
from pathlib import Path

from tools import CTX, tool

ROOT = Path(__file__).parent.parent
STATE = ROOT / "phone.json"
CHUNK = 190_000          # bytes of file per encrypted frame (stays well under the relay's 1 MB frame limit)
MAX_FILE = 40_000_000
MAX_AGE = 600            # a request older than 10 minutes is ignored (replay protection)
# Tools a phone can never use, even if the model asks: everything that changes, opens, links, saves or configures.
PHONE_DENY = {"file_open", "file_write", "file_edit", "file_move", "file_delete", "backup_now", "whatsapp_link",
              "whatsapp_sync", "iphone_whatsapp_import", "scan_everything", "scan_add_folder", "scan_settings",
              "update_settings", "learn_invoice_layout", "doc_collect", "email_settings", "add_to_calendar",
              "show_visual", "phone_pair", "phone_forget"}


def b64e(b: bytes) -> str:
    return base64.b64encode(b).decode()


def b64d(s: str) -> bytes:
    return base64.b64decode(s)


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


# ---------------- state ----------------
def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"relay": "", "device": "", "phones": []}


def _save(st: dict):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st), encoding="utf-8")
    tmp.replace(STATE)


def _secrets():
    from secrets_store import default_store
    return default_store()


def relay_url(cfg: dict | None = None) -> str:
    cfg = cfg or CTX.get("cfg", {})
    return (_load().get("relay") or (cfg.get("phone") or {}).get("relay_url") or "").rstrip("/")


def paired_phones() -> list[dict]:
    return _load().get("phones", [])


class Box:
    """AES-256-GCM with the shared key. Direction goes into the authenticated data, so a message can't be bounced back."""

    def __init__(self, key: bytes):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        self.g = AESGCM(key)

    def seal(self, obj: dict, direction: str) -> dict:
        n = secrets.token_bytes(12)
        return {"n": b64e(n), "c": b64e(self.g.encrypt(n, json.dumps(obj).encode(), direction.encode()))}

    def open(self, frame: dict, direction: str) -> dict:
        return json.loads(self.g.decrypt(b64d(frame["n"]), b64d(frame["c"]), direction.encode()))


def key_bytes() -> bytes:
    st = _secrets()
    k = st.get("phone_key")
    if not k:
        k = b64e(secrets.token_bytes(32))
        st.set("phone_key", k)
    return b64d(k)


def _http(method: str, url: str, **kw):
    import requests
    return requests.request(method, url, timeout=20, **kw)


def ensure_device(relay: str) -> tuple[str, str]:
    st = _load()
    sec = _secrets().get("phone_secret")
    if st.get("device") and sec and st.get("relay") == relay:
        return st["device"], sec
    r = _http("POST", f"{relay}/api/device", json={"name": CTX.get("cfg", {}).get("owner_name", "")})
    r.raise_for_status()
    d = r.json()
    _secrets().set("phone_secret", d["secret"])
    st.update(relay=relay, device=d["device"], phones=[])
    _save(st)
    return d["device"], d["secret"]


def start_pairing(cfg: dict | None = None) -> dict:
    """A one-time code and the link/QR text for the phone."""
    relay = relay_url(cfg)
    if not relay:
        raise RuntimeError("The phone link isn't set up on this copy of Jarvis yet. Ask Apricot Digital.")
    dev, sec = ensure_device(relay)
    r = _http("POST", f"{relay}/api/pair/start?device={dev}", headers={"Authorization": f"Bearer {sec}"})
    r.raise_for_status()
    code = r.json()["code"]
    link = f"{relay}/#c={code}&k={b64url(key_bytes())}"
    return {"code": code, "link": link, "expires_in": r.json()["expires_in"]}


# ---------------- the agent ----------------
class PhoneAgent(threading.Thread):
    """Keeps the laptop's connection to the relay open and answers the phone. ask_fn(text) -> {"text", "files"}."""

    def __init__(self, cfg: dict, ask_fn, notify=None):
        super().__init__(daemon=True, name="phone-agent")
        self.cfg, self.ask_fn, self.notify = cfg, ask_fn, notify
        self.connected = False
        self.seen: list[str] = []
        self.fileids: dict[str, str] = {}
        self._stop = threading.Event()
        self._wake = threading.Event()

    def poke(self):
        self._wake.set()

    def run(self):
        asyncio.run(self.main())

    async def main(self):
        backoff = 2
        while not self._stop.is_set():
            relay = relay_url(self.cfg)
            st = _load()
            sec = _secrets().get("phone_secret")
            if not (relay and st.get("device") and sec):
                self._wake.wait(30)  # not paired yet: look again later (or when poked)
                self._wake.clear()
                continue
            try:
                await self.session(relay, st["device"], sec)
                backoff = 2
            except Exception as e:
                print("[phone] connection:", type(e).__name__, e)
            self.connected = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def session(self, relay: str, device: str, secret: str):
        import aiohttp
        url = relay.replace("https://", "wss://").replace("http://", "ws://") + f"/ws/laptop?device={device}"
        box = Box(key_bytes())
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(url, headers={"Authorization": f"Bearer {secret}"}, heartbeat=25,
                                    max_msg_size=1_000_000) as ws:
                self.connected = True
                print("[phone] connected to the relay")
                self.ws, self.loop = ws, asyncio.get_running_loop()
                async for m in ws:
                    if m.type != aiohttp.WSMsgType.TEXT:
                        continue
                    f = json.loads(m.data)
                    if f.get("t") == "paired":
                        st = _load()
                        st["phones"] = [p for p in st.get("phones", []) if p["id"] != f["p"]] + [
                            {"id": f["p"], "name": f.get("name", "Phone"), "created": time.time()}]
                        _save(st)
                        if self.notify:
                            self.notify(f"A phone was connected: {f.get('name', 'Phone')}.")
                    elif f.get("t") == "from_phone":
                        asyncio.create_task(self.handle(box, f))

    async def send(self, box: Box, pid: str, obj: dict):
        await self.ws.send_str(json.dumps({"t": "to_phone", "p": pid} | box.seal(obj, "l2p")))

    async def handle(self, box: Box, f: dict):
        pid = f.get("p")
        try:
            msg = box.open(f, "p2l")
        except Exception:
            return  # not encrypted with our key (or tampered): ignore silently
        mid, kind = str(msg.get("id", "")), msg.get("kind")
        if not mid or mid in self.seen or abs(time.time() - float(msg.get("ts", 0))) > MAX_AGE:
            return  # replayed or stale
        self.seen = (self.seen + [mid])[-500:]
        try:
            if kind == "ask":
                await self.send(box, pid, {"kind": "working", "id": mid})
                r = await asyncio.get_running_loop().run_in_executor(None, self.ask_fn, str(msg.get("text", ""))[:2000])
                files = [self._card(i) for i in r.get("files", [])]
                await self.send(box, pid, {"kind": "reply", "id": mid, "text": r.get("text", ""), "files": files,
                                           "ts": time.time()})
            elif kind == "file":
                await self.send_file(box, pid, mid, str(msg.get("fid", "")))
            elif kind == "history":
                mem = CTX.get("memory")
                items = [{"ts": t, "role": ro, "text": tx} for t, ro, tx in (mem.chat_recent(40) if mem else [])]
                await self.send(box, pid, {"kind": "history", "id": mid, "items": items})
            elif kind == "ping":
                await self.send(box, pid, {"kind": "pong", "id": mid})
        except Exception as e:
            print("[phone] handle:", e)
            try:
                await self.send(box, pid, {"kind": "error", "id": mid, "text": "Sorry, something went wrong on the laptop."})
            except Exception:
                pass

    def _card(self, it: dict) -> dict:
        fid = hashlib.sha1(it["path"].encode()).hexdigest()[:16]
        self.fileids[fid] = it["path"]
        try:
            size = Path(it["path"]).stat().st_size
        except OSError:
            size = 0
        return {"fid": fid, "name": it.get("name", ""), "type": it.get("type", ""), "amount": it.get("amount"),
                "date": it.get("date"), "chat": it.get("chat", ""), "size": size,
                "mime": mimetypes.guess_type(it["path"])[0] or "application/octet-stream"}

    def _resolve(self, fid: str) -> Path | None:
        """A file id -> a path, but ONLY a file Jarvis has indexed (never an arbitrary path from the phone)."""
        path = self.fileids.get(fid)
        import docsearch
        db = docsearch._db()
        try:
            if path:
                ok = db.execute("SELECT 1 FROM docs WHERE path=?", (path,)).fetchone()
                return Path(path) if ok else None
            for (p,) in db.execute("SELECT path FROM docs"):
                if hashlib.sha1(p.encode()).hexdigest()[:16] == fid:
                    return Path(p)
        finally:
            db.close()
        return None

    async def send_file(self, box: Box, pid: str, mid: str, fid: str):
        p = self._resolve(fid)
        if not p or not p.is_file():
            return await self.send(box, pid, {"kind": "error", "id": mid, "text": "That file isn't available any more."})
        size = p.stat().st_size
        if size > MAX_FILE:
            return await self.send(box, pid, {"kind": "error", "id": mid, "text": "That file is too big to send to the phone."})
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        i = 0
        with open(p, "rb") as fh:
            while True:
                data = fh.read(CHUNK)
                last = len(data) < CHUNK or fh.tell() >= size
                await self.send(box, pid, {"kind": "chunk", "id": mid, "i": i, "last": last, "name": p.name,
                                           "mime": mime, "size": size, "data": b64e(data)})
                i += 1
                if last:
                    break
                await asyncio.sleep(0)

    def revoke(self, pid: str):
        st = _load()
        st["phones"] = [p for p in st.get("phones", []) if p["id"] != pid]
        _save(st)
        if self.connected:
            asyncio.run_coroutine_threadsafe(self.ws.send_str(json.dumps({"t": "revoke", "p": pid})), self.loop)


AGENT: PhoneAgent | None = None


@tool("phone_pair", "Show the code and link that connects a new phone to Jarvis (the owner scans it with the phone's "
                    "camera). Only when the owner asks to connect a phone.", {}, [])
def phone_pair():
    try:
        d = start_pairing()
    except Exception as e:
        return f"I couldn't start the phone link: {e}"
    if AGENT:
        AGENT.poke()
    return (f"On your phone, open this link: {d['link']}\n(or open {relay_url()} and type the code {d['code']}). "
            f"It works for {d['expires_in'] // 60} minutes. Keep this laptop switched on, plugged in and on Wi-Fi.")


@tool("phone_status", "Say whether the phone link is on, and which phones are connected.", {}, [])
def phone_status():
    ph = paired_phones()
    on = bool(AGENT and AGENT.connected)
    return (f"Phone link: {'online' if on else 'offline'}. Phones: " + (", ".join(p["name"] for p in ph) or "none") + ".")


@tool("phone_forget", "Disconnect a phone (by name) so it can no longer reach Jarvis.", {"name": {"type": "string"}},
      ["name"])
def phone_forget(name):
    hit = [p for p in paired_phones() if name.lower() in p["name"].lower()]
    if not hit:
        return "I don't see a phone with that name."
    for p in hit:
        if AGENT:
            AGENT.revoke(p["id"])
        else:
            st = _load()
            st["phones"] = [x for x in st["phones"] if x["id"] != p["id"]]
            _save(st)
    return "Disconnected: " + ", ".join(p["name"] for p in hit) + "."
