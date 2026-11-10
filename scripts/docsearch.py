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

TYPES = {  # canonical type -> words that mean it
    "sales invoice": ["sales invoice", "sale invoice", "sales inv", "tax invoice", "sales bill", "sales invoices", "sale invoices", "سیلز انوائس", "فروخت کا انوائس", "سیل انوائس"],
    "invoice": ["invoice", "invoices", "inv", "bill", "bills", "انوائس", "انوائسز", "بل"],
    "quotation": ["quotation", "quote", "quotes", "quotations", "estimate", "proforma", "pro forma", "کوٹیشن", "اقتباس"],
    "receipt": ["receipt", "receipts", "payment slip", "voucher", "رسید", "رسیدیں"],
    "purchase order": ["purchase order", "po"],
}
STOP = set("""a an the of for from to by with in on at and or me my find show get give all every any
file files document documents doc docs pdf photo photos picture pictures image images client clients
please can you jarvis look up lookup search send those these that this is are was were i want need
details detail items item whatsapp computer laptop pc folder compile compiled specific
 کا کی کے سے میں پر کو کلائنٹ تمام سب دکھاؤ دکھائیں تلاش ڈھونڈو ڈھونڈیں فائل فائلیں واٹس ایپ کمپیوٹر""".split())


def _db():
    DATA.mkdir(exist_ok=True)
    c = sqlite3.connect(DATA / "docs.db")
    c.execute("""CREATE TABLE IF NOT EXISTS docs(path TEXT PRIMARY KEY, source TEXT, chat TEXT, name TEXT,
                 ext TEXT, mtime REAL, size INTEGER, text TEXT, doc_type TEXT, amount TEXT)""")
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


def classify(name: str, text: str) -> str:
    hay = _norm(name) + " " + text.lower()[:3000]
    for typ in ("sales invoice", "quotation", "receipt", "purchase order", "invoice"):
        if any(re.search(rf"\b{re.escape(w)}\b", hay) for w in TYPES[typ]):
            return typ
    return ""


def find_amount(text: str) -> str:
    m = re.findall(r"(?:total|amount|grand total|net)\D{0,15}([\d][\d,]*\.?\d*)", text.lower())
    return m[-1].replace(",", "") if m else ""


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
            db.execute("REPLACE INTO docs VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (key, source, chat, p.name, p.suffix.lower(), st.st_mtime, st.st_size, text[:30000],
                        classify(p.name, text), find_amount(text)))
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
def parse(query: str):
    """Returns (doc_type, terms). doc_type '' means any type."""
    q = " " + _norm(query) + " "
    doc_type = ""
    for typ in ("sales invoice", "quotation", "receipt", "purchase order", "invoice"):
        for w in sorted(TYPES[typ], key=len, reverse=True):
            if re.search(rf"\b{re.escape(w)}\b", q):
                doc_type = doc_type or typ
                q = re.sub(rf"\b{re.escape(w)}\b", " ", q)
    terms = [t for t in re.findall(r"[\w']+", q.replace(",", "")) if t not in STOP]
    return doc_type, terms


def _term_score(term: str, hay: str, words: set[str]) -> float:
    if term in hay:
        return 1.0
    if len(term) >= 4 and difflib.get_close_matches(term, words, n=1, cutoff=0.82):
        return 0.8
    return 0.0


def search(query: str, source: str = "any", doc_type: str = "", limit: int = 200) -> dict:
    qtype, terms = parse(query)
    doc_type = doc_type or qtype
    db = _db()
    rows = db.execute("SELECT path,source,chat,name,ext,mtime,text,doc_type,amount FROM docs"
                      + ("" if source in ("any", "") else " WHERE source=?"),
                      () if source in ("any", "") else (source,)).fetchall()
    db.close()
    scored = []
    for path, src, chat, name, ext, mtime, text, typ, amount in rows:
        if doc_type:
            if doc_type == "invoice" and typ not in ("invoice", "sales invoice"):
                continue
            if doc_type != "invoice" and typ != doc_type:
                continue
        head = _norm(f"{chat} {name}")
        hay = (head + " " + _norm(text)).replace(",", "")
        words = set(re.findall(r"[\w']+", hay))
        if terms:
            sc = [_term_score(t, hay, words) for t in terms]
            hits = sum(1 for s in sc if s)
            if hits == 0:
                continue
            score = sum(sc) / len(terms) + 0.3 * sum(1 for t in terms if t in head) / len(terms)
            full = hits == len(terms)
        else:
            score, full = 1.0, True
        scored.append((full, score, mtime, dict(path=path, source=src, chat=chat, name=name, type=typ,
                                                 amount=amount, mtime=mtime)))
    exact = sorted([s for s in scored if s[0]], key=lambda s: (-s[1], -s[2]))
    if terms and exact:
        mode, picked = "specific", exact
    elif terms:  # nothing matched every word: offer the nearest, clearly labelled
        mode = "close"
        picked = sorted([s for s in scored if s[1] >= 0.5], key=lambda s: (-s[1], -s[2]))[:5]
    else:
        mode, picked = "all", exact
    return {"mode": mode, "type": doc_type, "terms": terms, "total": len(picked),
            "items": [s[3] for s in picked[:limit]]}


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
    head = {"all": f"All {r['type'] or 'documents'}: {r['total']} found.",
            "specific": f"{r['total']} matching file(s).",
            "close": "No exact match. These are the closest - ask the user if one of them is right."}[r["mode"]]
    lines = [f"{i}. {it['name']}" + (f" (chat: {it['chat']})" if it["chat"] else "")
             + (f" [{it['type']}]" if it["type"] else "") + (f" total {it['amount']}" if it["amount"] else "")
             + f" - {time.strftime('%d %b %Y', time.localtime(it['mtime']))}"
             for i, it in enumerate(r["items"][:n], 1)]
    more = f"\n...and {r['total'] - n} more." if r["total"] > n else ""
    return head + "\n" + "\n".join(lines) + more


def _wa_ready() -> bool:
    return WA_DIR.exists() and any(WA_DIR.iterdir())


@tool("doc_search",
      "Find documents (invoices, quotations, receipts, photos, files). source: 'computer' for files on this "
      "laptop, 'whatsapp' for files from WhatsApp chats, 'any' if the user did not say. Put the user's own words "
      "in query, in English letters (translate Urdu document words, write names in English letters) (client name, description, amount, date). If they ask for ALL of a type, query is just the type "
      "(e.g. 'sales invoices'). Report only what the tool returns.",
      {"query": {"type": "string"}, "source": {"type": "string", "enum": ["computer", "whatsapp", "any"]}},
      ["query"])
def doc_search(query, source="any"):
    cfg = CTX.get("cfg", {})
    if source == "whatsapp" and not _wa_ready():
        return "WhatsApp is not connected on this laptop yet, so I can't search it."
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
