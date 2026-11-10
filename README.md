# Jarvis

A personal/client assistant: voice in/out, a tiered brain (free local model →
Haiku → Sonnet), computer control, and a visual explainer window. One
codebase — each install (you, a client) just has its own `config.local.json`.

This repo is how updates get distributed: I (Claude) commit changes here,
you pull them with one double-click.

## First-time setup (on your Windows PC)

1. Install [Python 3.10+](https://python.org) if you don't have it.
2. Install [git](https://git-scm.com/download/win) if you don't have it.
3. Clone this repo (or if you already have the folder, skip to step 4):
   ```
   git clone https://github.com/Tawwlel/jarvis-
   cd jarvis-
   ```
4. Double-click `setup.bat` (or run it from a terminal). This installs
   dependencies, downloads the 5 voices (~200MB), and creates your personal
   `config.local.json` for you to add your Anthropic API key to.

## Getting updates later

Whenever I've pushed changes, just double-click `update.bat`. That's it —
pulls the latest code and updates dependencies.

## Try it

**Test a voice speaking something:**
```
python scripts/tts.py "Good morning, sir. You have a meeting in twenty minutes." --voice ryan --play
```
Try `--voice amy`, `ryan`, `alan`, `lessac`, or `southern` to hear each one.

**Test transcribing a recording:**
```
python scripts/stt.py path/to/some_audio.wav
```

**Full loop (mic in → text → text → speech out):**
```
python scripts/listen_and_respond.py --voice amy
```
Press ENTER, say something, press ENTER again, and Jarvis will transcribe
it and read it back. Right now the "thinking" part is a placeholder — it
just repeats what you said. That's the next piece we wire in: the Claude
API call that actually decides what Jarvis should do or say.

## The 5 voices

| Name | Voice | Character |
|---|---|---|
| `amy` | en_US-amy-medium | US female, warm, default |
| `ryan` | en_US-ryan-high | US male, clear, highest quality |
| `alan` | en_GB-alan-medium | UK male, crisp British |
| `lessac` | en_US-lessac-medium | US neutral, calm narrator |
| `southern` | en_GB-southern_english_female-low | UK female, soft |

You can add more any time from the full Piper voice list:
https://github.com/OHF-voice/piper1-gpl/blob/main/VOICES.md
(just add the voice ID to `download_voices.py` and `VOICE_FILES` in `tts.py`)

## Setting up the calendar

In Google Calendar: Settings > your calendar > "Secret address in iCal format". In Outlook: Settings > Calendar > Shared calendars > Publish, copy the ICS link. Paste it into `integrations.calendar_ics_url` in `config.local.json`. Treat that link like a password.

## Architecture

**Tiered brain** (cheapest first):
- **Tier 0 — local, free**: a small on-device model handles trivial stuff
  (time, simple math, routing) and decides if a request needs to go up a tier
- **Tier 1 — Haiku**: everyday assistant work — reminders, chat, visual
  explainer specs, project summaries
- **Tier 2 — Sonnet**: harder reasoning — multi-step computer control,
  ambiguous judgment calls

**One codebase, per-user config**: `config.local.json` holds each install's
name, voice, enabled tools, and API key. Never committed to git.

## What's next
1. ✅ Voice pipeline
2. ✅ GitHub-based update distribution
3. ⬜ Tier 0 local model + Tier 1/2 cloud brain (Claude API), with memory
4. ⬜ Computer control: let it click/type/see your screen for automation
5. ⬜ Visual explainer window (small on-screen graphs/diagrams)
6. ⬜ Calendar + project integrations: meeting reminders, project status
   (this is the client's main need)
