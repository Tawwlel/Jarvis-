"""
Urdu reader for photos and scanned documents.

Uses Tesseract's Urdu model (tessdata_best, Apache-2.0) - free for commercial use.
(UTRNet reads printed Urdu even better, but its licence is non-commercial: it can be switched in here only with
written permission from its authors.)

The Tesseract program ships inside the Jarvis zip; the Urdu + English language files (~23 MB) download once into
data/tessdata the first time an image is read.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
TESSDATA = ROOT / "data" / "tessdata"
LANG_URLS = ["https://github.com/Tawwlel/Jarvis-/releases/download/models/{}.traineddata",
             "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main/{}.traineddata"]
SHA256 = {"urd": "65af3f6e50a3c3df15d7b405aab5d467e53433207745c8f5be5b8ff1a58a67c8",
          "eng": "8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba"}
ARABIC = re.compile(r"[\u0600-\u06FF]")
_lock = threading.Lock()
_missing = {"exe": False}


def tesseract_exe() -> str | None:
    cands = [ROOT / "tesseract" / "tesseract.exe", ROOT.parent / "tesseract" / "tesseract.exe",
             Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tesseract-OCR" / "tesseract.exe",
             Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe"]
    for c in cands:
        if c.exists():
            return str(c)
    return shutil.which("tesseract")


def _ensure_langs() -> bool:
    with _lock:
        TESSDATA.mkdir(parents=True, exist_ok=True)
        for lang in ("urd", "eng"):
            f = TESSDATA / f"{lang}.traineddata"
            if f.exists() and f.stat().st_size > 1_000_000:
                continue
            for url in LANG_URLS:
                try:
                    tmp = f.with_suffix(".part")
                    with urllib.request.urlopen(url.format(lang), timeout=120) as r, open(tmp, "wb") as out:
                        shutil.copyfileobj(r, out)
                    import hashlib
                    if hashlib.sha256(tmp.read_bytes()).hexdigest() == SHA256[lang]:  # only the exact expected file
                        tmp.replace(f)
                        break
                    tmp.unlink(missing_ok=True)
                except Exception as e:
                    print("[urdu-ocr] language download failed:", e)
            if not f.exists():
                return False
        return True


def available() -> bool:
    return bool(tesseract_exe())


def read(img) -> str:
    """Text from a PIL image in Urdu + English. Empty string if the reader isn't installed."""
    exe = tesseract_exe()
    if not exe:
        if not _missing["exe"]:
            print("[urdu-ocr] Tesseract not found - Urdu photos won't be read.")
            _missing["exe"] = True
        return ""
    if not _ensure_langs():
        return ""
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        im = img.convert("L")
        if im.width < 1400:  # small phone photos read much better when enlarged
            k = 1400 / im.width
            im = im.resize((1400, int(im.height * k)))
        im.save(path)
        flags = 0x08000000 if sys.platform == "win32" else 0  # no console window
        r = subprocess.run([exe, path, "stdout", "--tessdata-dir", str(TESSDATA), "-l", "urd+eng", "--psm", "3", "-c", "tessedit_create_tsv=1"],
                           capture_output=True, timeout=90, creationflags=flags)
        return _confident(r.stdout.decode("utf-8", "ignore"))
    except Exception as e:
        print("[urdu-ocr] failed:", e)
        return ""
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _confident(tsv: str, min_conf=65) -> str:
    """Keep only words Tesseract is sure about, line by line (drops the junk it 'sees' in English-only photos)."""
    lines, cur, key = [], [], None
    for row in tsv.splitlines()[1:]:
        c = row.split("\t")
        if len(c) < 12 or not c[11].strip():
            continue
        try:
            conf = float(c[10])
        except ValueError:
            continue
        k = (c[2], c[3], c[4])  # block, paragraph, line
        if k != key and cur:
            lines.append(" ".join(cur))
            cur = []
        key = k
        if conf >= min_conf:
            cur.append(c[11])
    if cur:
        lines.append(" ".join(cur))
    return "\n".join(l for l in lines if l.strip())


def has_urdu(text: str, min_chars=8) -> bool:
    return len(ARABIC.findall(text or "")) >= min_chars
