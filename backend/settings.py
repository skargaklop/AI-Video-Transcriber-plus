"""Shared settings management for CLI and GUI via settings.json."""

import json
import os
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_FILE = PROJECT_ROOT / "settings.json"

DEFAULT_SETTINGS = {
    "groq_api_key": "",
    "openai_api_key": "",
    "openai_base_url": "https://api.openai.com/v1",
    "groq_model": "whisper-large-v3-turbo",
    "groq_language": "",
    "groq_prompt": "",
    "transcription_provider": "groq",
    "try_subtitles_first": True,
    "use_local_fallback": False,
    "local_backend": "whisper",
    "local_model_preset": "base",
    "local_model_id": "",
    "local_language": "",
    "local_api_base_url": "",
    "local_api_key": "",
    "local_api_model": "",
    "local_api_language": "",
    "local_api_prompt": "",
    "include_timecodes": False,
    "summary_language": "en",
    "summary_model": "",
    "summary_format": "markdown",
    "summary_prompt": "",
    "reasoning_effort": "",
    "summary_chunk_threshold": 15000,
    "dual_local_transcription": False,
    "dual_whisper_model_preset": "base",
    "dual_whisper_model_id": "",
    "dual_parakeet_model_preset": "",
    "dual_parakeet_model_id": "",
    "merge_use_ai": False,
    "merge_api_key": "",
    "merge_base_url": "",
    "merge_model": "",
    "merge_prompt": "",
    "merge_reasoning_effort": "",
    "multi_source_enabled": False,
    "transcription_sources": "",
    "merge_mode": "",
    "merge_primary_source": "",
}

_write_lock = threading.Lock()


def load_settings() -> dict:
    """Read settings.json, merge with defaults for missing keys."""
    result = dict(DEFAULT_SETTINGS)
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                result.update(saved)
    except (json.JSONDecodeError, OSError):
        pass
    return result


def save_settings(data: dict) -> dict:
    """Merge *data* with existing settings and write atomically."""
    with _write_lock:
        current = load_settings()
        current.update(data)
        # Only persist keys from DEFAULT_SETTINGS to avoid schema drift
        to_save = {k: current.get(k, DEFAULT_SETTINGS[k]) for k in DEFAULT_SETTINGS}
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(to_save, f, ensure_ascii=False, indent=2)
            tmp.replace(SETTINGS_FILE)
        except OSError:
            tmp.unlink(missing_ok=True)
            raise
    return to_save


def get_credential(env_var: str, settings_key: str) -> str:
    """Return env var value if set, otherwise settings.json value, else ''."""
    env_val = os.getenv(env_var, "").strip()
    if env_val:
        return env_val
    return load_settings().get(settings_key, "").strip()


def mask_credential(value: str) -> str:
    """Mask a credential for display: first 4 + last 4 chars."""
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def get_masked_settings() -> dict:
    """Load settings and mask credential fields."""
    s = load_settings()
    s["groq_api_key"] = mask_credential(s.get("groq_api_key", ""))
    s["openai_api_key"] = mask_credential(s.get("openai_api_key", ""))
    s["merge_api_key"] = mask_credential(s.get("merge_api_key", ""))
    return s
