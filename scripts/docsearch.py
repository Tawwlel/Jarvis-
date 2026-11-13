"""
Document finder: invoices, quotations, receipts, photos and files, from the computer or from
WhatsApp, with the rule the client asked for:

  * "all sales invoices"                 -> everything of that type
  * a client name / description / amount -> only the matching files (and "close" matches
                                            are labelled as such)

Sources:
  computer  - the user's allowed folders (config: file_roots + doc_folders)
  whatsapp  - data/whatsapp/<chat name>/<files>, filled by the WhatsApp reader (read-only)

Everything stays on this computer. The index lives in data/docs.db.
"""
import difflib
import json
import re
import sys
import shutil
import sqlite3
import threading
import time
from pathlib import Path

from tools import CTX, tool

DATA = Path(__file__).parent.parent / "data"
WA_DIR = DATA / "whatsapp"
EMAIL_DIR = DATA / "email_docs"  # attachments saved by the email agent, one folder per sender
OUT_DIR = Path.home() / "Documents" / "Jarvis Files"
# Every kind of document Jarvis reads, on the computer, in WhatsApp and in email (whatsapp_reader / email_agent import this).
EXTS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".pptx", ".ppt", ".odt", ".zip", ".rar",
        ".jpg", ".jpeg", ".png", ".webp", ".heic", ".txt"}
IMG = {".jpg", ".jpeg", ".png", ".webp"}
SKIP = {"node_modules", "__pycache__", "venv", ".venv", "AppData", "$RECYCLE.BIN", "Jarvis Files", "site-packages",
        "SAVEDATA", "PPSSPP", "Program Files", "Program Files (x86)", "Windows"}

TYPES = {  # canonical type -> words that mean it (checked longest first)
    "sales invoice": ["sales invoice", "sale invoice", "sales inv", "tax invoice", "sales bill", "sales invoices",
                      "sale invoices", "سیلز انوائس", "فروخت کا انوائس", "سیل انوائس", "سیلز انوائسز"],
    "purchase invoice": ["purchase invoice", "purchase invoices", "purchase bill", "supplier invoice",
                         "vendor invoice", "خریداری انوائس", "پرچیز انوائس"],
    "credit note": ["credit note", "credit notes", "credit memo", "کریڈٹ نوٹ"],
    "delivery challan": ["delivery challan", "delivery challans", "challan", "challans", "delivery note",
                         "gate pass", "چالان", "ڈیلیوری چالان"],
    "purchase order": ["purchase order", "purchase orders", "po", "پرچیز آرڈر"],
    "quotation": ["quotation", "quote", "quotes", "quotations", "price quote", "estimate", "estimates",
                  "کوٹیشن", "کوٹیشنز"],
    "proforma invoice": ["proforma invoice", "pro forma invoice", "proforma", "pro forma", "performa invoice",
                         "پرو فارما"],
    "debit note": ["debit note", "debit notes", "debit memo", "ڈیبٹ نوٹ"],
    "statement of account": ["statement of account", "statement of accounts", "account statement", "customer statement",
                             "supplier statement", "bank statement", "soa", "اکاؤنٹ اسٹیٹمنٹ", "گوشوارہ"],
    "purchase requisition": ["purchase requisition", "purchase requisitions", "requisition", "purchase request",
                             "material requisition"],
    "sales order": ["sales order", "sales orders", "sale order", "so confirmation", "order confirmation", "سیلز آرڈر"],
    "bill of lading": ["bill of lading", "bills of lading", "house bill of lading", "master bill of lading", "bol"],
    "nda": ["non disclosure", "nondisclosure", "nda", "confidentiality agreement", "نان ڈسکلوژر"],
    "vendor contract": ["vendor contract", "supplier contract", "vendor agreement", "supplier agreement",
                        "service agreement", "master services agreement", "msa"],
    "terms of service": ["terms of service", "terms of use", "terms and conditions", "terms conditions", "tos", "t c"],
    "mou": ["memorandum of understanding", "mou", "m o u", "یادداشت"],
    "license or permit": ["license", "licence", "licenses", "licences", "permit", "permits", "noc",
                          "registration certificate", "لائسنس", "پرمٹ"],
    "articles of incorporation": ["articles of incorporation", "articles of association", "memorandum of association",
                                  "certificate of incorporation", "moa", "aoa"],
    "business plan": ["business plan", "business plans", "feasibility report", "کاروباری منصوبہ"],
    "meeting minutes": ["meeting minutes", "minutes of meeting", "minutes of the meeting", "minutes of meetings",
                        "minutes", "mom", "میٹنگ منٹس"],
    "bylaws": ["bylaws", "by laws", "bye laws", "byelaws"],
    "employment contract": ["employment contract", "employment agreement", "contract of employment",
                            "appointment letter", "offer letter", "ملازمت کا معاہدہ"],
    "job description": ["job description", "job descriptions", "jd", "job profile", "role description"],
    "employee handbook": ["employee handbook", "staff handbook", "employee manual", "hr manual", "hr policy",
                          "handbook"],
    "performance appraisal": ["performance appraisal", "performance review", "appraisal", "performance evaluation",
                              "annual review"],
    "receipt": ["receipt", "receipts", "payment receipt", "payment slip", "voucher", "رسید", "رسیدیں"],
    "invoice": ["invoice", "invoices", "inv", "bill", "bills", "انوائس", "انوائسز", "بل"],
    "agreement": ["agreement", "agreements", "contract", "contracts", "rent deed", "معاہدہ", "معاہدے", "کرایہ نامہ",
                  "اقرار نامہ"],
}
TYPE_ORDER = ["sales invoice", "purchase invoice", "proforma invoice", "credit note", "debit note", "delivery challan",
              "bill of lading", "purchase requisition", "purchase order", "sales order", "quotation",
              "statement of account", "receipt", "invoice", "agreement"]
# Formal documents are recognised by their title (file name or first words), so an NDA that mentions "invoice date"
# in its terms is still an NDA. Most specific first; plain "agreement" last.
FORMAL = ["employment contract", "nda", "mou", "terms of service", "vendor contract", "articles of incorporation",
          "bylaws", "employee handbook", "performance appraisal", "job description", "business plan",
          "meeting minutes", "license or permit", "agreement"]
NOT_MONEY = set(FORMAL) - {"agreement", "vendor contract"}  # no invoice-style total to read from these
NOT_DOCS = re.compile(r"curriculum vitae|\bresume\b|\bcv\b|price list|meeting notes|\bagenda\b", re.I)
STOP = set("""a an the of for from to by with in on at and or me my find show get give all every any
file files document documents doc docs pdf photo photos picture pictures image images client clients
please can you jarvis look up lookup search send those these that this is are was were i want need
details detail items item whatsapp computer laptop pc folder compile compiled specific named called
company's customer customers rs pkr rupees amount total worth of
we us our ours i i'm im he she they them their his her him it its which what where who whom whose when
did do does done have has had having was be been being made make sent gave give given got received issued
created prepared shared there here one ones some just also only same kindly pls plz thanks thank
could would should will shall can't cant tell list bring pull open check see view know related regarding
about against under over above below upto than more less least most new old
ki ka ke ko se mein main mai me aur bhi sari saari sara sare saare sab dikhao dikha dikhado do mujhe mujhay
mera meri mere hamara hamari wali wala wale hai hain tha thi thy zara yaar bhai jo jis kis kya kahan
 اینڈ اور بھی مجھے میرا میری میرے ہمارا ہماری ہے ہیں تھا تھی جو جس کس کیا کہاں ذرا
 کا کی کے سے میں پر کو کلائنٹ تمام سب دکھاؤ دکھائیں تلاش ڈھونڈو ڈھونڈیں فائل فائلیں واٹس ایپ کمپیوٹر والی والے""".split())
STOP |= set("""nikalo nikal nikaalo nikaal dikha dikhao dikhaein dikhayen batao bata sunao kul kitni kitna kitne hui hua huwa hue
ki ka ke ko se par pe mein main wali wala wale ne jo thi tha thay woh wo yeh ye aur bhi saari sari sab tamam chahiye chahye
do dedo de karo kar kardo ho hain hai ka total batana dhoondo dhundo dhoond talash kholo khol bhejo jama daal
mujhe mujhay hamari hamara apni apna apne unki unka iska iski uska uski zara please plz""".split())
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
UR_MONTHS = ["جنوری", "فروری", "مارچ", "اپریل", "مئی", "جون", "جولائی", "اگست", "ستمبر", "اکتوبر", "نومبر", "دسمبر"]
MON_ALIAS = {m[:3]: i for i, m in enumerate(MONTHS)} | {m: i for i, m in enumerate(MONTHS)} | \
            {m: i for i, m in enumerate(UR_MONTHS)} | {"sept": 8}


def _db():
    DATA.mkdir(exist_ok=True)
    c = sqlite3.connect(DATA / "docs.db", timeout=15)
    try:
        c.execute("PRAGMA journal_mode=WAL")  # searches keep answering while a scan is writing
    except sqlite3.DatabaseError:
        pass
    cols = [r[1] for r in c.execute("PRAGMA table_info(docs)").fetchall()]
    if cols and ("doc_date" not in cols or "fields" not in cols):
        c.execute("DROP TABLE docs")  # older index format: rebuild it (also re-reads photos for Urdu)
    c.execute("""CREATE TABLE IF NOT EXISTS docs(path TEXT PRIMARY KEY, source TEXT, chat TEXT, name TEXT,
                 ext TEXT, mtime REAL, size INTEGER, text TEXT, doc_type TEXT, amount TEXT, doc_date TEXT,
                 v2 INTEGER, fields TEXT)""")
    c.execute("CREATE TABLE IF NOT EXISTS prefs(key TEXT, path TEXT, n INTEGER, PRIMARY KEY(key, path))")  # files the owner confirmed for a request
    c.execute("CREATE TABLE IF NOT EXISTS hashes(path TEXT PRIMARY KEY, h TEXT)")  # content fingerprints: same file, different names
    _migrate(c)
    return c


INDEX_REV = 4  # bump when classify/find_date/junk rules change: stored rows are re-labelled from their saved text


def _migrate(c):
    c.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    row = c.execute("SELECT v FROM meta WHERE k='rev'").fetchone()
    if row and row[0] == str(INDEX_REV):
        return
    try:
        for path, name, text, mtime in c.execute("SELECT path,name,text,mtime FROM docs").fetchall():
            if _junk(name):
                c.execute("DELETE FROM docs WHERE path=?", (path,))
                continue
            text = text or ""
            c.execute("UPDATE docs SET doc_type=?, doc_date=? WHERE path=?",
                      (classify(name, text), find_date(name, text, mtime or 0), path))
        c.execute("REPLACE INTO meta VALUES('rev',?)", (str(INDEX_REV),))
        c.commit()
    except sqlite3.DatabaseError as e:
        print("[docs] migrate:", e)


# ---------------- reading files ----------------
_rapid = {}


def _ocr(img) -> str:
    """English/number text with RapidOCR, plus Urdu with the Urdu reader (both kept, so either language finds it)."""
    latin = ""
    try:
        from rapidocr_onnxruntime import RapidOCR
        import numpy as np
        if "eng" not in _rapid:
            _rapid["eng"] = RapidOCR()  # load the model once, not per picture
        res, _ = _rapid["eng"](np.array(img.convert("RGB")))
        latin = " ".join(r[1] for r in (res or []))
    except Exception:
        pass
    urdu = ""
    try:
        import urdu_ocr
        if urdu_ocr.available():
            u = urdu_ocr.read(img)
            if urdu_ocr.has_urdu(u):
                urdu = u
            elif not latin:
                latin = u  # no RapidOCR: Tesseract's English is better than nothing
    except Exception:
        pass
    if not latin and not urdu:
        try:
            import pytesseract
            latin = pytesseract.image_to_string(img)
        except Exception:
            pass
    head = _ocr_header(img)
    if head:
        have = set(re.findall(r"\w+", latin.lower()))
        new = [w for w in head.split() if w.lower() not in have]
        if new:
            latin = " ".join(new) + "\n" + latin
    return (latin + "\n" + urdu).strip()


def _ocr_header(img) -> str:
    """Bank apps print their name in white on a coloured bar (Meezan, HBL, JazzCash...): readers miss it. Read the
    top band again as dark text on white."""
    try:
        from PIL import ImageOps, ImageStat
        w, h = img.size
        if h < 200:
            return ""
        band = img.convert("L").crop((0, 0, w, max(60, int(h * 0.16))))
        if ImageStat.Stat(band).mean[0] >= 140:
            return ""  # already dark text on a light bar: the first read had it
        band = ImageOps.autocontrast(ImageOps.invert(band))
        band = band.resize((band.width * 2, band.height * 2))
        txt = ""
        try:
            from rapidocr_onnxruntime import RapidOCR
            import numpy as np
            if "eng" not in _rapid:
                _rapid["eng"] = RapidOCR()
            res, _ = _rapid["eng"](np.array(band.convert("RGB")))
            txt = " ".join(r[1] for r in (res or []))
        except Exception:
            pass
        if not txt:
            import pytesseract
            txt = pytesseract.image_to_string(band)
        return " ".join(txt.split())[:200]
    except Exception:
        return ""


PDF_PAGES, PDF_OCR_PAGES = 60, 6  # text of the first 60 pages; up to 6 scanned pages read as pictures
MAX_MB = {".pdf": 80, ".docx": 40, ".xlsx": 40, ".doc": 40, ".xls": 40, ".pptx": 80, ".ppt": 80, ".odt": 40,
          ".zip": 150, ".rar": 150}
IMG_MIN_BYTES, IMG_MAX_BYTES, IMG_MAX_SIDE = 12_000, 40_000_000, 2200
FILE_SECONDS = 90  # one file that takes longer than this is skipped, never allowed to stall a scan


def _cloud_only(p: Path) -> bool:
    """OneDrive 'online-only' files: reading them would download them. Index by name only."""
    try:
        attrs = getattr(p.stat(), "st_file_attributes", 0)
        return bool(attrs & (0x1000 | 0x400000 | 0x40000))  # OFFLINE | RECALL_ON_DATA_ACCESS | RECALL_ON_OPEN
    except OSError:
        return False


def extract_text(p: Path) -> str:
    """Text of a file, safely. Never raises, never reads a huge file whole, gives up after FILE_SECONDS."""
    import concurrent.futures as cf
    try:
        size = p.stat().st_size
    except OSError:
        return ""
    ext = p.suffix.lower()
    if _cloud_only(p) or size > MAX_MB.get(ext, 10_000) * 1_000_000 and ext in MAX_MB:
        return ""
    if ext in IMG and not IMG_MIN_BYTES <= size <= IMG_MAX_BYTES:
        return ""  # icons/stickers carry no document; giant images are not documents
    box = {}
    th = threading.Thread(target=lambda: box.update(t=_extract(p, ext)), daemon=True)
    th.start()
    th.join(FILE_SECONDS)
    if th.is_alive():
        print(f"[docs] skipped (took too long): {p.name}")
        return ""
    return box.get("t", "")


def _zip_xml_text(p: Path, prefixes) -> str:
    """Text of .pptx slides / .odt content: they are zip files of XML, so no extra library is needed."""
    import zipfile
    out = []
    with zipfile.ZipFile(p) as z:
        names = sorted(n for n in z.namelist() if n.startswith(prefixes) and n.endswith(".xml"))
        for n in names[:200]:
            if z.getinfo(n).file_size > 20_000_000:
                continue
            xml = z.read(n).decode("utf-8", "ignore")
            out.append(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", xml)))
    return " ".join(out)


def _binary_strings(p: Path) -> str:
    """Old .doc/.ppt (binary): the readable text runs inside the file, good enough to find a document by."""
    data = p.read_bytes()[:30_000_000]
    runs = re.findall(rb"[\x20-\x7e\xa0-\xff]{5,}", data) + [r.decode("utf-16le", "ignore").encode()
                                                          for r in re.findall(rb"(?:[\x20-\x7e]\x00){5,}", data)]
    txt = " ".join(r.decode("cp1252", "ignore") for r in runs)
    return re.sub(r"\s+", " ", txt)[:30000]


ARCHIVE_DOCS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".pptx", ".ppt", ".odt", ".jpg", ".jpeg", ".png", ".txt"}


def _archive_text(p: Path, ext: str) -> str:
    """A .zip/.rar: its file names plus the text of the documents inside (a few, size-limited, never executed)."""
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="jarvis_arc_"))
    try:
        names, picked = [], []
        if ext == ".zip":
            import zipfile
            z = zipfile.ZipFile(p)
            infos = [i for i in z.infolist() if not i.is_dir()]
            names = [i.filename for i in infos]
            budget = 200_000_000
            for i in infos:
                if len(picked) >= 40 or i.file_size > 40_000_000 or budget - i.file_size < 0 or i.flag_bits & 1:
                    continue  # too many/too big (zip bombs) or password-protected
                if Path(i.filename).suffix.lower() in ARCHIVE_DOCS and not _junk(Path(i.filename).name):
                    budget -= i.file_size
                    dest = tmp / f"{len(picked)}{Path(i.filename).suffix.lower()}"
                    with z.open(i) as src, open(dest, "wb") as out:
                        shutil.copyfileobj(src, out)
                    picked.append((i.filename, dest))
        else:
            names, picked = _rar_members(p, tmp)
        parts = ["[files: " + ", ".join(names[:200]) + "]"]
        for fn, dest in picked:
            t = _extract(dest, dest.suffix.lower())
            if t.strip():
                parts.append(f"[{fn}] {t[:4000]}")
        return "\n".join(parts)[:30000]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _rar_members(p: Path, tmp: Path):
    """RAR needs an unpacker: the 'rarfile' module with UnRAR, or Windows' own tar (it reads RAR). Names only if neither works."""
    try:
        import rarfile
        r = rarfile.RarFile(str(p))
        infos = [i for i in r.infolist() if not i.is_dir()]
        names, picked = [i.filename for i in infos], []
        for i in infos:
            if len(picked) < 40 and i.file_size <= 40_000_000 and Path(i.filename).suffix.lower() in ARCHIVE_DOCS:
                dest = tmp / f"{len(picked)}{Path(i.filename).suffix.lower()}"
                dest.write_bytes(r.read(i))
                picked.append((i.filename, dest))
        return names, picked
    except Exception:
        pass
    import subprocess
    try:
        flags = 0x08000000 if sys.platform == "win32" else 0  # no console window
        lst = subprocess.run(["tar", "-tf", str(p)], capture_output=True, text=True, timeout=60, creationflags=flags)
        names = [n for n in lst.stdout.splitlines() if n and not n.endswith("/")]
        subprocess.run(["tar", "-xf", str(p), "-C", str(tmp)], capture_output=True, timeout=120, creationflags=flags)
        picked = []
        for f in tmp.rglob("*"):
            if len(picked) < 40 and f.is_file() and f.suffix.lower() in ARCHIVE_DOCS and f.stat().st_size <= 40_000_000:
                picked.append((str(f.relative_to(tmp)), f))
        return names, picked
    except Exception:
        return [], []


def _extract(p: Path, ext: str) -> str:
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            r = PdfReader(str(p))
            if r.is_encrypted:
                try:
                    r.decrypt("")
                except Exception:
                    return ""  # password-protected: known by name only
            pages = r.pages[:PDF_PAGES]
            texts = [(pg.extract_text() or "") for pg in pages]
            # scanned pages (no text layer) are read as pictures: the first few of them, so a scanned invoice is found
            blank = [i for i, x in enumerate(texts) if len(x.strip()) < 20][:PDF_OCR_PAGES]
            if blank:
                import pypdfium2 as pdfium
                doc = pdfium.PdfDocument(str(p))
                for i in blank:
                    texts[i] = _ocr(doc[i].render(scale=2).to_pil())
            return " ".join(texts)
        if ext in IMG:
            from PIL import Image
            Image.MAX_IMAGE_PIXELS = 60_000_000  # bigger than this is refused (decompression bombs)
            im = Image.open(p)
            im.draft("RGB", (IMG_MAX_SIDE, IMG_MAX_SIDE))  # JPEGs decode at reduced size: much faster
            if max(im.size) > IMG_MAX_SIDE:
                im.thumbnail((IMG_MAX_SIDE, IMG_MAX_SIDE))
            return _ocr(im)
        if ext == ".docx":
            import docx
            d = docx.Document(str(p))
            cells = [c.text for t in d.tables for r in t.rows for c in r.cells]  # invoices keep their figures in tables
            return " ".join([x.text for x in d.paragraphs] + cells)
        if ext in (".pptx", ".odt"):
            return _zip_xml_text(p, ("ppt/slides/slide", "ppt/notesSlides/") if ext == ".pptx" else ("content.xml",))
        if ext in (".doc", ".ppt"):
            return _binary_strings(p)
        if ext == ".xls":
            try:
                import xlrd
                wb = xlrd.open_workbook(str(p), on_demand=True)
                out = []
                for ws in list(wb.sheets())[:3]:
                    for r in range(min(ws.nrows, 60)):
                        out += [str(c) for c in ws.row_values(r) if c not in ("", None)]
                return " ".join(out)
            except Exception:
                return _binary_strings(p)
        if ext in (".zip", ".rar"):
            return _archive_text(p, ext)
        if ext == ".xlsx":
            import openpyxl
            wb = openpyxl.load_workbook(str(p), read_only=True, data_only=True)
            out = []
            for ws in wb.worksheets[:3]:
                for row in ws.iter_rows(max_row=60, values_only=True):
                    out += [str(c) for c in row if c is not None]
            return " ".join(out)
        if ext in (".txt", ".csv"):
            with open(p, "r", errors="ignore") as f:
                return f.read(20000)  # the start only: never the whole of a 2 GB log
    except Exception:
        pass
    return ""


_DIGITS = str.maketrans("\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9"  # Urdu/Persian digits
                        "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669",  # Arabic-Indic digits
                        "0123456789" * 2)
_OCR_FIX = str.maketrans("OoIlSsBZ", "00115582")  # what OCR confuses with digits


def _norm(s: str) -> str:
    return re.sub(r"[_\-\.]+", " ", s.translate(_DIGITS).lower())


def _ocr_numbers(text: str) -> str:
    """Words made of digits plus look-alike letters ("l148", "INV-O012", "5O00") also written with real digits, so a
    scanned document is found by its number even when the OCR misread a character."""
    out = []
    for w in re.findall(r"[A-Za-z0-9]{3,}", text):
        if re.search(r"\d", w) and re.search(r"[OoIlSsBZ]", w):
            fixed = w.translate(_OCR_FIX)
            digits = re.sub(r"\D", "", fixed)
            if len(digits) >= 3 and fixed.lower() != w.lower():
                out.append(fixed.lower())
                m = re.search(r"\d{3,}", fixed)
                if m:
                    out.append(m.group())
    return " ".join(out)


def _has(words, hay):
    return any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", hay) for w in words)


DOC_NO = re.compile(r"\b(?:inv|qt|quo|po|pinv|rcpt|rec|dc|cn|so|bill)[-#/ ]?\d{2,}", re.I)


def classify(name: str, text: str) -> str:
    """Type from the file name first, then the document's heading (first few lines) - never from
    anywhere in the text, so a CV that mentions 'sales invoices' is not a sales invoice.
    Spreadsheets/lists holding many document numbers are 'register' (an invoice list, not an invoice)."""
    fname = _norm(Path(name).stem)
    head = " ".join(text.lower().split()[:40])
    if re.match(r"screenshot|screen shot|snip", fname):
        return "screenshot"
    if NOT_DOCS.search(fname + " " + head):
        return ""
    if len(set(m.lower() for m in DOC_NO.findall(text))) >= 3 or re.search(r"\b(list|register|ledger|summary)\b", fname):
        return "register"
    def first(hay):
        return next((typ for typ in TYPE_ORDER if _has(TYPES[typ], hay)), "")
    title = _norm(" ".join(text.lower().split()[:6]))
    for typ in FORMAL:  # (the plain word "agreement" is last, so "agreement.pdf" titled "Non-Disclosure Agreement" is an NDA)
        if _has(TYPES[typ], title):
            return typ
    for typ in FORMAL:
        if _has(TYPES[typ], fname):
            return typ  # an agreement that mentions "invoice date" in its terms is not an invoice
    by_name, by_head = first(fname), first(head)
    if Path(name).suffix.lower() in (".xlsx", ".xls", ".csv") and not by_name:
        # a workbook that merely mentions invoices in its first cells is a list/worksheet, not an invoice
        # a real invoice/credit-note workbook carries its own number ("Credit No: CN-1326", "Invoice #12");
        # a worksheet that only mentions invoices does not
        numbered = DOC_NO.search(text) or re.search(r"\b(invoice|inv|credit|quotation|quote|receipt|order|challan|bill)\s*(no|number|#)", head)
        return by_head if (by_head and numbered) else ("register" if by_head else "")
    # a specific type in the file name wins; a bare "inv"/"invoice" name defers to the heading
    if by_name and by_name != "invoice":
        return by_name
    return by_head or by_name


_CUR = r"(?:pkr|rs\.?|rupees|usd|aed|sar|\$|£|€|روپے|روپیہ|روپ)"
_AMT = r"(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d{3,}(?:\.\d+)?)"


def find_amount(text: str) -> str:
    """The document's total: a currency amount on a total/amount line first, then the
    largest currency amount, then any 3+ digit number after a total/amount label."""
    t = text.lower()
    def clean(v):
        return v.replace(",", "").removesuffix(".00").rstrip(".")
    lines = t.splitlines()
    for i, line in enumerate(lines):
        if re.search(r"grand total|total amount|amount received|amount paid|amount due|total|amount|net payable"
                     r"|کل رقم|کل|رقم|ٹوٹل|میزان", line):
            for cand in (line, lines[i + 1] if i + 1 < len(lines) else ""):  # value may sit on the next line
                m = re.search(rf"{_CUR}\s*{_AMT}", cand) or re.search(rf"{_AMT}\s*{_CUR}", cand)
                if m:
                    return clean(m.group(1))
    cur = [clean(v) for v in re.findall(rf"{_CUR}\s*{_AMT}", t)]
    if cur:
        return max(cur, key=float)
    m = re.findall(rf"(?:grand total|total|amount|net payable|کل رقم|ٹوٹل|رقم)\D{{0,15}}{_AMT}", t)
    return clean(m[-1]) if m else ""


def find_date(name: str, text: str, mtime: float) -> str:
    """Document date as YYYY-MM-DD: from the text, then the file name (WhatsApp names carry it), then mtime."""
    t = text[:3000].lower()
    m = re.search(r"\b(20\d\d)[-/.](\d{1,2})[-/.](\d{1,2})\b", t)
    if m:
        y, mo, d = map(int, m.groups())
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.search(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](20\d\d)\b", t)  # Pakistani style DD/MM/YYYY
    if m:
        d, mo, y = map(int, m.groups())
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.search(r"\b(\d{1,2})[\s-]+([a-z]{3,9})[,\s-]+(20\d\d)\b", t)
    if m and m.group(2)[:3] in MON_ALIAS:
        return f"{m.group(3)}-{MON_ALIAS[m.group(2)[:3]] + 1:02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b([a-z]{3,9})\.?\s+(\d{1,2}),?\s+(20\d\d)\b", t)  # Nov 4, 2026
    if m and m.group(1)[:3] in MON_ALIAS:
        return f"{m.group(3)}-{MON_ALIAS[m.group(1)[:3]] + 1:02d}-{int(m.group(2)):02d}"
    m = re.search(r"(?<!\d)(20\d\d)[-_. ]?(\d\d)[-_. ]?(\d\d)(?!\d)", name)  # WhatsApp Image 2026-11-11 / IMG_20261111
    if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(3)) <= 31:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return time.strftime("%Y-%m-%d", time.localtime(mtime))


def _date_words(d: str) -> str:
    try:
        y, mo, _ = d.split("-")
        return f" {y} {MONTHS[int(mo) - 1]} {MONTHS[int(mo) - 1][:3]} {UR_MONTHS[int(mo) - 1]} "
    except Exception:
        return ""


# ---------------- indexing ----------------
def _folders(cfg: dict) -> list[Path]:
    import files
    extra = [Path(p).expanduser() for p in cfg.get("doc_folders", [])]
    try:  # folders the owner allowed Jarvis to scan (see deep_scan.py)
        import deep_scan
        extra += deep_scan.extra_folders()
    except Exception:
        pass
    out, seen = [], set()
    for p in files.roots() + extra:
        if p.exists() and str(p.resolve()) not in seen:
            seen.add(str(p.resolve()))
            out.append(p)
    return out


def _generic_name(name: str) -> bool:
    """Camera/WhatsApp/scanner file names that say nothing about the document."""
    return bool(re.match(r"(?i)(doc|img|vid|ptt|scan|image|photo|whatsapp image|whatsapp document)[-_ ]?\d", name))


def _fingerprint(p: Path) -> str:
    """Cheap content fingerprint (size + first MB): a PDF forwarded on WhatsApp and also attached to an email is one document."""
    import hashlib
    try:
        with open(p, "rb") as f:
            return hashlib.sha1(f.read(1_000_000) + str(p.stat().st_size).encode(), usedforsecurity=False).hexdigest()
    except OSError:
        return ""


def _junk(name: str) -> bool:
    """Office lock files (~$x.docx), editor backups and system files are never documents."""
    n = name.lower()
    return n.startswith(("~$", ".~", "~wr")) or n in ("thumbs.db", "desktop.ini", "icon0.png")


def _walk(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in EXTS:
            rel = p.relative_to(root).parts
            if any(x.startswith(".") or x in SKIP for x in rel[:-1]) or _junk(p.name):
                continue
            yield p


def reindex(cfg: dict, include_computer=True, include_whatsapp=True, progress=None, include_email=True) -> dict:
    db, seen, added = _db(), set(), 0
    light = _light()
    jobs = []
    if include_computer:
        jobs += [("computer", r, None) for r in _folders(cfg)]
    if include_whatsapp and WA_DIR.exists():
        jobs += [("whatsapp", WA_DIR, "chat")]
    if include_email and EMAIL_DIR.exists():
        jobs += [("email", EMAIL_DIR, "chat")]
    for source, root, mode in jobs:
        for p in _walk(root):
            key = str(p)
            seen.add(key)
            st = p.stat()
            row = db.execute("SELECT mtime,size FROM docs WHERE path=?", (key,)).fetchone()
            if row and abs(row[0] - st.st_mtime) < 1 and row[1] == st.st_size:
                if not db.execute("SELECT 1 FROM hashes WHERE path=?", (key,)).fetchone():
                    db.execute("REPLACE INTO hashes VALUES(?,?)", (key, _fingerprint(p)))  # older rows get theirs too
                continue
            db.execute("REPLACE INTO hashes VALUES(?,?)", (key, _fingerprint(p)))
            text = "" if light else extract_text(p)  # light mode: remember the location only, read when asked
            chat = p.relative_to(root).parts[0] if mode == "chat" and len(p.relative_to(root).parts) > 1 else ""
            typ = classify(p.name, text)
            fields = _fields(text, p.name, typ)
            cat = json.loads(fields).get("category") if fields else None
            if cat:  # "petrol receipts" should find a Shell receipt that never says "petrol"
                text = text + "\n[" + CAT_WORDS.get(cat, cat.lower()) + "]"
            db.execute("REPLACE INTO docs VALUES(?,?,?,?,?,?,?,?,?,?,?,1,?)",
                       (key, source, chat, p.name, p.suffix.lower(), st.st_mtime, st.st_size, text[:30000],
                        typ, "" if typ in NOT_MONEY else find_amount(text), find_date(p.name, text, st.st_mtime), fields))
            added += 1
            time.sleep(0.002)  # let a waiting question through: scans must never make answers slow
            if added % 5 == 0:  # save as we go: a big first scan is searchable early and survives a crash
                db.commit()
                if progress and added % 100 == 0:
                    progress(added)
    scope = tuple(s for s, ok in (("computer", include_computer), ("whatsapp", include_whatsapp),
                                                 ("email", include_email and EMAIL_DIR.exists())) if ok)
    for (path,) in db.execute(f"SELECT path FROM docs WHERE source IN ({','.join('?' * len(scope))})", scope).fetchall():
        if path not in seen:
            db.execute("DELETE FROM docs WHERE path=?", (path,))
    db.commit()
    total = db.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    db.close()
    return {"added": added, "total": total}


CAT_WORDS = {"Fuel": "fuel petrol diesel پٹرول", "Groceries": "groceries grocery sauda سودا", "Food": "food khana کھانا",
             "Medical": "medical medicine dawai دوائی", "Utilities": "utility bill bijli بجلی",
             "Transport": "transport travel kiraya کرایہ", "Office supplies": "office stationery",
             "Hardware & building": "hardware building material"}


def _fields(text, name, typ) -> str:
    """Exact invoice/receipt details (number, total, tax, customer...) as JSON - see invoice_fields.py."""
    if typ in ("other", "cv", "register") or typ in NOT_MONEY or not text:
        return ""
    try:
        import invoice_fields
        return json.dumps(invoice_fields.extract(text, name, typ), ensure_ascii=False)
    except Exception as e:
        print("[docs] fields:", e)
        return ""


def refresh_fields():
    """Re-read details of every indexed document (after a new invoice layout was learned)."""
    db = _db()
    for path, text, name, typ in db.execute("SELECT path,text,name,doc_type FROM docs").fetchall():
        db.execute("UPDATE docs SET fields=? WHERE path=?", (_fields(text, name, typ), path))
    db.commit()
    db.close()


# ---------------- searching ----------------
def _relative_dates(q: str) -> str:
    """'last month' -> 'october 2026' etc., so dates match like any other word."""
    import datetime as dt
    today = dt.date.today()

    def mon(d):
        return f" {MONTHS[d.month - 1]} {d.year} "
    first = today.replace(day=1)
    def rng(a, b):  # an exact day range, picked up by parse_filters
        return f" zzrange {a:%Y%m%d} {b:%Y%m%d} "
    monday = today - dt.timedelta(days=today.weekday())
    day = dt.timedelta(days=1)
    m = re.search(r"\b(?:last|past|pichh?le|pichlay|guzishta)\s+(\d{1,3})\s+(?:days?|din|dino+n?)\b", q)
    if m:
        q = q[:m.start()] + rng(today - int(m.group(1)) * day, today) + q[m.end():]
    rules = [(r"\b(this|current) month\b|\bi[sz]+ (mahine|maheene|mahinay|month)\b|اس مہینے", mon(today)),
             (r"\b(last|previous) month\b|\b(pichh?le|pichlay|guzishta|last) (mahine|maheene|mahinay)\b|پچھلے مہینے",
              mon(first - dt.timedelta(days=1))),
             (r"\b(this|current) year\b|\bi[sz]+ saal\b|اس سال", f" {today.year} "),
             (r"\b(last|previous) year\b|\b(pichh?le|pichlay|guzishta) saal\b|پچھلے سال", f" {today.year - 1} "),
             (r"\b(this|current) week\b|\bi[sz]+ (hafte|haftay|week)\b|اس ہفتے", rng(monday, today)),
             (r"\b(last|previous) week\b|\b(pichh?le|pichlay|guzishta|last) (hafte|haftay)\b|پچھلے ہفتے",
              rng(monday - 7 * day, monday - day)),
             (r"\btoday'?s?\b|\baaj\b|آج", rng(today, today)),
             (r"\byesterday'?s?\b|\bkal\b|گزشتہ کل", rng(today - day, today - day)),
             (r"\bsab ?se (purani|purana|purane|pehli|pehla)\b|سب سے پرانی|سب سے پرانا", " oldest "),
             (r"\bsab ?se (nayi|naya|naye|nai|taaza|taza)\b|\b(aakh?ri|akh?ri|taaza|taza tareen)\b|سب سے نئی|سب سے نیا|آخری",
              " latest ")]
    for pat, rep in rules:
        q = re.sub(pat, rep, q)
    return q


MULT = {"k": 1e3, "thousand": 1e3, "hazar": 1e3, "hazaar": 1e3, "ہزار": 1e3, "lakh": 1e5, "lac": 1e5,
        "lakhs": 1e5, "لاکھ": 1e5, "m": 1e6, "million": 1e6, "mn": 1e6, "crore": 1e7, "کروڑ": 1e7}
_NUM = r"(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|hazaa?r|ہزار|lakhs?|lac|لاکھ|million|mn|m|crore|کروڑ)?\b"
AMOUNT_RULES = [
    # Urdu word order: the number comes first ("2 lakh se zyada", "50 hazar se kam")
    (rf"{_NUM}\s*(?:rs\.?|pkr|rupees|rupay|روپے)?\s*(?:se|say)\s+(?:zyada|ziada|zyaada|upar|oopar|barh kar)\b|{_NUM}\s*(?:روپے)?\s*سے زیادہ", "min"),
    (rf"{_NUM}\s*(?:rs\.?|pkr|rupees|rupay|روپے)?\s*(?:se|say)\s+(?:kam|neeche|niche)\b|{_NUM}\s*(?:روپے)?\s*سے کم", "max"),
    (rf"\b(?:above|over|more than|greater than|at least|minimum|min|exceeding|bigger than|se zyada|سے زیادہ)\s+(?:rs\.?\s*|pkr\s*)?{_NUM}", "min"),
    (rf"\b(?:below|under|less than|at most|maximum|max|upto|up to|smaller than|se kam|سے کم)\s+(?:rs\.?\s*|pkr\s*)?{_NUM}", "max"),
]


def parse_filters(q: str):
    """Pulls amount limits and 'latest/oldest N' out of the query. Returns (rest, filters)."""
    f = {}
    for pat, kind in AMOUNT_RULES:
        m = re.search(pat, q)
        if m and kind not in f:
            g = [x for x in m.groups()]
            num, unit = (g[0], g[1]) if g[0] else (g[2], g[3]) if len(g) > 2 else (None, None)
            if num:
                f[kind] = float(num.replace(",", "")) * MULT.get(unit or "", 1)
                q = q[:m.start()] + " " + q[m.end():]
    m = re.search(r"\bzzrange (\d{8}) (\d{8})\b", q)
    if m:
        f["from"], f["to"] = m.group(1), m.group(2)
        q = q[:m.start()] + " " + q[m.end():]
    m = re.search(r"\b(latest|newest|most recent|recent|last|oldest|first|earliest)\b(?:\s+(\d{1,2})\b)?", q)
    if m:
        f["order"] = "old" if m.group(1) in ("oldest", "first", "earliest") else "new"
        f["count"] = int(m.group(2)) if m.group(2) else 1
        q = q[:m.start()] + " " + q[m.end():]
    m = re.search(r"\b(?:all|sab|saari|sari|tamam|تمام)\b", q)
    if m and "order" in f and not re.search(r"\d", q[m.start():m.start() + 20]):
        f["count"] = 0  # "all the latest ..." -> just sort
    return q, f


def parse(query: str):
    """Returns (doc_type, terms). doc_type '' means any type."""
    q, _ = parse_filters(" " + _relative_dates(_norm(query).replace("&", " and ")) + " ")
    q = re.sub(r"(?<![\w])([a-z]{1,4})(\d{3,})(?!\w)", r"\1 \2", q)  # "INV1148" / "QT1250" -> "inv 1148" / "qt 1250"
    doc_type = ""
    for typ in TYPE_ORDER:
        for w in sorted(TYPES[typ], key=len, reverse=True):
            if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", q):
                doc_type = doc_type or typ
                q = re.sub(rf"(?<!\w){re.escape(w)}(?!\w)", " ", q)
    if not doc_type and re.search(r"\bsales\b", q):  # "kul sales kitni hai" means the sales invoices
        doc_type = "sales invoice"
    if doc_type == "sales invoice":
        q = re.sub(r"\bsales\b", " ", q)
    q = re.sub(r"(?<=\d),(?=\d{3})", "", q)  # 284,500 -> 284500
    # "may" is only the month when it reads like a date ("in may", "may 2026")
    q = re.sub(r"\b(in|of|from|during)\s+may\b", r"\1 maymonth", q)
    q = re.sub(r"\bmay(?=\s+20\d\d)", "maymonth", q)
    q = re.sub(r"\bmay\b", " ", q).replace("maymonth", "may")
    terms = []
    for t in re.findall(r"[\w']+", q):
        if t in STOP or t == "and":
            continue
        terms.append(MONTHS[MON_ALIAS[t]] if t in MON_ALIAS else t)
    return doc_type, list(dict.fromkeys(terms))


# Urdu script -> rough Latin consonants, so an Urdu-written name can still find "Zahid & Sons" (backup only:
# the assistant normally passes names in English letters already)
_UR2LAT = {"ب": "b", "پ": "p", "ت": "t", "ٹ": "t", "ث": "s", "ج": "j", "چ": "ch", "ح": "h", "خ": "kh", "د": "d",
           "ڈ": "d", "ذ": "z", "ر": "r", "ڑ": "r", "ز": "z", "ژ": "z", "س": "s", "ش": "sh", "ص": "s", "ض": "z",
           "ط": "t", "ظ": "z", "ع": "", "غ": "gh", "ف": "f", "ق": "q", "ک": "k", "گ": "g", "ل": "l", "م": "m",
           "ن": "n", "ں": "n", "و": "", "ہ": "", "ھ": "h", "ء": "", "ی": "", "ے": "", "ا": "", "آ": "", "ئ": ""}


def _skeleton_ur(t: str) -> str:
    return "".join(_UR2LAT.get(ch, "") for ch in t).replace("kh", "k").replace("q", "k")


def _skeleton_lat(w: str) -> str:
    w = re.sub(r"[aeiouyw]", "", w.lower()).replace("kh", "k").replace("q", "k").replace("c", "k")
    return re.sub(r"h(?![s])", "", w) if len(w) > 2 else w


TYPE_FAMILY = {"invoice": {"invoice", "sales invoice", "purchase invoice"}}


def _hay(chat, name, text, doc_date):
    head = _norm(f"{chat} {name}")
    body = re.sub(r"(?<=\d),(?=\d{3})", "", _norm(text).replace("&", " and "))
    return head, head + " " + body + " " + _ocr_numbers(text[:4000]) + _date_words(doc_date)


def _phon(s: str) -> str:
    """Rough sound of a word or name: 'Khan Traders' and a misheard 'contrators' come out nearly the same."""
    s = re.sub(r"[^a-z]", "", s.lower())
    for a, b in (("kh", "k"), ("ph", "f"), ("ck", "k"), ("c", "k"), ("q", "k"), ("z", "s"), ("x", "ks"), ("v", "w")):
        s = s.replace(a, b)
    s = re.sub(r"[aeiouyh]", "", s)
    return re.sub(r"(.)\1+", r"\1", s)


def _known_names() -> list[str]:
    names = set()
    try:
        db = _db()
        for f, chat in db.execute("SELECT fields, chat FROM docs").fetchall():
            n = (json.loads(f).get("partner_name") if f else "") or ""
            for x in (n, chat or ""):
                x = x.strip()
                if x.isascii() and 2 < len(x) < 40 and re.search(r"[a-zA-Z]{3}", x):
                    names.add(x)
        db.close()
    except Exception:
        pass
    return sorted(names)


def _repair(query: str):
    """Speech recognition mishears names ('contrators' for 'Khan Traders'). If part of the request sounds like a
    customer name we know from the documents, swap the real name in. Returns (new_query, note) or (query, '')."""
    words = re.findall(r"[A-Za-z']+", query)
    if not words:
        return query, ""
    best = None
    for name in _known_names():
        nk = _phon(name)
        if len(nk) < 3:
            continue
        nwords = [w.lower() for w in name.split()]
        for size in range(1, min(3, len(words)) + 1):
            for i in range(len(words) - size + 1):
                win = words[i:i + size]
                if [w.lower() for w in win] == nwords or win[0].lower() in STOP or win[-1].lower() in STOP:
                    continue
                wk = _phon("".join(win))
                if len(wk) < 3 or wk[0] != nk[0]:
                    continue
                ratio = difflib.SequenceMatcher(None, wk, nk).ratio()
                if ratio >= 0.84 and (best is None or ratio > best[0] or (ratio == best[0] and size > best[3])):
                    best = (ratio, " ".join(win), name, size)
    if not best:
        return query, ""
    _, heard, name, _ = best
    return re.sub(re.escape(heard), name, query, count=1, flags=re.I), f"Heard '{heard}' - taken as '{name}'."


def _light() -> bool:
    try:
        import deep_scan
        return deep_scan.learn_mode() == "light"
    except Exception:
        return False


def read_pending(terms=(), n: int = 40, seconds: float = 40) -> int:
    """Light mode: read files that so far are only known by name - the likeliest first - and remember what they say."""
    db = _db()
    rows = db.execute("SELECT path, name, mtime FROM docs WHERE (text='' OR text IS NULL) AND mtime>0 "
                      "AND ext NOT IN ('.zip','.rar')").fetchall()
    rows += db.execute("SELECT path, name, mtime FROM docs WHERE (text='' OR text IS NULL) AND mtime>0 "
                       "AND ext IN ('.zip','.rar')").fetchall()
    rows.sort(key=lambda r: (-sum(t in r[1].lower() for t in terms), -r[2]))
    done, t0 = 0, time.time()
    for path, name, mtime in rows[:n]:
        if time.time() - t0 > seconds:
            break
        p = Path(path)
        if not p.exists():
            continue
        text = extract_text(p) or " "  # a blank file is not asked about again
        typ = classify(name, text)
        fields = _fields(text, name, typ)
        db.execute("UPDATE docs SET text=?, doc_type=?, amount=?, doc_date=?, fields=? WHERE path=?",
                   (text[:30000], typ, "" if typ in NOT_MONEY else find_amount(text),
                    find_date(name, text, mtime), fields, path))
        done += 1
    db.commit()
    db.close()
    return done


def _chat_scope(query: str):
    """If the question names a chat we know ("meezan bank from daddy mobilink"), return (chat, query without the
    chat's words). The chat is a place to look, not words the files must contain."""
    try:
        db = _db()
        chats = [r[0] for r in db.execute("SELECT DISTINCT chat FROM docs WHERE chat!=''")]
        db.close()
    except Exception:
        return "", query
    qwords = re.findall(r"[\w']+", _norm(query))
    best = None
    for c in chats:
        cw = [w for w in re.findall(r"[\w']+", _norm(c)) if len(w) >= 2]
        if not cw:
            continue
        used = []
        for w in cw:
            m = [q for q in qwords if q == w or (len(q) >= 4 and len(w) >= 4
                                                  and difflib.SequenceMatcher(None, w, q).ratio() >= 0.85)]
            if not m:
                break
            used += m
        else:
            if best is None or len(" ".join(cw)) > best[1]:
                best = (c, len(" ".join(cw)), set(used))
    if not best:
        return "", query
    rest = " ".join(w for w in re.findall(r"[\w']+", query) if _norm(w) not in best[2])
    return best[0], rest


def _read_chat_pending(chat: str, n: int = 80, seconds: float = 60) -> int:
    """Read (OCR) the files of ONE chat that so far are known only by name, so what is written inside can be searched."""
    db = _db()
    rows = db.execute("SELECT path, name, mtime FROM docs WHERE chat=? AND (text='' OR text IS NULL) AND mtime>0 "
                      "ORDER BY mtime DESC", (chat,)).fetchall()
    done, t0 = 0, time.time()
    for path, name, mtime in rows[:n]:
        if time.time() - t0 > seconds:
            break
        p = Path(path)
        if not p.exists():
            continue
        text = extract_text(p) or " "
        typ = classify(name, text)
        db.execute("UPDATE docs SET text=?, doc_type=?, amount=?, doc_date=?, fields=? WHERE path=?",
                   (text[:30000], typ, "" if typ in NOT_MONEY else find_amount(text),
                    find_date(name, text, mtime), _fields(text, name, typ), path))
        done += 1
    db.commit()
    db.close()
    return done


def _search_in_chat(chat, rest, source, doc_type, limit):
    """Look for the content words only inside that chat; if nothing matches, show what the chat does contain."""
    read = _read_chat_pending(chat)
    _scope.chat = chat
    try:
        r = _search_all(rest, source, doc_type, limit)
        if r["items"] and r["mode"] not in ("close", "meaning"):
            r["chat_scope"] = chat
            return r
        everything = _search("", source, doc_type, 100000)
        if not everything["items"] and doc_type:
            everything = _search("", source, "", 100000)
        db = _db()
        unread = db.execute("SELECT COUNT(*) FROM docs WHERE chat=? AND (text='' OR text=' ' OR text IS NULL)",
                            (chat,)).fetchone()[0]
        db.close()
    finally:
        _scope.chat = ""
    items = sorted(everything["items"], key=lambda i: i.get("mtime") or 0, reverse=True)
    for it in items:
        it.pop("_t", None)
    return {"mode": "chat_files", "type": doc_type, "terms": parse(rest)[1], "filters": {}, "total": len(items),
            "items": items[:limit], "ambiguous": False, "chat_scope": chat, "unread": unread, "read_now": read,
            "wanted": rest.strip()}


def search(query: str, source: str = "any", doc_type: str = "", limit: int = 200) -> dict:
    r = _search_all(query, source, doc_type, limit)
    failed = not r["items"] or r["mode"] in ("close", "meaning")
    if failed and source in ("any", "whatsapp", "email") and not getattr(_scope, "chat", ""):
        # nothing matched every word. If the question names a chat ("... from daddy mobilink"), look INSIDE that chat
        # (reading its unread screenshots) instead of listing look-alikes from everywhere and saying nothing was found
        chat, rest = _chat_scope(query)
        if chat:
            r2 = _search_in_chat(chat, rest, source, doc_type, limit)
            if r2["items"]:
                return r2
    if _light() and (not r["items"] or r["mode"] == "close"):
        for _ in range(3):  # read the next likeliest files, then look again
            if not read_pending(parse(query)[1]):
                break
            r = _search_all(query, source, doc_type, limit)
            if r["items"] and r["mode"] != "close":
                break
    return r


def _search_all(query: str, source: str = "any", doc_type: str = "", limit: int = 200) -> dict:
    """Exact word search first; if that finds nothing sure, try a misheard-name repair, then search by meaning."""
    query = re.sub(r"ان\s+وائس", "انوائس", query)  # speech-to-text often splits this Urdu word
    r = _search(query, source, doc_type, limit)
    if r["mode"] != "close" and r["items"]:
        return r
    if not r["items"] and r.get("type"):
        # nothing is labelled with that type: fall back to files that SAY it in their name ("Payment Invoice.pdf")
        word = r["type"].split()[-1]
        r2 = _search(query, source, "", limit)
        named = [i for i in r2["items"] if word in i["name"].lower()]
        if not r["terms"]:
            named = named or [i for i in _search("", source, "", 100000)["items"] if word in i["name"].lower()]
        if named:
            r2.update(items=named[:limit], total=len(named), mode="specific", type=r["type"])
            return r2
    q2, note = _repair(query)
    if note:
        r2 = _search(q2, source, doc_type, limit)
        if r2["mode"] != "close" and r2["items"]:
            r2["heard_as"] = note
            return r2
    if r["terms"]:
        by_meaning = _meaning(query, source)
        if by_meaning:
            r.update(mode="meaning", items=by_meaning[:limit], total=len(by_meaning))
    return r


_scope = threading.local()

# Words that say what KIND of file, not what is written in it ("meezan bank screenshots", "profile presentation")
_IMG = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif", ".bmp"}
FORMAT_WORDS = {"screenshot": _IMG, "screenshots": _IMG, "screen shot": _IMG, "pic": _IMG, "pics": _IMG,
                "tasveer": _IMG, "tasweer": _IMG, "snapshot": _IMG,
                "presentation": {".pptx", ".ppt"}, "presentations": {".pptx", ".ppt"}, "slides": {".pptx", ".ppt"},
                "powerpoint": {".pptx", ".ppt"}, "deck": {".pptx", ".ppt"},
                "excel": {".xlsx", ".xls", ".csv"}, "spreadsheet": {".xlsx", ".xls", ".csv"},
                "zip": {".zip", ".rar"}}
# A word in the question that the document may say differently ("payment" -> "Funds Transfer Successful")
SYNONYMS = {"payment": {"transfer", "paid", "transaction", "raast", "ibft", "deposit", "sent", "remittance"},
            "payments": {"transfer", "paid", "transaction", "raast", "ibft", "deposit", "sent"},
            "paid": {"payment", "transfer", "transaction"}, "transfer": {"payment", "transaction", "raast", "ibft"},
            "salary": {"salaries", "payroll", "wages"}, "rent": {"rental", "tenancy", "lease"},
            "agreement": {"contract"}, "contract": {"agreement"}}


def _search(query: str, source: str = "any", doc_type: str = "", limit: int = 200) -> dict:
    qtype, terms = parse(query)
    _, filters = parse_filters(" " + _relative_dates(_norm(query)) + " ")
    doc_type = doc_type or qtype
    exts = set()
    for w in [t for t in terms if t in FORMAT_WORDS]:
        exts |= FORMAT_WORDS[w]
        terms.remove(w)
    db = _db()
    where, args = [], []
    if source not in ("any", ""):
        where.append("source=?")
        args.append(source)
    if getattr(_scope, "chat", ""):
        where.append("chat=?")  # the question named one chat: only that chat's files
        args.append(_scope.chat)
    rows = db.execute("SELECT path,source,chat,name,ext,mtime,text,doc_type,amount,doc_date FROM docs"
                      + (" WHERE " + " AND ".join(where) if where else ""), tuple(args)).fetchall()
    fp = dict(db.execute("SELECT path, h FROM hashes").fetchall())
    db.close()
    allowed = TYPE_FAMILY.get(doc_type, {doc_type})
    cands, heads = [], {}
    for path, src, chat, name, ext, mtime, text, typ, amount, doc_date in rows:
        if doc_type and typ not in allowed and not (typ == "register" and terms):
            continue
        if "min" in filters or "max" in filters:
            try:
                val = float(amount)
            except (TypeError, ValueError):
                continue
            if val <= filters.get("min", -1) or val >= filters.get("max", float("inf")):
                continue
        if "from" in filters:
            day = (doc_date or "").replace("-", "")
            if not day or not (filters["from"] <= day <= filters["to"]):
                continue
        if exts and (ext or "").lower() not in exts:
            continue
        head, hay = _hay(chat, name, text, doc_date)
        item = dict(path=path, source=src, chat=chat, name=name, type=typ, amount=amount, date=doc_date, mtime=mtime,
                    _t=(text or "")[:30000])
        heads[id(item)] = head
        cands.append((set(re.findall(r"[\w']+", hay)), head, hay, item))
    # Words in most candidate documents (letterhead, "Bill To", "Total") don't tell documents apart
    n = len(cands)
    from collections import Counter
    df = Counter(w for words, *_ in cands for w in words)
    common = {w for w, c in df.items() if n >= 6 and c / n > 0.6}

    def score_term(t, words, hay):
        if re.search(r"\d", t):  # numbers (amounts, invoice numbers, years) must match exactly
            return 1.0 if re.search(rf"(?<!\d){re.escape(t)}(?:\.0+)?(?!\d)", hay) else 0.0
        if t in words:
            return 1.0
        if t in SYNONYMS and SYNONYMS[t] & words:
            return 0.9
        if len(t) >= 3 and any(w.startswith(t) for w in words if len(w) - len(t) <= 3):
            return 0.9  # "trad" -> "traders"
        if re.search(r"[\u0600-\u06FF]", t):
            sk = _skeleton_ur(t).replace("z", "s")

            def close(w):
                lw = _skeleton_lat(w).replace("z", "s")
                if not lw or lw[0] != sk[0]:
                    return False
                return lw == sk if len(sk) <= 3 else difflib.SequenceMatcher(None, sk, lw).ratio() >= 0.8
            if len(sk) >= 2 and any(close(w) for w in words if w not in common and w.isascii() and len(w) >= 3):
                return 0.7
            return 0.0
        if t.isascii() and t.isalpha() and len(t) >= 3:  # "rehman" vs "رحمان" printed in Urdu
            lt = _skeleton_lat(t).replace("z", "s").replace("h", "")
            urw = [w for w in words if re.search(r"[\u0600-\u06FF]", w) and len(w) >= 2]
            for w in urw:
                sk = _skeleton_ur(w).replace("z", "s").replace("h", "")
                if len(lt) >= 2 and sk and sk[0] == lt[0] and (sk == lt if len(lt) <= 3 else
                                                              difflib.SequenceMatcher(None, lt, sk).ratio() >= 0.8):
                    return 0.7
        if len(t) >= 5:
            near = difflib.get_close_matches(t, [w for w in words if w not in common and abs(len(w) - len(t)) <= 2],
                                             n=1, cutoff=0.8)
            if near:
                return 0.8
        return 0.0

    def ur_common(t):  # an Urdu word that just means a letterhead/common word, e.g. "اسٹیل" -> steel
        if not re.search(r"[\u0600-\u06FF]", t):
            return False
        sk = _skeleton_ur(t).replace("z", "s")
        if len(sk) < 2:
            return False
        same = lambda w: w.isascii() and _skeleton_lat(w).replace("z", "s") == sk
        # common only if it matches a common word and nothing more specific ("بلال" is Bilal, not "Bill")
        return any(same(w) for w in common) and not any(same(w) for w in df if w not in common)
    key_terms = [t for t in terms if t not in common and not ur_common(t)] or terms
    liked = _liked(terms)
    scored = []
    for words, head, hay, item in cands:
        if terms:
            sc = {t: score_term(t, words, hay) for t in terms}
            hits = [t for t in key_terms if sc[t]]
            if not hits:
                continue
            score = sum(sc[t] for t in key_terms) / len(key_terms) \
                + 0.3 * sum(1 for t in key_terms if t in head) / len(key_terms)
            full = len(hits) == len(key_terms)
        else:
            score, full = 1.0, True
        if item["path"] in liked and terms:
            score += 0.5  # the owner already confirmed this file for a request like this one
            item["learned"] = True
        item["score"] = round(score, 2)
        scored.append((full, score, item["mtime"], item))
    exact = sorted([s for s in scored if s[0]], key=lambda s: (-round(s[1], 2), s[3]["date"] or ""), reverse=False)
    exact.sort(key=lambda s: s[3]["date"] or "", reverse=True)
    exact.sort(key=lambda s: -round(s[1], 2))  # best match first, newest first among equals
    nums = [t for t in terms if re.fullmatch(r"\d{3,6}", t) and not re.fullmatch(r"(19|20)\d\d", t)]
    if nums and exact:  # asking for a document by its number: that document, not everything of its type
        pat = re.compile(rf"(?<!\d)({'|'.join(nums)})(?!\d)")
        by_no = [s_ for s_ in exact if pat.search(s_[3]["name"]) or pat.search(heads.get(id(s_[3]), ""))]
        if by_no:
            same = {fp.get(s_[3]["path"]) for s_ in by_no} - {None, ""}
            exact = by_no + [s_ for s_ in exact if s_ not in by_no and fp.get(s_[3]["path"]) in same]  # its copies too
    if terms and exact:
        mode, picked = "specific", exact
    elif terms:  # nothing matched every word: offer the nearest, clearly labelled
        mode = "close"
        picked = sorted([s for s in scored if s[1] >= 0.5], key=lambda s: (-s[1], -s[2]))[:5]
    else:
        mode, picked = "all", exact
    if "order" in filters and mode != "close":
        picked = sorted(picked, key=lambda s: s[3]["date"] or "", reverse=filters["order"] == "new")
        if filters.get("count"):
            picked = picked[:filters["count"]]
        mode = "specific" if filters.get("count") else mode
    items, seen = [], {}
    for s_ in picked:  # the same file forwarded to several chats is listed once
        it = s_[3]
        if fp.get(it["path"]):
            k = (fp[it["path"]],)  # identical content, whatever the file is called
        else:
            try:
                k = (it["name"].lower(), Path(it["path"]).stat().st_size)
            except OSError:
                k = (it["path"],)
        where = (f"email from {it['chat']}" if it["source"] == "email" and it["chat"] else it["chat"] or it["source"])
        if k in seen:
            keep = seen[k]
            if _generic_name(keep["name"]) and not _generic_name(it["name"]):  # show the copy that has a real name
                it["also_in"] = keep["also_in"]
                items[items.index(keep)] = it
                seen[k] = keep = it
            if where and where not in keep["also_in"]:
                keep["also_in"].append(where)
            continue
        it["also_in"] = [where] if where else []
        seen[k] = it
        items.append(it)
    shown = items[:limit]
    ask_terms = [t for t in key_terms if t]
    for i, it in enumerate(shown):  # show WHY a file matched, so a wrong match is easy to spot
        if i < 12 and mode in ("specific", "close") and ask_terms:
            it["why"] = _snippet(it.get("_t", ""), ask_terms)
        it.pop("_t", None)
    for it in items[limit:]:
        it.pop("_t", None)
    ambiguous = (mode == "specific" and bool(terms) and "order" not in filters and not nums and 2 <= len(items) <= 4
                 and (items[0].get("score", 0) - items[1].get("score", 0)) < 0.05 and not items[0].get("learned"))
    return {"mode": mode, "type": doc_type, "terms": terms, "filters": filters, "total": len(items),
            "items": shown, "ambiguous": ambiguous}


_TYPE_WORDS = {"invoice": "invoice", "receipt": "receipt", "quotation": "quot", "quote": "quot", "contract": "contract",
               "agreement": "agreement", "statement": "statement", "challan": "delivery"}


def _label_note(it) -> str:
    """The file's name says one kind of document, the reader labelled it as another: say so rather than hide it."""
    name, typ = it["name"].lower(), (it.get("type") or "").lower()
    if not typ or typ == "register":
        return ""
    for w, stem in _TYPE_WORDS.items():
        if re.search(rf"\b{w}", name) and stem not in typ and not any(st in typ for st in _TYPE_WORDS.values() if st in name):
            return f" (read as {it['type']}, but the file name says {w})"
    return ""


def _snippet(text: str, terms, width=90) -> str:
    """The line of the document that contains the searched words (first hit), shortened."""
    if not text:
        return ""
    low = text.lower()
    best = -1
    for t in terms:
        i = low.find(t.lower()) if t else -1
        if i >= 0 and (best < 0 or i < best):
            best = i
    if best < 0:
        return ""
    a = low.rfind("\n", 0, best) + 1
    b = low.find("\n", best)
    line = re.sub(r"\s+", " ", text[a: b if b > 0 else len(text)]).strip()
    if len(line) > width:
        k = best - a
        start = max(0, min(k - 30, len(line) - width))
        line = ("..." if start else "") + line[start:start + width] + "..."
    return line


def _pref_key(terms) -> str:
    return " ".join(sorted({t.lower() for t in terms if len(t) >= 3}))


def _liked(terms) -> set:
    """Paths the owner confirmed for a similar request (same words, or nearly)."""
    mine = set(_pref_key(terms).split())
    if not mine:
        return set()
    try:
        db = _db()
        rows = db.execute("SELECT key, path, n FROM prefs").fetchall()
        db.close()
    except Exception:
        return set()
    out = set()
    for key, path, n in rows:
        theirs = set(key.split())
        if theirs and len(mine & theirs) / len(mine | theirs) >= 0.6:
            out.add(path)
    return out


def remember_choice(terms, path: str):
    key = _pref_key(terms)
    if not key:
        return
    db = _db()
    db.execute("INSERT INTO prefs VALUES(?,?,1) ON CONFLICT(key,path) DO UPDATE SET n=n+1", (key, path))
    db.commit()
    db.close()


def _meaning(query, source, k=8):
    """Documents that match what the user MEANT, when no words match (semantic.py)."""
    try:
        import semantic
        if not semantic.ready():
            return []
        hits = semantic.search(query, source, k=k)
    except Exception as e:
        print("[docs] meaning search:", e)
        return []
    if not hits:
        return []
    db = _db()
    out = []
    for score, path in hits:
        r = db.execute("SELECT path,source,chat,name,doc_type,amount,doc_date,mtime FROM docs WHERE path=?",
                       (path,)).fetchone()
        if r:
            out.append(dict(path=r[0], source=r[1], chat=r[2], name=r[3], type=r[4], amount=r[5], date=r[6],
                            mtime=r[7], also_in=[r[2]] if r[2] else [], score=round(score, 3)))
    db.close()
    return out


def compile_folder(items: list[dict], label: str) -> Path:
    """Copies the found files into one tidy folder (originals untouched)."""
    slug = re.sub(r"[^\w\- ]+", "", label).strip()[:50] or "files"
    dest = OUT_DIR / f"{slug} {time.strftime('%Y-%m-%d %H%M')}"
    dest.mkdir(parents=True, exist_ok=True)
    used = set()
    for it in items:
        src = Path(it["path"])
        prefix = f"{it['chat']} - " if it.get("chat") else ""
        name = prefix + src.name
        n = 1
        while name in used:
            name = f"{prefix}{src.stem} ({n}){src.suffix}"
            n += 1
        used.add(name)
        shutil.copy2(src, dest / name)
    return dest


# ---------------- tools ----------------
def _fmt(r: dict, n=12) -> str:
    if not r["items"]:
        return "No matching files found."
    kind = (r["type"] + "s") if r["type"] else "documents"
    head = {"all": f"All {kind}: {r['total']} found.",
            "specific": f"{r['total']} matching file(s).",
            "close": "No exact match. These are the closest - ask the user if one of them is right.",
            "meaning": "No file has those exact words; these match the MEANING - tell the user they're the likely "
                       "ones and ask if they're right.",
            "chat_files": (f"I looked inside the chat '{r.get('chat_scope')}' ({r['total']} file(s)). None of them contains "
                           f"the words '{r.get('wanted')}'" + (f"; {r.get('unread')} file(s) could not be read (blurry or "
                           "no text)." if r.get("unread") else ".") + " Do NOT say that no files exist: tell the user these "
                           "are the files in that chat, newest first, and ask which one they mean, or offer to open the "
                           "latest ones.")}[r["mode"]]
    if r.get("heard_as"):
        head = r["heard_as"] + " Tell the user this in one short phrase. " + head
    def where(it):
        locs = it.get("also_in") or ([it["chat"]] if it["chat"] else [])
        if len(locs) > 1:
            return f" (found in: {', '.join(locs)})"
        return f" (chat: {it['chat']})" if it["chat"] else (f" (from {it['source']})" if it["source"] in ("email",) else "")
    lines = []
    for i, it in enumerate(r["items"][:n], 1):
        line = (f"{i}. {it['name']}" + where(it) + (f" [{it['type']}]" if it["type"] else "")
                + (f" total {it['amount']}" if it["amount"] else "") + f" - {_pretty_date(it.get('date'), it['mtime'])}"
                + _label_note(it) + (" (you picked this one before)" if it.get("learned") else ""))
        if it.get("why"):
            line += f"\n   matched: \"{it['why']}\""
        lines.append(line)
    more = f"\n...and {r['total'] - n} more." if r["total"] > n else ""
    if r.get("ambiguous"):
        head += (" Several files fit equally well: if the user wants ONE, read them the matched lines and ask which "
                 "one they mean, then call doc_choose with their answer.")
    return head + "\n" + "\n".join(lines) + more


def _pretty_date(d, mtime):
    try:
        return time.strftime("%d %b %Y", time.strptime(d, "%Y-%m-%d"))
    except Exception:
        return time.strftime("%d %b %Y", time.localtime(mtime))


_index_lock = __import__("threading").Lock()


_last_bg = [0.0]


def background_index(cfg: dict, min_gap: float = 0):
    """Builds/refreshes the index quietly so the first search is fast. Safe to call any time.
    min_gap: skip if one ran this recently (searches ask often; a big folder tree should not be re-walked each time)."""
    if time.time() - _last_bg[0] < min_gap or not _index_lock.acquire(blocking=False):
        return
    _last_bg[0] = time.time()
    try:
        t0 = time.time()
        r = reindex(cfg)
        print(f"[docs] index ready: {r['total']} files ({r['added']} new/changed) in {time.time() - t0:.0f}s")
        threading.Thread(target=_vectors, daemon=True).start()
    except Exception as e:
        print("[docs] indexing failed:", e)
    finally:
        _index_lock.release()


_vec_lock = threading.Lock()


def _vectors():
    """Meaning vectors for new files, in the background (first run downloads the ~120 MB model once)."""
    if not _vec_lock.acquire(blocking=False):
        return
    try:
        import semantic
        t0 = time.time()
        n = semantic.update_vectors()
        if n:
            print(f"[docs] meaning vectors: {n} new in {time.time() - t0:.0f}s")
    except Exception as e:
        print("[docs] meaning vectors failed:", e)
    finally:
        _vec_lock.release()


_vocab = {"t": 0.0, "text": ""}


def vocabulary(max_names=25) -> str:
    """A short 'expect to hear' line for the speech recogniser: document words plus the owner's own customer
    names taken from the indexed documents. Refreshed every 10 minutes."""
    if time.time() - _vocab["t"] < 600 and _vocab["text"]:
        return _vocab["text"]
    from collections import Counter
    names = Counter()
    try:
        db = _db()
        for (f,) in db.execute("SELECT fields FROM docs WHERE fields != ''").fetchall():
            n = (json.loads(f).get("partner_name") or "").strip()
            if n and n.isascii() and 2 < len(n) < 40:
                names[n] += 1
        db.close()
    except Exception:
        pass
    text = ("Jarvis. Sales invoices, purchase invoices, quotations, receipts, delivery challans, agreements, "
            "WhatsApp, computer, folder." + (" " + ", ".join(n for n, _ in names.most_common(max_names)) + "." if names else ""))
    _vocab.update(t=time.time(), text=text)
    return text


def _wa_ready() -> bool:
    return WA_DIR.exists() and any(WA_DIR.iterdir())


def _index_empty(source="any") -> bool:
    db = _db()
    q = "SELECT COUNT(*) FROM docs" + ("" if source == "any" else " WHERE source=?")
    n = db.execute(q, () if source == "any" else (source,)).fetchone()[0]
    db.close()
    return n == 0


def _not_ready() -> str:
    if _index_lock.locked():
        return ("I'm still reading your files for the first time, so I can't answer yet. Ask again in a minute - "
                "it only happens once.")
    return "I haven't read any files yet. Say 'scan everything' and I will learn where all your documents are."


@tool("doc_search",
      "Find documents (invoices, quotations, receipts, photos, files). source: 'computer' for files on this "
      "laptop, 'whatsapp' for files from WhatsApp chats, 'email' for attachments from email, 'any' if the user did not say. Put the user's own words "
      "in query, in English letters (translate Urdu document words, write names in English letters) (client name, description, amount, date). If they ask for ALL of a type, query is just the type "
      "(e.g. 'sales invoices'). It understands dates ('march', 'last month', '2025'), 'latest'/'oldest', "
      "amount limits ('above 2 lakh', 'under 50k'), invoice numbers and amounts. Report only what the tool "
      "returns; if it says closest matches, ask the user which one they mean.",
      {"query": {"type": "string"}, "source": {"type": "string", "enum": ["computer", "whatsapp", "email", "any"]}},
      ["query"])
def doc_search(query, source="any"):
    cfg = CTX.get("cfg", {})
    if source == "whatsapp" and not _wa_ready():
        return "No WhatsApp files are saved on this laptop yet. Link WhatsApp (whatsapp_link) and then run whatsapp_sync, or tell the user to do so."
    if _index_empty("any"):  # nothing read yet: say so instead of making the owner wait
        return _not_ready()
    threading.Thread(target=background_index, args=(cfg, 60), daemon=True).start()  # pick up new files, at most once a minute
    r = search(query, source)
    if source != "any" and not r.get("items"):
        # the source was a guess ("from Apricot Digital" may be a client, not a WhatsApp chat): look everywhere before giving up
        wider = search(query, "any")
        if wider.get("items") and wider.get("mode") not in ("close", "meaning"):
            r = wider
    if r.get("mode") in ("close", "meaning") and not r.get("items"):
        empty = _empty_chat(query)
        if empty:
            return (f"The WhatsApp chat '{empty}' is linked and has been read, but no documents or photos were saved "
                    f"from it. Say that plainly; do not guess other files.")
    note_phone_files(r.get("items", []))
    _LAST.update(terms=r.get("terms", []), items=[i["path"] for i in r.get("items", [])[:12]],
                 names=[i["name"] for i in r.get("items", [])[:12]])
    return _fmt(r)


_LAST = {"terms": [], "items": [], "names": []}


@tool("doc_choose",
      "Call this when the user tells you WHICH file they meant after a search (e.g. 'the second one', 'yes that one', "
      "'no, the other one'). It remembers the choice so the same kind of request finds that file first next time. "
      "pick = the number from the last list, or part of the file name.",
      {"pick": {"type": "string"}}, ["pick"])
def doc_choose(pick):
    if not _LAST["items"]:
        return "There is no recent search to attach that choice to."
    idx = None
    m = re.search(r"\d+", str(pick))
    if m and 1 <= int(m.group()) <= len(_LAST["items"]):
        idx = int(m.group()) - 1
    else:
        for i, nm in enumerate(_LAST["names"]):
            if str(pick).strip().lower() and str(pick).strip().lower() in nm.lower():
                idx = i
                break
    if idx is None:
        return "I could not tell which file that is. Ask the user for its number in the list."
    remember_choice(_LAST["terms"], _LAST["items"][idx])
    return f"Remembered: for requests like this I will show '{_LAST['names'][idx]}' first."


def _empty_chat(query: str) -> str:
    """Name of a synced WhatsApp chat the user mentioned that has no saved files (e.g. 'Family group'), else ''."""
    try:
        words = [w for w in re.findall(r"[a-z0-9']+", query.lower()) if len(w) >= 4 and w not in STOP]
        have = {c for (c,) in _db().execute("SELECT DISTINCT chat FROM docs WHERE chat!=''")}
        synced = {p.name for p in WA_DIR.iterdir() if p.is_dir()} if WA_DIR.exists() else set()
        for chat in sorted(synced - have):
            if any(w in chat.lower() for w in words):
                return chat
    except Exception:
        pass
    return ""


def note_phone_files(items):
    """While a PHONE asked the question, remember which documents the answer is about, so the phone can show and
    open them (see phone_bridge.py)."""
    if CTX.get("phone_mode"):
        CTX.setdefault("phone_files", []).extend(items[:8])


@tool("doc_find_by_meaning",
      "Find documents from a vague description when exact words won't work, e.g. 'the steel deal from the summer', "
      "'contract with 30-day payment terms', 'woh bill jis mein late fee ka zikr tha'. Works across Urdu and "
      "English. Tell the user these are likely matches.",
      {"description": {"type": "string"}, "source": {"type": "string", "enum": ["computer", "whatsapp", "email", "any"]}},
      ["description"])
def doc_find_by_meaning(description, source="any"):
    try:
        import semantic
        if not semantic.ready():
            threading.Thread(target=_vectors, daemon=True).start()
            return "Meaning search is still getting ready (first-time setup). Use doc_search for now."
    except Exception:
        return "Meaning search isn't available on this laptop."
    items = _meaning(description, source)
    if not items:
        return "Nothing matched that description."
    note_phone_files(items)
    return _fmt({"mode": "meaning", "type": "", "total": len(items), "items": items})


@tool("doc_collect",
      "Gather the files found for a query into one folder and open it. Use after doc_search when the user wants "
      "the files together. Same query/source as doc_search.",
      {"query": {"type": "string"}, "source": {"type": "string", "enum": ["computer", "whatsapp", "email", "any"]}},
      ["query"])
def doc_collect(query, source="any"):
    cfg = CTX.get("cfg", {})
    r = search(query, source)
    if not r["items"]:
        return "Nothing to collect."
    if r["mode"] == "close":
        return "Only close matches exist; ask the user which they mean before collecting."
    dest = compile_folder(r["items"], query)
    try:
        import os, subprocess
        if os.name == "nt":
            os.startfile(dest)  # noqa
        else:
            subprocess.Popen(["xdg-open", str(dest)])
    except Exception:
        pass
    return f"Copied {len(r['items'])} file(s) into the folder: {dest}"


@tool("fresh_start",
      "Remove what Jarvis itself saved so the owner can start clean: 'whatsapp' = the WhatsApp files Jarvis copied, "
      "their search index and any old WhatsApp logins kept aside; 'computer' = Jarvis's index of the PC (the owner's "
      "own files are never touched); 'both' does both. Chats and memory stay. This cannot be undone, so FIRST call "
      "it without confirm to get the counts, tell the owner exactly what will go, and call again with confirm=true "
      "only after the owner clearly says yes.",
      {"scope": {"type": "string"}, "confirm": {"type": "boolean"}}, ["scope"])
def fresh_start(scope="both", confirm=False):
    import shutil
    scope = (scope or "both").lower()
    if scope not in ("whatsapp", "computer", "both"):
        return "Say what to remove: whatsapp, computer, or both."
    srcs = [x for x in ("whatsapp", "computer") if scope in (x, "both")]
    db = _db()
    counts = {x: db.execute("SELECT COUNT(*) FROM docs WHERE source=?", (x,)).fetchone()[0] for x in srcs}
    old_logins = sorted(DATA.glob("wa_profile_old_*")) if "whatsapp" in srcs else []
    wa_files = sum(1 for f in WA_DIR.rglob("*") if f.is_file()) if "whatsapp" in srcs and WA_DIR.exists() else 0
    if not confirm:
        db.close()
        parts = []
        if "whatsapp" in srcs:
            parts.append(f"{counts['whatsapp']} WhatsApp files in the search index, {wa_files} saved WhatsApp copies "
                         f"and {len(old_logins)} old WhatsApp login(s) kept aside")
        if "computer" in srcs:
            parts.append(f"the index of {counts['computer']} PC files (the files themselves stay where they are)")
        return ("Nothing removed yet. This would remove: " + "; ".join(parts) + ". Your chats, notes and memory stay. "
                "It cannot be undone. Ask the owner to confirm, then call fresh_start again with confirm=true.")
    for x in srcs:
        paths = [r[0] for r in db.execute("SELECT path FROM docs WHERE source=?", (x,))]
        for i in range(0, len(paths), 500):
            chunk = paths[i:i + 500]
            q = ",".join("?" * len(chunk))
            for tbl in ("docs", "hashes", "prefs", "vecs"):
                try:
                    db.execute(f"DELETE FROM {tbl} WHERE path IN ({q})", chunk)
                except sqlite3.DatabaseError:
                    pass
    db.commit()
    db.close()
    if "whatsapp" in srcs:
        shutil.rmtree(WA_DIR, ignore_errors=True)
        for d in old_logins:
            shutil.rmtree(d, ignore_errors=True)
    for fn, key in (("wa_agent.json", "whatsapp"), ("scan.json", "computer")):
        if key in srcs:
            try:
                f = DATA / fn
                j = json.loads(f.read_text(encoding="utf-8"))
                j["last_sync"] = 0
                f.write_text(json.dumps(j), encoding="utf-8")
            except Exception:
                pass
    left = {"whatsapp": "WhatsApp", "computer": "PC"}
    return ("Done. Removed: " + ", ".join(f"{counts[x]} {left[x]} files from the index" for x in srcs)
            + (f", the saved WhatsApp copies and {len(old_logins)} old login(s)" if "whatsapp" in srcs else "")
            + ". Run a sync or scan to start fresh.")
