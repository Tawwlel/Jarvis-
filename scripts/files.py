"""
File tools: find, read, create, edit, move, open and delete files.

Safety rules (enforced here in code, not just in the prompt):
- Only inside the user's allowed folders (default: Documents, Desktop, Downloads);
  hidden folders and system locations are always off limits.
- DELETE always asks permission, every single time. It never deletes permanently:
  files go to the Recycle Bin (or ~/.jarvis/trash if there is none).
- Overwriting or editing an existing file asks permission and saves a backup copy first
  in ~/.jarvis/backups. Creating a new file or moving to a free name does not ask.
- Single files only; Jarvis will not delete folders.
"""
import os
import shutil
import subprocess
import time
from pathlib import Path

from tools import CTX, tool

HOME = Path.home()
JARVIS_DIR = HOME / ".jarvis"
SKIP_DIRS = {"node_modules", "__pycache__", "venv", ".venv", "AppData", "$RECYCLE.BIN", "System Volume Information"}
TEXT_EXT = {".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".html", ".css", ".xml", ".yml", ".yaml",
            ".ini", ".log", ".tex", ".sql", ".bat", ".sh", ".rtf", ""}


def roots() -> list[Path]:
    cfg_roots = CTX.get("cfg", {}).get("file_roots")
    rs = [Path(r).expanduser() for r in cfg_roots] if cfg_roots else [HOME / "Documents", HOME / "Desktop", HOME / "Downloads"]
    return [r.resolve() for r in rs if r.exists()]


def _inside(p: Path) -> Path:
    """Resolve p and make sure it is inside an allowed root and not hidden."""
    p = p.expanduser()
    if not p.is_absolute():
        for r in roots():
            if (r / p).exists():
                p = r / p
                break
        else:
            p = (roots() or [HOME])[0] / p
    p = p.resolve()
    for r in roots():
        try:
            rel = p.relative_to(r)
        except ValueError:
            continue
        if any(part.startswith(".") or part in SKIP_DIRS for part in rel.parts):
            raise PermissionError("That location is off limits.")
        return p
    raise PermissionError(f"I'm only allowed to touch files in: {', '.join(str(r) for r in roots())}")


def _confirm(question: str) -> bool:
    fn = CTX.get("confirm")
    return bool(fn(question)) if fn else False


def _backup(p: Path) -> Path:
    dest = JARVIS_DIR / "backups"
    dest.mkdir(parents=True, exist_ok=True)
    b = dest / f"{time.strftime('%Y%m%d-%H%M%S')}_{p.name}"
    shutil.copy2(p, b)
    return b


def _trash(p: Path) -> str:
    try:
        from send2trash import send2trash

        send2trash(str(p))
        return "the Recycle Bin"
    except Exception:
        dest = JARVIS_DIR / "trash"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(dest / f"{time.strftime('%Y%m%d-%H%M%S')}_{p.name}"))
        return str(dest)


@tool("file_find", "Find files by part of the name (case-insensitive) in the user's allowed folders. "
      "Optional folder to narrow the search.", {"query": {"type": "string"}, "folder": {"type": "string"}}, ["query"])
def file_find(query, folder=None):
    q, hits = query.lower(), []
    for root in ([_inside(Path(folder))] if folder else roots()):
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS]
            for f in files:
                if q in f.lower():
                    p = Path(dirpath) / f
                    hits.append((p.stat().st_mtime, p))
    hits.sort(reverse=True)
    return "\n".join(f"{p}  ({time.strftime('%d %b %Y', time.localtime(m))})" for m, p in hits[:20]) or "No matching files."


@tool("file_read", "Read a text file (txt, md, csv, json, code...).",
      {"path": {"type": "string"}, "max_chars": {"type": "integer"}}, ["path"])
def file_read(path, max_chars=6000):
    p = _inside(Path(path))
    if p.suffix.lower() not in TEXT_EXT:
        return f"I can only read plain-text files, not {p.suffix} files."
    return p.read_text(encoding="utf-8", errors="replace")[: int(max_chars)]


@tool("file_write", "Create a text file. If it already exists, the user is asked before it is overwritten "
      "(and a backup is kept).", {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"])
def file_write(path, content):
    p = _inside(Path(path))
    if p.exists():
        if not _confirm(f"{p.name} already exists. Overwrite it? I'll keep a backup."):
            return "The user said no. Nothing was changed."
        _backup(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Saved {p}"


@tool("file_edit", "Replace one exact piece of text in an existing text file. Asks the user first and keeps a backup.",
      {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}}, ["path", "old", "new"])
def file_edit(path, old, new):
    p = _inside(Path(path))
    text = p.read_text(encoding="utf-8")
    if text.count(old) != 1:
        return f"The text to replace appears {text.count(old)} times; it must appear exactly once."
    if not _confirm(f"Edit {p.name}: replace '{old[:40]}' with '{new[:40]}'?"):
        return "The user said no. Nothing was changed."
    b = _backup(p)
    p.write_text(text.replace(old, new), encoding="utf-8")
    return f"Edited {p.name}. Backup kept at {b}"


@tool("file_move", "Move or rename a file. Refuses to replace an existing file.",
      {"source": {"type": "string"}, "destination": {"type": "string"}}, ["source", "destination"])
def file_move(source, destination):
    s, d = _inside(Path(source)), _inside(Path(destination))
    if d.is_dir():
        d = d / s.name
    if d.exists():
        return "A file with that name already exists there, so I didn't move anything."
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    return f"Moved to {d}"


@tool("file_open", "Open a file with its default app.", {"path": {"type": "string"}}, ["path"])
def file_open(path):
    p = _inside(Path(path))
    if os.name == "nt":
        os.startfile(str(p))  # noqa: S606 - user's own file, inside allowed folders
    else:
        subprocess.Popen(["xdg-open", str(p)])
    return f"Opened {p.name}"


@tool("file_delete", "Delete ONE file. ALWAYS asks the user for permission first, every time. "
      "The file goes to the Recycle Bin, so it can be restored.", {"path": {"type": "string"}}, ["path"])
def file_delete(path):
    p = _inside(Path(path))
    if not p.exists():
        return "That file doesn't exist."
    if p.is_dir():
        return "I only delete single files, not folders."
    if not _confirm(f"Delete {p.name}? It will go to the Recycle Bin."):
        return "The user said no. Nothing was deleted."
    where = _trash(p)
    return f"Moved {p.name} to {where}."
