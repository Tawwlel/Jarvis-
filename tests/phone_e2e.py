"""End-to-end: relay + laptop PhoneAgent + a real browser (Playwright) doing WebCrypto. Relay must only see ciphertext."""
import asyncio, json, sys, tempfile, threading, time, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts")); sys.path.insert(0, str(Path(__file__).parent.parent / "relay"))
from aiohttp import web
import server, phone_bridge as pb
from tools import CTX

tmp = Path(tempfile.mkdtemp()); pb.STATE = tmp / "phone.json"
class Mem:
    d = {}
    def get(s, k): return s.d.get(k)
    def set(s, k, v): s.d[k] = v
sec = Mem(); pb._secrets = lambda: sec
sec.get = lambda k: sec.d.get(k); sec.set = lambda k, v: sec.d.__setitem__(k, v)
doc = tmp / "invoice1.txt"; doc.write_text("INVOICE 100 " * 30000)  # ~360 KB => several chunks
secret_text = "SECRETQUESTION-Zebra"
seen_by_relay = []
orig = server.ws_phone
ok = fail = 0
def check(n, c):
    global ok, fail
    if c: ok += 1
    else: fail += 1; print("FAIL", n)

def ask_fn(t):
    return {"text": "Found it for: " + t, "files": [{"path": str(doc), "name": "invoice1.txt", "type": "invoice", "amount": "100", "date": "2026-01-01", "chat": ""}]}

class FakeDB:
    def execute(s, q, a=()): return type("C", (), {"fetchone": lambda s2: (1,), "__iter__": lambda s2: iter([])})()
    def close(s): pass
import docsearch; docsearch._db = lambda: FakeDB()

def run_relay(port, ready):
    async def go():
        app = server.make_app()
        r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", port).start(); ready.set()
        await asyncio.sleep(120)
    asyncio.run(go())

port = 18765; ready = threading.Event()
threading.Thread(target=run_relay, args=(port, ready), daemon=True).start(); ready.wait()
relay = f"http://127.0.0.1:{port}"
CTX["cfg"] = {"phone": {"relay_url": relay}}
d = pb.start_pairing(CTX["cfg"])
check("link has key not sent to server", "#c=" in d["link"] and "&k=" in d["link"])
agent = pb.PhoneAgent(CTX["cfg"], ask_fn); agent.start()
for _ in range(50):
    if agent.connected: break
    time.sleep(.2)
check("laptop connected", agent.connected)

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(); ctx = b.new_context(accept_downloads=True); pg = ctx.new_page()
    reqs = []
    pg.on("request", lambda r: reqs.append((r.url, r.post_data or "")))
    pg.on("websocket", lambda w: w.on("framesent", lambda f: reqs.append(("ws", str(f)))))
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(d["link"]); pg.wait_for_selector("text=your laptop is online", timeout=15000)
    check("paired + online", True)
    check("key never in any request", all(re.search(r"k=", u) is None or "#" in u for u, _ in reqs) and not any(d["link"].split("k=")[1] in (u + pd) for u, pd in reqs))
    pg.fill("#msg", secret_text); pg.click("#send")
    pg.wait_for_selector("text=Found it for: " + secret_text, timeout=15000); check("reply decrypted", True)
    check("plaintext never on the wire", not any(secret_text in pd for _, pd in reqs))
    pg.click("text=OPEN"); pg.wait_for_selector(".sheet.show", timeout=15000)
    pg.wait_for_function("document.querySelector('#sbody iframe')", timeout=15000)
    size = pg.evaluate("fetch(document.querySelector('#sbody iframe').src).then(r=>r.blob()).then(b=>b.size)")
    check("file reassembled exactly", size == doc.stat().st_size)
    # reload: should stay paired
    pg.reload(); pg.wait_for_selector("text=your laptop is online", timeout=15000); check("stays paired after reload", True)
    # code is one-use
    r = ctx.new_page(); r.goto(relay); 
    res = r.evaluate("fetch('/api/pair/claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:'%s'})}).then(r=>r.status)" % d["code"])
    check("code single-use", res == 400)
    check("no page errors", not errs)
    # revoke
    ph = pb.paired_phones(); check("laptop saw the phone", len(ph) == 1)
    agent.revoke(ph[0]["id"]); time.sleep(1.5)
    pg.wait_for_selector("text=reconnecting", timeout=10000); check("revoked phone is cut off", True)
    # wrong token
    st = pg.evaluate("fetch('/ws/phone?token=bad').then(r=>r.status)"); check("bad token 401", st == 401)
    b.close()
print(f"{ok} ok, {fail} failed"); sys.exit(1 if fail else 0)
