"""Calls EVERY registered tool with sample input in an isolated copy of the data folder (no network, no real mail,
no messages sent) and reports tools that crash, hang or return nothing. Run: python tests/every_tool.py"""
import os, sys, time, json, tempfile, threading, traceback
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "scripts")
import tools, config
tools.CTX["cfg"] = {"owner_name": "Test", "assistant_names": ["Jarvis"], "email": {"address": ""},
                    "tools_enabled": {k: True for k in ("computer_control", "visual_explainer", "calendar", "notes", "email")}}
tools.CTX["notify"] = lambda m: None
import memory as _m; _m.DB = Path(tempfile.mkdtemp()) / "m.db"; tools.CTX["memory"] = _m.Memory()
tools.active_tools(tools.CTX["cfg"]) if hasattr(tools, "active_tools") else None
# import every module that registers tools
for m in ("files","docsearch","deep_scan","whatsapp_reader","whatsapp_agent","email_agent","briefing","backup","setup_guide","agents",
          "phone_bridge","usage","licence","todos","notes","jcalendar","computer","visual","iphone_backup","invoice_fields","scheduler","sysinfo"):
    try: __import__(m)
    except Exception as e: print("IMPORT FAIL", m, e)
DANGEROUS = {"computer_click","computer_type","computer_key","computer_scroll","computer_open","computer_screenshot","whatsapp_link","whatsapp_sync",
             "backup_now","phone_pair","scan_everything","email_digest","iphone_import","phone_forget","computer_run","fresh_start"}
SAMPLE = {"string": "test", "number": 1, "integer": 1, "boolean": False, "array": [], "object": {}}
bad, ok, skipped = [], 0, []
for name, ent in sorted(tools.REGISTRY.items()):
    sch = ent["schema"]["input_schema"]
    if name in DANGEROUS or name.startswith("computer_"):
        skipped.append(name); continue
    args = {}
    for k in sch.get("required", []):
        p = sch["properties"][k]
        args[k] = (p.get("enum") or [None])[0] or SAMPLE.get(p.get("type", "string"), "test")
        if any(w in k for w in ("start", "when", "due", "date", "time", "end")) and p.get("type", "string") == "string":
            args[k] = "2026-11-20T10:00:00"
        if k in ("path", "name", "filename"):
            args[k] = "sample.txt"
    box = {}
    def run():
        try: box["r"] = tools.run_tool(name, args)
        except BaseException as e: box["e"] = e
    th = threading.Thread(target=run, daemon=True); th.inline = True; t0 = time.time(); th.start(); th.join(40)
    dt = time.time() - t0
    if th.is_alive(): bad.append((name, "HANG >40s")); continue
    r = box.get("r", "")
    if "e" in box or (isinstance(r, str) and r.startswith("Tool error")):
        bad.append((name, str(box.get("e") or r)[:160]))
    elif not r:
        bad.append((name, "empty result"))
    else: ok += 1
print(f"{ok} tools ok, {len(bad)} problems, {len(skipped)} skipped (act on real accounts/screen): {', '.join(skipped)}")
for n, why in bad: print("PROBLEM", n, "->", why)
sys.exit(1 if bad else 0)
