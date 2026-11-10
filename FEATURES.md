# Jarvis — Feature List

Legend: ✅ built · 🟡 partly built · ⬜ planned

## Core
- ✅ Speech-to-text (faster-whisper, local, free)
- ✅ Text-to-speech, 5 switchable voices (Piper, local, free)
- ✅ Tiered brain: rules → local model (Ollama) → Haiku → Sonnet
- ✅ Tool registry: add a capability with one decorated function (`scripts/tools.py`)
- ✅ Only enabled tools are sent to the model (saves tokens)
- ✅ Memory: chat history, long-term facts, reminders (local SQLite)
- ✅ Per-install config, so one codebase serves you and every client
- ✅ One-click `setup.bat` and `update.bat`; updates ship through GitHub
- ✅ Reminders spoken on time by a background timer
- ✅ Calendar: reads any Google/Outlook/Apple calendar via its private .ics link, adds local events, warns before meetings
- ✅ Computer control (screenshot, click, type, keys, scroll, open app) with per-task approval, extra approval for risky keys/apps, 40-action cap, screen-corner abort, and old screenshots dropped to save tokens
- ✅ First-run welcome screen (Iron Man styled): name, what you work on, assistant names, voice, API key, calendar, brief time, shortcut, abilities - Jarvis speaks the intro
- ✅ Corner orb pop-up with the Apricot Digital logo on a transparent background; pulses with the voice; draggable; tray icon
- ✅ Call it by shortcut key, "Hey <name>" (any name, several names), or tray
- ✅ Hands-free listening: stops when you stop talking (no Enter key)
- ✅ Daily brief at a set time (meetings, what to prepare, yesterday's summaries, reminders); change by voice or settings
- ✅ Meeting prep: heads-up includes the last summary of the same meeting
- ✅ Meeting notes: offers to take notes when a meeting starts (or say "take notes"), listens quietly with zero token cost, offers a Haiku summary at the end, and answers later questions about past notes
- ✅ One app for everyone: features switched on/off per person in config.local.json
- 🟡 Visual explainer window: bar/line charts and definition cards (needs testing on Windows)

## Planned
- ⬜ Write events back to Google/Outlook (needs OAuth)
- ⬜ Capture the other side of a call (Windows system-audio loopback); today notes come from the microphone
- ⬜ Meeting prep: show last meeting's summary before the next one
- ⬜ Trained wake-word model (openWakeWord) for lower CPU use and fewer false triggers
- ⬜ Windows installer (.exe) so nobody needs Python
- ⬜ Project tracker rollup ("what's going on right now")
- ⬜ Email/message triage
- ⬜ Turn action items from notes into tasks
- ⬜ End-of-day summary
- ⬜ Web search and research mode
- ⬜ Coding helper mode
- ⬜ Spend tracker and monthly cap per install
- ⬜ Voice cloning for a custom signature voice
