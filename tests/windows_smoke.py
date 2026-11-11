"""Runs inside the built Jarvis folder on Windows (CI): every document-finder part must load and work."""
import shutil
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
app = Path(sys.argv[1]).resolve()  # Jarvis/app
sys.path.insert(0, str(app / "scripts"))
fx = Path(__file__).parent / "fixtures"
ok = True


def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, info)


import tools, docsearch, invoice_fields, semantic, urdu_ocr, iphone_backup, whatsapp_reader, email_agent  # noqa
check("imports", True)
check("tesseract found", urdu_ocr.available(), urdu_ocr.tesseract_exe())
from PIL import Image
u = urdu_ocr.read(Image.open(fx / "urdu_invoice.png"))
check("urdu ocr", "85,000" in u and urdu_ocr.has_urdu(u), u.replace("\n", " | ")[:120])
check("meaning model", semantic.ready())
v = semantic.embed(["query: bijli ka bill", "passage: K-Electric bill"])
check("embedding", v is not None and v.shape == (2, 384))
tmp = Path(tempfile.mkdtemp())
pc = tmp / "pc"
pc.mkdir()
for f in fx.iterdir():
    if f.is_file():
        shutil.copy(f, pc)
docsearch.DATA = tmp / "data"
docsearch.WA_DIR = tmp / "data" / "whatsapp"
cfg = {"file_roots": [str(pc)]}
tools.CTX["cfg"] = cfg
check("index", docsearch.reindex(cfg)["total"] == 2)
r = docsearch.search("Rehman Hardware ka bill", "computer")
check("urdu invoice found by english name", any(i["name"] == "urdu_invoice.png" for i in r["items"]), r["mode"])
t = invoice_fields.invoice_totals("sales invoices")
check("exact totals", "Rs. 130,000" in t, t.splitlines()[0])
check("vectors", semantic.update_vectors() == 2)
from invoice2data.extract.loader import read_templates  # noqa
check("invoice2data", True)
import iphone_backup_decrypt, Whatsapp_Chat_Exporter  # noqa
check("iphone libs", True)
# ---- WhatsApp reader: the bundled browser must start and download from a (mock) WhatsApp Web page ----
import functools, http.server, threading  # noqa
import whatsapp_reader as wr  # noqa
bundled = app.parent / "browsers"
check("browser bundled in the folder", bundled.is_dir(), str(bundled))
H = type("Q", (http.server.SimpleHTTPRequestHandler,), {"log_message": lambda *a: None})
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8765), functools.partial(H, directory=str(fx / "fakewa")))
threading.Thread(target=srv.serve_forever, daemon=True).start()
wr.DATA = tmp / "data"
wr.WA_DIR = tmp / "data" / "whatsapp"
wr.PROFILE = tmp / "data" / "wa_profile"
wr.PROFILE.mkdir(parents=True)
wr.WA_URL = "http://127.0.0.1:8765/index.html"
try:
    r1 = wr.sync()
    r2 = wr.sync()
    got = sorted(p.name for p in wr.WA_DIR.rglob("*.pdf"))
    check("whatsapp reader downloads on Windows", sum(v for v in r1.values() if isinstance(v, int)) == 3, f"{r1} {got}")
    check("nothing downloaded twice", sum(v for v in r2.values() if isinstance(v, int)) == 0, r2)
    docsearch.reindex(cfg)
    r = docsearch.search("Khan Traders sales invoice", "whatsapp")
    check("downloaded WhatsApp file is searchable", any("INV-9001" in i["name"] for i in r["items"]))
except Exception as e:
    check("whatsapp reader on Windows", False, repr(e))
srv.shutdown()
# ---- windows open without a display crash: chat + settings ----
try:
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    qa = QApplication([])
    import ui, config
    b = ui.Bridge()
    w = ui.ChatWindow(b, "Jarvis")
    w.show()
    s = ui.SettingsWindow(config.load_config(), str(app / "assets" / "logo.png"), False, ["amy"], lambda v: None,
                          store=None, roles={}, profile={})
    qa.processEvents()
    check("chat + settings windows build on Windows", "email" in s.values())
except Exception as e:
    check("windows build on Windows", False, repr(e))
import tts, stt  # noqa
check("default voice bundled", (app / "voices" / "en_US-amy-medium.onnx").exists())
check("listening models bundled", (app / "whisper_model" / "faster-whisper-base" / "model.bin").exists()
      and (app / "whisper_model" / "faster-whisper-tiny.en" / "model.bin").exists())
print("ALL OK" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
