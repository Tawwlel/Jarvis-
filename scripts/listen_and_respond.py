"""
Jarvis - main voice app (push-to-talk).

Press ENTER, speak, press ENTER again. On the very first run Jarvis introduces
itself and sets everything up (name, what you work on, voice, API key, calendar).

Run:   python scripts/listen_and_respond.py        (or double-click start.bat)
"""
import argparse
import getpass
import queue
import sys
import threading
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

import notes as notes_mod
import onboarding
import tools
from brain import Brain
from config import load_config, save_config
from memory import Memory
from notes import NotesSession
from scheduler import Scheduler
from stt import JarvisEars
from tts import JarvisVoice

SAMPLE_RATE = 16000
CHUNK_SECONDS = 20  # notes mode listens in chunks of this length
AUDIO = Path(__file__).parent.parent / "audio"
AUDIO.mkdir(exist_ok=True)
MIC_FILE = str(AUDIO / "_mic_input.wav")


def write_wav(path: str, audio: np.ndarray):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())


def record_until_enter(out_path: str, skip_start: bool = False):
    if not skip_start:
        print("Press ENTER to start recording...")
        input()
    print("Recording... press ENTER to stop.")
    q = queue.Queue()
    frames = []
    stop = {"flag": False}

    def waiter():
        input()
        stop["flag"] = True

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                        callback=lambda indata, *_: q.put(indata.copy())):
        t = threading.Thread(target=waiter)
        t.start()
        while not stop["flag"]:
            try:
                frames.append(q.get(timeout=0.1))
            except queue.Empty:
                continue
        t.join()
    write_wav(out_path, np.concatenate(frames, axis=0))


def record_seconds(out_path: str, seconds: int):
    audio = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
    sd.wait()
    write_wav(out_path, audio)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", default=None, help="overrides config voice")
    parser.add_argument("--whisper-model", default="base.en")
    args = parser.parse_args()

    cfg = load_config()
    ears = JarvisEars(model_size=args.whisper_model)
    mouth = JarvisVoice()
    speak_lock = threading.Lock()
    voice = {"name": args.voice or cfg.get("voice", "amy")}

    def say(msg: str):
        print(f"Jarvis: {msg}")
        with speak_lock:
            mouth.speak(msg, voice_name=voice["name"], play=True)

    def listen() -> str:
        record_until_enter(MIC_FILE)
        text = ears.transcribe(MIC_FILE)
        print(f"You said: {text}")
        return text

    # ---------- first-run setup ----------
    if not cfg.get("onboarded"):
        def ask() -> str:
            typed = input("Type your answer, or just press Enter to speak: ").strip()
            if typed:
                return typed
            record_until_enter(MIC_FILE, skip_start=True)
            text = ears.transcribe(MIC_FILE)
            print(f"You said: {text}")
            return text

        def preview(v, msg):
            with speak_lock:
                mouth.speak(msg, voice_name=v, play=True)

        cfg = onboarding.run(cfg, say, ask, getpass.getpass, preview, Memory())
        save_config(cfg)
        voice["name"] = cfg["voice"]
        print("\nSetup saved. You can change anything later in config.local.json.\n")

    brain = Brain(cfg)
    notes = NotesSession(brain.mem, brain.summarize_notes)

    def confirm(question: str) -> bool:
        say(question)
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")

    tools.CTX["say"], tools.CTX["confirm"] = say, confirm
    Scheduler(cfg, brain.mem, say, cfg.get("tools_enabled", {}).get("calendar", False), notes).start()

    def notes_mode():
        """Listen continuously and just store text. No model calls = no token cost."""
        try:
            while True:
                record_seconds(MIC_FILE, CHUNK_SECONDS)
                text = ears.transcribe(MIC_FILE).strip()
                if notes_mod.looks_like_noise(text):
                    continue
                if notes_mod.STOP.search(text):
                    break
                notes.add(text)
                print(f"[note] {text}")
        except KeyboardInterrupt:
            print("\nStopping notes.")
        say(notes.stop())

    print(f"Jarvis ready, {cfg.get('owner_name', '')}. Ctrl+C to quit.\n")
    while True:
        try:
            text = listen()
            if not text.strip():
                continue
            reply = notes.handle(text)
            if reply is not None:
                say(reply)
                if notes.state == "active":
                    notes_mode()
                continue
            say(brain.respond(text))
        except KeyboardInterrupt:
            print("\nGoodbye.")
            sys.exit(0)


if __name__ == "__main__":
    main()
