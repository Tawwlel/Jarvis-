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


def _load(size):
    import os
    threads = max(2, (os.cpu_count() or 4) - 1)
    return WhisperModel(size, device="cpu", compute_type="int8", download_root=str(MODEL_DIR), cpu_threads=threads)


class JarvisEars:
    """
    language None (auto): a fast model decides English vs Urdu and writes English itself;
    only Urdu speech goes to the bigger, slower Urdu-capable model.
    """

    def __init__(self, model_size: str = "base.en", device: str = "cpu", compute_type: str = "int8",
                 language: str | None = None, urdu_model: str | None = None):
        self.language = language if not model_size.endswith(".en") else "en"
        self.model = _load(model_size)
        self.urdu = _load(urdu_model) if (urdu_model and urdu_model != model_size and self.language != "en") else None

    def _run(self, model, samples, lang, prompt=None):
        return model.transcribe(samples, beam_size=1, vad_filter=True, language=lang, initial_prompt=prompt,
                                condition_on_previous_text=False, without_timestamps=True)

    def transcribe_array(self, audio, prompt: str | None = None) -> str:
        """Transcribe raw 16 kHz int16 samples straight from the microphone."""
        import numpy as np

        samples = audio.astype(np.float32) / 32768.0
        if self.language == "ur":
            segments, _ = self._run(self.urdu or self.model, samples, "ur", prompt)
        else:
            segments, info = self._run(self.model, samples, self.language, prompt)
            if self.language is None:
                # Decide English vs Urdu before decoding (segments are decoded lazily, so this is cheap).
                # Whisper often labels spoken Urdu as Hindi/Arabic/Persian: count all of those as Urdu.
                probs = dict(getattr(info, "all_language_probs", None) or [])
                en = probs.get("en", 1.0 if info.language == "en" else 0.0)
                ur = sum(probs.get(k, 0.0) for k in URDU_LIKE) or (1.0 if info.language in URDU_LIKE else 0.0)
                if ur > en:
                    segments, _ = self._run(self.urdu or self.model, samples, "ur", prompt)
                elif info.language != "en":
                    segments, _ = self._run(self.model, samples, "en", prompt)
        return " ".join(s.text.strip() for s in segments).strip()

    def warm_up(self):
        """One short silent run per model so the first real request isn't slow."""
        import numpy as np
        z = np.zeros(16000, dtype=np.float32)
        for m, lang in ((self.model, self.language or "en"), (self.urdu, "ur")):
            if m is not None:
                try:
                    list(self._run(m, z, lang)[0])
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
