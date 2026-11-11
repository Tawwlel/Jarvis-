"""Every example sentence printed in the client guide must work in the finder. Run: python tests/guide_examples.py"""
import sys, datetime as dt; sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent / 'scripts'))
import docsearch as ds, shutil, pathlib, tools, os, time
d=pathlib.Path(__import__('tempfile').mkdtemp()); shutil.rmtree(d,ignore_errors=True); pc=d/'pc'; pc.mkdir(parents=True)
today=dt.date.today(); monday=today-dt.timedelta(days=today.weekday())
def mk(name, typ, no, cust, amt, date, extra=""):
    (pc/name).write_text(f"{typ.upper()}\nNo: {no}\nDate: {date:%Y-%m-%d}\nBill To: {cust}\n{extra}\nGrand Total: Rs. {amt:,}\n")
lastm=(today.replace(day=1)-dt.timedelta(days=1)).replace(day=12)
mk("Sales Invoice INV-2291 Khan Traders.txt","Sales Invoice","INV-2291","Khan Traders",250000,today)
mk("Sales Invoice INV-2200 Khan Traders.txt","Sales Invoice","INV-2200","Khan Traders",40000,lastm)
mk("Sales Invoice INV-1900 Ali Enterprises.txt","Sales Invoice","INV-1900","Ali Enterprises",30000,dt.date(today.year,3,14))
mk("Quotation QT-114 Bilal Steel.txt","Quotation","QT-114","Bilal Steel Mills",9800000,dt.date(today.year,6,18),"Supply of 40 tons steel rebar")
mk("Quotation QT-090 Bilal Steel.txt","Quotation","QT-090","Bilal Steel Mills",500000,dt.date(today.year-1,3,2))
mk("Payment Receipt RCPT-77 Zahid.txt","Payment Receipt","RCPT-77","Zahid and Sons",20000,monday-dt.timedelta(days=3))
(pc/"Shell receipt.txt").write_text(f"SHELL PAKISTAN\nDate: {monday-dt.timedelta(days=5):%Y-%m-%d}\nHi-Octane 20 L\nTOTAL Rs. 6,450\nPaid by card\n")
ds.DATA=d/'data'; ds.WA_DIR=d/'data/whatsapp'; cfg={"file_roots":[str(pc)]}; tools.CTX["cfg"]=cfg; ds.reindex(cfg)
T=[("Sales invoices dikhao",{"INV-2291","INV-2200","INV-1900"}),("Show all quotations",{"QT-114","QT-090"}),
("Khan Traders ki invoices dikhao",{"INV-2291","INV-2200"}),("Bilal Steel ki quotation nikalo",{"QT-114","QT-090"}),
("March ki sales invoices",{"INV-1900"}),(f"Receipts from {today.year}",{"RCPT-77","Shell"}),
("Pichle mahine ke bills",{"INV-2200"} if lastm.month!=(monday-dt.timedelta(days=5)).month else None),
("Ali Enterprises ki latest invoice",{"INV-1900"}),("Sab se purani quotation",{"QT-090"}),("Bilal Steel ki latest quotation",{"QT-114"}),
("2 lakh se zyada wali invoices",{"INV-2291"}),("Invoices under 50 thousand",{"INV-2200","INV-1900"}),("Invoice INV-2291 dikhao",{"INV-2291"}),
("Computer se sales invoices dikhao",{"INV-2291","INV-2200","INV-1900"}),("March ki quotations dikhao",{"QT-090"}),
("Pichle hafte petrol ki receipts ka total",{"Shell"}),("aaj ki sales invoices",{"INV-2291"}),("is mahine ki sales invoices",{"INV-2291"}),
("receipts last week",{"RCPT-77","Shell"}),("Khan Traders ki kul sales kitni hai?",{"INV-2291","INV-2200"}),("invoices from the last 3 days",{"INV-2291"})]
bad=0
for q,exp in T:
    if exp is None: continue
    r=ds.search(q,"computer"); got={k for k in ["INV-2291","INV-2200","INV-1900","QT-114","QT-090","RCPT-77","Shell"] if any(k in i["name"] for i in r["items"])}
    ok = got==exp and r["mode"]!="close"
    bad+=not ok
    print("PASS" if ok else "FAIL", repr(q), r["mode"], sorted(got), "" if ok else f"expected {sorted(exp)} terms={r['terms']} filters={r['filters']}")
print("bad",bad)
sys.exit(1 if bad else 0)
