"""
Run this ONCE on your own Windows PC (after `pip install -r requirements.txt`)
to download the 5 Jarvis voices. Needs internet access to huggingface.co.

Usage:
    python download_voices.py
"""
from piper.download_voices import download_voice
import os

VOICES_DIR = os.path.join(os.path.dirname(__file__), "..", "voices")
os.makedirs(VOICES_DIR, exist_ok=True)

# 5 distinct voices: mix of US/UK, male/female, so each persona feels different.
# Full catalog: https://github.com/OHF-voice/piper1-gpl/blob/main/VOICES.md
VOICES = {
    "amy":     "en_US-amy-medium",                   # US female, warm/default
    "ryan":    "en_US-ryan-high",                     # US male, clear/high quality
    "alan":    "en_GB-alan-medium",                   # UK male, crisp British
    "lessac":  "en_US-lessac-medium",                 # US male/neutral, calm narrator
    "southern":"en_GB-southern_english_female-low",   # UK female, soft
}

if __name__ == "__main__":
    for name, voice_id in VOICES.items():
        print(f"\n=== Downloading '{name}' ({voice_id}) ===")
        download_voice(voice_id, VOICES_DIR)
    print("\nAll 5 voices downloaded to:", VOICES_DIR)
