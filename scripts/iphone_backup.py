"""
iPhone backup reader: imports EVERY WhatsApp document and photo ever received, straight from the iPhone backup
on this laptop (made with the Apple Devices app or iTunes). WhatsApp Web only shows recent weeks; the backup has
the whole history.

Built on KnugiHK/WhatsApp-Chat-Exporter (MIT): its identifiers for WhatsApp's files inside an iOS backup, and
iphone_backup_decrypt for password-protected backups. Only document/photo files are copied - not chats' text,
videos or voice notes - into data/whatsapp/<chat>/, dated with the day they were sent.

Read-only: the backup itself is never changed.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

from tools import CTX, tool

DATA = Path(__file__).parent.parent / "data"
WA_DIR = DATA / "whatsapp"
STATE = DATA / "iphone_import.json"
APPLE_TIME = 978307200  # seconds between 1970 and 2001 (Apple's clock start)
KEEP_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".txt"}

try:  # the exporter's own constants, so we follow its knowledge of WhatsApp's file layout
    from Whatsapp_Chat_Exporter.utility import WhatsAppBusinessIdentifier as _B, WhatsAppIdentifier as _W
    APPS = [(str(_W.DOMAIN), str(_W.MESSAGE)), (str(_B.DOMAIN), str(_B.MESSAGE))]
except Exception:  # pragma: no cover - same values, in case the package is missing
    APPS = [("AppDomainGroup-group.net.whatsapp.WhatsApp.shared", "7c7fba66680ef796b916b067077cc246adacf01d"),
            ("AppDomainGroup-group.net.whatsapp.WhatsAppSMB.shared", "724bd3b98b18518b455a87c1f3ac3a0d189c4466")]


def backup_folders() -> list[Path]:
    """Where Apple Devices / iTunes keep iPhone backups on Windows (newest first)."""
    home = Path.home()
    roots = [Path(os.environ.get("APPDATA", home / "AppData/Roaming")) / "Apple Computer/MobileSync/Backup",
             home / "Apple/MobileSync/Backup", home / "AppData/Roaming/Apple Computer/MobileSync/Backup"]
    extra = CTX.get("cfg", {}).get("iphone_backup_dir")
    if extra:
        roots.insert(0, Path(extra))
    found = []
    for r in roots:
        if (r / "Manifest.db").exists():
            found.append(r)
        elif r.is_dir():
            found += [d for d in r.iterdir() if (d / "Manifest.db").exists()]
    return sorted(set(found), key=lambda d: (d / "Manifest.db").stat().st_mtime, reverse=True)


def _fid(domain: str, rel: str) -> str:
    return hashlib.sha1(f"{domain}-{rel}".encode()).hexdigest()


def _is_encrypted(base: Path) -> bool:
    try:
        with sqlite3.connect(base / "Manifest.db") as db:
            db.execute("SELECT count() FROM Files").fetchone()
        return False
    except sqlite3.DatabaseError:
        return True


class _Source:
    """Gives files out of a backup, encrypted or not."""

    def __init__(self, base: Path, password: str | None):
        self.base, self.enc = base, None
        if _is_encrypted(base):
            if not password:
                raise PermissionError("password")
            from iphone_backup_decrypt import EncryptedBackup
            self.enc = EncryptedBackup(backup_directory=str(base), passphrase=password)

    def get(self, domain: str, rel: str, out: Path) -> bool:
        if self.enc is not None:
            try:
                self.enc.extract_file(relative_path=rel, domain_like=domain, output_filename=str(out))
                return out.exists()
            except Exception:
                return False
        f = _fid(domain, rel)
        src = self.base / f[:2] / f
        if not src.exists():
            return False
        shutil.copyfile(src, out)
        return True


def _safe(name: str) -> str:
    import re
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip(" .")[:120] or "file"


def import_backup(password: str | None = None, base: Path | None = None) -> dict:
    bases = [base] if base else backup_folders()
    if not bases:
        return {"error": "no_backup"}
    base = bases[0]
    src = _Source(base, password)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    done = set(state.get(str(base), []))
    added, per_chat = 0, {}
    tmp = Path(tempfile.mkdtemp(prefix="jarvis_ios_"))
    try:
        for domain, msg_id in APPS:
            dbfile = tmp / f"{msg_id}.sqlite"
            if not src.get(domain, "ChatStorage.sqlite", dbfile):
                continue
            names = {}
            cfile = tmp / f"{msg_id}_contacts.sqlite"
            if src.get(domain, "ContactsV2.sqlite", cfile):  # phone numbers -> contact names
                try:
                    with sqlite3.connect(cfile) as cdb:
                        names = {j: n for j, n in cdb.execute(
                            "SELECT ZWHATSAPPID, ZFULLNAME FROM ZWAADDRESSBOOKCONTACT WHERE ZFULLNAME IS NOT NULL")}
                except sqlite3.DatabaseError:
                    pass
            db = sqlite3.connect(dbfile)
            rows = db.execute("""
                SELECT ZWAMEDIAITEM.Z_PK, ZWAMEDIAITEM.ZMEDIALOCALPATH, ZWAMEDIAITEM.ZTITLE,
                       ZWAMESSAGE.ZMESSAGEDATE, ZWACHATSESSION.ZPARTNERNAME, ZWACHATSESSION.ZCONTACTJID
                FROM ZWAMEDIAITEM
                    JOIN ZWAMESSAGE ON ZWAMEDIAITEM.ZMESSAGE = ZWAMESSAGE.Z_PK
                    JOIN ZWACHATSESSION ON ZWAMESSAGE.ZCHATSESSION = ZWACHATSESSION.Z_PK
                WHERE ZWAMEDIAITEM.ZMEDIALOCALPATH IS NOT NULL""").fetchall()
            db.close()
            for pk, local, title, when, chat, jid in rows:
                key = f"{domain[-12:]}:{pk}"
                ext = Path(local).suffix.lower()
                if key in done or ext not in KEEP_EXT or "/Stickers/" in local or "/Avatar" in local:
                    continue
                chat = _safe(chat or names.get(jid) or (jid or "WhatsApp").split("@")[0])
                day = time.strftime("%Y-%m-%d", time.localtime(APPLE_TIME + float(when or 0)))
                if title and Path(title).suffix.lower() == ext:
                    name = title  # documents keep their real file name
                elif ext in (".jpg", ".jpeg", ".png", ".heic"):
                    cap = f" {title.strip()[:50]}" if title else ""
                    name = f"WhatsApp photo {day}{cap}{ext}"  # photos: date + caption, so they're findable
                else:
                    name = f"WhatsApp file {day}{ext}"
                folder = WA_DIR / chat
                folder.mkdir(parents=True, exist_ok=True)
                dest = folder / _safe(name)
                got = tmp / f"m{pk}{ext}"
                if not src.get(domain, f"Message/{local}", got):
                    done.add(key)
                    continue
                if dest.exists() and dest.stat().st_size == got.stat().st_size:
                    got.unlink()  # already here (e.g. restored from a Jarvis backup): never keep two copies
                    done.add(key)
                    continue
                if dest.exists():
                    dest = folder / f"{dest.stem}_{pk}{dest.suffix}"
                shutil.move(str(got), dest)
                if True:
                    ts = APPLE_TIME + float(when or 0)
                    try:
                        os.utime(dest, (ts, ts))  # so "latest", "in March" etc. work by the day it was sent
                    except OSError:
                        pass
                    added += 1
                    per_chat[chat] = per_chat.get(chat, 0) + 1
                done.add(key)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    state[str(base)] = sorted(done)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state))
    return {"added": added, "chats": per_chat, "backup": base.name}


@tool("iphone_whatsapp_import",
      "Import ALL old WhatsApp documents and photos from the iPhone backup on this laptop (full history, not just "
      "recent). Use when the owner asks for old WhatsApp files, or after they made a new iPhone backup.", {}, [])
def iphone_whatsapp_import():
    try:
        from secrets_store import default_store
        pw = default_store().get("iphone_backup_password")
    except Exception:
        pw = None
    try:
        r = import_backup(pw)
    except PermissionError:
        return ("The iPhone backup is password-protected. Ask the owner to enter the backup password in "
                "Settings > WhatsApp, then try again.")
    except Exception as e:
        return f"Couldn't read the iPhone backup: {e}"
    if r.get("error"):
        return ("No iPhone backup found on this laptop. Ask the owner to connect the iPhone by cable, open the "
                "Apple Devices app (or iTunes), and click 'Back Up Now'. Then ask again.")
    try:
        import docsearch
        with docsearch._index_lock:
            docsearch.reindex(CTX.get("cfg", {}), include_computer=False, include_whatsapp=True)
    except Exception:
        pass
    if not r["added"]:
        return "The iPhone backup has no new WhatsApp documents since the last import."
    top = ", ".join(f"{c} ({n})" for c, n in sorted(r["chats"].items(), key=lambda x: -x[1])[:6])
    return f"Imported {r['added']} WhatsApp document(s)/photo(s) from the iPhone backup: {top}. They're searchable now."


def watch_new_backup(last_seen: dict) -> bool:
    """True when a newer backup appeared since the last check (used by the WhatsApp agent)."""
    b = backup_folders()
    if not b:
        return False
    m = (b[0] / "Manifest.db").stat().st_mtime
    if last_seen.get("mtime") != m:
        last_seen["mtime"] = m
        return True
    return False
