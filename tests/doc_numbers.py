"""Finding a document by its number, however it is typed: INV-1148, INV1148, inv 1148, invoice 1148, 1148."""
import sys
from pathlib import Path
sys.path.insert(0, "scripts")
import docsearch as d
here = Path(__file__).resolve().parent
d.DATA = here / "data"; d.WA_DIR = here / "corpus" / "whatsapp"
ok = bad = 0
for q, want in [("invoice 1148", "INV-1148"), ("INV1148", "INV-1148"), ("inv 1148", "INV-1148"), ("1148", "INV-1148"), ("INV-1148", "INV-1148"),
                ("quotation 1250", "QT-1250"), ("QT1250", "QT-1250"), ("qt 1021", "QT-1021"), ("DC1126", "DC-1126"), ("chalan 1126", "DC-1126")]:
    r = d.search(q, "any")
    good = len(r["items"]) == 1 and want in r["items"][0]["name"]
    ok += good; bad += not good
    if not good: print("FAIL", q, [i["name"] for i in r["items"]][:3])
print(f"{ok} ok, {bad} failed"); sys.exit(1 if bad else 0)
