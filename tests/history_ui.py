"""Chat history: every line is kept (encrypted), the window replays the latest on open, History shows every day and searches."""
import os, sys, time, tempfile
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import secrets_store, memory
T = Path(tempfile.mkdtemp(prefix="hist_"))
secrets_store.set_default_store(secrets_store.SecretStore(data_dir=T / "s"))
memory.DB = T / "m.db"
from PySide6.QtWidgets import QApplication
import ui
app = QApplication([])
mem = memory.Memory()
FAILS = []
def check(n, ok, info=""):
    print("PASS" if ok else "FAIL", n, str(info)[:150]); ok or FAILS.append(n)

now = time.time()
mem.add_chat("user", "Khan Traders ki invoice dikhao", now - 3 * 86400)
mem.add_chat("assistant", "Mujhe 2 invoices mili: INV-1 aur INV-2", now - 3 * 86400 + 4)
mem.add_chat("user", "total sales this month", now - 86400)
mem.add_chat("assistant", "Total: Rs. 1,250,000", now - 86400 + 3)
raw = mem.db.execute("SELECT content FROM chat_log LIMIT 1").fetchone()[0]
check("chat is stored encrypted", "Khan" not in raw)
check("days listed newest first", [n for _, n in mem.chat_days()] == [2, 2] and mem.chat_days()[0][0] > mem.chat_days()[1][0])
check("search finds old messages", len(mem.chat_search("khan")) == 1 and mem.chat_search("zzz") == [])

b = ui.Bridge(); b.recorder = mem.add_chat
w = ui.ChatWindow(b, "Jarvis", mem)
check("window replays earlier chats on open", "Khan Traders ki invoice" in w.log.toPlainText() and "earlier chats above" in w.log.toPlainText())
b.chat("user", "hello again")
time.sleep(0.05)
b.chat_sig.emit  # signal delivered synchronously in the same thread
check("new messages are recorded", any("hello again" in t for _, _, t in mem.chat_recent(5)))
check("replayed messages are not recorded twice", sum("Khan Traders ki invoice" in t for _, _, t in mem.chat_recent(50)) == 1)
w.show_history()
h = w._history_win
check("history lists the days", h.days.count() == 3, h.days.count())
h.search.setText("total sales"); h._find()
check("history search shows the match with its date", "Total: Rs." in h.view.toPlainText() or "total sales" in h.view.toPlainText().lower())
print("FAILS:", FAILS or "none"); sys.exit(1 if FAILS else 0)
