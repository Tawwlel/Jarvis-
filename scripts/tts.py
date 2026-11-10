"""
Text-to-Speech wrapper around Piper. Supports switching between 5 voices.

Usage (standalone test):
    python tts.py "Good morning. You have a meeting at ten." --voice amy
    python tts.py "Good morning." --voice ryan --play

As a module:
    from tts import Jarvis Voice
    voice = JarvisVoice()
    voice.speak("Hello", voice_name="amy")
"""
import argparse
import os
import subprocess
import wave
from pathlib import Path

from piper import PiperVoice

VOICES_DIR = Path(__file__).parent.parent / "voices"
AUDIO_DIR = Path(__file__).parent.parent / "audio"
AUDIO_DIR.mkdir(exist_ok=True)

VOICE_FILES = {
    "amy": "en_US-amy-medium.onnx",
    "ryan": "en_US-ryan-high.onnx",
    "alan": "en_GB-alan-medium.onnx",
    "lessac": "en_US-lessac-medium.onnx",
    "southern": "en_GB-southern_english_female-low.onnx",
}


class JarvisVoice:
    """Loads Piper voices lazily and caches them, so switching voices is instant
    after the first use of each one."""

    def __init__(self):
        self._loaded = {}

    def _get_voice(self, voice_name: str) -> PiperVoice:
        if voice_name not in VOICE_FILES:
            raise ValueError(
                f"Unknown voice '{voice_name}'. Choose from: {list(VOICE_FILES)}"
            )
        if voice_name not in self._loaded:
            model_path = VOICES_DIR / VOICE_FILES[voice_name]
            if not model_path.exists():
                raise FileNotFoundError(
                    f"Voice model not found at {model_path}.\n"
                    f"Run `python scripts/download_voices.py` first."
                )
            self._loaded[voice_name] = PiperVoice.load(str(model_path))
        return self._loaded[voice_name]

    def speak(self, text: str, voice_name: str = "amy", out_path: str | None = None, play: bool = False) -> str:
        """Synthesize `text` with the given voice. Returns the path to the wav file."""
        voice = self._get_voice(voice_name)

        if out_path is None:
            out_path = str(AUDIO_DIR / f"out_{voice_name}.wav")

        with wave.open(out_path, "wb") as wav_file:
            voice.synthesize_wav(text, wav_file)

        if play:
            self._play(out_path)

        return out_path

    @staticmethod
    def _play(path: str):
        # Windows: use built-in player. On Linux/Mac this would use aplay/afplay instead.
        if os.name == "nt":
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME)
        else:
            player = "afplay" if subprocess.os.uname().sysname == "Darwin" else "aplay"
            subprocess.run([player, path])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("text")
    parser.add_argument("--voice", default="amy", choices=list(VOICE_FILES))
    parser.add_argument("--play", action="store_true")
    args = parser.parse_args()

    jv = JarvisVoice()
    path = jv.speak(args.text, voice_name=args.voice, play=args.play)
    print(f"Saved: {path}")
