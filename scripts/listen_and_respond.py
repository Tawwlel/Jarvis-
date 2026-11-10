"""
Jarvis voice loop (v1 - push-to-talk).

Press ENTER, speak your command, press ENTER again to stop recording.
Jarvis transcribes it, prints it (this is where you'll later plug in the
Claude API call to decide what to do / what to say back), and speaks the
reply in your chosen voice.

This is the proof-of-concept for the voice I/O layer. Next step after this
works: swap the wake-word trigger in for push-to-talk, and plug Claude's
API in for the "decide what to do" step.

Run on your Windows PC (needs a real mic/speaker):
    python listen_and_respond.py --voice ryan
"""
import argparse
import queue
import sys
import wave

import numpy as np
import sounddevice as sd

from brain import Brain
from config import load_config
from stt import JarvisEars
from tts import JarvisVoice

SAMPLE_RATE = 16000


def record_until_enter(out_path: str):
    print("Press ENTER to start recording...")
    input()
    print("Recording... press ENTER to stop.")

    q = queue.Queue()

    def callback(indata, frames, time, status):
        q.put(indata.copy())

    frames = []
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", callback=callback):
        import threading
        stop_flag = {"stop": False}

        def wait_for_enter():
            input()
            stop_flag["stop"] = True

        t = threading.Thread(target=wait_for_enter)
        t.start()
        while not stop_flag["stop"]:
            try:
                frames.append(q.get(timeout=0.1))
            except queue.Empty:
                continue
        t.join()

    audio = np.concatenate(frames, axis=0)
    with wave.open(out_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())

    print("Saved recording to", out_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", default=None, help="overrides config voice")
    parser.add_argument("--whisper-model", default="base.en")
    args = parser.parse_args()

    cfg = load_config()
    voice = args.voice or cfg.get("voice", "amy")
    brain = Brain(cfg)
    ears = JarvisEars(model_size=args.whisper_model)
    mouth = JarvisVoice()

    print(f"Jarvis ready. Voice = {voice}. Ctrl+C to quit.\n")

    while True:
        try:
            record_path = "audio/_mic_input.wav"
            record_until_enter(record_path)

            text = ears.transcribe(record_path)
            print(f"You said: {text}")

            for due in brain.mem.due_reminders():
                mouth.speak(f"Reminder: {due}", voice_name=voice, play=True)

            if not text.strip():
                continue
            reply = brain.respond(text)

            print(f"Jarvis: {reply}")
            mouth.speak(reply, voice_name=voice, play=True)

        except KeyboardInterrupt:
            print("\nGoodbye.")
            sys.exit(0)


if __name__ == "__main__":
    main()
