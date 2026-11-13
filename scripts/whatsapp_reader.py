"""
WhatsApp reader (read-only). Uses WhatsApp Web in its own browser profile (the 'linked device' you scan once).
It only DOWNLOADS documents and photos into data/whatsapp/<chat name>/ - it never sends, deletes or edits anything.
Jarvis's document finder then searches those folders.

Limits (WhatsApp's own): a linked device only holds recent history, and some old messages say "Waiting for this
message". For older invoices, use WhatsApp > chat > More > Export chat > Include media and drop the result into
data/whatsapp/<chat name>/.

Selectors live in SEL so they are easy to patch if WhatsApp changes its page.
"""
import json
import re
import time
from pathlib import Path

from tools import CTX, tool

DATA = Path(__file__).parent.parent / "data"
WA_DIR = DATA / "whatsapp"
PROFILE = DATA / "wa_profile"
WA_URL = "https://web.whatsapp.com/"
DOC_EXT = (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".pptx", ".ppt", ".odt", ".zip", ".rar",
           ".jpg", ".jpeg", ".png", ".webp", ".txt")

SEL = {
    "logged_in": "#pane-side",
    "qr": "canvas[aria-label], div[data-ref]",
    "chat_rows": "#pane-side [role='row'], #pane-side [role='listitem']",
    "messages": "#main [data-id]",
    "doc_title": "span[dir='auto'][title], span[title]",
}


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip(" .")[:60] or "chat"


def _safe_file(name: str) -> str:
    """A file name only: no folders, no '..', nothing Windows rejects."""
    name = Path(str(name).replace("\\", "/")).name
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" .")[:150] or f"file_{int(time.time())}"


def _browser_ready():
    """The zip carries its own browser in Jarvis/browsers; other installs fetch it once on first use."""
    import os
    import subprocess
    import sys
    bundled = Path(__file__).parent.parent.parent / "browsers"
    if bundled.is_dir():
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(bundled))
        return
    mark = DATA / ".browser_ok"
    if not mark.exists():
        flags = 0x08000000 if sys.platform == "win32" else 0
        r = subprocess.run([sys.executable.replace("pythonw", "python"), "-m", "playwright", "install", "chromium"],
                           creationflags=flags, timeout=900)
        if r.returncode == 0:
            DATA.mkdir(parents=True, exist_ok=True)
            mark.write_text("ok")


def _launch(p, headless: bool):
    return p.chromium.launch_persistent_context(
        str(PROFILE), headless=headless, accept_downloads=True, viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36")


def _open(page) -> bool:
    """Open WhatsApp Web. The page never finishes 'loading' (it keeps connections open), so wait only for the first
    content and allow a slow connection two tries."""
    for _ in range(2):
        try:
            page.goto(WA_URL, wait_until="domcontentloaded", timeout=90000)
            return True
        except Exception as e:
            print("[whatsapp] open failed:", str(e).splitlines()[0])
    return False


_LINK = {"ctx": None, "cancel": None}


def archive_profile() -> str:
    """Put the current WhatsApp login aside (kept, never deleted) so the next link shows a fresh QR code
    for a different account. Files already saved from the old account stay searchable."""
    if not PROFILE.exists():
        return ""
    dest = PROFILE.with_name(f"wa_profile_old_{time.strftime('%Y%m%d_%H%M%S')}")
    try:
        PROFILE.rename(dest)
        return dest.name
    except Exception as e:  # a leftover browser may hold the folder
        print("[whatsapp] could not set the old login aside:", e)
        return ""


def cancel_link() -> bool:
    """Close the visible WhatsApp window if a link attempt is open."""
    ev = _LINK.get("cancel")
    if ev is not None:
        ev.set()
        return True
    return False


def link(timeout=180, fresh=False) -> str:
    """Opens WhatsApp Web visibly so the owner can scan the QR code once. fresh=True links a different account."""
    import threading
    from playwright.sync_api import sync_playwright
    if fresh:
        archive_profile()
    PROFILE.mkdir(parents=True, exist_ok=True)
    _browser_ready()  # before Playwright starts: it reads the browser location at start-up
    cancel = threading.Event()
    _LINK["cancel"] = cancel
    try:
        with sync_playwright() as p:
            ctx = _launch(p, headless=False)
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                if not _open(page):
                    return "I couldn't reach WhatsApp Web. Check the internet connection and try again."
                end = time.time() + timeout
                while time.time() < end:
                    if cancel.is_set():
                        return "I closed the WhatsApp window. Say 'link WhatsApp' when you want to try again."
                    try:
                        if page.is_closed():
                            return "The WhatsApp window was closed before linking finished."
                        if page.query_selector(SEL["logged_in"]):
                            time.sleep(5)  # let the profile save its session
                            return "WhatsApp is linked."
                    except Exception:
                        return "The WhatsApp window was closed before linking finished."
                    time.sleep(1)
                return "The QR code was not scanned in time. Try again."
            finally:
                try:
                    ctx.close()  # always: a window left open locks the WhatsApp profile and blocks every later command
                except Exception:
                    pass
    finally:
        _LINK["cancel"] = None


def _dismiss_popups(page):
    """A freshly linked account shows pop-ups (what's new, notifications, chat backup...) that sit over the chat
    list and make every click time out. Close them."""
    for _ in range(3):
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        clicked = False
        for label in ("OK", "Ok", "Got it", "Continue", "Not now", "Close", "Dismiss", "Skip", "Later", "Maybe later"):
            try:
                b = page.get_by_role("button", name=label, exact=True)
                if b.count() and b.first.is_visible():
                    b.first.click(timeout=1500)
                    clicked = True
            except Exception:
                pass
        if not clicked:
            return
        page.wait_for_timeout(500)


def _open_chat(page, name) -> None:
    """Open one chat: click it in the list; if something is in the way, close pop-ups and use the search box."""
    try:
        page.locator("#pane-side").get_by_title(name, exact=True).first.click(timeout=5000)
        return
    except Exception:
        _dismiss_popups(page)
    try:
        page.locator("#pane-side").get_by_title(name, exact=True).first.click(timeout=4000)
        return
    except Exception:
        pass
    box = page.locator("div[contenteditable='true'][data-tab='3'], [aria-label='Search input textbox'], "
                       "div[role='textbox'][aria-label*='Search']").first
    box.click(timeout=4000)
    page.keyboard.press("Control+A")
    page.keyboard.type(name, delay=15)
    page.wait_for_timeout(1500)
    page.locator("#pane-side").get_by_title(name, exact=True).first.click(timeout=5000)
    try:
        page.keyboard.press("Escape")  # clear the search so the next chat is found in the full list
    except Exception:
        pass


def _chat_names(page, limit, deep=False):
    """The chats in the list. deep=True scrolls the whole list (WhatsApp only draws the visible rows)."""
    names = []

    def collect():
        new = 0
        for row in page.query_selector_all(SEL["chat_rows"]):
            t = row.query_selector("span[title]")
            if t:
                n = (t.get_attribute("title") or "").strip()
                if n and n not in names:
                    names.append(n)
                    new += 1
        return new

    collect()
    if deep:
        quiet = 0
        for _ in range(120):
            page.evaluate("() => { const e = document.querySelector('#pane-side'); if (e) e.scrollBy(0, 900); }")
            page.wait_for_timeout(350)
            quiet = 0 if collect() else quiet + 1
            if quiet >= 4 or len(names) >= limit:
                break
        page.evaluate("() => { const e = document.querySelector('#pane-side'); if (e) e.scrollTo(0, 0); }")
    return names[:limit]


def _load_history(page, deep: bool, seconds: int = 120):
    """Scroll a chat upwards so older messages load. Light: a few pulls. Deep: until nothing more arrives."""
    if not deep:
        for _ in range(3):
            page.mouse.wheel(0, -4000)
            page.wait_for_timeout(800)
        return
    t0, last, quiet = time.time(), -1, 0
    while time.time() - t0 < seconds and quiet < 3:
        page.mouse.wheel(0, -6000)
        page.wait_for_timeout(900)
        n = len(page.query_selector_all(SEL["messages"]))
        quiet = quiet + 1 if n == last else 0
        last = n


def _download_chat(page, chat: str, max_files: int, seen: set) -> int:
    out = WA_DIR / _safe(chat)
    out.mkdir(parents=True, exist_ok=True)
    seen_file = out / ".seen"  # message ids already saved, so nothing downloads twice
    done = set(seen_file.read_text().split()) if seen_file.exists() else set()
    seen |= done
    got, fails = 0, 0
    tries_file = out / ".tries"
    try:
        tries = json.loads(tries_file.read_text()) if tries_file.exists() else {}
    except Exception:
        tries = {}
    rows = page.query_selector_all(SEL["messages"])
    for m in reversed(rows):  # newest first
        if got >= max_files or fails >= 6:  # 6 failures in a row: expired media, move on
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
        label = _safe_file(label)
        if is_doc and (out / label).exists():
            done.add(mid)
            continue
        ok = False
        try:
            m.scroll_into_view_if_needed()
            if is_doc:  # documents download straight from the message
                with page.expect_download(timeout=10000) as dl:
                    btn = m.query_selector("[data-icon='audio-download'], [data-icon='download'], [data-icon^='document']")
                    (btn or title or m).click()
                d = dl.value
                name = _safe_file(d.suggested_filename or label or f"photo_{int(time.time())}.jpg")
                d.save_as(str(out / name))
                ok = True
            else:  # photos: open the viewer and save it from there (no pointless wait for a direct download)
                try:
                    m.query_selector("img[src^='blob:']").click()
                    page.wait_for_timeout(800)
                    with page.expect_download(timeout=8000) as dl:
                        page.click("[data-icon='download'], [aria-label='Download']")
                    d = dl.value
                    d.save_as(str(out / _safe_file(d.suggested_filename or f"photo_{int(time.time())}.jpg")))
                    ok = True
                finally:
                    page.keyboard.press("Escape")
        except Exception:
            ok = False
        if ok:
            got += 1
            fails = 0
            done.add(mid)
            if got % 10 == 0:  # remember progress, so an interrupted scan does not start this chat again
                seen_file.write_text("\n".join(sorted(done)))
        else:
            fails += 1
            tries[mid] = tries.get(mid, 0) + 1
            if tries[mid] >= 2:  # failed twice (expired media): never spend minutes on it again
                done.add(mid)
    seen_file.write_text("\n".join(sorted(done)))
    tries_file.write_text(json.dumps(tries))
    return got


_busy = __import__("threading").Lock()


def sync(chats=None, per_chat=40, chat_limit=15, deep=False, progress=None) -> dict:
    """Saves documents/photos of the given chats (or the most recent ones) into data/whatsapp.
    deep=True goes through EVERY chat and loads each chat's whole available history."""
    if not _busy.acquire(blocking=False):  # one browser per profile at a time
        return {"busy": 0}
    try:
        if deep:
            per_chat, chat_limit = max(per_chat, 1000), max(chat_limit, 500)
        return _sync(chats, per_chat, chat_limit, deep, progress)
    finally:
        _busy.release()


def _sync(chats, per_chat, chat_limit, deep=False, progress=None) -> dict:
    from playwright.sync_api import sync_playwright
    if not PROFILE.exists():
        return {"error": "not linked"}
    WA_DIR.mkdir(parents=True, exist_ok=True)
    result = {}
    _browser_ready()
    with sync_playwright() as p:
        ctx = _launch(p, headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if not _open(page):
            ctx.close()
            return {"error": "offline"}
        try:
            page.wait_for_selector(SEL["logged_in"], timeout=90000)
        except Exception:
            ctx.close()
            return {"error": "not linked"}
        page.wait_for_timeout(3000)
        _dismiss_popups(page)
        names = chats or _chat_names(page, chat_limit, deep)
        fails = 0
        deadline = time.time() + 3 * 3600 if deep else None  # a deep scan never runs more than 3 hours
        for i, name in enumerate(names, 1):
            if deadline and time.time() > deadline:
                result["(stopped after 3 hours)"] = 0
                break
            try:
                _open_chat(page, name)
                page.wait_for_timeout(2500)
                _load_history(page, deep)
                t_chat = time.time()
                result[name] = _download_chat(page, name, per_chat, set())
                print(f"[wa] {name}: {result[name]} new file(s) in {time.time() - t_chat:.0f}s")
            except Exception as e:
                result[name] = f"skipped ({type(e).__name__})"
                print(f"[wa] {name}: skipped ({type(e).__name__}: {str(e).splitlines()[0][:120]})")
                fails += 1
                if fails == 1:
                    try:  # one picture of what was in the way, for diagnosis (overwritten each time)
                        page.screenshot(path=str(DATA / "wa_debug.png"))
                    except Exception:
                        pass
            if progress:
                progress(i, len(names), name)
        ctx.close()
    return result


@tool("whatsapp_link",
      "Connect WhatsApp so Jarvis can search files in chats. Opens WhatsApp Web; the owner scans the QR code "
      "once (WhatsApp > Linked devices). Set different_account to true when the owner wants to link another / "
      "second / different WhatsApp number: the old login is kept aside and a fresh QR code is shown. Read-only.",
      {"different_account": {"type": "boolean"}}, [])
def whatsapp_link(different_account=False):
    try:
        import playwright  # noqa: F401
    except ImportError:
        return "WhatsApp support is not installed yet. Run update.bat once, then try again."
    from tools import background
    if different_account and "whatsapp_link" in _running_labels():
        cancel_link()  # an earlier window is still open: close it first so the new code can start
    return background("whatsapp_link", lambda: _link_and_offer(bool(different_account)),
                      "Opening WhatsApp now. On your phone: WhatsApp > Settings > Linked devices > Link a device, "
                      "then scan the code on the screen. I'll tell you as soon as it's linked.")


def _running_labels():
    try:
        import tools
        return tools._running
    except Exception:
        return set()


@tool("whatsapp_link_cancel",
      "Close the WhatsApp linking window if it is stuck open or the owner wants to stop linking.", {}, [])
def whatsapp_link_cancel():
    try:
        import tools
        tools._running.discard("whatsapp_link")
    except Exception:
        pass
    return "I closed the WhatsApp window." if cancel_link() else "No WhatsApp window is open."


def _link_and_offer(fresh=False) -> str:
    msg = link(fresh=fresh)
    if msg == "WhatsApp is linked.":
        try:
            import deep_scan
            msg += " " + deep_scan.offer()
        except Exception as e:
            print("[scan] offer:", e)
    return msg


def _known_chats(asked):
    """Keep only chat names that really exist in the saved WhatsApp files (closest spelling wins)."""
    try:
        import difflib
        import docsearch
        db = docsearch._db()
        known = [r[0] for r in db.execute("SELECT DISTINCT chat FROM docs WHERE source='whatsapp' AND chat!=''")]
        db.close()
    except Exception:
        return asked
    if not known:
        return asked
    low = {k.lower(): k for k in known}
    out = []
    for a in asked:
        m = difflib.get_close_matches(a.lower(), list(low), n=1, cutoff=0.8)
        if m:
            out.append(low[m[0]])
    return out or None


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
    if names:
        names = _known_chats(names)  # a chat name that does not exist (misheard word) is dropped, not invented
    if not PROFILE.exists():
        return "WhatsApp is not linked yet. Say 'link WhatsApp' first."
    from tools import background
    return background("whatsapp_sync", lambda: _sync_and_report(names),
                      "Checking WhatsApp for new files in the background. I'll tell you when it's done.")


def _sync_and_report(names) -> str:
    r = sync(names)
    if "busy" in r:
        return "WhatsApp is already being checked in the background; try the search in a minute."
    if r.get("error") == "offline":
        return "I couldn't reach WhatsApp Web right now. Check the internet connection and try again."
    if r.get("error"):
        return "WhatsApp is not linked yet. Say 'link WhatsApp' first."
    try:
        import whatsapp_agent
        whatsapp_agent.mark_synced()
    except Exception:
        pass
    total = sum(v for v in r.values() if isinstance(v, int))
    try:
        import docsearch
        docsearch.reindex(CTX.get("cfg", {}), include_computer=False)
    except Exception:
        pass
    skipped = [k for k, v in r.items() if isinstance(v, str) and v.startswith("skipped")]
    done = len(r) - len(skipped)
    msg = f"Saved {total} new file(s) from {done} chat(s)."
    if skipped:
        msg += (f" {len(skipped)} chat(s) could not be opened ({', '.join(skipped[:5])}"
                + ("..." if len(skipped) > 5 else "") + "); I'll try them again next sync.")
    return msg + (" You can search them now." if done else "")
