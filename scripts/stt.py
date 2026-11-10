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
    def __init__(self, model_size: str = "base.en", device: str = "cpu", compute_type: str = "int8"):
        # "base.en" is a good budget default: fast on CPU, accurate enough for commands.
        # Options (speed vs accuracy): tiny.en < base.en < small.en < medium.en
        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            download_root=str(MODEL_DIR),
        )

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
