"""Loads per-install settings from config.local.json, filling in defaults for anything missing."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent

DEFAULTS = {
    "onboarded": False,
    "owner_name": "",
    "assistant_names": ["Jarvis"],
    "voice": "amy",
    "hotkey": "ctrl+alt+j",
    "wake_word_enabled": True,
    "briefing_enabled": True,
    "briefing_time": "08:30",
    "meeting_reminder_minutes": 10,
    "language": "auto",  # auto | en | ur
    "overlay_corner": "bottom-right",
    "overlay_caption": True,
    "models": {"tier0_local": None, "tier0_local_heavy": None, "tier1_cloud": "claude-haiku-5-5", "tier2_cloud": "claude-sonnet-5-5"},
    "slots": {
        "llm": {"provider": "anthropic", "base_url": "https://api.openai.com/v1"},
        "stt": {"provider": "local_whisper", "model": "base.en"},
        "tts": {"provider": "piper", "elevenlabs_voice_id": "", "urdu_voice": "ur-PK-AsadNeural"},
    },
    "privacy": {"mode": "balanced", "private_terms": [], "local_only_terms": []},
    "file_roots": [],
    "tools_enabled": {"reminders": True, "calendar": False, "notes": True, "todos": True, "files": True,
                      "computer_control": False, "visual_explainer": True},
    "integrations": {"calendar_ics_url": None},
}


def _merge(base: dict, over: dict) -> dict:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def save_config(cfg: dict):
    """Writes the per-install file (gitignored). API keys are NOT stored here - see secrets_store."""
    clean = {k: v for k, v in cfg.items() if k not in ("anthropic_api_key",)}
    (ROOT / "config.local.json").write_text(json.dumps(clean, indent=2), encoding="utf-8")


def load_config() -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    for name in ("config.local.json", "config.example.json"):
        p = ROOT / name
        if p.exists():
            raw = json.loads(p.read_text(encoding="utf-8"))
            raw.pop("_comment", None)
            merged = _merge(cfg, raw)
            if merged["models"].get("tier2_cloud") == "claude-sonnet-5":  # older installs used a wrong id
                merged["models"]["tier2_cloud"] = "claude-sonnet-5-5"
            return merged
    return cfg
