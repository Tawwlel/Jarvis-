"""Usage meter + document-label accuracy regressions found on a real client laptop."""
import sys, tempfile, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import usage, docsearch as d
ok = bad = 0
def check(n, c):
    global ok, bad
    if c: ok += 1
    else: bad += 1; print("FAIL", n)
t = Path(tempfile.mkdtemp()); usage.DATA = t; usage.FILE = t / "u.json"
check("starts at 0%", usage.percent() == 0)
usage.record("claude-haiku-5-5", 100_000, 0); check("100K haiku input = $0.01", abs(usage.snapshot()["cost"] - 0.01) < 1e-9)
usage.record("claude-haiku-5-5", 0, 1_000_000); check("1M haiku output = $0.50", abs(usage.snapshot()["cost"] - 0.51) < 1e-9)
usage.record("claude-haiku-5-5", 200_000, 0); check(">100K prompt costs x5", abs(usage.snapshot()["cost"] - (0.51 + 0.10)) < 1e-9)
check("percent", usage.percent() == round(100 * 0.61 / 5, 1))
check("not blocked", not usage.blocked())
check("set budget", (usage._set_budget(0.5) or True) and usage.blocked())
check("bad budget refused", "isn't valid" in usage.redeem("JV-garbage.sig"))
check("percent capped at 100", usage.percent() == 100.0)
usage._set_budget(5); check("unblocked after raise", not usage.blocked())
# labels
c = d.classify
check("agreement not invoice", c("Transportation Services Agreement - WSA (4).pdf", "Invoice date payable within 30 days") == "agreement")
check("worksheet mentioning invoices is a register", c("adjusting entries for audit.xlsx", "Missing Invoices trip invoice 1523.75 Kuwait invoice 4604") == "register")
check("numbered credit-note workbook kept", c("CN_1326.xlsx", "Apricot Steel Works (Pvt) Ltd Plot 12 CREDIT NOTE Credit No: CN-1326 Date: 2026-04-17") == "credit note")
check("screenshot", c("Screenshot 2023-03-26 134952.png", "") == "screenshot")
check("WhatsApp date from name", d.find_date("WhatsApp Image 2026-11-05 at 2.33.25 PM.jpeg", "", 1794400000) == "2026-11-05")
check("camera date from name", d.find_date("IMG_20261111_101010.jpg", "", 0) == "2026-11-11")
check("junk", all(d._junk(x) for x in ("~$Book.xlsx", "Thumbs.db", "ICON0.PNG")) and not d._junk("invoice.pdf"))
c = "JV-eyJhIjogMTAuMCwgImlkIjogImE2ZWY1ZmFiZWI3ZCJ9.Dm4ha6dNg5PLl568UEYqpSZ_5IrGm3RuI2oTALWVfkQH9S_Yp8ywqXntwMyxDjhL2UsP_mHuVF9nDSxHhpJQBA"
check("valid code raises allowance", "increased" in usage.redeem(c) and usage.snapshot()["budget"] == 10.0)
check("code works once", "already" in usage.redeem(c))
check("tampered code refused", "isn't valid" in usage.redeem(c[:-3] + "AAA"))
print(f"{ok} ok, {bad} failed"); sys.exit(1 if bad else 0)
