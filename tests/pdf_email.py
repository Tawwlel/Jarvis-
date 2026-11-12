"""All pages of a PDF are read, scanned pages are read as pictures, and email attachments are saved and found."""
import sys, tempfile, email.message, email.utils
from datetime import datetime
from pathlib import Path
sys.path.insert(0, "scripts")
import docsearch as d, email_agent as ea
ok = bad = 0
def check(n, c):
    global ok, bad
    if c: ok += 1
    else: bad += 1; print("FAIL", n)
t = Path(tempfile.mkdtemp())
from reportlab.pdfgen import canvas
f = t / "multi.pdf"; c = canvas.Canvas(str(f))
for i in range(1, 16):
    c.drawString(72, 700, f"Page {i} filler"); 
    if i == 14: c.drawString(72, 650, "Total payable PKR 884,300 invoice INV-5521 Khan Traders")
    c.showPage()
c.save()
txt = d.extract_text(f)
check("text from page 14 (beyond old 10-page limit)", "INV-5521" in txt)
# scanned pdf: page 1 blank-with-image, page 2 text image
from PIL import Image, ImageDraw
im = Image.new("RGB", (1200, 800), "white"); ImageDraw.Draw(im).text((100, 100), "INVOICE INV-7788 TOTAL 12500", fill="black")
s = t / "scan.pdf"; im.save(s, "PDF")
txt = d.extract_text(s)
check("scanned pdf read by OCR", "7788" in txt)
# email attachment saved
m = email.message.EmailMessage(); m["From"] = "Ali Khan <ali@khantraders.pk>"; m["Subject"] = "Invoice"; m["Date"] = email.utils.format_datetime(datetime(2026, 11, 2, 10))
m.set_content("see attached"); m.add_attachment(f.read_bytes(), maintype="application", subtype="pdf", filename="Invoice 5521.pdf")
root = t / "email_docs"
check("attachment saved", ea.save_attachments(m, root, m["From"], datetime(2026, 11, 2, 10)) == 1)
check("saved under sender", (root / "Ali Khan" / "2026-11-02_Invoice 5521.pdf").exists())
check("not saved twice", ea.save_attachments(m, root, m["From"], datetime(2026, 11, 2, 10)) == 0)
d.DATA = t; d.EMAIL_DIR = root; d.DB = t / "docs.db" if hasattr(d, "DB") else None
print(f"{ok} ok, {bad} failed"); sys.exit(1 if bad else 0)
