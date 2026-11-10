"""Loads per-install settings from config.local.json (falls back to the example)."""
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent


def save_config(cfg: dict):
    """Writes the per-install file (gitignored: holds the API key)."""
    (ROOT / "config.local.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def load_config() -> dict:
    for name in ("config.local.json", "config.example.json"):
        p = ROOT / name
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    raise FileNotFoundError("No config file found. Run setup.bat first.")
