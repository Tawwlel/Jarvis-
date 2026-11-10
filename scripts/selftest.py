"""
Document finder self-test, run from the tray menu ("Run document test").
Indexes the sample documents in tests/corpus (76 invoices, quotations, receipts, scans, photos,
WhatsApp-style files and decoys) in a separate test index - your real files and index are not touched -
then runs real searches and shows each result next to the right answer in the chat window.
"""
import importlib.util
import json
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"


def _isolated_docsearch():
    """A separate copy of the finder with its own index, so the test never mixes with real files."""
    spec = importlib.util.spec_from_file_location("docsearch_selftest", Path(__file__).parent / "docsearch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DATA = TESTS / "selftest_index"
    mod.WA_DIR = TESTS / "corpus" / "whatsapp"
    mod.OUT_DIR = TESTS / "selftest_out"
    return mod


def cases(T):
    S = lambda t: t["type"] == "sales invoice"
    W = lambda f: {t["name"] for t in T if f(t)}

    def latest(f):
        xs = sorted([t for t in T if f(t)], key=lambda t: t["date"], reverse=True)
        return {xs[0]["name"]} if xs else set()
    c = [
        ("All of one type", "all sales invoices", "any", W(S)),
        ("All of one type", "all quotations", "any", W(lambda t: t["type"] == "quotation")),
        ("All of one type", "all receipts", "any", W(lambda t: t["type"] == "receipt")),
        ("Client", "sales invoices for Khan Traders", "any", W(lambda t: S(t) and t["client"] == "Khan Traders")),
        ("Look-alike client", "Khan Trading Company invoices", "any",
         W(lambda t: t["type"] in ("sales invoice", "purchase invoice") and t["client"] == "Khan Trading Company")),
        ("Letterhead word 'Steel' on every page", "quotation for Bilal Steel", "any",
         W(lambda t: t["type"] == "quotation" and t["client"] == "Bilal Steel Mills")),
        ("Ampersand in name", "sales invoice Zahid and Sons", "any", W(lambda t: S(t) and t["client"] == "Zahid & Sons")),
        ("Hyphenated name", "al noor builders sales invoice", "any", W(lambda t: S(t) and t["client"] == "Al-Noor Builders")),
        ("Only WhatsApp", "sales invoices", "whatsapp", W(lambda t: S(t) and t["source"] == "whatsapp")),
        ("Only computer", "sales invoices", "computer", W(lambda t: S(t) and t["source"] == "computer")),
        ("Spelling mistakes", "khaan tradrs sales invoice", "any", W(lambda t: S(t) and t["client"] == "Khan Traders")),
        ("Month and year", "sales invoices march 2026", "any", W(lambda t: S(t) and t["date"].startswith("2026-03"))),
        ("Other types", "purchase invoices", "any", W(lambda t: t["type"] == "purchase invoice")),
        ("Other types", "delivery challan", "any", W(lambda t: t["type"] == "delivery challan")),
        ("Client that doesn't exist", "sales invoice for Imran Motors", "any", set()),
        ("Natural sentence", "can you please find me the quotations we sent to bilal steel mills", "any",
         W(lambda t: t["type"] == "quotation" and t["client"] == "Bilal Steel Mills")),
        ("Latest", "latest sales invoice for Zahid and Sons", "any", latest(lambda t: S(t) and t["client"] == "Zahid & Sons")),
        ("Amount above", "sales invoices above 3 lakh", "any", W(lambda t: S(t) and t["amount"] > 300000)),
        ("Amount below", "quotations under 50k", "any", W(lambda t: t["type"] == "quotation" and t["amount"] < 50000)),
        ("Name spelled differently", "Rahman hardware sales invoices", "any", W(lambda t: S(t) and t["client"] == "Rehman Hardware")),
        ("Roman Urdu", "Zahid & Sons ki sari sales invoices dikhao", "any", W(lambda t: S(t) and t["client"] == "Zahid & Sons")),
        ("Urdu", "زاہد اینڈ سنز کی تمام سیلز انوائس", "any", W(lambda t: S(t) and t["client"] == "Zahid & Sons")),
        ("Urdu", "بلال اسٹیل کی کوٹیشن", "any", W(lambda t: t["type"] == "quotation" and t["client"] == "Bilal Steel Mills")),
        ("Hidden folder is ignored", "invoice INV-9999", "any", set()),
    ]
    for t in [t for t in T if S(t)][:3]:
        c.append(("Invoice number", f"invoice {t['number']}", "any", {t["name"]}))
        c.append(("Client + amount", f"sales invoice {t['client']} {t['amount']:,}", "any", {t["name"]}))
    return c


def run(cfg: dict, say):
    """say(text) posts a line to the chat window. Returns (passed, total)."""
    corpus = TESTS / "corpus"
    if not (corpus / "pc").exists():
        say("The sample documents are missing (tests/corpus). Run update and try again.")
        return 0, 0
    T = json.loads((TESTS / "truth.json").read_text(encoding="utf-8"))
    d = _isolated_docsearch()
    shutil.rmtree(d.DATA, ignore_errors=True)
    tcfg = {"file_roots": [str(corpus / "pc")]}
    say(f"DOCUMENT FINDER TEST\nSample set: {len(T)} files - typed PDFs, scanned PDFs, tilted/blurry photos, Word, "
        f"Excel, WhatsApp files, and decoys (a CV, a bank statement, a price list). Your real files are not touched.\n"
        f"Step 1: reading every file (photos are read with OCR, so this is the slow part)...")
    import tools
    saved_cfg = tools.CTX.get("cfg")
    tools.CTX["cfg"] = tcfg  # point the finder at the sample folder just for this run
    t0 = time.time()
    try:
        r = d.reindex(tcfg)
    finally:
        tools.CTX["cfg"] = saved_cfg if saved_cfg is not None else cfg
    say(f"Read {r['total']} files in {time.time() - t0:.0f}s.\nStep 2: running {len(cases(T))} searches...")
    passed = 0
    all_cases = cases(T)
    for i, (what, q, src, exp) in enumerate(all_cases, 1):
        t1 = time.time()
        res = d.search(q, src)
        ms = (time.time() - t1) * 1000
        got = {Path(it["path"]).name for it in res["items"]}
        if not exp and res["mode"] == "close":
            got_exact = set()
        else:
            got_exact = got
        ok = got_exact == exp
        passed += ok
        where = "" if src == "any" else f" [{src} only]"
        line = (f"{'PASS' if ok else 'FAIL'}  {i}/{len(all_cases)}  {what}\n"
                f"   \"{q}\"{where}\n   found {len(got_exact)}, expected {len(exp)} ({ms:.0f} ms)")
        if got_exact and len(got_exact) <= 3:
            line += "\n   -> " + ", ".join(sorted(got_exact))
        if not exp and res["mode"] == "close" and got:
            line += "\n   (no exact match, so Jarvis would offer the closest ones and ask)"
        if not ok:
            wrong, missed = sorted(got_exact - exp)[:3], sorted(exp - got_exact)[:3]
            line += f"\n   wrong: {wrong}  missed: {missed}"
        say(line)
        time.sleep(0.15)  # so it's readable as it scrolls
    say(f"RESULT: {passed} of {len(all_cases)} searches returned exactly the right files.")
    return passed, len(all_cases)
