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
import re
import shutil
import sqlite3
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
}
TYPE_ORDER = ["sales invoice", "purchase invoice", "credit note", "delivery challan", "purchase order",
              "quotation", "receipt", "invoice"]
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
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
UR_MONTHS = ["جنوری", "فروری", "مارچ", "اپریل", "مئی", "جون", "جولائی", "اگست", "ستمبر", "اکتوبر", "نومبر", "دسمبر"]
MON_ALIAS = {m[:3]: i for i, m in enumerate(MONTHS)} | {m: i for i, m in enumerate(MONTHS)} | \
            {m: i for i, m in enumerate(UR_MONTHS)} | {"sept": 8}


def _db():
    DATA.mkdir(exist_ok=True)
    c = sqlite3.connect(DATA / "docs.db", timeout=15)
    cols = [r[1] for r in c.execute("PRAGMA table_info(docs)").fetchall()]
    if cols and ("doc_date" not in cols or "v2" not in cols):
        c.execute("DROP TABLE docs")  # older index format: rebuild it
    c.execute("""CREATE TABLE IF NOT EXISTS docs(path TEXT PRIMARY KEY, source TEXT, chat TEXT, name TEXT,
                 ext TEXT, mtime REAL, size INTEGER, text TEXT, doc_type TEXT, amount TEXT, doc_date TEXT,
                 v2 INTEGER)""")
    return c


# ---------------- reading files ----------------
def _ocr(img) -> str:
    try:
        from rapidocr_onnxruntime import RapidOCR
        import numpy as np
        res, _ = RapidOCR()(np.array(img.convert("RGB")))
        return " ".join(r[1] for r in (res or []))
    except Exception:
        pass
    try:
        import pytesseract
        return pytesseract.image_to_string(img)
    except Exception:
        return ""


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
    by_name, by_head = first(fname), first(head)
    # a specific type in the file name wins; a bare "inv"/"invoice" name defers to the heading
    if by_name and by_name != "invoice":
        return by_name
    return by_head or by_name


_CUR = r"(?:pkr|rs\.?|rupees|usd|aed|sar|\$|£|€)"
_AMT = r"(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d{3,}(?:\.\d+)?)"


def find_amount(text: str) -> str:
    """The document's total: a currency amount on a total/amount line first, then the
    largest currency amount, then any 3+ digit number after a total/amount label."""
    t = text.lower()
    def clean(v):
        return v.replace(",", "").removesuffix(".00").rstrip(".")
    lines = t.splitlines()
    for i, line in enumerate(lines):
        if re.search(r"grand total|total amount|amount received|amount paid|amount due|total|amount|net payable", line):
            for cand in (line, lines[i + 1] if i + 1 < len(lines) else ""):  # value may sit on the next line
                m = re.search(rf"{_CUR}\s*{_AMT}", cand) or re.search(rf"{_AMT}\s*{_CUR}", cand)
                if m:
                    return clean(m.group(1))
    cur = [clean(v) for v in re.findall(rf"{_CUR}\s*{_AMT}", t)]
    if cur:
        return max(cur, key=float)
    m = re.findall(rf"(?:grand total|total|amount|net payable)\D{{0,15}}{_AMT}", t)
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
    return [p for p in files.roots() + extra if p.exists()]


def _walk(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in EXTS:
            rel = p.relative_to(root).parts
            if any(x.startswith(".") or x in SKIP for x in rel[:-1]):
                continue
            yield p


def reindex(cfg: dict, include_computer=True, include_whatsapp=True) -> dict:
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
            db.execute("REPLACE INTO docs VALUES(?,?,?,?,?,?,?,?,?,?,?,1)",
                       (key, source, chat, p.name, p.suffix.lower(), st.st_mtime, st.st_size, text[:30000],
                        classify(p.name, text), find_amount(text), find_date(p.name, text, st.st_mtime)))
            added += 1
    scope = tuple(s for s, ok in (("computer", include_computer), ("whatsapp", include_whatsapp)) if ok)
    for (path,) in db.execute(f"SELECT path FROM docs WHERE source IN ({','.join('?' * len(scope))})", scope).fetchall():
        if path not in seen:
            db.execute("DELETE FROM docs WHERE path=?", (path,))
    db.commit()
    total = db.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    db.close()
    return {"added": added, "total": total}


# ---------------- searching ----------------
def _relative_dates(q: str) -> str:
    """'last month' -> 'october 2026' etc., so dates match like any other word."""
    import datetime as dt
    today = dt.date.today()

    def mon(d):
        return f" {MONTHS[d.month - 1]} {d.year} "
    first = today.replace(day=1)
    rules = [(r"\b(this|current) month\b|اس مہینے", mon(today)),
             (r"\b(last|previous) month\b|پچھلے مہینے", mon(first - dt.timedelta(days=1))),
             (r"\b(this|current) year\b|اس سال", f" {today.year} "),
             (r"\b(last|previous) year\b|پچھلے سال", f" {today.year - 1} ")]
    for pat, rep in rules:
        q = re.sub(pat, rep, q)
    return q


MULT = {"k": 1e3, "thousand": 1e3, "hazar": 1e3, "hazaar": 1e3, "ہزار": 1e3, "lakh": 1e5, "lac": 1e5,
        "lakhs": 1e5, "لاکھ": 1e5, "m": 1e6, "million": 1e6, "mn": 1e6, "crore": 1e7, "کروڑ": 1e7}
_NUM = r"(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|hazaa?r|ہزار|lakhs?|lac|لاکھ|million|mn|m|crore|کروڑ)?\b"
AMOUNT_RULES = [
    (rf"\b(?:above|over|more than|greater than|at least|minimum|min|exceeding|bigger than|se zyada|سے زیادہ)\s+(?:rs\.?\s*|pkr\s*)?{_NUM}", "min"),
    (rf"\b(?:below|under|less than|at most|maximum|max|upto|up to|smaller than|se kam|سے کم)\s+(?:rs\.?\s*|pkr\s*)?{_NUM}", "max"),
]


def parse_filters(q: str):
    """Pulls amount limits and 'latest/oldest N' out of the query. Returns (rest, filters)."""
    f = {}
    for pat, kind in AMOUNT_RULES:
        m = re.search(pat, q)
        if m:
            f[kind] = float(m.group(1).replace(",", "")) * MULT.get(m.group(2) or "", 1)
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


def search(query: str, source: str = "any", doc_type: str = "", limit: int = 200) -> dict:
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
            "close": "No exact match. These are the closest - ask the user if one of them is right."}[r["mode"]]
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
    except Exception as e:
        print("[docs] indexing failed:", e)
    finally:
        _index_lock.release()


def _wa_ready() -> bool:
    return WA_DIR.exists() and any(WA_DIR.iterdir())


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
    with _index_lock:  # wait for a background index run instead of doing the work twice
        reindex(cfg, include_computer=source != "whatsapp", include_whatsapp=source != "computer")
    return _fmt(search(query, source))


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
