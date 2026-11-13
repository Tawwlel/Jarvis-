"""
Audio plumbing: one shared microphone stream, voice-activity detection (no
"press Enter to stop" - it stops when you stop talking), and playback that
reports its loudness so the on-screen orb can pulse with the voice.
"""
import queue
import threading
import time
import wave
from collections import deque

import numpy as np

SR = 16000
FRAME = int(SR * 0.03)  # 30 ms frames


def clean_audio(audio: np.ndarray) -> np.ndarray:
    """int16 in, int16 out: remove DC offset and lift quiet microphones to a steady level (helps every listener)."""
    if audio is None or audio.size == 0:
        return audio
    x = audio.astype(np.float32) / 32768.0
    x = x - float(np.mean(x))
    peak = float(np.max(np.abs(x)))
    if 0.003 < peak < 0.5:
        x = x * min(0.7 / peak, 12.0)
    return (np.clip(x, -1.0, 1.0) * 32767).astype(np.int16)


def save_debug_clip(audio: np.ndarray, path):
    """Keep the last thing heard (one file, overwritten) and log its loudness so bad listening can be diagnosed."""
    try:
        x = audio.astype(np.float32) / 32768.0
        print(f"[audio] heard {len(audio) / SR:.1f}s peak={float(np.max(np.abs(x))):.3f} "
              f"rms={float(np.sqrt(np.mean(x ** 2))):.4f}")
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SR)
            wf.writeframes(audio.tobytes())
    except Exception:
        pass


def rms_level(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean((frame.astype(np.float32) / 32768.0) ** 2)))


class Segmenter:
    """Feed 30 ms frames; returns a finished speech segment (int16 array) once the
    speaker has paused, else None. Pure logic, so it is easy to test."""

    def __init__(self, end_silence=0.8, max_seconds=30.0, start_frames=3, floor=0.007):
        self.end_frames = int(end_silence / 0.03)
        self.max_frames = int(max_seconds / 0.03)
        self.start_frames, self.floor = start_frames, floor
        self.noise = 0.004
        self.level = 0.0
        self.active = False
        self._reset()

    def _reset(self):
        self.active = False
        self.buf, self.speech_run, self.silence_run = [], 0, 0
        self.pre = deque(maxlen=24)  # ~700 ms of lead-in so first syllables are kept

    def feed(self, frame: np.ndarray):
        self.level = rms = rms_level(frame)
        voiced = rms > max(self.floor, self.noise * 3.0)
        if not self.active:
            self.pre.append(frame)
            if not voiced:
                self.noise = 0.95 * self.noise + 0.05 * rms
                self.speech_run = 0
                return None
            self.speech_run += 1
            if self.speech_run >= self.start_frames:
                self.active, self.buf, self.silence_run = True, list(self.pre), 0
            return None
        self.buf.append(frame)
        self.silence_run = 0 if voiced else self.silence_run + 1
        if self.silence_run >= self.end_frames or len(self.buf) >= self.max_frames:
            seg = np.concatenate(self.buf)
            self._reset()
            return seg
        return None


class Mic:
    """A single always-open microphone stream shared by the wake listener and the
    command listener (two separate streams on one mic is flaky on Windows)."""

    def __init__(self):
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._stream = None

    def start(self):
        import sounddevice as sd

        self._stream = sd.InputStream(samplerate=SR, channels=1, dtype="int16",
                                      blocksize=FRAME, callback=self._cb)
        self._stream.start()

    def _cb(self, indata, frames, t, status):
        f = indata[:, 0].copy()
        with self._lock:
            for q in self._subs:
                try:
                    q.put_nowait(f)
                except queue.Full:
                    pass

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=400)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)


def listen_for_speech(mic: Mic, on_level=None, no_speech_timeout=6.0, end_silence=1.0,
                      max_seconds=30.0, cancel: threading.Event | None = None):
    """Wait for the user to speak and finish. Returns int16 audio, or None if nobody spoke."""
    q = mic.subscribe()
    seg = Segmenter(end_silence=end_silence, max_seconds=max_seconds)
    t0 = time.time()
    try:
        while True:
            if cancel is not None and cancel.is_set():
                return None
            try:
                frame = q.get(timeout=0.2)
            except queue.Empty:
                frame = None
            if frame is not None:
                out = seg.feed(frame)
                if on_level:
                    on_level(min(1.0, seg.level * 9))
                if out is not None:
                    return out
            if not seg.active and time.time() - t0 > no_speech_timeout:
                return None
    finally:
        mic.unsubscribe(q)


def envelope(samples: np.ndarray, sr: int, step=0.04) -> np.ndarray:
    """Loudness per `step` seconds, scaled to ~0..1, for driving the orb."""
    n = max(1, int(sr * step))
    x = samples.astype(np.float32) / 32768.0
    env = np.array([np.sqrt(np.mean(x[i:i + n] ** 2)) for i in range(0, len(x), n)] or [0.0])
    peak = max(float(np.percentile(env, 95)), 1e-4)
    return np.clip(env / peak, 0, 1)


_stop_play = threading.Event()


def stop_playback():
    _stop_play.set()
    try:
        import sounddevice as sd

        sd.stop()
    except Exception:
        pass


def play_wav(path: str, on_level=None):
    """Play a wav file, calling on_level(0..1) in time with the voice."""
    import sounddevice as sd

    with wave.open(path, "rb") as wf:
        sr, ch = wf.getframerate(), wf.getnchannels()
        data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    if ch > 1:
        data = data.reshape(-1, ch)[:, 0]
    env = envelope(data, sr)
    _stop_play.clear()
    sd.play(data, sr)
    t0 = time.time()
    dur = len(data) / sr
    while time.time() - t0 < dur and not _stop_play.is_set():
        if on_level:
            on_level(float(env[min(len(env) - 1, int((time.time() - t0) / 0.04))]))
        time.sleep(0.02)
    sd.stop()
    if on_level:
        on_level(0.0)
