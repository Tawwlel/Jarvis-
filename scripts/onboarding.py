"""
First-run setup. Jarvis introduces itself, asks a few questions, and writes
config.local.json - so nobody has to edit a file by hand.

Everything is injected (say / ask / secret / preview) so it can be tested
without a microphone.
"""
import copy
import re

from notes import NO, YES

VOICE_NAMES = ["amy", "ryan", "alan", "lessac", "southern"]
PLACEHOLDER_KEY = "sk-ant-..."


def clean_name(raw: str) -> str:
    s = re.sub(r"(?i)\b(hi|hello|hey|my name is|my name's|i am|i'm|it's|its|call me|this is)\b", "", raw)
    s = re.sub(r"[^A-Za-z' -]", "", s).strip()
    return " ".join(w.capitalize() for w in s.split()[:3]) or "friend"


def pick_voice(answer: str, default: str) -> str:
    low = answer.lower()
    for v in VOICE_NAMES:
        if v in low:
            return v
    return default


def run(cfg: dict, say, ask, secret, preview, memory) -> dict:
    cfg = copy.deepcopy(cfg)

    say("Hi, I'm Jarvis, your personal assistant. I'll help with your meetings, "
        "your notes and your reminders, and I can even take control of your computer "
        "to get things done. First, what's your name?")
    name = clean_name(ask())
    cfg["owner_name"] = name
    memory.remember("user_name", name)

    say(f"Nice to meet you, {name}. What are you currently working on?")
    work = ask().strip()
    if work:
        memory.remember("currently_working_on", work)
        say("Got it. I'll keep that in mind when I help you.")

    say("Let me introduce my voices.")
    for v in VOICE_NAMES:
        preview(v, f"Hi {name}, this is the {v} voice.")
    say("Which voice would you like? Say its name.")
    cfg["voice"] = pick_voice(ask(), cfg.get("voice", "amy"))
    preview(cfg["voice"], "Great, I'll use this one.")

    key = cfg.get("anthropic_api_key", "")
    if not key or key == PLACEHOLDER_KEY:
        say("To think, I need an Anthropic API key. Paste it into the window now. "
            "It stays on this computer. Press Enter to skip and add it later.")
        key = secret("Anthropic API key: ").strip()
        if key:
            cfg["anthropic_api_key"] = key

    say("If you use Google or Outlook calendar, paste your calendar's private iCal link "
        "so I can remind you before meetings. Press Enter to skip.")
    link = secret("Calendar iCal link: ").strip()
    if link:
        cfg.setdefault("integrations", {})["calendar_ics_url"] = link
    cfg.setdefault("tools_enabled", {})["calendar"] = bool(link)
    cfg["tools_enabled"]["notes"] = True

    say("I can also take control of your computer for tasks you ask for. I always ask "
        "before I start, and you can stop me by moving the mouse into a screen corner. "
        "Do you want that turned on?")
    ans = ask()
    cfg["tools_enabled"]["computer_control"] = bool(YES.search(ans)) and not NO.search(ans)

    cfg["onboarded"] = True
    say(f"All set, {name}. Try saying: what's on my calendar, remind me in ten minutes "
        "to stretch, or take notes. I'm ready when you are.")
    return cfg
