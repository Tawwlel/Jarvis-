"""Score the 27 group-pack questions against a copy of the LAPTOP's real index (docs.db staged from the device)."""
import sys, json, shutil, tempfile
from pathlib import Path, PureWindowsPath
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import docsearch as d, tools  # noqa: E402
src_db = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/ldb")
tmp = Path(tempfile.mkdtemp()); [shutil.copy2(f, tmp / f.name) for f in src_db.iterdir()]
d.DATA = tmp; tools.CTX["cfg"] = {}
src = (HERE / "group_pack.py").read_text()
T = json.load(open(HERE / "truth.json"))
extra = {"Shop 14 Saddar agreement.docx": {"rent"}, "Book1.xlsx": {"salary"}, "tyre_prices.csv": {"tyre"},
         "Profile v3.pptx": {"profile"}, "noc.odt": {"noc"}, "notes.txt": {"meeting"}, "Project Alpha.zip": {"alpha", "scope"},
         "IMG-20261110-WA0011.jpg": {"meezan", "daddy"}, "IMG-20261110-WA0012.jpg": {"meezan", "daddy"},
         "Screenshot_20261111-101500.png": {"meezan"}, "IMG-20261112-WA0020.jpg": {"hbl"}}
ns = {"T": T, "extra": extra}; exec(src[src.index("S = lambda t"):src.index("rows, by_area")], ns)
f1s, strict = [], []
for area, q, exp in ns["Q"]:
    r = d.search(q.replace(" from the Apricot Digital group", ""), "any")
    allp = [PureWindowsPath(i["path"]) for i in r["items"]]
    got = {p.name for p in allp if "test_pack" in str(p)}; others = [p.name for p in allp if "test_pack" not in str(p)]
    tp = len(got & exp); p = tp / len(got) if got else (1.0 if not exp else 0); rc = tp / len(exp) if exp else 1
    f1 = 0 if p + rc == 0 else 2 * p * rc / (p + rc); f1s.append(f1)
    ps = tp / len(allp) if allp else 0; strict.append(0 if ps + rc == 0 else 2 * ps * rc / (ps + rc))
    print(f"{'OK ' if f1 == 1 else ('~  ' if f1 >= .5 else 'BAD')} {area:15} got {len(got):2}/{len(exp):2} +{len(others)} other [{r['mode']}] {q}")
    if f1 < 1: print("     wrong:", sorted(got - exp)[:3], " missed:", sorted(exp - got)[:3])
    if others: print("     also:", others[:4])
print(f"\nexact {sum(1 for f in f1s if f == 1)}/{len(f1s)}  test files {sum(f1s)/len(f1s)*10:.1f}/10   with other laptop files counted wrong {sum(strict)/len(strict)*10:.1f}/10")
