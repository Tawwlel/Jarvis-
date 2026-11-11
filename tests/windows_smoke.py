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
print("ALL OK" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
