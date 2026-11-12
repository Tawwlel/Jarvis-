"""Every file type Jarvis must read: pdf docx doc xlsx xls csv pptx ppt zip rar jpg png odt."""
import sys, tempfile, zipfile, subprocess, shutil
from pathlib import Path
sys.path.insert(0, "scripts")
import docsearch as d
ok = bad = 0
def check(n, c):
    global ok, bad
    if c: ok += 1
    else: bad += 1; print("FAIL", n)
t = Path(tempfile.mkdtemp()); K = "INV-4417"
for e in (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".pptx", ".ppt", ".zip", ".rar", ".jpg", ".png", ".odt"):
    check("listed " + e, e in d.EXTS)
import docx; D = docx.Document(); D.add_paragraph("hello"); tb = D.add_table(1, 1); tb.cell(0, 0).text = f"Invoice {K}"; D.save(t / "a.docx")
check("docx incl. table", K in d.extract_text(t / "a.docx"))
import openpyxl; wb = openpyxl.Workbook(); wb.active.append([K, 5000]); wb.save(t / "a.xlsx")
check("xlsx", K in d.extract_text(t / "a.xlsx"))
(t / "a.csv").write_text(f"no,total\n{K},900\n"); check("csv", K in d.extract_text(t / "a.csv"))
from pptx import Presentation
pr = Presentation(); s = pr.slides.add_slide(pr.slide_layouts[5]); s.shapes.title.text = f"Quotation {K}"; pr.save(t / "a.pptx")
check("pptx", K in d.extract_text(t / "a.pptx"))
from odf.opendocument import OpenDocumentText; from odf.text import P
o = OpenDocumentText(); o.text.addElement(P(text=f"Receipt {K}")); o.save(str(t / "a.odt"))
check("odt", K in d.extract_text(t / "a.odt"))
(t / "old.doc").write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 50 + f"Quotation {K} total".encode("cp1252") + b"\x00" * 30)
check("legacy doc strings", K in d.extract_text(t / "old.doc"))
(t / "old.ppt").write_bytes(b"\x00" * 20 + f"S\x00l\x00i\x00d\x00e\x00 \x00{K}\x00".encode("latin1"))
check("legacy ppt utf16", K in d.extract_text(t / "old.ppt"))
with zipfile.ZipFile(t / "pack.zip", "w") as z:
    z.write(t / "a.docx", "inside/contract.docx"); z.write(t / "a.xlsx", "sheet.xlsx")
txt = d.extract_text(t / "pack.zip")
check("zip lists names", "contract.docx" in txt); check("zip reads inside", K in txt)
if shutil.which("tar"):
    r = subprocess.run(["tar", "-cf", str(t / "x.tar"), "-C", str(t), "a.csv"], capture_output=True)
    check("rar path does not crash on a non-rar", isinstance(d.extract_text(t / "x.tar"), str))
(t / "bad.rar").write_bytes(b"not really a rar"); check("broken rar safe", isinstance(d.extract_text(t / "bad.rar"), str))
(t / "bad.zip").write_bytes(b"nope"); check("broken zip safe", d.extract_text(t / "bad.zip") == "")
print(f"{ok} ok, {bad} failed"); sys.exit(1 if bad else 0)
