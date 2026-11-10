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
- 🟡 Reminders (spoken when due; checked after each interaction — background timer is next)
- 🟡 Visual explainer window: bar/line charts and definition cards (needs testing on Windows)

## Planned
- ⬜ Wake word ("Hey Jarvis") instead of push-to-talk
- ⬜ Background reminder timer
- ⬜ Computer control (screenshots + mouse/keyboard) with approval prompts for risky actions
- ⬜ Calendar integration (Google or Outlook) and meeting reminders with prep
- ⬜ Project tracker rollup ("what's going on right now")
- ⬜ Email/message triage
- ⬜ Meeting notes → tasks
- ⬜ Morning briefing and end-of-day summary
- ⬜ Web search and research mode
- ⬜ Coding helper mode
- ⬜ Spend tracker and monthly cap per install
- ⬜ Voice cloning for a custom signature voice
