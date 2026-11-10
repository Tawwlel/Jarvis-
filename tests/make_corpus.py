"""Builds a messy, realistic document set with ground truth labels.

    python tests/make_corpus.py && python tests/evaluate.py && python tests/evaluate2.py
(needs reportlab; photos are read with OCR)
"""
import json, os, random, shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from reportlab.pdfgen import canvas
import docx, openpyxl

random.seed(7)
ROOT = Path(__file__).resolve().parent / "corpus"; shutil.rmtree(ROOT, ignore_errors=True)
PC = ROOT / "pc"; WA = ROOT / "whatsapp"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
truth = []

def add(path, source, client, typ, amount=None, number=None, date=None, chat=""):
    truth.append(dict(name=Path(path).name, path=str(path), source=source, client=client, type=typ,
                      amount=amount, number=number, date=date, chat=chat))

def lines_for(typ, client, num, amount, date):
    title = {"sales invoice": "SALES INVOICE", "purchase invoice": "PURCHASE INVOICE", "quotation": "QUOTATION",
             "receipt": "PAYMENT RECEIPT", "invoice": "INVOICE", "credit note": "CREDIT NOTE",
             "delivery challan": "DELIVERY CHALLAN", "purchase order": "PURCHASE ORDER"}[typ]
    who = "Supplier" if typ in ("purchase invoice",) else "Bill To"
    return ["Apricot Steel Works (Pvt) Ltd", "Plot 12, SITE Area, Karachi", title,
            f"{title.title().split()[0]} No: {num}", f"Date: {date}", f"{who}: {client}",
            "Item            Qty   Rate", "MS Pipe 2in     40    1,250", "GI Sheet        12    3,400",
            f"Grand Total: Rs. {amount:,}", "Thank you for your business"]

def pdf(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path))
    for i, l in enumerate(lines):
        c.drawString(60, 790 - i * 22, l)
    c.save()

def photo(path, lines, rotate=0, blur=0, small=False, scan_pdf=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (1240, 900), (250, 249, 244)); d = ImageDraw.Draw(im)
    f = ImageFont.truetype(FONT, 30)
    for i, l in enumerate(lines):
        d.text((60, 50 + i * 68), l, fill=(20, 20, 30), font=f)
    if rotate: im = im.rotate(rotate, expand=True, fillcolor=(120, 110, 100))
    if blur: im = im.filter(ImageFilter.GaussianBlur(blur))
    if small: im = im.resize((im.width // 2, im.height // 2))
    if scan_pdf:
        im.save(path, "PDF")
    else:
        im.save(path, quality=70)

def docxf(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    dd = docx.Document()
    for l in lines: dd.add_paragraph(l)
    dd.save(path)

def xlsxf(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook(); ws = wb.active
    for l in lines: ws.append([l])
    wb.save(path)

clients = ["Khan Traders", "Khan Trading Company", "Ali Enterprises", "Bilal Steel Mills",
           "Al-Noor Builders", "Zahid & Sons", "Rehman Hardware", "Faisal Construction"]
types = ["sales invoice"] * 5 + ["quotation"] * 3 + ["receipt", "purchase invoice", "delivery challan",
                                                     "credit note", "purchase order"]
months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
n = 1000
for k in range(70):
    client = random.choice(clients); typ = random.choice(types)
    n += random.randint(1, 9); amount = random.randint(5, 900) * 500
    date = f"{random.choice(months)}-{random.randint(1, 28):02d}"
    prefix = {"sales invoice": "INV", "purchase invoice": "PINV", "quotation": "QT", "receipt": "RCPT",
              "delivery challan": "DC", "credit note": "CN", "purchase order": "PO"}[typ]
    num = f"{prefix}-{n}"
    L = lines_for(typ, client, num, amount, date)
    style = random.choice(["pdf", "pdf", "pdf", "scan", "photo", "photo_bad", "docx", "xlsx", "wa_pdf", "wa_img"])
    cslug = client.replace(" ", "_").replace("&", "and")
    if style == "pdf":
        name = random.choice([f"{num}.pdf", f"{num} {client}.pdf", f"{typ.title()} {num}.pdf", f"{cslug}_{date}.pdf"])
        p = PC / "Accounts" / date[:7] / name; pdf(p, L); src = "computer"; chat = ""
    elif style == "scan":
        p = PC / "Scanned Documents" / f"Scan_{date.replace('-', '')}_{k:03d}.pdf"; photo(p, L, scan_pdf=True); src = "computer"; chat = ""
    elif style == "photo":
        p = PC / "Pictures" / f"IMG_{2000 + k}.jpg"; photo(p, L, rotate=random.choice([0, 0, 2, -3])); src = "computer"; chat = ""
    elif style == "photo_bad":
        p = PC / "Pictures" / f"IMG_{2000 + k}.jpg"; photo(p, L, rotate=random.choice([4, -5]), blur=1.2, small=True); src = "computer"; chat = ""
    elif style == "docx":
        p = PC / "Office" / f"{typ} {client} {k}.docx"; docxf(p, L); src = "computer"; chat = ""
    elif style == "xlsx":
        p = PC / "Office" / f"{prefix}_{n}.xlsx"; xlsxf(p, L); src = "computer"; chat = ""
    elif style == "wa_pdf":
        chat = client if random.random() < 0.7 else random.choice(["Accounts Group", "Ahmed Bhai"])
        p = WA / chat / f"DOC-{date.replace('-', '')}-WA00{k:02d}.pdf"; pdf(p, L); src = "whatsapp"
    else:
        chat = client if random.random() < 0.7 else random.choice(["Accounts Group", "Ahmed Bhai"])
        p = WA / chat / f"IMG-{date.replace('-', '')}-WA00{k:02d}.jpg"; photo(p, L, rotate=random.choice([0, 3]), blur=random.choice([0, 0.8])); src = "whatsapp"
    add(p, src, client, typ, amount, num, date, chat)

# noise: things that must NOT come back as invoices
for i, (nm, L) in enumerate([("Muhammad_Zahid_CV.pdf", ["Curriculum Vitae", "Muhammad Zahid", "Experience: accounts officer, prepared sales invoices"]),
                             ("Meeting notes.docx", ["Meeting with Khan Traders about new rates", "Follow up next week"]),
                             ("Price list 2026.xlsx", ["Price List", "MS Pipe 1,250", "GI Sheet 3,400"]),
                             ("product_photo.jpg", ["SESAME SEED HAIR OIL", "100% natural"]),
                             ("bank statement march.pdf", ["Bank Statement", "Khan Traders deposit 45,000"])]):
    p = PC / "Misc" / nm
    {"pdf": pdf, "docx": docxf, "xlsx": xlsxf, "jpg": photo}[nm.rsplit(".", 1)[1]](p, L)
    add(p, "computer", None, "other")
# hidden / system folder that must be ignored
pdf(PC / ".hidden" / "INV-9999.pdf", lines_for("sales invoice", "Khan Traders", "INV-9999", 1000, "2026-01-01"))
# Urdu-named chat
pdf(WA / "خان ٹریڈرز" / "DOC-20260715-WA0099.pdf", lines_for("sales invoice", "Khan Traders", "INV-5555", 77000, "2026-07-15"))
add(WA / "خان ٹریڈرز" / "DOC-20260715-WA0099.pdf", "whatsapp", "Khan Traders", "sales invoice", 77000, "INV-5555", "2026-07-15", "خان ٹریڈرز")
json.dump(truth, open(Path(__file__).resolve().parent / "truth.json", "w"), indent=1, ensure_ascii=False)
from collections import Counter
print(len(truth), Counter(t["type"] for t in truth), Counter(t["source"] for t in truth))
