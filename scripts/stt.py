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


class JarvisEars:
    def __init__(self, model_size: str = "base.en", device: str = "cpu", compute_type: str = "int8",
                 language: str | None = None):
        # language: None = detect (English/Urdu), "en" or "ur" to force one
        self.language = language if not model_size.endswith(".en") else "en"
        # "base.en" is a good budget default: fast on CPU, accurate enough for commands.
        # Options (speed vs accuracy): tiny.en < base.en < small.en < medium.en
        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            download_root=str(MODEL_DIR),
        )

    def transcribe_array(self, audio) -> str:
        """Transcribe raw 16 kHz int16 samples straight from the microphone."""
        import numpy as np

        samples = audio.astype(np.float32) / 32768.0
        lang = self.language
        segments, info = self.model.transcribe(samples, beam_size=1, vad_filter=True, language=lang)
        text = " ".join(s.text.strip() for s in segments).strip()
        # Whisper often labels spoken Urdu as Hindi/Arabic/Persian: redo it as Urdu so we get Urdu script
        if lang is None and getattr(info, "language", "en") in ("hi", "ar", "fa", "pa", "ps", "sd", "ur"):
            segments, _ = self.model.transcribe(samples, beam_size=1, vad_filter=True, language="ur")
            text = " ".join(s.text.strip() for s in segments).strip()
        return text

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
