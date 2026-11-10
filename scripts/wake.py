"""
"Hey Jarvis" wake word that works for ANY name the user gives the assistant.

Instead of a trained keyword model, a quiet always-on listener cuts the mic
into short utterances, transcribes only those (local tiny Whisper, free) and
checks whether they start with "hey <name>". Fuzzy matching tolerates
mis-hearings such as "Jarvas". Only speech is ever transcribed, and nothing
leaves the computer.
"""
import difflib
import queue
import re
import threading

from audio import Segmenter

GREETINGS = {"hey", "hi", "ok", "okay", "yo", "hello"}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def match_wake(text: str, names: list[str], threshold: float = 0.78):
    """Returns the command spoken after the wake phrase ('' if none), or None if the
    utterance wasn't addressed to the assistant."""
    words = _words(text)
    if not words:
        return None
    greeted = words[0] in GREETINGS
    body = words[1:] if greeted else words
    for name in names:
        n = _words(name)
        if not n or len(body) < len(n):
            continue
        heard = " ".join(body[:len(n)])
        if difflib.SequenceMatcher(None, heard, " ".join(n)).ratio() >= threshold:
            rest = body[len(n):]
            if greeted or not rest:  # bare name only counts when it is the whole utterance
                return " ".join(rest)
    return None


class WakeListener(threading.Thread):
    def __init__(self, mic, ears, get_names, on_wake, is_busy):
        super().__init__(daemon=True)
        self.mic, self.ears = mic, ears
        self.get_names, self.on_wake, self.is_busy = get_names, on_wake, is_busy
        self.running = True

    def run(self):
        q = self.mic.subscribe()
        seg = Segmenter(end_silence=0.6, max_seconds=8.0)
        while self.running:
            try:
                frame = q.get(timeout=0.5)
            except queue.Empty:
                continue
            if self.is_busy():
                seg._reset()
                continue
            audio = seg.feed(frame)
            if audio is None or len(audio) < 4800:  # ignore clicks under 0.3 s
                continue
            try:
                text = self.ears.transcribe_array(audio)
                cmd = match_wake(text, self.get_names())
                if cmd is not None:
                    self.on_wake(cmd)
            except Exception as e:
                print("[wake]", e)
