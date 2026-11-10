"""
Downloads the 5 Jarvis voices into the voices folder (needs internet).
Safe to run again: voices that are already there are skipped.

    python scripts/download_voices.py
"""
import sys
from pathlib import Path

from piper.download_voices import download_voice

VOICES_DIR = Path(__file__).resolve().parent.parent / "voices"

VOICES = {
    "amy": "en_US-amy-medium",
    "ryan": "en_US-ryan-high",
    "alan": "en_GB-alan-medium",
    "lessac": "en_US-lessac-medium",
    "southern": "en_GB-southern_english_female-low",
}

if __name__ == "__main__":
    VOICES_DIR.mkdir(exist_ok=True)
    failed = []
    for name, voice_id in VOICES.items():
        print(f"\n=== Downloading '{name}' ({voice_id}) ===", flush=True)
        try:
            download_voice(voice_id, VOICES_DIR)
        except Exception as e:  # keep going so one bad download doesn't block the rest
            print(f"FAILED: {e}")
            failed.append(name)
    if failed:
        print("\nThese voices did not download:", ", ".join(failed), "- run this again later.")
        sys.exit(1)
    print("\nAll 5 voices are in:", VOICES_DIR)
