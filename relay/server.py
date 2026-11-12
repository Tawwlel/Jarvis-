"""
Jarvis relay - the small server that lets a client's PHONE talk to their LAPTOP at home.

The laptop connects OUT to this server (so no router set-up is needed); the phone connects to it too, and the relay
passes messages between the two. Everything that matters is END-TO-END ENCRYPTED between phone and laptop with a key
the relay never sees (it travels in the QR code's '#' part, which browsers never send to a server). The relay only
ever handles ciphertext, pairing codes and hashed tokens, so it cannot read a client's questions, answers or files.

Run:   python relay/server.py --port 8080 --db relay.db        (put it behind HTTPS, e.g. Caddy - see relay/README.md)
"""
import argparse
import asyncio
import hashlib
import json
import secrets
import sqlite3
import time
from pathlib import Path

from aiohttp import WSMsgType, web

STATIC = Path(__file__).parent / "static"
MAX_FRAME = 1_000_000
CODE_TTL = 600
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


def h(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, secret_hash TEXT, created REAL, name TEXT);
            CREATE TABLE IF NOT EXISTS phones(id TEXT PRIMARY KEY, device TEXT, token_hash TEXT, name TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS codes(code TEXT PRIMARY KEY, device TEXT, expires REAL);
        """)

    def q(self, sql, *a):
        cur = self.db.execute(sql, a)
        self.db.commit()
        return cur


class Hub:
    """Who is connected right now."""

    def __init__(self):
        self.laptops: dict[str, web.WebSocketResponse] = {}
        self.phones: dict[str, tuple[str, web.WebSocketResponse]] = {}  # phone id -> (device, ws)
        self.hits: dict[str, list] = {}

    def limited(self, key: str, n: int, per: float) -> bool:
        now = time.time()
        xs = [t for t in self.hits.get(key, []) if now - t < per]
        xs.append(now)
        self.hits[key] = xs
        return len(xs) > n


def ip(req) -> str:
    return req.headers.get("X-Forwarded-For", req.remote or "?").split(",")[0].strip()


async def device_new(req):  # a laptop introduces itself once
    hub: Hub = req.app["hub"]
    if hub.limited("dev:" + ip(req), 10, 3600):
        return web.json_response({"error": "slow down"}, status=429)
    body = await req.json() if req.can_read_body else {}
    did, secret = secrets.token_urlsafe(9), secrets.token_urlsafe(32)
    req.app["store"].q("INSERT INTO devices VALUES(?,?,?,?)", did, h(secret), time.time(), str(body.get("name", ""))[:60])
    return web.json_response({"device": did, "secret": secret})


def auth_device(req) -> str | None:
    did = req.query.get("device") or req.headers.get("X-Device", "")
    secret = req.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    row = req.app["store"].q("SELECT secret_hash FROM devices WHERE id=?", did).fetchone()
    return did if row and secrets.compare_digest(row[0], h(secret)) else None


async def pair_start(req):  # laptop: make a one-time pairing code
    did = auth_device(req)
    if not did:
        return web.json_response({"error": "unauthorized"}, status=401)
    code = "".join(secrets.choice(ALPHABET) for _ in range(8))
    st = req.app["store"]
    st.q("DELETE FROM codes WHERE device=? OR expires<?", did, time.time())
    st.q("INSERT INTO codes VALUES(?,?,?)", code, did, time.time() + CODE_TTL)
    return web.json_response({"code": code, "expires_in": CODE_TTL})


async def pair_claim(req):  # phone: trade the code for a token (one use)
    hub: Hub = req.app["hub"]
    if hub.limited("claim:" + ip(req), 8, 600):
        return web.json_response({"error": "too many tries"}, status=429)
    body = await req.json()
    code = str(body.get("code", "")).upper().strip()
    st = req.app["store"]
    row = st.q("SELECT device, expires FROM codes WHERE code=?", code).fetchone()
    st.q("DELETE FROM codes WHERE code=?", code)  # one use, success or not
    if not row or row[1] < time.time():
        return web.json_response({"error": "That code is wrong or has expired."}, status=400)
    pid, token = secrets.token_urlsafe(9), secrets.token_urlsafe(32)
    name = str(body.get("name", "Phone"))[:40]
    st.q("INSERT INTO phones VALUES(?,?,?,?,?)", pid, row[0], h(token), name, time.time())
    lap = hub.laptops.get(row[0])
    if lap:
        await lap.send_json({"t": "paired", "p": pid, "name": name})
    return web.json_response({"token": token, "phone": pid, "device": row[0], "laptop_online": row[0] in hub.laptops})


async def ws_laptop(req):
    hub: Hub = req.app["hub"]
    did = auth_device(req)
    if not did:
        return web.Response(status=401)
    ws = web.WebSocketResponse(heartbeat=25, max_msg_size=MAX_FRAME)
    await ws.prepare(req)
    old = hub.laptops.get(did)
    if old is not None:
        await old.close()  # one laptop per identity: the newest connection wins
    hub.laptops[did] = ws
    for pid, (dev, pws) in list(hub.phones.items()):
        if dev == did:
            await pws.send_json({"t": "presence", "laptop": True})
    try:
        async for m in ws:
            if m.type != WSMsgType.TEXT:
                continue
            try:
                f = json.loads(m.data)
            except ValueError:
                continue
            if f.get("t") == "to_phone":
                tgt = hub.phones.get(f.get("p"))
                if tgt and tgt[0] == did:  # a laptop can only talk to ITS phones
                    await tgt[1].send_str(json.dumps({k: v for k, v in f.items() if k not in ("p", "t")} | {"t": "msg"}))
            elif f.get("t") == "revoke":
                pid = f.get("p")
                row = req.app["store"].q("SELECT device FROM phones WHERE id=?", pid).fetchone()
                if row and row[0] == did:
                    req.app["store"].q("DELETE FROM phones WHERE id=?", pid)
                    tgt = hub.phones.pop(pid, None)
                    if tgt:
                        await tgt[1].close()
    finally:
        if hub.laptops.get(did) is ws:
            hub.laptops.pop(did, None)
            for pid, (dev, pws) in list(hub.phones.items()):
                if dev == did:
                    try:
                        await pws.send_json({"t": "presence", "laptop": False})
                    except Exception:
                        pass
    return ws


async def ws_phone(req):
    hub: Hub = req.app["hub"]
    token = req.query.get("token", "")
    row = req.app["store"].q("SELECT id, device FROM phones WHERE token_hash=?", h(token)).fetchone()
    if not row:
        return web.Response(status=401)
    pid, did = row
    ws = web.WebSocketResponse(heartbeat=25, max_msg_size=MAX_FRAME)
    await ws.prepare(req)
    old = hub.phones.get(pid)
    if old:
        await old[1].close()
    hub.phones[pid] = (did, ws)
    await ws.send_json({"t": "presence", "laptop": did in hub.laptops})
    try:
        async for m in ws:
            if m.type != WSMsgType.TEXT:
                continue
            lap = hub.laptops.get(did)
            if lap is None:
                await ws.send_json({"t": "presence", "laptop": False})
                continue
            if hub.limited("msg:" + pid, 120, 60):
                await ws.send_json({"t": "error", "error": "slow down"})
                continue
            try:
                f = json.loads(m.data)
            except ValueError:
                continue
            f.pop("p", None)
            await lap.send_str(json.dumps(f | {"t": "from_phone", "p": pid}))
    finally:
        if hub.phones.get(pid, (None, None))[1] is ws:
            hub.phones.pop(pid, None)
    return ws


async def health(req):
    return web.json_response({"ok": True, "laptops": len(req.app["hub"].laptops), "phones": len(req.app["hub"].phones)})


async def index(req):
    return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


def make_app(db: str = ":memory:") -> web.Application:
    app = web.Application(client_max_size=64_000)
    app["store"], app["hub"] = Store(db), Hub()
    app.add_routes([
        web.post("/api/device", device_new), web.post("/api/pair/start", pair_start),
        web.post("/api/pair/claim", pair_claim), web.get("/ws/laptop", ws_laptop),
        web.get("/ws/phone", ws_phone), web.get("/health", health), web.get("/", index),
        web.static("/", STATIC, show_index=False)])
    return app


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--db", default="relay.db")
    a = ap.parse_args()
    web.run_app(make_app(a.db), host=a.host, port=a.port)
