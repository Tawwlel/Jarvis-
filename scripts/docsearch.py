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
import shutil
import sqlite3
import threading
import time
from pathlib import Path

from tools import CTX, tool

DATA = Path(__file__).parent.parent / "data"
WA_DIR = DATA / "whatsapp"
OUT_DIR = Path.home() / "Documents" / "Jarvis Files"
EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".docx", ".xlsx", ".txt", ".csv"}
IMG = {".jpg", ".jpeg", ".png", ".webp"}
SKIP = {"node_modules", "__pycache__", "venv", ".venv", "AppData", "$RECYCLE.BIN", "Jarvis Files"}

TYPES = {  # canonical type -> words that mean it (checked longest first)
    "sales invoice": ["sales invoice", "sale invoice", "sales inv", "tax invoice", "sales bill", "sales invoices",
                      "sale invoices", "سیلز انوائس", "فروخت کا انوائس", "سیل انوائس", "سیلز انوائسز"],
    "purchase invoice": ["purchase invoice", "purchase invoices", "purchase bill", "supplier invoice",
                         "vendor invoice", "خریداری انوائس", "پرچیز انوائس"],
    "credit note": ["credit note", "credit notes", "credit memo", "کریڈٹ نوٹ"],
    "delivery challan": ["delivery challan", "delivery challans", "challan", "challans", "delivery note",
                         "gate pass", "چالان", "ڈیلیوری چالان"],
    "purchase order": ["purchase order", "purchase orders", "po", "پرچیز آرڈر"],
    "quotation": ["quotation", "quote", "quotes", "quotations", "estimate", "estimates", "proforma",
                  "pro forma", "کوٹیشن", "کوٹیشنز"],
    "receipt": ["receipt", "receipts", "payment receipt", "payment slip", "voucher", "رسید", "رسیدیں"],
    "invoice": ["invoice", "invoices", "inv", "bill", "bills", "انوائس", "انوائسز", "بل"],
    "agreement": ["agreement", "agreements", "contract", "contracts", "rent deed", "معاہدہ", "معاہدے", "کرایہ نامہ",
                  "اقرار نامہ"],
}
TYPE_ORDER = ["sales invoice", "purchase invoice", "credit note", "delivery challan", "purchase order",
              "quotation", "receipt", "invoice", "agreement"]
NOT_DOCS = re.compile(r"curriculum vitae|\bresume\b|\bcv\b|bank statement|account statement|price list|"
                      r"meeting notes|minutes of meeting|\bagenda\b", re.I)
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
    cols = [r[1] for r in c.execute("PRAGMA table_info(docs)").fetchall()]
    if cols and ("doc_date" not in cols or "fields" not in cols):
        c.execute("DROP TABLE docs")  # older index format: rebuild it (also re-reads photos for Urdu)
    c.execute("""CREATE TABLE IF NOT EXISTS docs(path TEXT PRIMARY KEY, source TEXT, chat TEXT, name TEXT,
                 ext TEXT, mtime REAL, size INTEGER, text TEXT, doc_type TEXT, amount TEXT, doc_date TEXT,
                 v2 INTEGER, fields TEXT)""")
    return c


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
    return (latin + "\n" + urdu).strip()


def extract_text(p: Path) -> str:
    ext = p.suffix.lower()
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            r = PdfReader(str(p))
            t = " ".join((pg.extract_text() or "") for pg in r.pages[:10])
            if len(t.strip()) < 20:  # scanned PDF: read the first page as a picture
                import pypdfium2 as pdfium
                t = _ocr(pdfium.PdfDocument(str(p))[0].render(scale=2).to_pil())
            return t
        if ext in IMG:
            from PIL import Image
            return _ocr(Image.open(p))
        if ext == ".docx":
            import docx
            return " ".join(x.text for x in docx.Document(str(p)).paragraphs)
        if ext == ".xlsx":
            import openpyxl
            wb = openpyxl.load_workbook(str(p), read_only=True, data_only=True)
            out = []
            for ws in wb.worksheets[:3]:
                for row in ws.iter_rows(max_row=60, values_only=True):
                    out += [str(c) for c in row if c is not None]
            return " ".join(out)
        if ext in (".txt", ".csv"):
            return p.read_text(errors="ignore")[:20000]
    except Exception:
        pass
    return ""


def _norm(s: str) -> str:
    return re.sub(r"[_\-\.]+", " ", s.lower())


def _has(words, hay):
    return any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", hay) for w in words)


DOC_NO = re.compile(r"\b(?:inv|qt|quo|po|pinv|rcpt|rec|dc|cn|so|bill)[-#/ ]?\d{2,}", re.I)


def classify(name: str, text: str) -> str:
    """Type from the file name first, then the document's heading (first few lines) - never from
    anywhere in the text, so a CV that mentions 'sales invoices' is not a sales invoice.
    Spreadsheets/lists holding many document numbers are 'register' (an invoice list, not an invoice)."""
    fname = _norm(Path(name).stem)
    head = " ".join(text.lower().split()[:40])
    if NOT_DOCS.search(fname + " " + head):
        return ""
    if len(set(m.lower() for m in DOC_NO.findall(text))) >= 3 or re.search(r"\b(list|register|ledger|summary)\b", fname):
        return "register"
    def first(hay):
        return next((typ for typ in TYPE_ORDER if _has(TYPES[typ], hay)), "")
    title = " ".join(text.lower().split()[:6])
    if _has(TYPES["agreement"], fname) or _has(TYPES["agreement"], title):
        return "agreement"  # an agreement that mentions "invoice date" in its terms is not an invoice
    by_name, by_head = first(fname), first(head)
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
    m = re.search(r"(20\d\d)(\d\d)(\d\d)", name)
    if m and 1 <= int(m.group(2)) <= 12:
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


def _walk(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in EXTS:
            rel = p.relative_to(root).parts
            if any(x.startswith(".") or x in SKIP for x in rel[:-1]):
                continue
            yield p


def reindex(cfg: dict, include_computer=True, include_whatsapp=True, progress=None) -> dict:
    db, seen, added = _db(), set(), 0
    jobs = []
    if include_computer:
        jobs += [("computer", r, None) for r in _folders(cfg)]
    if include_whatsapp and WA_DIR.exists():
        jobs += [("whatsapp", WA_DIR, "chat")]
    for source, root, mode in jobs:
        for p in _walk(root):
            key = str(p)
            seen.add(key)
            st = p.stat()
            row = db.execute("SELECT mtime,size FROM docs WHERE path=?", (key,)).fetchone()
            if row and abs(row[0] - st.st_mtime) < 1 and row[1] == st.st_size:
                continue
            text = extract_text(p)
            chat = p.relative_to(root).parts[0] if mode == "chat" and len(p.relative_to(root).parts) > 1 else ""
            typ = classify(p.name, text)
            fields = _fields(text, p.name, typ)
            cat = json.loads(fields).get("category") if fields else None
            if cat:  # "petrol receipts" should find a Shell receipt that never says "petrol"
                text = text + "\n[" + CAT_WORDS.get(cat, cat.lower()) + "]"
            db.execute("REPLACE INTO docs VALUES(?,?,?,?,?,?,?,?,?,?,?,1,?)",
                       (key, source, chat, p.name, p.suffix.lower(), st.st_mtime, st.st_size, text[:30000],
                        typ, find_amount(text), find_date(p.name, text, st.st_mtime), fields))
            added += 1
            if added % 25 == 0:  # save as we go: a big first scan is searchable early and survives a crash
                db.commit()
                if progress and added % 100 == 0:
                    progress(added)
    scope = tuple(s for s, ok in (("computer", include_computer), ("whatsapp", include_whatsapp)) if ok)
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
    if typ in ("other", "cv", "register") or not text:
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
    return head, head + " " + body + _date_words(doc_date)


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


def search(query: str, source: str = "any", doc_type: str = "", limit: int = 200) -> dict:
    """Exact word search first; if that finds nothing sure, try a misheard-name repair, then search by meaning."""
    query = re.sub(r"ان\s+وائس", "انوائس", query)  # speech-to-text often splits this Urdu word
    r = _search(query, source, doc_type, limit)
    if r["mode"] != "close" and r["items"]:
        return r
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


def _search(query: str, source: str = "any", doc_type: str = "", limit: int = 200) -> dict:
    qtype, terms = parse(query)
    _, filters = parse_filters(" " + _relative_dates(_norm(query)) + " ")
    doc_type = doc_type or qtype
    db = _db()
    rows = db.execute("SELECT path,source,chat,name,ext,mtime,text,doc_type,amount,doc_date FROM docs"
                      + ("" if source in ("any", "") else " WHERE source=?"),
                      () if source in ("any", "") else (source,)).fetchall()
    db.close()
    allowed = TYPE_FAMILY.get(doc_type, {doc_type})
    cands = []
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
        head, hay = _hay(chat, name, text, doc_date)
        cands.append((set(re.findall(r"[\w']+", hay)), head, hay,
                      dict(path=path, source=src, chat=chat, name=name, type=typ, amount=amount,
                           date=doc_date, mtime=mtime)))
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
        scored.append((full, score, item["mtime"], item))
    exact = sorted([s for s in scored if s[0]], key=lambda s: (-round(s[1], 2), s[3]["date"] or ""), reverse=False)
    exact.sort(key=lambda s: s[3]["date"] or "", reverse=True)
    exact.sort(key=lambda s: -round(s[1], 2))  # best match first, newest first among equals
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
        try:
            k = (it["name"].lower(), Path(it["path"]).stat().st_size)
        except OSError:
            k = (it["path"],)
        if k in seen:
            if it["chat"] and it["chat"] not in seen[k]["also_in"]:
                seen[k]["also_in"].append(it["chat"])
            continue
        it["also_in"] = [it["chat"]] if it["chat"] else []
        seen[k] = it
        items.append(it)
    return {"mode": mode, "type": doc_type, "terms": terms, "filters": filters, "total": len(items),
            "items": items[:limit]}


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
                       "ones and ask if they're right."}[r["mode"]]
    if r.get("heard_as"):
        head = r["heard_as"] + " Tell the user this in one short phrase. " + head
    lines = [f"{i}. {it['name']}" + (f" (chat: {', '.join(it.get('also_in') or [it['chat']])})" if it["chat"] else "")
             + (f" [{it['type']}]" if it["type"] else "") + (f" total {it['amount']}" if it["amount"] else "")
             + f" - {_pretty_date(it.get('date'), it['mtime'])}"
             for i, it in enumerate(r["items"][:n], 1)]
    more = f"\n...and {r['total'] - n} more." if r["total"] > n else ""
    return head + "\n" + "\n".join(lines) + more


def _pretty_date(d, mtime):
    try:
        return time.strftime("%d %b %Y", time.strptime(d, "%Y-%m-%d"))
    except Exception:
        return time.strftime("%d %b %Y", time.localtime(mtime))


_index_lock = __import__("threading").Lock()


def background_index(cfg: dict):
    """Builds/refreshes the index quietly so the first search is fast. Safe to call any time."""
    if not _index_lock.acquire(blocking=False):
        return
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
      "laptop, 'whatsapp' for files from WhatsApp chats, 'any' if the user did not say. Put the user's own words "
      "in query, in English letters (translate Urdu document words, write names in English letters) (client name, description, amount, date). If they ask for ALL of a type, query is just the type "
      "(e.g. 'sales invoices'). It understands dates ('march', 'last month', '2025'), 'latest'/'oldest', "
      "amount limits ('above 2 lakh', 'under 50k'), invoice numbers and amounts. Report only what the tool "
      "returns; if it says closest matches, ask the user which one they mean.",
      {"query": {"type": "string"}, "source": {"type": "string", "enum": ["computer", "whatsapp", "any"]}},
      ["query"])
def doc_search(query, source="any"):
    cfg = CTX.get("cfg", {})
    if source == "whatsapp" and not _wa_ready():
        return "No WhatsApp files are saved on this laptop yet. Link WhatsApp (whatsapp_link) and then run whatsapp_sync, or tell the user to do so."
    if _index_empty(source):  # nothing read yet: say so instead of making the owner wait
        return _not_ready()
    threading.Thread(target=background_index, args=(cfg,), daemon=True).start()  # pick up new files for next time
    return _fmt(search(query, source))


@tool("doc_find_by_meaning",
      "Find documents from a vague description when exact words won't work, e.g. 'the steel deal from the summer', "
      "'contract with 30-day payment terms', 'woh bill jis mein late fee ka zikr tha'. Works across Urdu and "
      "English. Tell the user these are likely matches.",
      {"description": {"type": "string"}, "source": {"type": "string", "enum": ["computer", "whatsapp", "any"]}},
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
    return _fmt({"mode": "meaning", "type": "", "total": len(items), "items": items})


@tool("doc_collect",
      "Gather the files found for a query into one folder and open it. Use after doc_search when the user wants "
      "the files together. Same query/source as doc_search.",
      {"query": {"type": "string"}, "source": {"type": "string", "enum": ["computer", "whatsapp", "any"]}},
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
