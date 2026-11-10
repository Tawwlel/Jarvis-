import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import tools, docsearch as d
here = Path(__file__).parent.resolve()
d.DATA = here / "data"; d.WA_DIR = here / "corpus" / "whatsapp"
cfg = {"file_roots": [str(here / "corpus" / "pc")]}; tools.CTX["cfg"] = cfg
T = json.load(open(here / "truth.json"))
S = lambda t: t["type"] == "sales invoice"
W = lambda f: {t["name"] for t in T if f(t)}
def latest(f, k=1):
    xs = sorted([t for t in T if f(t)], key=lambda t: t["date"], reverse=True)
    return {t["name"] for t in xs[:k]}
Q = [
 ("can you please find me the quotations we sent to bilal steel mills", W(lambda t: t["type"] == "quotation" and t["client"] == "Bilal Steel Mills")),
 ("show me all the invoices of khan", W(lambda t: t["type"] in ("sales invoice", "purchase invoice") and t["client"] in ("Khan Traders", "Khan Trading Company"))),
 ("latest sales invoice for Zahid and Sons", latest(lambda t: S(t) and t["client"] == "Zahid & Sons")),
 ("the most recent quotation", latest(lambda t: t["type"] == "quotation")),
 ("sales invoices above 300,000", W(lambda t: S(t) and t["amount"] > 300000)),
 ("sales invoices over 3 lakh", W(lambda t: S(t) and t["amount"] > 300000)),
 ("quotations under 50k", W(lambda t: t["type"] == "quotation" and t["amount"] < 50000)),
 ("Rahman hardware sales invoices", W(lambda t: S(t) and t["client"] == "Rehman Hardware")),
 ("which receipts did faisal construction give us", W(lambda t: t["type"] == "receipt" and t["client"] == "Faisal Construction")),
 ("I need the sales invoice that I made for Ali Enterprises in may", W(lambda t: S(t) and t["client"] == "Ali Enterprises" and t["date"][5:7] == "05")),
 ("زاہد اینڈ سنز کی تمام سیلز انوائس", W(lambda t: S(t) and t["client"] == "Zahid & Sons")),
 ("Zahid & Sons ki sari sales invoices dikhao", W(lambda t: S(t) and t["client"] == "Zahid & Sons")),
]
for q, exp in Q:
    r = d.search(q, "any")
    got = {Path(i["path"]).name for i in r["items"]}
    ok = got == exp
    print(f"{'OK ' if ok else 'BAD'} n={len(got):2}/{len(exp):2} {r['mode']:8} terms={r['terms']} {q}")
    if not ok:
        print("    wrong:", sorted(got - exp)[:4], " missed:", sorted(exp - got)[:4])
