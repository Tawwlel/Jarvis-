"""A scan writes thousands of files while several searches run at once: no errors, no long waits."""
import sys, time, random, tempfile, threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import docsearch, files, tools
T = Path(tempfile.mkdtemp(prefix="cc_")); PC = T / "pc"; PC.mkdir()
docsearch.DATA = T / "data"; docsearch.WA_DIR = T / "data" / "whatsapp"; files.HOME = T
cfg = {"file_roots": [str(PC)]}; tools.CTX["cfg"] = cfg
random.seed(3); clients = ["Khan Traders", "Bilal Steel", "Ali Enterprises", "Noor Textiles", "Hassan Motors"]
N = 4000
for i in range(N):
    c = random.choice(clients); k = random.choice(["Sales Invoice", "Quotation", "Payment Receipt"])
    (PC / f"{k} {i:05d} {c}.txt").write_text(f"{k.upper()}\nNo: INV-{i}\nBill To: {c}\nGrand Total: Rs. {random.randint(1,500)*1000:,}\n")
# first, a small index so searches have something while the big scan runs
errs, lat, stop = [], [], threading.Event()
def searcher(q):
    while not stop.is_set():
        t = time.time()
        try:
            tools.run_tool("doc_search", {"query": q})
        except Exception as e:
            errs.append(repr(e))
        lat.append(time.time() - t); time.sleep(0.05)
t0 = time.time()
scan = threading.Thread(target=lambda: docsearch.reindex(cfg, include_whatsapp=False), daemon=True); scan.start()
ths = [threading.Thread(target=searcher, args=(q,), daemon=True) for q in ("Khan Traders invoice", "Bilal Steel quotation", "receipts", "total sales invoices")]
[t.start() for t in ths]
scan.join(600); stop.set(); [t.join(5) for t in ths]
took = time.time() - t0
db = docsearch._db(); n = db.execute("SELECT COUNT(*) FROM docs").fetchone()[0]; db.close()
lat.sort(); p95 = lat[int(len(lat) * .95)] if lat else 0
bad_tool = [e for e in errs if "locked" in e.lower() or "Error" in e]
print(f"indexed {n}/{N} in {took:.0f}s; {len(lat)} searches, p95 {p95:.2f}s, max {max(lat):.2f}s, errors {len(errs)}")
ok = n == N and not errs and max(lat) < 5
print("PASS" if ok else "FAIL", errs[:3]); sys.exit(0 if ok else 1)
