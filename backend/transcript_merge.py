"""Merge transcripts from dual local transcription (Whisper + Parakeet)."""

import asyncio
import logging
from typing import Any

import openai

from groq_transcriber import format_seconds

logger = logging.getLogger(__name__)


def normalize_transcription_result(result: dict[str, Any], source: str) -> dict[str, Any]:
    """Extract timestamped segments from a backend result.

    Falls back to paragraph chunks when timestamps are absent.
    """
    raw = result.get("raw", {})
    segments = raw.get("segments")

    if segments:
        normalized = []
        for seg in segments:
            text = str(seg.get("text") or "").strip()
            has_timestamps = seg.get("start") is not None and seg.get("end") is not None
            if not text and not has_timestamps:
                continue
            normalized.append({
                "start": seg.get("start"),
                "end": seg.get("end"),
                "text": text,
            })
        if normalized:
            return {"source": source, "segments": normalized}

    text = str(raw.get("text") or "").strip()
    if not text:
        markdown = str(result.get("markdown") or "").strip()
        if markdown:
            text = markdown
    if text:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        segments_out = []
        for para in paragraphs:
            if para:
                segments_out.append({"start": None, "end": None, "text": para})
        return {"source": source, "segments": segments_out}

    return {"source": source, "segments": []}


def _parse_time(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    if ":" in text:
        try:
            parts = [float(p) for p in text.split(":")]
        except ValueError:
            return None
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + part
        return seconds
    try:
        return float(text)
    except ValueError:
        return None


def _time_ranges_overlap(
    s1: float | None, e1: float | None, s2: float | None, e2: float | None
) -> bool:
    if s1 is None or e1 is None or s2 is None or e2 is None:
        return False
    return s1 < e2 and s2 < e1


def _format_segments_with_timecodes(segments: list[dict[str, Any]]) -> str:
    has_timestamps = any(s.get("start") is not None for s in segments)
    if not has_timestamps:
        return "\n\n".join(seg["text"] for seg in segments)
    lines: list[str] = []
    for seg in segments:
        start_val = _parse_time(seg.get("start"))
        end_val = _parse_time(seg.get("end"))
        if start_val is not None and end_val is not None:
            lines.append(f"**[{format_seconds(start_val)} - {format_seconds(end_val)}]**")
            lines.append("")
        lines.append(seg["text"])
        lines.append("")
    return "\n".join(lines).strip()


def merge_transcripts_deterministic(
    whisper_result: dict[str, Any], parakeet_result: dict[str, Any]
) -> dict[str, Any]:
    """Deterministic merge: Whisper is primary, Parakeet fills gaps and adds non-overlapping spans."""
    whisper = normalize_transcription_result(whisper_result, "whisper")
    parakeet = normalize_transcription_result(parakeet_result, "parakeet")

    w_segs = whisper["segments"]
    p_segs = parakeet["segments"]
    whisper_has_timestamps = w_segs and w_segs[0].get("start") is not None
    parakeet_has_timestamps = p_segs and p_segs[0].get("start") is not None

    if not w_segs and not p_segs:
        return {
            "markdown": "",
            "stats": {
                "whisper_segments": 0,
                "parakeet_segments": 0,
                "merged_segments": 0,
                "parakeet_fill_count": 0,
                "parakeet_append_count": 0,
            },
        }

    if not w_segs:
        merged_text = _format_segments_with_timecodes(p_segs)
        stats = {
            "whisper_segments": 0,
            "parakeet_segments": len(p_segs),
            "merged_segments": len(p_segs),
            "parakeet_fill_count": 0,
            "parakeet_append_count": len(p_segs),
        }
        return {"markdown": merged_text, "stats": stats}

    if not p_segs:
        merged_text = _format_segments_with_timecodes(w_segs)
        stats = {
            "whisper_segments": len(w_segs),
            "parakeet_segments": 0,
            "merged_segments": len(w_segs),
            "parakeet_fill_count": 0,
            "parakeet_append_count": 0,
        }
        return {"markdown": merged_text, "stats": stats}

    if not whisper_has_timestamps or not parakeet_has_timestamps:
        merged_text = _format_segments_with_timecodes(w_segs)
        parakeet_extra = _format_segments_with_timecodes(p_segs)
        if parakeet_extra:
            merged_text = merged_text + "\n\n" + parakeet_extra
        stats = {
            "whisper_segments": len(w_segs),
            "parakeet_segments": len(p_segs),
            "merged_segments": len(w_segs) + len(p_segs),
            "parakeet_fill_count": 0,
            "parakeet_append_count": len(p_segs),
        }
        return {"markdown": merged_text, "stats": stats}

    merged: list[dict[str, Any]] = []
    fill_count = 0
    append_count = 0

    for w_seg in w_segs:
        ws = _parse_time(w_seg.get("start"))
        we = _parse_time(w_seg.get("end"))
        text = str(w_seg.get("text") or "").strip()
        if text or (ws is not None and we is not None):
            merged.append({"start": ws, "end": we, "text": text, "source": "whisper"})

    for p_seg in p_segs:
        ps = _parse_time(p_seg.get("start"))
        pe = _parse_time(p_seg.get("end"))
        p_text = str(p_seg.get("text") or "").strip()
        if not p_text:
            continue

        overlaps = False
        for m_seg in merged:
            ms = _parse_time(m_seg.get("start"))
            me = _parse_time(m_seg.get("end"))
            if _time_ranges_overlap(ps, pe, ms, me):
                overlaps = True
                if not str(m_seg.get("text") or "").strip():
                    m_seg["text"] = p_text
                    m_seg["source"] = "parakeet"
                    fill_count += 1
                break

        if not overlaps:
            merged.append({"start": ps, "end": pe, "text": p_text, "source": "parakeet"})
            append_count += 1

    merged.sort(key=lambda s: _parse_time(s.get("start")) or 0.0)

    merged_text = _format_segments_with_timecodes(merged)
    stats = {
        "whisper_segments": len(w_segs),
        "parakeet_segments": len(p_segs),
        "merged_segments": len(merged),
        "parakeet_fill_count": fill_count,
        "parakeet_append_count": append_count,
    }
    return {"markdown": merged_text, "stats": stats}


async def merge_transcripts_ai(
    whisper_result: dict[str, Any],
    parakeet_result: dict[str, Any],
    *,
    api_key: str,
    base_url: str = "",
    model: str = "",
    prompt: str = "",
    reasoning_effort: str = "",
) -> dict[str, Any]:
    """Merge transcripts using an AI chat model."""
    whisper = normalize_transcription_result(whisper_result, "whisper")
    parakeet = normalize_transcription_result(parakeet_result, "parakeet")

    whisper_text = "\n\n".join(seg["text"] for seg in whisper["segments"])
    parakeet_text = "\n\n".join(seg["text"] for seg in parakeet["segments"])

    if not whisper_text and not parakeet_text:
        return {"markdown": "", "stats": {}}

    system_prompt = (
        "You are a transcript merging assistant. You will receive two transcripts of the same audio, "
        "one from Whisper and one from Parakeet. Your task:\n"
        "1. Merge them into a single coherent transcript.\n"
        "2. Preserve the source language exactly — do not translate.\n"
        "3. Do NOT summarize, do NOT add commentary, do NOT invent content.\n"
        "4. When the transcripts agree, keep the more accurate version.\n"
        "5. When one transcript has content the other lacks, include it.\n"
        "6. Output plain text with blank-line-separated paragraphs.\n"
    )
    if prompt:
        system_prompt += f"\nAdditional instructions: {prompt}\n"

    user_content = f"## Whisper Transcript\n\n{whisper_text}\n\n## Parakeet Transcript\n\n{parakeet_text}"

    effective_url = base_url.rstrip("/") or None
    kwargs: dict[str, Any] = {
        "api_key": api_key,
    }
    if effective_url:
        kwargs["base_url"] = effective_url

    client = openai.OpenAI(**kwargs)

    chat_kwargs: dict[str, Any] = {
        "model": model or "gpt-4o",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 8000,
        "temperature": 0.2,
    }

    if reasoning_effort:
        chat_kwargs["reasoning_effort"] = reasoning_effort

    response = await asyncio.to_thread(client.chat.completions.create, **chat_kwargs)
    merged_text = (response.choices[0].message.content or "").strip()

    return {"markdown": merged_text, "stats": {"ai_merge": True}}


def resolve_merge_credentials(
    *,
    form_merge_api_key: str = "",
    form_merge_base_url: str = "",
    form_merge_model: str = "",
    form_merge_prompt: str = "",
    form_merge_reasoning_effort: str = "",
    form_summary_api_key: str = "",
    form_summary_base_url: str = "",
    form_summary_model: str = "",
) -> dict[str, str]:
    """Resolve merge credentials with fallback chain.

    Precedence: form merge fields -> settings.json merge fields -> MERGE_* env vars
                -> form summary fields -> existing summary settings/env vars.
    """
    import os
    from settings import load_settings

    settings = load_settings()

    def _first(*values: str) -> str:
        for v in values:
            if v and v.strip():
                return v.strip()
        return ""

    api_key = _first(
        form_merge_api_key,
        settings.get("merge_api_key", ""),
        os.getenv("MERGE_API_KEY", ""),
        form_summary_api_key,
        settings.get("openai_api_key", ""),
        os.getenv("OPENAI_API_KEY", ""),
    )
    base_url = _first(
        form_merge_base_url,
        settings.get("merge_base_url", ""),
        os.getenv("MERGE_BASE_URL", ""),
        form_summary_base_url,
        settings.get("openai_base_url", ""),
        os.getenv("OPENAI_BASE_URL", ""),
    )
    model = _first(
        form_merge_model,
        settings.get("merge_model", ""),
        os.getenv("MERGE_MODEL", ""),
        form_summary_model,
        settings.get("summary_model", ""),
    )

    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "prompt": _first(form_merge_prompt, settings.get("merge_prompt", "")),
        "reasoning_effort": _first(
            form_merge_reasoning_effort, settings.get("merge_reasoning_effort", "")
        ),
    }
