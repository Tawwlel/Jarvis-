import sys, json, shutil, tempfile, time, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import config, memory, secrets_store, tools, backup
T=Path(tempfile.mkdtemp()); ok=True
def check(n,c,i=""):
    global ok; ok&=bool(c); print("PASS" if c else "FAIL", n, str(i)[:160])
# ----- old laptop -----
A=T/"A"/"app"; A.mkdir(parents=True)
config.ROOT=A; memory.DB=A/"jarvis_memory.db"
sa=secrets_store.SecretStore(data_dir=T/"A"/"sec"); secrets_store.set_default_store(sa)
sa.set("anthropic","sk-ant-OLDKEY"); sa.set("email_password","app-pw-123")
m=memory.Memory(); m.add_note("Khan (2026-11-11)","Khan Traders wants 30 day credit"); m.remember("accountant","Mr Rashid"); m.add_todo("Pay electricity bill"); m.add_reminder(time.time()+3600,"Call Bilal")
oldhome=str(Path.home())
cfg={"owner_name":"Zeeshan","language":"ur","onboarded":True,"file_roots":["C:\\Users\\old\\Documents", str(T)],"email":{"address":"me@gmail.com"},"backup":{"email":"me@gmail.com"}}
(A/"config.local.json").write_text(json.dumps(cfg))
(A/"data"/"whatsapp"/"Talal Jazz").mkdir(parents=True); shutil.copy(""+str(Path(__file__).resolve().parent / 'fixtures' / 'Sales Invoice INV-9001 Khan Traders.pdf')+"", A/"data"/"whatsapp"/"Talal Jazz"); (A/"data"/"whatsapp"/"Talal Jazz"/".seen").write_text("m1")
(A/"data"/"invoice_templates").mkdir(); (A/"data"/"invoice_templates"/"noor.yml").write_text("issuer: NOOR")
(A/"data"/"docs.db").write_text("index"); 
big=A/"data"/"whatsapp"/"Talal Jazz"/"big.jpg"; big.write_bytes(os.urandom(3*1024*1024+123))
t=time.time(); small=backup.create("secret12",T/"out",full=False,cfg=cfg); full=backup.create("secret12",T/"out",full=True,cfg=cfg,label="x"); 
check("small + full backups made", small.exists() and full.exists(), f"{small.stat().st_size} / {full.stat().st_size} bytes in {time.time()-t:.1f}s")
raw=full.read_bytes()
check("nothing readable inside the file", b"sk-ant-OLDKEY" not in raw and b"Khan Traders" not in raw and b"app-pw-123" not in raw)
check("label readable without password", backup.info(full)["owner"]=="Zeeshan" and backup.info(full)["kind"]=="full", backup.info(full))
try: backup.create("123",T/"out",cfg=cfg); check("short password refused",False)
except ValueError as e: check("short password refused",True,e)
m.db.close()
# ----- new laptop -----
B=T/"B"/"app"; B.mkdir(parents=True); (B/"data").mkdir(); (B/"data"/"docs.db").write_text("stale")
config.ROOT=B; memory.DB=B/"jarvis_memory.db"
sb=secrets_store.SecretStore(data_dir=T/"B"/"sec"); secrets_store.set_default_store(sb)
check("new laptop starts empty", sb.get("anthropic") is None)
for bad,label in (("wrongpass","wrong password"),):
    try: backup.restore(full,bad); check(label+" refused",False)
    except PermissionError as e: check(label+" refused", not (B/"restore_pending").exists() or not any((B/"restore_pending").iterdir()), e)
tam=T/"tampered.jbk"; b=bytearray(raw); b[len(b)//2]^=1; tam.write_bytes(b)
try: backup.restore(tam,"secret12"); check("tampered file refused",False)
except PermissionError as e: check("tampered file refused",True,e)
cut=T/"cut.jbk"; cut.write_bytes(raw[:len(raw)-1024*1024-40])
try: backup.restore(cut,"secret12"); check("cut-short file refused",False)
except Exception as e: check("cut-short file refused",True,e)
try: backup.restore(Path(""+str(Path(__file__).resolve().parent / 'fixtures' / 'Sales Invoice INV-9001 Khan Traders.pdf')+""),"x"); check("non-backup refused",False)
except ValueError as e: check("non-backup file refused",True,e)
shutil.rmtree(B/"restore_pending",ignore_errors=True)
meta=backup.restore(full,"secret12")
check("keys moved into the new laptop's secure storage", sb.get("anthropic")=="sk-ant-OLDKEY" and sb.get("email_password")=="app-pw-123" and sb.get("backup_password")=="secret12")
check("files wait until restart", not (B/"jarvis_memory.db").exists() and (B/"restore_pending"/"jarvis_memory.db").exists())
check("apply at start-up", backup.apply_pending() and not (B/"restore_pending").exists())
m2=memory.Memory()
check("notes readable on the new laptop", "30 day credit" in m2.notes_search("credit"))
check("facts, to-dos, reminders came along", "Rashid" in m2.facts_text() and m2.list_todos()[0]["text"]=="Pay electricity bill" and "Call Bilal" in str(m2.reminders_today()), m2.reminders_today())
c2=json.loads((B/"config.local.json").read_text())
check("settings came along; folders that don't exist here dropped", c2["owner_name"]=="Zeeshan" and c2["language"]=="ur" and c2.get("file_roots")==[str(T)], c2.get("file_roots"))
wa=B/"data"/"whatsapp"/"Talal Jazz"
check("WhatsApp files + download record came along (big file intact)", (wa/"Sales Invoice INV-9001 Khan Traders.pdf").exists() and (wa/".seen").read_text()=="m1" and (wa/"big.jpg").read_bytes()==big.read_bytes())
check("learned layouts came along; old index cleared for rebuild", (B/"data"/"invoice_templates"/"noor.yml").exists() and not (B/"data"/"docs.db").exists())
check("second start: nothing pending", backup.apply_pending() is False)
# small backup has no WhatsApp files
C=T/"C"/"app"; C.mkdir(parents=True); config.ROOT=C; memory.DB=C/"jarvis_memory.db"; secrets_store.set_default_store(secrets_store.SecretStore(data_dir=T/"C"/"sec"))
backup.restore(small,"secret12"); backup.apply_pending()
check("small backup: memory yes, WhatsApp files no", (C/"jarvis_memory.db").exists() and not (C/"data"/"whatsapp").exists())
# ----- automatic backups + email copy -----
config.ROOT=B; memory.DB=B/"jarvis_memory.db"; secrets_store.set_default_store(sb)
cfgb=json.loads((B/"config.local.json").read_text()); cfgb["backup"]["folder"]=str(T/"auto"); cfgb["backup"]["email"]="me@gmail.com"
sent=[]
import smtplib
class FakeSMTP:
    def __init__(s,host,port,timeout=0): s.host=host; assert port==465
    def __enter__(s): return s
    def __exit__(s,*a): pass
    def login(s,u,p): assert (u,p)==("me@gmail.com","app-pw-123")
    def send_message(s,m): sent.append((s.host,m["To"],m["Subject"],[a.get_filename() for a in m.iter_attachments()]))
smtplib.SMTP_SSL=FakeSMTP
notes=[]
r=backup.auto_backup(cfgb,notes.append); check("daily backup saved and emailed to the owner only", "saved" in r and "emailed" in r and sent and sent[0][0]=="smtp.gmail.com" and sent[0][1]=="me@gmail.com" and sent[0][3][0].endswith(".jbk"), (r,sent))
check("not repeated the same day", backup.auto_backup(cfgb,notes.append)=="not due")
st=backup._state(); 
for k in range(9):
    st["last"]=0; backup._save_state(st); time.sleep(0.01)
    p=backup.create("secret12",T/"auto",cfg=cfgb,label=f"auto"); os.utime(p,(time.time()-k*86400,)*2); p.rename(p.with_name(f"Jarvis-backup-auto-old{k}.jbk"))
st["last"]=0; backup._save_state(st); r=backup.auto_backup(cfgb,notes.append)
check("only the last 7 automatic backups are kept; emailed weekly not daily", len(list((T/"auto").glob("Jarvis-backup-auto-*.jbk")))==7 and len(sent)==1, (r,len(sent)))
sb.delete("backup_password"); st=backup._state(); st["last"]=0; st.pop("asked",None); backup._save_state(st)
r1=backup.auto_backup(cfgb,notes.append); r2=backup.auto_backup(cfgb,notes.append)
check("no password: asks once, never nags", r1=="no password" and len([n for n in notes if "backup password" in n])==1, notes[-1][:60] if notes else "")
tools.CTX["cfg"]=cfgb
check("backup_now tool explains when no password", "No backup password" in backup.backup_now())
sb.set("backup_password","secret12"); out=backup.backup_now(); check("backup_now tool makes a full backup", "Backup saved" in out, out[:90])
cfgb["email"]["address"]=""; check("no email connected -> reason given, no crash", backup.email_copy(small,cfgb)=="email is not connected")
print("ALL OK" if ok else "SOME FAILED")
