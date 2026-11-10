"""
Speech-to-Text wrapper around faster-whisper.

Usage (standalone test):
    python stt.py path/to/recording.wav

As a module:
    from stt import JarvisEars
    ears = JarvisEars()
    text = ears.transcribe("recording.wav")
"""
import argparse
from pathlib import Path

from faster_whisper import WhisperModel

MODEL_DIR = Path(__file__).parent.parent / "whisper_model"
MODEL_DIR.mkdir(exist_ok=True)


URDU_LIKE = {"ur", "hi", "ar", "fa", "pa", "ps", "sd"}


class JarvisEars:
    def __init__(self, model_size: str = "base.en", device: str = "cpu", compute_type: str = "int8",
                 language: str | None = None):
        # language: None = detect (English/Urdu), "en" or "ur" to force one
        import os

        self.language = language if not model_size.endswith(".en") else "en"
        threads = max(2, (os.cpu_count() or 4) - 1)
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type,
                                  download_root=str(MODEL_DIR), cpu_threads=threads)

    def _run(self, samples, lang):
        return self.model.transcribe(samples, beam_size=1, vad_filter=True, language=lang,
                                     condition_on_previous_text=False, without_timestamps=True)

    def transcribe_array(self, audio) -> str:
        """Transcribe raw 16 kHz int16 samples straight from the microphone."""
        import numpy as np

        samples = audio.astype(np.float32) / 32768.0
        segments, info = self._run(samples, self.language)
        if self.language is None:
            # Decide English vs Urdu before decoding (segments are decoded lazily, so this costs nothing).
            # Whisper often labels spoken Urdu as Hindi/Arabic/Persian: treat all of those as Urdu.
            probs = dict(getattr(info, "all_language_probs", None) or [])
            en = probs.get("en", 1.0 if info.language == "en" else 0.0)
            ur = sum(probs.get(k, 0.0) for k in URDU_LIKE) or (1.0 if info.language in URDU_LIKE else 0.0)
            if ur > en and info.language != "ur":
                segments, _ = self._run(samples, "ur")
        return " ".join(s.text.strip() for s in segments).strip()

    def warm_up(self):
        """One tiny silent run so the first real request isn't slow."""
        import numpy as np
        try:
            list(self._run(np.zeros(16000, dtype=np.float32), self.language or "en")[0])
        except Exception:
            pass

    def transcribe(self, audio_path: str) -> str:
        # vad_filter skips silence, which stops Whisper inventing words in quiet audio
        segments, _info = self.model.transcribe(audio_path, beam_size=5, vad_filter=True)
        return " ".join(seg.text.strip() for seg in segments)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_path")
    parser.add_argument("--model", default="base.en")
    args = parser.parse_args()

    ears = JarvisEars(model_size=args.model)
    text = ears.transcribe(args.audio_path)
    print("Transcribed:", text)
