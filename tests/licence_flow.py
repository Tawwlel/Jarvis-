"""The app checks in with the portal, obeys a signed pause, ignores forged answers, and keeps working offline."""
import sys, json, sqlite3, tempfile, threading, http.server, pathlib, urllib.request
sys.path.insert(0, "scripts")
import licence, usage
d = pathlib.Path(tempfile.mkdtemp()); licence.DATA = d; licence.FILE = d / "licence.json"; usage.DATA = d; usage.FILE = d / "usage.json"
fails = []
def ok(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails.append(m)
ok("doesn't look" in licence.set_key("hello"), "bad key refused")
ok(licence.check() == "" and not licence.blocked(), "no key: nothing reported, nothing blocked")
# a stand-in portal that signs like the real one (using the real private key kept outside the repo)
import base64
from cryptography.hazmat.primitives import serialization as S
priv = S.load_pem_private_key(pathlib.Path("/home/claude/jarvis-owner/allowance_private.key").read_bytes(), None)
b = lambda x: base64.urlsafe_b64encode(x).decode().rstrip("=")
state = {"status": "active", "forge": False, "seen": None, "old": False}
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        import time
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"]))); state["seen"] = body
        ts = int(time.time()) - (200000 if state["old"] else 0)
        sig = b(priv.sign(f"licence|{body['key']}|{state['status']}|{ts}".encode()))
        if state["forge"]: sig = b(b"x" * 64)
        out = json.dumps({"ok": True, "status": state["status"], "message": "This licence is paused. Please contact Apricot Digital.", "ts": ts, "sig": sig}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
    def log_message(self, *a): pass
srv = http.server.HTTPServer(("127.0.0.1", 8098), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
U = "http://127.0.0.1:8098/"
licence.set_key("jrv-abcd-2345-wxyz")
ok(licence.check(U) == "active" and not licence.blocked() and not usage.blocked(), "active answer accepted")
seen = json.dumps(state["seen"])
ok(set(state["seen"]) == {"key", "version", "usage_pct", "machine", "used_codes"}, "report has only key, version, usage, machine hash, code ids")
ok("invoice" not in seen.lower() and len(state["seen"]["machine"]) == 32, "nothing about files or chats is sent")
state["status"] = "suspended"
ok(licence.check(U) == "suspended" and licence.blocked() and usage.blocked(), "signed pause is obeyed and blocks the online assistant")
ok("paused" in licence.message(), "client sees a clear message")
state["status"] = "active"; state["forge"] = True
ok(licence.check(U) == "suspended" and licence.blocked(), "a forged 'active' answer does not lift a pause")
state["forge"] = False; state["status"] = "suspended"; licence.set_key("JRV-ABCD-2345-WXYZ")
state["forge"] = True; ok(licence.check(U) == "" and not licence.blocked(), "a forged 'suspended' answer does not pause anyone")
state["forge"] = False; state["old"] = True; state["status"] = "suspended"
ok(licence.check(U) == "" and not licence.blocked(), "an old (replayed) answer is ignored")
state["old"] = False; licence.check(U); ok(licence.blocked(), "paused again with a fresh answer")
srv.shutdown()
ok(licence.check("http://127.0.0.1:1/") == "suspended" and licence.blocked(), "portal offline: keeps the last verified state")
print("FAILS:", fails or "none"); sys.exit(1 if fails else 0)
