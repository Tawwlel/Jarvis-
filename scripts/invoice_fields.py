"""
Exact invoice / receipt details: number, date, total, tax, sub-total, customer (bill-to), issuer, and for
receipts the shop, payment method and spending category.

Three layers, most exact first:
  1. invoice2data templates (MIT) - one small file per regular invoice layout, in data/invoice_templates/.
     Jarvis can write a first draft itself from one sample ("learn this invoice layout").
  2. Built-in label rules that understand common Pakistani invoices (Rs./PKR, GST, "Bill To", "M/s",
     Urdu labels such as کل رقم and بل بنام).
  3. For receipt PHOTOS only, and only when asked: Claude reads the photo directly (the receipt-ocr approach:
     an AI model filling a fixed receipt form). Needs the API key; results are cached.
"""
import base64
import json
import re
from pathlib import Path

from tools import CTX, tool

ROOT = Path(__file__).parent.parent
TEMPLATES = ROOT / "data" / "invoice_templates"
_NUM = r"(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_CUR = r"(?:pkr|rs\.?|rupees|روپے)?"
_tpl_cache = {"mtime": None, "list": []}


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _labeled(text, labels, value=_NUM, cur=True):
    for lab in labels:
        m = re.search(rf"(?:{lab})\b\s*(?:no\.?|number|#)?\s*(?:\d+(?:\.\d+)?\s*%)?\s*[:#.\-=]?\s*"
                      rf"{_CUR if cur else ''}\s*{value}", text, re.I)
        if m:
            return m.group(1)
    return None


def _templates():
    """User/learned invoice2data templates (reloaded when the folder changes)."""
    try:
        mt = max((p.stat().st_mtime for p in TEMPLATES.glob("*.yml")), default=0)
    except OSError:
        mt = 0
    if mt and mt != _tpl_cache["mtime"]:
        try:
            from invoice2data.extract.loader import read_templates
            _tpl_cache["list"] = read_templates(str(TEMPLATES))
        except Exception as e:
            print("[invoice] templates:", e)
            _tpl_cache["list"] = []
        _tpl_cache["mtime"] = mt
    return _tpl_cache["list"] if mt else []


def _from_template(text):
    for t in _templates():
        try:
            if not t.matches_input(t.prepare_input(text)):
                continue
            out = t.extract(t.prepare_input(text), "", None) or {}
        except Exception:
            continue
        if out:
            res = {"template": t["template_name"], "issuer": t.get("issuer")}
            for k in ("invoice_number", "amount", "amount_tax", "amount_untaxed", "partner_name", "currency"):
                if out.get(k) not in (None, ""):
                    res[k] = out[k]
            if out.get("date"):
                d = out["date"]
                res["date"] = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
            return res
    return {}


PAY = [("jazzcash", "JazzCash"), ("easypaisa", "Easypaisa"), ("raast", "Raast"), ("visa", "Card"),
       ("master", "Card"), ("card", "Card"), ("debit", "Card"), ("credit", "Card"), ("bank transfer", "Bank transfer"),
       ("ibft", "Bank transfer"), ("cheque", "Cheque"), ("cash", "Cash"), ("نقد", "Cash")]
CATS = [(r"petrol|fuel|diesel|pso|shell|total parco|attock|hi-?octane|پٹرول", "Fuel"),
        (r"grocery|mart|metro|carrefour|imtiaz|chase up|naheed|al-?fatah|سودا", "Groceries"),
        (r"restaurant|cafe|pizza|burger|kfc|mcdonald|biryani|food|dine|ہوٹل", "Food"),
        (r"pharmacy|medical|clinic|hospital|medicine|دوا", "Medical"),
        (r"k-?electric|lesco|iesco|sui gas|ptcl|electricity|bill payment|بجلی", "Utilities"),
        (r"hardware|steel|cement|paint|plumb|electrical", "Hardware & building"),
        (r"stationery|printing|print|paper|toner", "Office supplies"),
        (r"uber|careem|indrive|taxi|rickshaw|toll|parking", "Transport")]


def extract(text: str, name: str = "", doc_type: str = "") -> dict:
    """Best available fields for one document (empty dict for non-business files)."""
    if not text:
        return {}
    f = _from_template(text)
    low = text.lower()
    f.setdefault("invoice_number", _labeled(low, [r"invoice", r"inv", r"bill", r"receipt", r"rcpt", r"quotation",
                                                  r"quote", r"challan", r"ref", r"نمبر"],
                                             r"([a-z]{0,5}[-/]?\d[\w\-/]{1,20})", cur=False))
    if f.get("invoice_number"):
        f["invoice_number"] = f["invoice_number"].upper()
    if "amount" not in f:
        a = _labeled(low, [r"grand total", r"net payable", r"total amount", r"amount due", r"amount received",
                           r"amount paid", r"net total", r"total", r"کل رقم", r"ٹوٹل", r"میزان"])
        if a is None:
            import docsearch
            a = docsearch.find_amount(text) or None
        f["amount"] = _num(a)
    f.setdefault("amount_tax", _num(_labeled(low, [r"sales tax", r"gst", r"vat", r"tax", r"ٹیکس"])))
    f.setdefault("amount_untaxed", _num(_labeled(low, [r"sub ?-?total", r"amount before tax"])))
    if "partner_name" not in f:
        m = re.search(r"(?:bill(?:ed)? to|customer|client|sold to|received from|prepared for|m/s|messrs|"
                      r"بل بنام|بنام|گاہک)\s*[:.\-]?\s*([^\n\r]{2,60})", text, re.I)
        if m:
            f["partner_name"] = re.split(r"\s{3,}|\t", m.group(1).strip())[0].strip(" .:-")
    if not f.get("issuer"):
        for line in text.splitlines()[:6]:
            s = line.strip()
            if len(s) > 2 and not re.search(r"sample document|invoice|receipt|quotation|^date|^\d|bill(ed)? to|"
                                            r"customer|m/s|^no\b|بنام|تاریخ|نمبر", s, re.I):
                f["issuer"] = s[:60]
                break
    if doc_type in ("receipt", "photo", "") or "receipt" in low:
        f["payment"] = next((v for k, v in PAY if k in low), None)
        f["category"] = next((v for pat, v in CATS if re.search(pat, low + " " + name.lower())), None)
    return {k: v for k, v in f.items() if v not in (None, "", [])}


# ---------------- learning a layout (invoice2data template) ----------------
def learn_layout(text: str, issuer_hint: str = "") -> Path:
    from invoice2data.extract.template_builder import suggested_template, to_yaml
    tpl = suggested_template(text)
    issuer = issuer_hint or tpl.get("issuer") or "layout"
    # a keyword that appears on every invoice from this sender: its own first line / name
    tpl["issuer"] = issuer
    tpl["keywords"] = ([issuer_hint] if issuer_hint else tpl.get("keywords", []))[:1]
    fields = tpl.setdefault("fields", {})
    fields.pop("bic", None)
    for lab in ("Grand Total", "Net Payable", "Total Amount", "Amount Due", "Total"):  # the real total, never Subtotal
        if re.search(rf"(?<![A-Za-z]){lab}\s*[:.]?\s*(?:Rs\.?|PKR)?\s*[\d,]+", text, re.I):
            fields["amount"] = {"parser": "regex", "type": "float",
                                "regex": rf"(?i)(?<![a-z]){lab}\s*[:.]?\s*(?:Rs\.?|PKR)?\s*([\d,]+(?:\.\d+)?)"}
            break
    tpl["options"] = {"currency": "PKR", "decimal_separator": ".", "remove_whitespace": False}
    TEMPLATES.mkdir(parents=True, exist_ok=True)
    out = TEMPLATES / (re.sub(r"[^\w\-]+", "_", issuer.lower()).strip("_")[:40] + ".yml")
    out.write_text(to_yaml(tpl), encoding="utf-8")
    _tpl_cache["mtime"] = None
    return out


# ---------------- receipt photos read by Claude (opt-in, per request) ----------------
RECEIPT_PROMPT = ("Read this receipt photo. Reply with JSON only: {\"merchant\":str,\"date\":\"YYYY-MM-DD\"|null,"
                  "\"total\":number|null,\"tax\":number|null,\"payment\":str|null,\"category\":str|null,"
                  "\"items\":[{\"name\":str,\"qty\":number|null,\"price\":number|null}]}. Use null when unreadable. "
                  "Text may be English or Urdu.")


def vision_receipt(path: Path, model="claude-haiku-5-5") -> dict:
    from secrets_store import default_store
    key = default_store().get("anthropic")
    if not key:
        return {}
    import anthropic
    from PIL import Image
    import io
    im = Image.open(path).convert("RGB")
    im.thumbnail((1600, 1600))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    msg = anthropic.Anthropic(api_key=key).messages.create(
        model=model, max_tokens=800,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(buf.getvalue()).decode()}},
            {"type": "text", "text": RECEIPT_PROMPT}]}])
    raw = "".join(getattr(b, "text", "") for b in msg.content)
    m = re.search(r"\{.*\}", raw, re.S)
    return json.loads(m.group(0)) if m else {}


# ---------------- tools ----------------
def _rows(query, source):
    import docsearch
    r = docsearch.search(query, source or "any", limit=100000)
    if not r["items"]:
        return r, []
    db = docsearch._db()
    out = []
    for it in r["items"]:
        row = db.execute("SELECT fields FROM docs WHERE path=?", (it["path"],)).fetchone()
        f = json.loads(row[0]) if row and row[0] else {}
        out.append((it, f))
    db.close()
    return r, out


@tool("invoice_totals",
      "Exact totals over invoices/receipts/quotations that match a request, e.g. 'Khan Traders sales invoices this "
      "month', 'petrol receipts last week', 'all quotations in 2025'. Returns count, total amount, total tax and "
      "per-customer sums from the documents themselves. Use for 'how much', 'kitni', 'total', 'kul'.",
      {"query": {"type": "string"}, "source": {"type": "string", "enum": ["any", "computer", "whatsapp"]}},
      ["query"])
def invoice_totals(query, source="any"):
    r, rows = _rows(query, source)
    if not rows:
        return "No matching documents."
    tot = tax = 0.0
    per, missing, lines = {}, [], []
    for it, f in rows:
        amt = f.get("amount") or _num(it.get("amount"))
        if amt is None:
            missing.append(it["name"])
            continue
        tot += amt
        tax += f.get("amount_tax") or 0
        who = f.get("partner_name") or it.get("chat") or "Unknown"
        per[who] = per.get(who, 0) + amt
        lines.append(f"- {it['name']}: Rs. {amt:,.0f}" + (f" (tax {f['amount_tax']:,.0f})" if f.get("amount_tax") else "")
                     + (f", {f['invoice_number']}" if f.get("invoice_number") else "") + (f", {it['date']}" if it.get("date") else ""))
    out = [f"{len(rows)} document(s). Total Rs. {tot:,.0f}" + (f", tax Rs. {tax:,.0f}" if tax else "") + "."]
    if len(per) > 1:
        out.append("By customer: " + "; ".join(f"{k}: Rs. {v:,.0f}" for k, v in sorted(per.items(), key=lambda x: -x[1])[:10]))
    out += lines[:25]
    if missing:
        out.append(f"No amount found on {len(missing)}: " + ", ".join(missing[:8]))
    if r["mode"] == "close":
        out.insert(0, "Closest matches only - confirm with the user.")
    return "\n".join(out)


@tool("invoice_details",
      "Exact details of specific invoices/receipts/quotations: number, date, total, tax, customer, issuer, payment "
      "method, category. e.g. 'INV-2291 ki date aur amount', 'details of the Bilal Steel quotation'. For receipt "
      "photos set read_photo=true to have the photo read again more carefully (uses the API).",
      {"query": {"type": "string"}, "read_photo": {"type": "boolean"}}, ["query"])
def invoice_details(query, read_photo=False):
    r, rows = _rows(query, "any")
    if not rows:
        return "No matching documents."
    out = []
    for it, f in rows[:8]:
        if read_photo and Path(it["path"]).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            try:
                v = vision_receipt(Path(it["path"]))
                if v:
                    f.update({"issuer": v.get("merchant") or f.get("issuer"), "amount": v.get("total") or f.get("amount"),
                              "amount_tax": v.get("tax") or f.get("amount_tax"), "payment": v.get("payment") or f.get("payment"),
                              "category": v.get("category") or f.get("category"), "items": v.get("items"),
                              "date": v.get("date") or f.get("date")})
                    _save_fields(it["path"], f)
            except Exception as e:
                f["note"] = f"photo read failed: {e}"
        f = {k: v for k, v in f.items() if k != "template"}
        out.append(f"{it['name']} ({it['type']}, chat: {it.get('chat') or '-'}): " + json.dumps(f, ensure_ascii=False))
    return ("Closest matches only - confirm with the user.\n" if r["mode"] == "close" else "") + "\n".join(out)


def _save_fields(path, f):
    import docsearch
    db = docsearch._db()
    db.execute("UPDATE docs SET fields=? WHERE path=?", (json.dumps(f, ensure_ascii=False), path))
    db.commit()
    db.close()


@tool("learn_invoice_layout",
      "Teach Jarvis one sender's invoice layout from a sample, so its number/date/total/tax are read exactly from "
      "now on. query = which document to learn from (e.g. 'latest Khan Traders invoice'); issuer = a word that "
      "appears on all of that sender's invoices (usually their company name).",
      {"query": {"type": "string"}, "issuer": {"type": "string"}}, ["query"])
def learn_invoice_layout(query, issuer=""):
    import docsearch
    r = docsearch.search(query, "any", limit=1)
    if not r["items"]:
        return "I couldn't find that document."
    it = r["items"][0]
    db = docsearch._db()
    text = (db.execute("SELECT text FROM docs WHERE path=?", (it["path"],)).fetchone() or [""])[0]
    db.close()
    if not text:
        return "That document has no readable text."
    out = learn_layout(text, issuer)
    f = extract(text, it["name"], it["type"])
    _save_fields(it["path"], f)
    docsearch.refresh_fields()  # short update: no need to wait for a running scan
    return f"Learned the layout from {it['name']} (saved as {out.name}). Read from it: " + json.dumps(f, ensure_ascii=False)
