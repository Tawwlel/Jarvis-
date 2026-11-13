"""Matched-line proof, 'which one?' on ties, label-vs-name warning, and remembering the owner's choice."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, "scripts")
import docsearch as d, docx
t = Path(tempfile.mkdtemp()); d.DATA = t; d.WA_DIR = t / "wa"; d.EMAIL_DIR = t / "em"; (t / "pc").mkdir()
d.WA_DIR.mkdir(); d.EMAIL_DIR.mkdir()
def mk(name, *lines):
    D = docx.Document()
    for l in lines: D.add_paragraph(l)
    D.save(t / "pc" / name)
mk("Khan Steel 1.docx", "Sales Invoice INV-1001", "Bill to Khan Steel Mills", "Total PKR 50,000")
mk("Khan Steel 2.docx", "Sales Invoice INV-1002", "Bill to Khan Steel Mills", "Total PKR 60,000")
mk("Payment Invoice.docx", "Payment Receipt", "Received from Ali Traders", "Amount received PKR 20,000")
d.reindex({"file_roots": [str(t / "pc")], "doc_folders": [str(t / "pc")]})
d.background_index = lambda *a, **k: None
fails = []
r = d.search("khan steel mills invoice")
if not any("khan steel mills" in (i.get("why") or "").lower() for i in r["items"]): fails.append(("no matched line", [i.get("why") for i in r["items"]]))
if not r.get("ambiguous"): fails.append(("tie not flagged", r["items"]))
out = d._fmt(r)
if "which" not in out or "matched:" not in out: fails.append(("format lacks ask/matched", out))
out2 = d._fmt(d.search("ali traders payment"))
if "name says invoice" not in out2: fails.append(("label mismatch not shown", out2))
# learn a choice
d.doc_search.__wrapped__ if hasattr(d.doc_search, "__wrapped__") else None
d._LAST.update(terms=r["terms"], items=[i["path"] for i in r["items"]], names=[i["name"] for i in r["items"]])
msg = d.doc_choose("2")
r2 = d.search("khan steel mills invoice")
if r2["items"][0]["path"] != r["items"][1]["path"] or r2.get("ambiguous"): fails.append(("choice not remembered", msg, [i["name"] for i in r2["items"]]))
if "you picked this one before" not in d._fmt(r2): fails.append(("learned marker missing",))
print("FAILS:", fails or "none"); sys.exit(1 if fails else 0)
