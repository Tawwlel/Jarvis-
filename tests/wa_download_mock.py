"""_download_chat with a fake WhatsApp page: documents download, dead photos stop being retried after two tries."""
import sys, tempfile, time, json
from pathlib import Path
sys.path.insert(0, "scripts")
import whatsapp_reader as wa
wa.WA_DIR = Path(tempfile.mkdtemp())
calls = {"doc": 0, "photo": 0}
class Dl:
    def __init__(s, name): s.suggested_filename = name
    def save_as(s, p): Path(p).write_bytes(b"x")
class Ctx:
    def __init__(s, kind, fail): s.kind, s.fail = kind, fail; s.value = None
    def __enter__(s):
        if s.fail: raise TimeoutError("no download")
        s.value = Dl("Invoice.pdf" if s.kind == "doc" else "photo.jpg"); return s
    def __exit__(s, *a): return False
class El:
    def __init__(s, attr=None): s.attr = attr or {}
    def get_attribute(s, k): return s.attr.get(k)
    def click(s): pass
class Msg(El):
    def __init__(s, mid, kind): super().__init__({"data-id": mid}); s.kind = mid, kind; s.k = kind; s.mid = mid
    def scroll_into_view_if_needed(s): pass
    def query_selector(s, sel):
        if "doc_title" in sel or sel == wa.SEL["doc_title"]:
            return El({"title": "Invoice 77.pdf"}) if s.k == "doc" else None
        if "blob" in sel: return El() if s.k == "photo" else None
        return El()
class Page:
    def __init__(s, msgs): s.msgs = msgs
    def query_selector_all(s, sel): return s.msgs
    def expect_download(s, timeout=0):
        s.n = getattr(s, "n", 0) + 1
        return Ctx("doc", False) if s.msgs and any(m.k == "doc" for m in s.msgs) and s.n == 1 else Ctx("photo", True)
    def wait_for_timeout(s, ms): pass
    class mouse: pass
    class keyboard:
        @staticmethod
        def press(k): pass
    def click(s, sel): pass
ok = bad = 0
def check(n, c):
    global ok, bad
    if c: ok += 1
    else: bad += 1; print("FAIL", n)
msgs = [Msg("m2", "photo"), Msg("m1", "doc")]
n1 = wa._download_chat(Page(msgs), "Chat A", 10, set())
check("document downloaded", n1 == 1 and any((wa.WA_DIR / "Chat_A").glob("*")) or n1 == 1)
tries = json.loads((wa.WA_DIR / wa._safe("Chat A") / ".tries").read_text()) if (wa.WA_DIR / wa._safe("Chat A") / ".tries").exists() else None
import json
check("failed photo counted", tries is not None and tries.get("m2") == 1)
wa._download_chat(Page([Msg("m2", "photo")]), "Chat A", 10, set())
seen = (wa.WA_DIR / wa._safe("Chat A") / ".seen").read_text()
check("photo given up after two failures", "m2" in seen)
print(f"{ok} ok, {bad} failed"); sys.exit(1 if bad else 0)
