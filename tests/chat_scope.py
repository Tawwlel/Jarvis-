"""A question that names a chat ("meezan bank from daddy mobilink") looks inside that chat, never says 'no files'."""
import sys, tempfile, pathlib, time, os
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
import docsearch as d
tmp = pathlib.Path(tempfile.mkdtemp()); d.DATA = tmp; d.WA_DIR = tmp / "whatsapp"
d.CTX["cfg"] = {}
fails = []
def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok: fails.append(name)
def add(chat, name, text, ago=0):
    f = d.WA_DIR / chat / name; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(text or "")
    db = d._db()
    db.execute("INSERT OR REPLACE INTO docs(path,source,chat,name,ext,mtime,size,text,doc_type,amount,doc_date,v2,fields) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (str(f), "whatsapp", chat, name, f.suffix, time.time() - ago, 10, text, "receipt" if text else "", "", "", 2, ""))
    db.commit(); db.close()
for i in range(3):
    add("Daddy Mobilink", f"Screenshot {i}.txt", f"Meezan Bank Raast payment successful Rs {5000+i*100} reference {i}", ago=i * 86400)
add("Daddy Mobilink", "unrelated.txt", "Jazz load receipt 500", ago=5 * 86400)
add("Family", "family receipt.txt", "Meezan Bank transfer 777", ago=1)
for i in range(8):
    add("Maryam", f"m{i}.txt", f"some invoice {i} steel", ago=i)
r = d.search("meezan bank files from daddy mobilink", "any")
names = [i["name"] for i in r["items"]]
check("finds the 3 Meezan screenshots in Daddy Mobilink", r["mode"] in ("specific", "all") and len(names) == 3 and all(n.startswith("Screenshot") for n in names))
check("does not bring Family's Meezan file", "family receipt.txt" not in names)
r = d.search("meezan bank payment receipts from daddy mobilink", "any")
check("receipt wording still finds them", len(r["items"]) >= 3 and r["items"][0]["chat"] == "Daddy Mobilink")
r = d.search("hbl bank files from daddy mobilink", "any")
check("no HBL text: shows the chat's files, mode chat_files", r["mode"] == "chat_files" and len(r["items"]) == 4)
txt = d._fmt(r)
check("message does not say 'no files'", "Do NOT say that no files exist" in txt and "Daddy Mobilink" in txt)
r = d.search("invoices from maryam", "any")
check("chat only + type works", r["items"] and all(i["chat"] == "Maryam" for i in r["items"]))
r = d.search("steel", "any")
check("no chat named: normal global search unchanged", len(r["items"]) >= 8)
print("FAILS:", fails or "none")
