"""
WhatsApp reader (read-only). Uses WhatsApp Web in its own browser profile (the 'linked device' you scan once).
It only DOWNLOADS documents and photos into data/whatsapp/<chat name>/ - it never sends, deletes or edits anything.
Jarvis's document finder then searches those folders.

Limits (WhatsApp's own): a linked device only holds recent history, and some old messages say "Waiting for this
message". For older invoices, use WhatsApp > chat > More > Export chat > Include media and drop the result into
data/whatsapp/<chat name>/.

Selectors live in SEL so they are easy to patch if WhatsApp changes its page.
"""
import re
import time
from pathlib import Path

from tools import CTX, tool

DATA = Path(__file__).parent.parent / "data"
WA_DIR = DATA / "whatsapp"
PROFILE = DATA / "wa_profile"
DOC_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".webp", ".docx", ".xlsx", ".csv", ".txt")

SEL = {
    "logged_in": "#pane-side",
    "qr": "canvas[aria-label], div[data-ref]",
    "chat_rows": "#pane-side [role='row'], #pane-side [role='listitem']",
    "messages": "#main [data-id]",
    "doc_title": "span[dir='auto'][title], span[title]",
}


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip(" .")[:60] or "chat"


def _launch(p, headless: bool):
    return p.chromium.launch_persistent_context(
        str(PROFILE), headless=headless, accept_downloads=True, viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36")


def link(timeout=300) -> str:
    """Opens WhatsApp Web visibly so the owner can scan the QR code once."""
    from playwright.sync_api import sync_playwright
    PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = _launch(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://web.whatsapp.com/")
        try:
            page.wait_for_selector(SEL["logged_in"], timeout=timeout * 1000)
            time.sleep(5)  # let the profile save its session
            ctx.close()
            return "WhatsApp is linked."
        except Exception:
            ctx.close()
            return "The QR code was not scanned in time. Try again."


def _chat_names(page, limit):
    names = []
    for row in page.query_selector_all(SEL["chat_rows"])[:limit * 2]:
        t = row.query_selector("span[title]")
        if t:
            n = (t.get_attribute("title") or "").strip()
            if n and n not in names:
                names.append(n)
    return names[:limit]


def _download_chat(page, chat: str, max_files: int, seen: set) -> int:
    out = WA_DIR / _safe(chat)
    out.mkdir(parents=True, exist_ok=True)
    got = 0
    rows = page.query_selector_all(SEL["messages"])
    for m in reversed(rows):  # newest first
        if got >= max_files:
            break
        mid = m.get_attribute("data-id") or ""
        if not mid or mid in seen:
            continue
        title = m.query_selector(SEL["doc_title"])
        label = (title.get_attribute("title") if title else "") or ""
        is_doc = label.lower().endswith(DOC_EXT)
        is_img = m.query_selector("img[src^='blob:']") is not None
        if not (is_doc or is_img):
            continue
        seen.add(mid)
        if is_doc and (out / label).exists():
            continue
        try:
            m.scroll_into_view_if_needed()
            with page.expect_download(timeout=20000) as dl:
                btn = m.query_selector("[data-icon='audio-download'], [data-icon='download'], [data-icon^='document']")
                (btn or title or m).click()
            d = dl.value
            name = d.suggested_filename or label or f"photo_{int(time.time())}.jpg"
            d.save_as(str(out / name))
            got += 1
        except Exception:
            if is_img:  # photos: open the viewer and save it
                try:
                    m.query_selector("img[src^='blob:']").click()
                    page.wait_for_timeout(800)
                    with page.expect_download(timeout=15000) as dl:
                        page.click("[data-icon='download'], [aria-label='Download']")
                    d = dl.value
                    d.save_as(str(out / (d.suggested_filename or f"photo_{int(time.time())}.jpg")))
                    got += 1
                except Exception:
                    pass
                finally:
                    page.keyboard.press("Escape")
    return got


def sync(chats=None, per_chat=40, chat_limit=15) -> dict:
    """Saves recent documents/photos of the given chats (or the most recent ones) into data/whatsapp."""
    from playwright.sync_api import sync_playwright
    if not PROFILE.exists():
        return {"error": "not linked"}
    WA_DIR.mkdir(parents=True, exist_ok=True)
    result = {}
    with sync_playwright() as p:
        ctx = _launch(p, headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://web.whatsapp.com/")
        try:
            page.wait_for_selector(SEL["logged_in"], timeout=60000)
        except Exception:
            ctx.close()
            return {"error": "not linked"}
        page.wait_for_timeout(3000)
        names = chats or _chat_names(page, chat_limit)
        for name in names:
            try:
                page.click(f"#pane-side span[title='{name}']", timeout=5000)
                page.wait_for_timeout(2500)
                for _ in range(3):  # load a bit more history
                    page.mouse.wheel(0, -4000)
                    page.wait_for_timeout(800)
                result[name] = _download_chat(page, name, per_chat, set())
            except Exception as e:
                result[name] = f"skipped ({type(e).__name__})"
        ctx.close()
    return result


@tool("whatsapp_link",
      "Connect WhatsApp so Jarvis can search files in chats. Opens WhatsApp Web; the owner scans the QR code "
      "once (WhatsApp > Linked devices). Read-only.", {}, [])
def whatsapp_link():
    try:
        import playwright  # noqa: F401
    except ImportError:
        return "WhatsApp support is not installed yet. Run update.bat once, then try again."
    return link()


@tool("whatsapp_sync",
      "Fetch the latest invoices/documents/photos from WhatsApp chats so they can be searched. chats is an "
      "optional comma-separated list of chat names; leave empty for the recent chats. Read-only.",
      {"chats": {"type": "string"}}, [])
def whatsapp_sync(chats=""):
    try:
        import playwright  # noqa: F401
    except ImportError:
        return "WhatsApp support is not installed yet. Run update.bat once, then try again."
    names = [c.strip() for c in chats.split(",") if c.strip()] or None
    r = sync(names)
    if r.get("error"):
        return "WhatsApp is not linked yet. Say 'link WhatsApp' first."
    total = sum(v for v in r.values() if isinstance(v, int))
    try:
        import docsearch
        docsearch.reindex(CTX.get("cfg", {}), include_computer=False)
    except Exception:
        pass
    return f"Saved {total} new file(s) from {len(r)} chat(s). You can search them now."
