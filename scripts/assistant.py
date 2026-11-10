"""
The assistant: listens (hotkey, "Hey <name>", or tray), thinks, speaks, and drives
the on-screen orb. Runs on worker threads; the UI only receives signals.
"""
import queue
import re
import threading

import audio
import briefing
import notes as notes_mod
import tools
from brain import Brain
from hotkey import start_hotkey
from notes import NO, YES, NotesSession
from scheduler import Scheduler
from stt import JarvisEars
from tts import JarvisVoice
from wake import WakeListener

BRIEF = re.compile(r"\b(daily )?(brief|briefing)\b|what'?s (on )?(my )?(day|today)|what do i have today", re.I)


class Assistant:
    def __init__(self, cfg: dict, bridge):
        self.cfg, self.bridge = cfg, bridge
        self.mic, self.mouth = audio.Mic(), JarvisVoice()
        self.ears = JarvisEars("base.en")
        self.brain = Brain(cfg)
        self.notes = NotesSession(self.brain.mem, self.brain.summarize_notes)
        self.triggers: queue.Queue = queue.Queue()
        self.busy = False
        self.stop_notes = threading.Event()
        self.speak_lock = threading.Lock()

    # ---------- startup ----------
    @property
    def names(self):
        return self.cfg.get("assistant_names") or ["Jarvis"]

    def start(self):
        self.mic.start()
        tools.CTX["say"], tools.CTX["confirm"] = self.say, self.confirm
        Scheduler(self.cfg, self.brain.mem, self.say, self.notes, self.brief,
                  on_offer=lambda: self.triggers.put("")).start()
        if self.cfg.get("wake_word_enabled", True):
            WakeListener(self.mic, JarvisEars("tiny.en"), lambda: self.names,
                         self.on_wake, lambda: self.busy).start()
        try:
            start_hotkey(self.cfg.get("hotkey", "ctrl+alt+j"), self.on_hotkey)
        except Exception as e:
            print("[hotkey] could not register:", e)
        threading.Thread(target=self.loop, daemon=True).start()

    # ---------- triggers ----------
    def on_hotkey(self):
        if self.notes.state == "active":
            self.stop_notes.set()  # pressing the shortcut again ends note-taking
            return
        audio.stop_playback()
        self.triggers.put("")

    def on_wake(self, command: str):
        audio.stop_playback()
        self.triggers.put(command)

    # ---------- speaking ----------
    def _rest_state(self):
        if self.notes.state == "active":
            self.bridge.state("notes")
        elif not self.busy:
            self.bridge.state("idle")
            self.bridge.hide_later(2500)

    def say(self, msg: str):
        print(f"{self.names[0]}: {msg}")
        with self.speak_lock:
            self.bridge.show()
            self.bridge.state("speaking")
            try:
                path = self.mouth.speak(msg, voice_name=self.cfg.get("voice", "amy"), play=False)
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
        t = self.ears.transcribe_array(a)
        print("[confirm]", t)
        return bool(YES.search(t)) and not NO.search(t)

    def brief(self) -> str:
        return briefing.generate(self.brain, self.cfg)

    # ---------- conversation ----------
    def loop(self):
        while True:
            pre = self.triggers.get()
            self.busy = True
            try:
                self.session(pre)
            except Exception as e:
                print("[session]", e)
                self.say("Sorry, something went wrong on my side.")
            finally:
                self.busy = False
                self._rest_state()

    def hear(self, timeout=6.0) -> str:
        self.bridge.show()
        self.bridge.state("listening")
        a = audio.listen_for_speech(self.mic, self.bridge.level, no_speech_timeout=timeout)
        if a is None:
            return ""
        self.bridge.state("thinking")
        text = self.ears.transcribe_array(a)
        print("You:", text)
        return text

    def session(self, pre: str):
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
                reply = self.brain.respond(text)
            self.say(reply)
            if self.notes.state == "active":
                self.say(self.notes_mode())
            expecting = self.notes.state in ("offered", "summary_offered") or reply.rstrip().endswith("?")
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
