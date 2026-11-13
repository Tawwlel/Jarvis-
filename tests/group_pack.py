"""Group test: every kind of file dropped into ONE WhatsApp group ("Apricot Digital"), then asked about the way an
owner would ask. Scores each question (precision / recall) and gives an overall rating out of 10.

    python tests/group_pack.py            # builds the pack, indexes it, asks, scores
    python tests/group_pack.py --pack DIR # also copies the sample files to DIR (to send them to the real group)
"""
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import tools  # noqa: E402
import docsearch as d  # noqa: E402

GROUP = "Apricot Digital"
tmp = Path(tempfile.mkdtemp())
d.DATA = tmp / "data"
d.WA_DIR = tmp / "whatsapp"
g = d.WA_DIR / GROUP
g.mkdir(parents=True)
tools.CTX["cfg"] = {"file_roots": [str(tmp / "pc_empty")]}
(tmp / "pc_empty").mkdir()

# 1) the 76 business documents (invoices, quotations, receipts, challans, credit notes...) as pdf/jpg/xlsx/docx
T = json.load(open(HERE / "truth.json"))
for t in T:
    shutil.copy2(t["path"], g / t["name"])

# 2) one of every other kind, with known contents
extra = {}


def mark(name, *labels):
    extra[name] = set(labels)


import docx  # noqa: E402
D = docx.Document(); D.add_heading("Shop Rental Agreement", 1)
D.add_paragraph("This rent agreement is made between Talal Ahmed (landlord) and Usman Ali (tenant) for Shop No. 14, "
                "Saddar, Karachi. Monthly rent Rs 85,000. Term 11 months from 1 December 2026.")
D.save(g / "Shop 14 Saddar agreement.docx"); mark("Shop 14 Saddar agreement.docx", "rent")

import openpyxl  # noqa: E402
wb = openpyxl.Workbook(); ws = wb.active; ws.title = "October 2026"
ws.append(["Employee", "Designation", "Salary"]); ws.append(["Ahsan", "Developer", 120000]); ws.append(["Sana", "Designer", 95000])
ws.append(["", "Total salary sheet October 2026", 215000]); wb.save(g / "Book1.xlsx"); mark("Book1.xlsx", "salary")

(g / "tyre_prices.csv").write_text("item,size,price\nHino truck tyre,1000-20,78000\nBridgestone tyre,295/80R22.5,96000\n")
mark("tyre_prices.csv", "tyre")

from pptx import Presentation  # noqa: E402
pr = Presentation(); s = pr.slides.add_slide(pr.slide_layouts[1])
s.shapes.title.text = "Apricot Digital - Company Profile"
s.placeholders[1].text = "Services: AI assistants, web development, automation for Pakistani businesses"
pr.save(g / "Profile v3.pptx"); mark("Profile v3.pptx", "profile")

from odf.opendocument import OpenDocumentText  # noqa: E402
from odf.text import P  # noqa: E402
o = OpenDocumentText(); o.text.addElement(P(text="No Objection Certificate (NOC). Apricot Digital has no objection to "
                                                "Mr. Hamza Khan joining another company.")); o.save(str(g / "noc.odt"))
mark("noc.odt", "noc")

(g / "notes.txt").write_text("Meeting notes 12 Nov 2026 with Bilal Steel: they want 5% discount, delivery in 10 days.")
mark("notes.txt", "meeting")

# a "folder": WhatsApp only carries folders as zip files
proj = tmp / "Project Alpha"; proj.mkdir()
D = docx.Document(); D.add_paragraph("Scope of work for Project Alpha: mobile app with WhatsApp login."); D.save(proj / "scope of work.docx")
wb = openpyxl.Workbook(); wb.active.append(["Project Alpha budget", 1450000]); wb.save(proj / "budget.xlsx")
with zipfile.ZipFile(g / "Project Alpha.zip", "w") as z:
    for f in proj.iterdir():
        z.write(f, f"Project Alpha/{f.name}")
mark("Project Alpha.zip", "alpha", "scope")

# bank payment screenshots (images: read by OCR)
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
F = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
big, small = ImageFont.truetype(F, 34), ImageFont.truetype(F, 26)


def shot(name, bank, amount, to, ref):
    im = Image.new("RGB", (720, 1280), "white"); dr = ImageDraw.Draw(im)
    dr.rectangle([0, 0, 720, 140], fill=(110, 30, 120) if bank == "Meezan Bank" else (0, 110, 80))
    dr.text((40, 50), bank, font=big, fill="white")
    y = 220
    for line in ("Funds Transfer Successful", f"Amount: Rs. {amount:,}", f"To: {to}", f"Reference: {ref}",
                 "Date: 10 Nov 2026 04:12 PM", "Channel: Raast"):
        dr.text((40, y), line, font=small, fill="black"); y += 70
    im.save(g / name, quality=88)


shot("IMG-20261110-WA0011.jpg", "Meezan Bank", 25000, "Daddy Mobilink", "MBL5521")
shot("IMG-20261110-WA0012.jpg", "Meezan Bank", 40000, "Daddy Mobilink", "MBL5530")
shot("Screenshot_20261111-101500.png", "Meezan Bank", 12500, "Shahida Khala", "MBL5602")
shot("IMG-20261112-WA0020.jpg", "HBL", 60000, "Khan Traders", "HBL8891")
for n in ("IMG-20261110-WA0011.jpg", "IMG-20261110-WA0012.jpg", "Screenshot_20261111-101500.png"):
    mark(n, "meezan")
mark("IMG-20261112-WA0020.jpg", "hbl")
mark("IMG-20261110-WA0011.jpg", "meezan", "daddy"); mark("IMG-20261110-WA0012.jpg", "meezan", "daddy")

if "--pack" in sys.argv:
    out = Path(sys.argv[sys.argv.index("--pack") + 1]); out.mkdir(parents=True, exist_ok=True)
    for f in g.iterdir():
        shutil.copy2(f, out / f.name)

# 3) index exactly as Jarvis does for WhatsApp files
r = d.reindex(tools.CTX["cfg"])
print(f"indexed {r['total']} files sent to the '{GROUP}' group")

S = lambda t: t["type"] == "sales invoice"  # noqa: E731
W = lambda f: {t["name"] for t in T if f(t)}  # noqa: E731
X = lambda lab: {n for n, ls in extra.items() if lab in ls}  # noqa: E731


def latest(f, k=1):
    return {t["name"] for t in sorted([t for t in T if f(t)], key=lambda t: t["date"], reverse=True)[:k]}


Q = [
    ("Documents", "quotations we sent to Bilal Steel Mills", W(lambda t: t["type"] == "quotation" and t["client"] == "Bilal Steel Mills")),
    ("Documents", "all the invoices of Khan", W(lambda t: t["type"] in ("sales invoice", "purchase invoice") and t["client"] in ("Khan Traders", "Khan Trading Company"))),
    ("Documents", "latest sales invoice for Zahid and Sons", latest(lambda t: S(t) and t["client"] == "Zahid & Sons")),
    ("Documents", "the most recent quotation", latest(lambda t: t["type"] == "quotation")),
    ("Amounts", "sales invoices above 3 lakh", W(lambda t: S(t) and t["amount"] > 300000)),
    ("Amounts", "quotations under 50k", W(lambda t: t["type"] == "quotation" and t["amount"] < 50000)),
    ("Documents", "receipts from Faisal Construction", W(lambda t: t["type"] == "receipt" and t["client"] == "Faisal Construction")),
    ("Documents", "all delivery challans", W(lambda t: t["type"] == "delivery challan")),
    ("Documents", "purchase invoices", W(lambda t: t["type"] == "purchase invoice")),
    ("Documents", "credit notes", W(lambda t: t["type"] == "credit note")),
    ("Numbers", "invoice INV-1007", W(lambda t: t["number"] == "INV-1007")),
    ("Numbers", "quotation QT-1021", W(lambda t: t["number"] == "QT-1021")),
    ("Dates", "sales invoices march 2026", W(lambda t: S(t) and t["date"].startswith("2026-03"))),
    ("Urdu", "زاہد اینڈ سنز کی تمام سیلز انوائس", W(lambda t: S(t) and t["client"] == "Zahid & Sons")),
    ("Roman Urdu", "Zahid & Sons ki sari sales invoices dikhao", W(lambda t: S(t) and t["client"] == "Zahid & Sons")),
    ("Group named", "receipts from the Apricot Digital group", W(lambda t: t["type"] == "receipt")),
    ("Word file", "shop rent agreement", X("rent")),
    ("Excel", "salary sheet october", X("salary")),
    ("CSV", "tyre price list", X("tyre")),
    ("PowerPoint", "company profile presentation", X("profile")),
    ("ODT", "NOC letter", X("noc")),
    ("Text", "meeting notes with bilal steel", X("meeting")),
    ("Folder (zip)", "Project Alpha folder", X("alpha")),
    ("Inside a folder", "scope of work", X("scope")),
    ("Screenshot", "meezan bank screenshots", X("meezan")),
    ("Screenshot", "meezan bank payment to daddy mobilink", X("daddy")),
    ("Screenshot", "HBL payment screenshot", X("hbl")),
]

rows, by_area = [], {}
if "--debug" in sys.argv:
    db = d._db(); print(db.execute("select name,text,doc_type,ext from docs where name like ?", ("IMG-2026111%",)).fetchall()); db.close()
for area, q, exp in Q:
    r = d.search(q, "any")
    got = {Path(i["path"]).name for i in r["items"]}
    tp = len(got & exp)
    p = tp / len(got) if got else (1.0 if not exp else 0.0)
    rc = tp / len(exp) if exp else 1.0
    f1 = 0 if p + rc == 0 else 2 * p * rc / (p + rc)
    rows.append((area, q, len(got), len(exp), p, rc, f1, r["mode"], sorted(got - exp)[:3], sorted(exp - got)[:3]))
    by_area.setdefault(area, []).append(f1)
for area, q, ng, ne, p, rc, f1, mode, wrong, missed in rows:
    flag = "OK " if f1 == 1 else ("~  " if f1 >= 0.5 else "BAD")
    print(f"{flag} {area:15} P={p:.2f} R={rc:.2f} got {ng:2}/{ne:2} [{mode}] {q}")
    if f1 < 1:
        print(f"      wrong: {wrong}  missed: {missed}")
score = sum(x[6] for x in rows) / len(rows)
print(f"\nexact answers: {sum(1 for x in rows if x[6] == 1)}/{len(rows)}   mean F1 {score:.2f}   RATING {score * 10:.1f}/10")
