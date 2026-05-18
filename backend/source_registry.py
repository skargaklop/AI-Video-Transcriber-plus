"""Source registry for multi-source transcription."""

VALID_SOURCES = ("platform", "groq", "local_whisper", "local_parakeet")

SOURCE_DISPLAY_NAMES = {
    "platform": "Platform subtitles",
    "groq": "Groq Whisper",
    "local_whisper": "Local Whisper",
    "local_parakeet": "Local Parakeet",
}


def parse_transcription_sources(value: str | list[str] | None) -> list[str]:
    """Parse transcription_sources from JSON array string, CSV, or list.

    Returns a deduplicated list of valid source IDs.
    Raises ValueError for invalid or empty results.
    """
    if not value:
        return []

    if isinstance(value, list):
        raw = [s.strip().lower() for s in value if isinstance(s, str) and s.strip()]
    else:
        text = str(value).strip()
        if not text:
            return []

        if text.startswith("["):
            import json
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    raw = [s.strip().lower() for s in parsed if isinstance(s, str) and s.strip()]
                else:
                    raise ValueError("transcription_sources JSON must be an array")
            except json.JSONDecodeError as e:
                raise ValueError(f"transcription_sources is not valid JSON: {e}") from e
        else:
            raw = [s.strip().lower() for s in text.split(",") if s.strip()]

    seen = set()
    result = []
    for s in raw:
        if s in VALID_SOURCES and s not in seen:
            seen.add(s)
            result.append(s)

    invalid = [s for s in raw if s not in VALID_SOURCES]
    if invalid:
        raise ValueError(
            f"Invalid transcription source(s): {', '.join(invalid)}. "
            f"Valid sources: {', '.join(VALID_SOURCES)}"
        )

    return result


def resolve_sources_from_legacy(
    transcription_provider: str = "",
    dual_local_transcription: bool = False,
    try_subtitles_first: bool = True,
    local_backend: str = "",
) -> list[str]:
    """Map old provider/dual flags to the new source list.

    This provides backward compatibility for requests that use the old fields.
    """
    provider = (transcription_provider or "").strip().lower()

    if dual_local_transcription:
        sources = ["local_whisper", "local_parakeet"]
        return sources

    if provider == "groq":
        sources = ["groq"]
        return sources

    if provider == "local":
        backend = (local_backend or "whisper").strip().lower()
        if backend == "parakeet":
            return ["local_parakeet"]
        return ["local_whisper"]

    if provider == "local_api":
        return ["groq"]

    return ["groq"]


def resolve_merge_mode(merge_use_ai: bool = False, merge_mode: str = "") -> str:
    """Determine merge mode from legacy and new flags."""
    mode = (merge_mode or "").strip().lower()
    if mode in ("system", "raw", "ai"):
        return mode
    if merge_use_ai:
        return "ai"
    return "system"


def normalize_source_result(
    source_id: str,
    result: dict | None = None,
    error: str | None = None,
) -> dict:
    """Normalize a single source transcription result into a standard shape."""
    entry = {
        "source_id": source_id,
        "display_name": SOURCE_DISPLAY_NAMES.get(source_id, source_id),
        "status": "error" if error else ("success" if result else "pending"),
        "warnings": [],
        "errors": [],
        "markdown": "",
        "segments": [],
        "language": "",
        "model": "",
        "artifact_filename": "",
    }

    if error:
        entry["errors"].append(str(error))
        return entry

    if not result:
        return entry

    entry["status"] = "success"
    entry["markdown"] = result.get("markdown", "")
    entry["language"] = result.get("language", "")
    entry["warnings"] = list(result.get("warnings") or [])

    raw = result.get("raw", {})
    if raw.get("segments"):
        entry["segments"] = [
            {
                "start": seg.get("start"),
                "end": seg.get("end"),
                "text": str(seg.get("text") or "").strip(),
            }
            for seg in raw["segments"]
            if seg.get("text") or seg.get("start") is not None
        ]

    if result.get("model"):
        entry["model"] = result["model"]

    return entry
