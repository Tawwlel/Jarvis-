import json, sys, time, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import tools, docsearch as d
here = Path(__file__).parent.resolve()
d.DATA = here / "data"; shutil.rmtree(d.DATA, ignore_errors=True)
d.WA_DIR = here / "corpus" / "whatsapp"; d.OUT_DIR = here / "out"
cfg = {"file_roots": [str(here / "corpus" / "pc")]}; tools.CTX["cfg"] = cfg
T = json.load(open(here / "truth.json"))
t0 = time.time(); print("index:", d.reindex(cfg), f"{time.time()-t0:.1f}s")
t0 = time.time(); d.reindex(cfg); print(f"re-index (no changes): {time.time()-t0:.2f}s")

def want(f):
    return {t["name"] for t in T if f(t)}
SALES = lambda t: t["type"] == "sales invoice"
Q = [
 ("all sales invoices", "any", want(SALES)),
 ("all quotations", "any", want(lambda t: t["type"] == "quotation")),
 ("all receipts", "any", want(lambda t: t["type"] == "receipt")),
 ("sales invoices for Khan Traders", "any", want(lambda t: SALES(t) and t["client"] == "Khan Traders")),
 ("Khan Trading Company invoices", "any", want(lambda t: t["type"] in ("sales invoice", "purchase invoice") and t["client"] == "Khan Trading Company")),
 ("quotation for Bilal Steel", "any", want(lambda t: t["type"] == "quotation" and t["client"] == "Bilal Steel Mills")),
 ("sales invoice Zahid and Sons", "any", want(lambda t: SALES(t) and t["client"] == "Zahid & Sons")),
 ("al noor builders sales invoice", "any", want(lambda t: SALES(t) and t["client"] == "Al-Noor Builders")),
 ("sales invoices from whatsapp", "whatsapp", want(lambda t: SALES(t) and t["source"] == "whatsapp")),
 ("sales invoices on my computer", "computer", want(lambda t: SALES(t) and t["source"] == "computer")),
 ("khaan tradrs sales invoice", "any", want(lambda t: SALES(t) and t["client"] == "Khan Traders")),
]
# specific lookups by number and amount
some = [t for t in T if SALES(t)][:4]
for t in some:
    Q.append((f"invoice {t['number']}", "any", {t["name"]}))
    Q.append((f"sales invoice {t['client']} {t['amount']:,}", "any", {t["name"]}))
# date
Q.append(("sales invoices march 2026", "any", want(lambda t: SALES(t) and t["date"].startswith("2026-03"))))
Q.append(("Khan Traders sales invoices from july", "any", want(lambda t: SALES(t) and t["client"] == "Khan Traders" and t["date"][5:7] == "07")))
Q.append(("purchase invoices", "any", want(lambda t: t["type"] == "purchase invoice")))
Q.append(("delivery challan", "any", want(lambda t: t["type"] == "delivery challan")))
Q.append(("sales invoice for Imran Motors", "any", set()))
Q.append(("خان ٹریڈرز سیلز انوائس", "any", want(lambda t: SALES(t) and t["client"] == "Khan Traders")))

tot_p = tot_r = 0; bad = []
for q, src, exp in Q:
    t0 = time.time(); r = d.search(q, src); dt = time.time() - t0
    got = {Path(i["path"]).name for i in r["items"]}
    tp = len(got & exp)
    p = tp / len(got) if got else (1.0 if not exp else 0.0)
    rc = tp / len(exp) if exp else (1.0 if not got else 0.0)
    tot_p += p; tot_r += rc
    flag = "OK " if p == 1 and rc == 1 else "BAD"
    print(f"{flag} P={p:.2f} R={rc:.2f} n={len(got):2}/{len(exp):2} {r['mode']:8} {dt*1000:4.0f}ms  {q}")
    if flag == "BAD":
        bad.append((q, sorted(got - exp)[:4], sorted(exp - got)[:4]))
print(f"\nmean precision {tot_p/len(Q):.2f}  mean recall {tot_r/len(Q):.2f}")
for q, extra, missing in bad:
    print(f"\n# {q}\n  wrong: {extra}\n  missed: {missing}")
