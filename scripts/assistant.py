"""
The assistant: listens (hotkey, "Hey <name>", or tray), thinks, speaks, and drives
the on-screen orb. Runs on worker threads; the UI only receives signals.
"""
import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import audio
import briefing
import notes as notes_mod
import tools
from brain import Brain
from hotkey import start_hotkey
from notes import NO, YES, NotesSession
from scheduler import Scheduler
from providers import make_stt, make_tts
from stt import JarvisEars
from wake import WakeListener

def _retry(load, tries=2):
    """Model loading can fail when memory is briefly short: free what we can and try again."""
    for i in range(tries):
        try:
            return load()
        except RuntimeError as e:
            if "alloc" not in str(e).lower() or i == tries - 1:
                raise MemoryError("Not enough free memory to load the listening model. Close some apps "
                                  "(or restart the laptop) and start Jarvis again.") from e
            import gc
            gc.collect()
            _free_ollama()
            time.sleep(3)


def _free_ollama():
    """Ask Ollama to unload every model it holds (they reload on demand)."""
    try:
        import requests
        for m in requests.get("http://localhost:11434/api/ps", timeout=2).json().get("models", []):
            requests.post("http://localhost:11434/api/generate", timeout=5,
                          json={"model": m.get("name"), "keep_alive": 0})
    except Exception:
        pass


BRIEF = re.compile(r"\b(daily )?(brief|briefing)\b|what'?s (on )?(my )?(day|today)|what do i have today", re.I)


def _spoken(msg: str, limit: int = 260) -> str:
    """What is read aloud: no markdown symbols, and only the first sentences of a long answer (the chat shows all
    of it). Long replies took 20 seconds to speak."""
    import re
    t = re.sub(r"[*#`|>_]+", " ", msg)
    t = re.sub(r"^\s*\d+\.\s+", "", t, flags=re.M)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) <= limit:
        return t
    cut = max(t.rfind(". ", 0, limit), t.rfind("۔", 0, limit), t.rfind("? ", 0, limit), t.rfind("! ", 0, limit))
    return t[:cut + 1] if cut > 60 else t[:limit].rsplit(" ", 1)[0] + "."


class Assistant:
    def __init__(self, cfg: dict, bridge, secrets=None):
        self.cfg, self.bridge = cfg, bridge
        self.mic = audio.Mic()
        t0 = time.time()
        # Brain and voice load alongside; the speech models load one at a time to keep memory use low
        with ThreadPoolExecutor(3) as pool:
            mouth = pool.submit(make_tts, cfg, secrets)
            brain = pool.submit(Brain, cfg, secrets)
            self.ears = _retry(lambda: make_stt(cfg, secrets))
            self.wake_ears = _retry(lambda: JarvisEars("tiny.en")) if cfg.get("wake_word_enabled", True) else None
            self.mouth, self.brain = mouth.result(), brain.result()
            # warm everything up so the first real request is quick
            warm = [pool.submit(e.warm_up) for e in (self.ears, self.wake_ears) if hasattr(e, "warm_up")]
            warm.append(pool.submit(self._warm_voice))
            threading.Thread(target=self.brain.local.warm_up, daemon=True).start()
            for w in warm:
                w.result()
        print(f"[timing] startup {time.time() - t0:.1f}s")
        self.notes = NotesSession(self.brain.mem, self.brain.summarize_notes)
        self.triggers: queue.Queue = queue.Queue()
        self.busy = False
        self.brain_lock = threading.Lock()
        self.stop_notes = threading.Event()
        self.speak_lock = threading.Lock()

    def _warm_voice(self):
        try:
            if hasattr(self.mouth, "base"):
                self.mouth.base._get_voice(self.cfg.get("voice", "amy"))
            elif hasattr(self.mouth, "_get_voice"):
                self.mouth._get_voice(self.cfg.get("voice", "amy"))
        except Exception as e:
            print("[voice]", e)

    # ---------- startup ----------
    @property
    def names(self):
        return self.cfg.get("assistant_names") or ["Jarvis"]

    def start(self):
        self.mic.start()
        tools.CTX["say"], tools.CTX["confirm"] = self.say, self.confirm
        Scheduler(self.cfg, self.brain.mem, self.say, self.notes, self.brief,
                  on_offer=lambda: self.triggers.put({"text": "", "silent": False})).start()
        if self.cfg.get("wake_word_enabled", True):
            WakeListener(self.mic, self.wake_ears, lambda: self.names,
                         self.on_wake, lambda: self.busy).start()
        try:
            start_hotkey(self.cfg.get("hotkey", "ctrl+alt+j"), self.on_hotkey)
        except Exception as e:
            print("[hotkey] could not register:", e)
        threading.Thread(target=self.loop, daemon=True).start()
        if self.cfg.get("tools_enabled", {}).get("documents", True):
            import docsearch  # build the document index in the background so the first search is quick
            threading.Thread(target=docsearch.background_index, args=(self.cfg,), daemon=True).start()
            from whatsapp_agent import WhatsAppAgent  # separate worker: keeps WhatsApp documents read and ready
            tools_mod = __import__("tools")
            tools_mod.CTX["notify"] = lambda t: self.bridge.chat("assistant", t)
            WhatsAppAgent(self.cfg, lambda t: self.bridge.chat("assistant", t)).start()
            import phone_bridge
            phone_bridge.AGENT = phone_bridge.PhoneAgent(self.cfg, self.phone_ask,
                                                         lambda t: self.bridge.chat("assistant", t))
            phone_bridge.AGENT.start()
            from deep_scan import ScanAgent  # asks once, then refreshes everything every 12 hours
            ScanAgent(self.cfg, lambda t: self.bridge.chat("assistant", t)).start()
        if self.cfg.get("tools_enabled", {}).get("email", True):
            from email_agent import EmailAgent  # daily email digest at the chosen time
            EmailAgent(self.cfg, lambda t: self.submit_text(t, speak=False)).start()

    # ---------- triggers ----------
    def on_hotkey(self):
        if self.notes.state == "active":
            self.stop_notes.set()  # pressing the shortcut again ends note-taking
            return
        audio.stop_playback()
        self.triggers.put({"text": "", "silent": False})

    def on_wake(self, command: str, clip=None):
        audio.stop_playback()
        if command and clip is not None and self.cfg.get("language", "auto") != "en":
            # the wake model only knows English: hear the command again with the Urdu-capable model
            from wake import match_wake
            self._hint()
            full = self.ears.transcribe_array(clip)
            again = match_wake(full, self.names)
            command = again if again else full
        self.triggers.put({"text": command, "silent": False})

    def _hint(self):
        """Tell the listener which words to expect: document types and this owner's customer names."""
        try:
            if hasattr(self.ears, "hint") and self.cfg.get("tools_enabled", {}).get("documents", True):
                import docsearch
                self.ears.hint = docsearch.vocabulary()
        except Exception:
            pass

    def submit_text(self, text: str, speak: bool = False):
        """Typed message from the chat window. Replies are silent unless asked."""
        self.triggers.put({"text": text, "silent": not speak})

    def talk(self):
        self.triggers.put({"text": "", "silent": False})

    # ---------- speaking ----------
    def _rest_state(self):
        if self.notes.state == "active":
            self.bridge.state("notes")
        elif not self.busy:
            self.bridge.state("idle")
            self.bridge.hide_later(2500)

    def say(self, msg: str, silent: bool = False):
        print(f"{self.names[0]}: {msg}")
        self.bridge.chat("assistant", msg)
        if silent:
            return
        with self.speak_lock:
            self.bridge.show()
            self.bridge.state("speaking")
            try:
                t0 = time.time()
                path = self.mouth.speak(_spoken(msg), voice_name=self.cfg.get("voice", "amy"), play=False)
                print(f"[timing] voice {time.time() - t0:.1f}s")
                audio.play_wav(path, self.bridge.level)
            except Exception as e:
                print("[speech]", e)
        self._rest_state()

    def confirm(self, question: str) -> bool:
        """Voice yes/no, used before risky computer actions."""
        self.say(question)
        self.bridge.state("listening")
        a = audio.listen_for_speech(self.mic, self.bridge.level, no_speech_timeout=8)
        self.bridge.state("working")
        if a is None:
            return False
        self._hint()
        t = self.ears.transcribe_array(a)
        print("[confirm]", t)
        return bool(YES.search(t)) and not NO.search(t)

    def brief(self) -> str:
        return briefing.generate(self.brain, self.cfg)

    # ---------- conversation ----------
    def phone_ask(self, text: str) -> dict:
        """A question typed on the owner's phone: answered with read-only tools, shown in the chat window too."""
        import tools as tools_mod
        t0 = time.time()
        with self.brain_lock:  # one conversation at a time, laptop or phone
            tools_mod.CTX["phone_mode"], tools_mod.CTX["phone_files"] = True, []
            try:
                reply = self.brain.respond(text, phone=True)
                files = list(tools_mod.CTX.get("phone_files", []))
            finally:
                tools_mod.CTX["phone_mode"] = False
                tools_mod.CTX.pop("phone_files", None)
        print(f"[phone] answered in {time.time() - t0:.1f}s")
        self.bridge.chat("user", "(phone) " + text)
        self.bridge.chat("assistant", reply)
        seen, uniq = set(), []
        for f in files:  # one card per file
            if f["path"] not in seen:
                seen.add(f["path"])
                uniq.append(f)
        return {"text": reply, "files": uniq[:8]}

    def loop(self):
        while True:
            trig = self.triggers.get()
            if isinstance(trig, str):
                trig = {"text": trig, "silent": False}
            self.busy = True
            try:
                self.session(trig["text"], trig["silent"])
            except Exception as e:
                print("[session]", e)
                self.say("Sorry, something went wrong on my side.")
            finally:
                self.busy = False
                self._rest_state()

    def hear(self, timeout=6.0) -> str:
        self.bridge.show()
        self.bridge.state("listening")
        a = audio.listen_for_speech(self.mic, self.bridge.level, no_speech_timeout=timeout, end_silence=0.7)
        if a is None:
            return ""
        self.bridge.state("thinking")
        t0 = time.time()
        self._hint()
        text = self.ears.transcribe_array(a)
        print(f"[timing] listening->text {time.time() - t0:.1f}s ({len(a) / 16000:.1f}s of speech)")
        print("You:", text)
        if text.strip():
            self.bridge.chat("user", text)
        return text

    def session(self, pre: str, silent: bool = False):
        if pre:
            self.bridge.chat("user", pre)
        text = pre or self.hear()
        for _ in range(4):  # allow short follow-ups ("want a summary?" -> "yes")
            if not text.strip():
                return
            self.bridge.state("thinking")
            reply = self.notes.handle(text)
            if reply is None and BRIEF.search(text):
                reply = self.brief()
            if reply is None:
                self.bridge.state("working")
                t0 = time.time()
                with self.brain_lock:
                    reply = self.brain.respond(text)
                print(f"[timing] thinking {time.time() - t0:.1f}s")
            self.say(reply, silent)
            if silent:
                return
            if self.notes.state == "active":
                self.say(self.notes_mode())
            expecting = self.notes.state in ("offered", "summary_offered") or reply.rstrip().endswith(("?", "؟"))
            if not expecting:
                return
            text = self.hear()

    def notes_mode(self) -> str:
        """Listen quietly and store text. No model calls, so no token cost."""
        self.stop_notes.clear()
        self.bridge.state("notes")
        while not self.stop_notes.is_set():
            a = audio.listen_for_speech(self.mic, lambda v: self.bridge.level(v * 0.4),
                                        no_speech_timeout=1e9, end_silence=1.2,
                                        max_seconds=25, cancel=self.stop_notes)
            if a is None:
                break
            text = self.ears.transcribe_array(a).strip()
            if notes_mod.looks_like_noise(text):
                continue
            if notes_mod.STOP.search(text):
                break
            self.notes.add(text)
            print("[note]", text)
        return self.notes.stop()
