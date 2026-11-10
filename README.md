# Jarvis by Apricot Digital

A personal assistant that lives on your PC: it hears you, speaks back in 5 voices, runs your
meetings, notes, reminders and daily brief, and can take control of the computer. One app for
everyone - each person's name, voice and abilities are set on the welcome screen.

## Install (Windows)

1. Install [Python 3.10+](https://python.org) and [git](https://git-scm.com/download/win).
2. `git clone https://github.com/Tawwlel/Jarvis-` and open the folder.
3. Double-click `setup.bat`. It installs everything, downloads the voices and opens the welcome screen.
4. Fill in your name, what you're working on, the names you'd like to call your assistant, your voice,
   role and profile, API keys (stored encrypted in Windows Credential Manager), optional calendar link, daily-brief time and shortcut. Click **Start Jarvis**.

Later: double-click `start.bat` (runs in the background; check `jarvis.log` if something is off, or use
`start_debug.bat`). Double-click `update.bat` to get new versions.

## Calling Jarvis

- Say **"Hey Jarvis"** (or any name you set, like "Hey Friday"). Recognised on your PC; nothing is sent anywhere.
- Press the shortcut (default **Ctrl+Alt+J**).
- Or use the tray icon.

A translucent orb with the Apricot Digital logo pops up in the corner of the screen and pulses with
your voice and his. Drag it wherever you like; it fades away when he's done.

## Daily brief

At the time you choose (default 08:30) Jarvis reads out today's meetings, what to prepare (including
the summary of the last meeting with the same name), yesterday's summaries and today's reminders.
Say "give me my brief" any time, or "brief me at 7:30" to change the time.

## Meeting notes

When a meeting starts Jarvis asks whether to take notes (say yes), or say "take notes" any time.
While taking notes it only listens and saves text, so it costs no tokens. Say "stop notes" or press
the shortcut again and it offers a short summary. Later: "what did we decide in the client sync?"
Notes come from the microphone, so for online calls use speakers or say the key points aloud.

## Calendar

In Google Calendar: Settings > your calendar > "Secret address in iCal format". In Outlook: Settings >
Calendar > Shared calendars > Publish, copy the ICS link. Paste it on the welcome/settings screen.
Treat that link like a password.

## Architecture

**Tiered brain** (cheapest first): rules -> free local model (Ollama, optional) -> Haiku -> Sonnet for
hard or computer-control tasks. Only enabled tools are sent to the model, and old screenshots are
dropped, to keep token use low.

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

**Per-install settings** live in `config.local.json` (never uploaded to GitHub).
