"""CI on Windows: Jarvis's own voice speaks a command, Jarvis's own ears hear it, and the wake word is recognised.
No microphone or speakers needed - the audio goes straight from the voice to the listener."""
import sys
import tempfile
import time
import wave
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
app = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(app / "scripts"))
import numpy as np  # noqa

ok = True


def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, "|", info)


def load16k(path):
    with wave.open(path) as w:
        sr = w.getframerate()
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    n = int(len(a) * 16000 / sr)
    return np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.int16)


tmp = tempfile.mkdtemp()
from tts import JarvisVoice  # noqa
from stt import JarvisEars  # noqa
from wake import match_wake  # noqa
import lang  # noqa

# ---- English: Piper voice -> Whisper ----
t = time.time()
wav = JarvisVoice().speak("Hey Jarvis, show me the sales invoices of Khan Traders.", "amy", out_path=tmp + "/en.wav")
t_tts = time.time() - t
ears = JarvisEars("base", language=None, urdu_model="small")
t = time.time()
heard = ears.transcribe_array(load16k(wav))
t_stt = time.time() - t
check("English voice is heard correctly", "sales invoices" in heard.lower() and "khan" in heard.lower(),
      f"heard: {heard!r}  (speak {t_tts:.1f}s, listen {t_stt:.1f}s)")
cmd = match_wake(heard, ["Jarvis"])
check("wake word recognised, command extracted", cmd is not None and "invoices" in cmd, f"command: {cmd!r}")
wake_ears = JarvisEars("tiny.en")
heard2 = wake_ears.transcribe_array(load16k(wav), prompt="Hey Jarvis.")
check("small wake-word model hears the name", match_wake(heard2, ["Jarvis"]) is not None, f"heard: {heard2!r}")
wav = JarvisVoice().speak("What is the weather like in Lahore today?", "amy", out_path=tmp + "/en2.wav")
h3 = wake_ears.transcribe_array(load16k(wav), prompt="Hey Jarvis.")
check("ordinary talk does NOT wake Jarvis", match_wake(h3, ["Jarvis"]) is None, f"heard: {h3!r}")

# ---- Urdu: Edge voice -> Whisper (auto language) ----
try:
    from providers import EdgeVoice
    t = time.time()
    wav = EdgeVoice("ur-PK-AsadNeural").speak("خان ٹریڈرز کی سیلز انوائس دکھاؤ", out_path=tmp + "/ur.wav")
    t_tts = time.time() - t
    t = time.time()
    heard = ears.transcribe_array(load16k(wav))
    t_stt = time.time() - t
    check("Urdu voice is produced and heard as Urdu", lang.is_urdu(heard) and ("انوائس" in heard or "خان" in heard),
          f"heard: {heard!r}  (speak {t_tts:.1f}s, listen {t_stt:.1f}s incl. first load of the Urdu model)")
    t = time.time()
    heard = ears.transcribe_array(load16k(wav))
    check("Urdu second time (model already loaded)", lang.is_urdu(heard), f"listen {time.time() - t:.1f}s")
except Exception as e:
    check("Urdu voice round trip", False, f"error: {e}")
print("VOICE ALL OK" if ok else "VOICE SOME FAILED")
sys.exit(0 if ok else 1)
