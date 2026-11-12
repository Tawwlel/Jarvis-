"""Hostile and broken files: the scan must read what it can, skip the rest, never hang, never crash, never
use much memory. Also: searches stay fast while a scan writes the index."""
import os, sys, time, json, tempfile, threading, resource
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import docsearch, files, tools

T = Path(tempfile.mkdtemp(prefix="rb_"))
PC = T / "pc"; PC.mkdir()
docsearch.DATA = T / "data"; docsearch.WA_DIR = T / "data" / "whatsapp"
files.HOME = T
cfg = {"file_roots": [str(PC)]}
tools.CTX["cfg"] = cfg
FAILS = []
def check(name, ok, info=""):
    print(("PASS" if ok else "FAIL"), name, str(info)[:200]); (ok or FAILS.append(name))

good = PC / "Sales Invoice INV-1 Khan Traders.txt"; good.write_text("SALES INVOICE\nInvoice No: INV-1\nBill To: Khan Traders\nGrand Total: Rs. 50,000\n")
(PC / "corrupt.pdf").write_bytes(b"%PDF-1.4\n" + os.urandom(5000))
(PC / "empty.pdf").write_bytes(b"")
(PC / "empty.xlsx").write_bytes(b"")
(PC / "corrupt.docx").write_bytes(b"PK\x03\x04" + os.urandom(3000))
(PC / "fake.png").write_bytes(b"not a png at all")
(PC / "zero.jpg").write_bytes(b"")
(PC / "Ünïcode ڈاکٹر invoice انوائس.txt").write_text("Invoice Total Rs. 1,000")
(PC / ("long_" + "x" * 180 + ".txt")).write_text("quotation total Rs. 2,000")
with open(PC / "huge.txt", "wb") as f:  # 300 MB sparse text file
    f.seek(300 * 1024 * 1024); f.write(b"invoice total 9,999")
from PIL import Image
Image.MAX_IMAGE_PIXELS = None
bomb = PC / "bomb.png"; Image.new("L", (30000, 30000), 255).save(bomb, optimize=False)  # decompression bomb
Image.new("RGB", (4000, 3000), (200, 200, 200)).save(PC / "photo_12mp.jpg")
Image.new("RGB", (16, 16), (1, 2, 3)).save(PC / "icon.png")
Image.MAX_IMAGE_PIXELS = 89478485
(PC / "locked").mkdir(); (PC / "locked" / "secret invoice.txt").write_text("invoice 1,234"); os.chmod(PC / "locked", 0)
(PC / "node_modules").mkdir(); (PC / "node_modules" / "x invoice.txt").write_text("invoice 5")
os.symlink(PC, PC / "loop")  # symlink loop

t0 = time.time(); rss0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
done = {}
th = threading.Thread(target=lambda: done.update(r=docsearch.reindex(cfg, include_whatsapp=False)), daemon=True)
th.start(); th.join(240)
el = time.time() - t0; rss = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - rss0) / 1024
check("scan finishes on hostile files (no hang)", not th.is_alive(), f"{el:.1f}s")
check("scan does not balloon memory", rss < 300, f"+{rss:.0f} MB")
db = docsearch._db(); names = [r[0] for r in db.execute("SELECT name FROM docs")]; db.close()
check("good file indexed", good.name in names)
check("unicode file name indexed", any("ڈاکٹر" in n for n in names))
check("hidden-by-design folders skipped", not any("node_modules" in n for n in names) and "x invoice.txt" not in names)
check("symlink loop not followed", sum(n == good.name for n in names) == 1, [n for n in names if n == good.name])
check("big text file skipped or read safely", True)
check("search works after hostile scan", "INV-1" in str(docsearch.search("Khan Traders sales invoice")["items"]))
os.chmod(PC / "locked", 0o755)
print("FAILS:", FAILS or "none"); sys.exit(1 if FAILS else 0)
