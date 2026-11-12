"""
Setup guide: Jarvis can check what is connected and walk the owner through connecting the rest, step by step,
in the owner's language. Read-only: it only looks at what exists; the steps are done by the owner (or by the
normal tools such as whatsapp_link).
"""
from pathlib import Path

from tools import CTX, tool

DATA = Path(__file__).parent.parent / "data"

STEPS = {
    "key": (
        "ONLINE BRAIN (Anthropic key)\n"
        "1. On a phone or computer open console.anthropic.com and sign up.\n"
        "2. Billing: add a card and buy about $5 of credits. Set a monthly spend limit.\n"
        "3. Keys and access > Create key > 'Somewhere else'. Name it Jarvis. Copy the key (starts with sk-ant-).\n"
        "4. Jarvis tray icon > Settings > 'Keys and models' > paste it in the Anthropic box > Save.\n"
        "Never paste the key into chat."),
    "whatsapp": (
        "WHATSAPP (read-only: Jarvis only reads and saves documents/photos, never sends)\n"
        "1. Tell Jarvis 'link WhatsApp' (or tray icon > Link WhatsApp). A browser window opens with a QR code.\n"
        "2. On the phone: WhatsApp > Settings > Linked devices > Link a device > scan the QR code.\n"
        "3. Wait until chats appear, then the window closes by itself. This is done once.\n"
        "4. Jarvis then asks to scan everything (computer + every WhatsApp chat). Say 'yes, scan everything'. After "
        "that it refreshes every 12 hours by itself; 'check WhatsApp' fetches new files any time.\n"
        "WhatsApp only gives recent files this way. For the full old history on an iPhone, use the iPhone step."),
    "iphone": (
        "OLD WHATSAPP FILES FROM AN IPHONE (full history)\n"
        "1. Install 'Apple Devices' from the Microsoft Store (or iTunes) on this laptop.\n"
        "2. Connect the iPhone by cable, tap 'Trust' on the phone, open Apple Devices.\n"
        "3. Click 'Back Up Now'. If it asks to encrypt the backup, choose a password and tell Jarvis in "
        "Settings > 'Email & WhatsApp'. (An encrypted backup is fine; Jarvis only reads it.)\n"
        "4. Say 'import old WhatsApp files' (or tray icon > Import old WhatsApp files)."),
    "email": (
        "EMAIL (read-only: Jarvis reads new mail for the daily digest, never sends or deletes)\n"
        "1. Settings > 'Email & WhatsApp': type the email address.\n"
        "2. It needs an APP PASSWORD, not the normal password:\n"
        "   Gmail: Google Account > Security > turn on 2-Step Verification > search 'App passwords' > create one.\n"
        "   Yahoo: Account security > Generate app password.\n"
        "   iCloud: appleid.apple.com > Sign-In and Security > App-Specific Passwords.\n"
        "   Business mail: use the mailbox password and ask the IT person for the IMAP server name.\n"
        "3. Paste the app password in Jarvis, set the digest time (default 09:00), Save.\n"
        "4. Say 'check my email' to test. Outlook/Hotmail are not supported yet."),
    "backup": (
        "BACKUP (so Jarvis can move to a new laptop)\n"
        "1. Settings > Backup: type your backup email and choose a backup password (6+ characters).\n"
        "2. Jarvis then saves one locked backup a day to the 'Jarvis Backups' folder and emails a copy weekly "
        "(needs the email step above).\n"
        "3. Before changing laptops say 'back up Jarvis now'. On the new laptop use 'Restore from a backup' on "
        "the welcome screen.\nA forgotten backup password cannot be recovered."),
    "voice": (
        "VOICE\n"
        "1. Plug in or enable a microphone (Windows Settings > Sound > Input).\n"
        "2. Say 'Jarvis' then the request, or press Ctrl+Alt+J.\n"
        "3. Urdu or English both work; keep sentences short. If it mishears, say it again slowly."),
}


def _status() -> list[str]:
    cfg = CTX.get("cfg", {})
    try:
        from secrets_store import default_store
        st = default_store()
        has = lambda k: bool(st.get(k))  # noqa: E731
    except Exception:
        has = lambda k: False  # noqa: E731
    wa_dir = DATA / "whatsapp"
    wa_files = sum(1 for _ in wa_dir.rglob("*") if _.is_file()) if wa_dir.exists() else 0
    mail = (cfg.get("email") or {}).get("address", "")
    bk = (cfg.get("backup") or {}).get("email", "")
    rows = [
        ("key", has("anthropic"), "online brain key saved" if has("anthropic") else "no Anthropic key yet"),
        ("whatsapp", (DATA / "wa_profile").exists(),
         f"linked, {wa_files} file(s) saved" if (DATA / "wa_profile").exists() else "not linked"),
        ("iphone", (DATA / "iphone_import.json").exists(),
         "old files imported" if (DATA / "iphone_import.json").exists() else "not imported (optional, iPhone only)"),
        ("email", bool(mail and has("email_password")),
         f"connected as {mail}" if mail and has("email_password") else "not connected"),
        ("backup", bool(bk), f"backup email {bk}" if bk else "no backup email yet"),
    ]
    return [f"{'DONE' if ok else 'TODO'} - {k}: {txt}" for k, ok, txt in rows]


@tool("setup_help",
      "Help the owner set Jarvis up: shows what is connected and what is still to do, and gives the exact steps for "
      "one thing. topic = 'status' (default, checks everything and says what to do next), or one of: key, whatsapp, "
      "iphone, email, backup, voice. Use whenever the owner asks how to set up, connect or fix any of these, or on "
      "first use. Give the steps ONE AT A TIME in the owner's language (Urdu or English), short, and wait for them "
      "to say 'done' before the next step. Never ask the owner to type passwords or keys into chat.",
      {"topic": {"type": "string"}}, [])
def setup_help(topic="status"):
    t = (topic or "status").strip().lower()
    if t in STEPS:
        return STEPS[t]
    todo = [r for r in _status() if r.startswith("TODO")]
    nxt = "Everything important is connected." if not todo else "Suggest doing the first TODO item next."
    return "SETUP STATUS\n" + "\n".join(_status()) + f"\n{nxt}\nOffer the exact steps with setup_help(topic=...)."
