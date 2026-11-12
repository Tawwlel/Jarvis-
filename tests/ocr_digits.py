"""Scanned documents: OCR look-alikes (l/I for 1, O for 0) and Urdu-script digits must not hide a document number."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, "scripts")
import docsearch as d, docx
t = Path(tempfile.mkdtemp()); d.DATA = t; d.WA_DIR = t / "wa"; d.EMAIL_DIR = t / "em"; (t / "pc").mkdir()
for n, txt in (("a.docx", "Sales Invoice No INV-l148 Khan Traders total PKR 5O,000"), ("b.docx", "Quotation QT-2O31 Bilal Steel total 90000"),
               ("c.docx", "Sales Invoice INV-3377 Zahid and Sons total 12000")):
    D = docx.Document(); D.add_paragraph(txt); D.save(t / "pc" / n)
d.reindex({"file_roots": [str(t / "pc")], "doc_folders": [str(t / "pc")]}, include_whatsapp=False, include_email=False)
ok = bad = 0
for q, want in [("invoice 1148", "a.docx"), ("INV1148", "a.docx"), ("quotation 2031", "b.docx"), ("QT2031", "b.docx"),
                ("انوائس ۳۳۷۷", "c.docx"), ("invoice ۳۳۷۷", "c.docx"), ("3377", "c.docx")]:
    r = d.search(q); names = [i["name"] for i in r["items"]]
    good = names == [want]
    ok += good; bad += not good
    if not good: print("FAIL", q, names)
print(f"{ok} ok, {bad} failed"); sys.exit(1 if bad else 0)
