"""The same file arriving through WhatsApp and email (different names) is listed once, with where it was found."""
import sys, tempfile, shutil
from pathlib import Path
sys.path.insert(0, "scripts")
import docsearch as d, docx
t = Path(tempfile.mkdtemp()); d.DATA = t; d.WA_DIR = t / "wa"; d.EMAIL_DIR = t / "em"
(d.WA_DIR / "Khan Traders").mkdir(parents=True); (d.EMAIL_DIR / "Ali").mkdir(parents=True); (t / "pc").mkdir()
D = docx.Document(); D.add_paragraph("Sales Invoice INV-9001 Khan Traders total PKR 77,000"); D.save(t / "pc" / "Invoice 9001.docx")
shutil.copy(t / "pc" / "Invoice 9001.docx", d.WA_DIR / "Khan Traders" / "DOC-20261101-WA0001.docx")
shutil.copy(t / "pc" / "Invoice 9001.docx", d.EMAIL_DIR / "Ali" / "2026-11-01_inv.docx")
d.reindex({"file_roots": [str(t / "pc")], "doc_folders": [str(t / "pc")]})
r = d.search("invoice 9001")
ok = len(r["items"]) == 1 and len(r["items"][0]["also_in"]) == 3
print("found once, in", r["items"][0]["also_in"] if r["items"] else None)
print("ok" if ok else "FAIL"); sys.exit(0 if ok else 1)
