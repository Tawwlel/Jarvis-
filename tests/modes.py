"""Fast vs light learning: light remembers locations only and reads files when asked; fast reads everything."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, "scripts")
import docsearch as d, deep_scan as ds
ok = bad = 0
def check(n, c):
    global ok, bad
    if c: ok += 1
    else: bad += 1; print("FAIL", n)
t = Path(tempfile.mkdtemp()); d.DATA = t; ds.STATE = t / "scan.json"
docs = t / "docs"; docs.mkdir()
import docx
for n, txt in (("scan1.docx", "NON-DISCLOSURE AGREEMENT between Apricot and Zeta Steel"), ("scan2.docx", "Quotation QT-9 Bilal Steel total 50,000")):
    D = docx.Document(); D.add_paragraph(txt); D.save(docs / n)
cfg = {"doc_folders": [str(docs)], "file_roots": [str(docs)]}
ds.grant([], True, True, "light"); check("light chosen", ds.learn_mode() == "light")
d.reindex(cfg, include_whatsapp=False, include_email=False)
db = d._db(); rows = db.execute("SELECT name,text FROM docs").fetchall(); db.close()
check("light: nothing read yet", rows and all(not r[1] for r in rows))
r = d.search("zeta steel")
check("light: found by reading on demand", any("scan1" in i["name"] for i in r["items"]))
db = d._db(); txt = db.execute("SELECT text, doc_type FROM docs WHERE name='scan1.docx'").fetchone(); db.close()
check("light: remembered after reading", "Zeta" in txt[0] and txt[1] == "nda")
ds.set_mode("fast"); d.reindex(cfg, include_whatsapp=False, include_email=False)
db = d._db(); left = db.execute("SELECT COUNT(*) FROM docs WHERE text='' OR text IS NULL").fetchone()[0]; db.close()
check("fast: everything read after switching", left == 0)
check("explains both modes", "Fast search" in ds.scan_mode() and "Light" in ds.scan_mode())
print(f"{ok} ok, {bad} failed"); sys.exit(1 if bad else 0)
