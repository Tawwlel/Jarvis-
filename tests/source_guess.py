"""A wrong source guess ("from Apricot Digital" taken as a WhatsApp chat) must not hide a file that exists elsewhere."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, "scripts")
import docsearch as d, docx
t = Path(tempfile.mkdtemp()); d.DATA = t; d.WA_DIR = t / "wa"; d.EMAIL_DIR = t / "em"
(d.WA_DIR / "Apricot Digital").mkdir(parents=True); d.EMAIL_DIR.mkdir(); (t / "pc").mkdir()
D = docx.Document(); D.add_paragraph("Invoice Apricot Digital total 20,000 date 5 Nov 2026"); D.save(t / "pc" / "Apricot Digital Payment Invoice.docx")
d.reindex({"file_roots": [str(t / "pc")], "doc_folders": [str(t / "pc")]})
d.background_index = lambda *a, **k: None  # the test has no settings; do not let a background pass re-read nothing
fails = []
a = d.doc_search("latest invoice from Apricot Digital", "whatsapp")
if "Payment Invoice" not in a: fails.append(("wrong source guess hid the file", a))
b = d.doc_search("receipt zzqq", "whatsapp")
if "Payment Invoice" in b: fails.append(("unrelated query listed the file", b))
c = d.doc_search("latest invoice from Apricot Digital", "email")
if "Payment Invoice" not in c: fails.append(("email guess hid the file", c))
print("FAILS:", fails or "none"); sys.exit(1 if fails else 0)
