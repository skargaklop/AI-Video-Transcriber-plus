"""Merge transcripts from multi-source transcription."""

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


def merge_transcripts_deterministic_n(
    source_results: list[dict[str, Any]],
    primary_source_id: str = "",
) -> dict[str, Any]:
    """Deterministic N-source merge.

    Uses the primary_source_id result as the base timeline.
    Other sources fill empty/low-confidence spans and append non-overlapping segments.
    Falls back to the first successful source if primary is unavailable.
    """
    if not source_results:
        return {"markdown": "", "stats": {"merged_segments": 0, "sources": 0}}

    normalized = []
    for sr in source_results:
        sid = sr.get("source_id", "unknown")
        segments = sr.get("segments", [])
        if segments or sr.get("markdown"):
            normalized.append({
                "source_id": sid,
                "segments": segments,
                "has_timestamps": bool(segments) and segments[0].get("start") is not None,
                "text": sr.get("markdown", ""),
            })

    if not normalized:
        return {"markdown": "", "stats": {"merged_segments": 0, "sources": len(source_results)}}

    if len(normalized) == 1:
        text = _format_segments_with_timecodes(normalized[0]["segments"]) if normalized[0]["segments"] else normalized[0]["text"]
        return {
            "markdown": text,
            "stats": {"merged_segments": len(normalized[0]["segments"]), "sources": 1, "primary": normalized[0]["source_id"]},
        }

    primary = None
    if primary_source_id:
        for n in normalized:
            if n["source_id"] == primary_source_id:
                primary = n
                break

    if primary is None:
        primary = normalized[0]

    secondaries = [n for n in normalized if n is not primary]

    if not primary["has_timestamps"]:
        parts = [_format_segments_with_timecodes(primary["segments"]) if primary["segments"] else primary["text"]]
        for sec in secondaries:
            sec_text = _format_segments_with_timecodes(sec["segments"]) if sec["segments"] else sec["text"]
            if sec_text:
                parts.append(sec_text)
        return {
            "markdown": "\n\n".join(parts),
            "stats": {
                "merged_segments": sum(len(n["segments"]) for n in normalized),
                "sources": len(normalized),
                "primary": primary["source_id"],
                "fill_count": 0,
                "append_count": sum(len(n["segments"]) for n in secondaries),
            },
        }

    merged: list[dict[str, Any]] = []
    for seg in primary["segments"]:
        text = str(seg.get("text") or "").strip()
        start = seg.get("start")
        end = seg.get("end")
        if text or (start is not None and end is not None):
            merged.append({"start": _parse_time(start), "end": _parse_time(end), "text": text, "source": primary["source_id"]})

    fill_count = 0
    append_count = 0
    for sec in secondaries:
        if not sec["has_timestamps"]:
            sec_text = _format_segments_with_timecodes(sec["segments"]) if sec["segments"] else sec["text"]
            if sec_text:
                merged.append({"start": None, "end": None, "text": sec_text, "source": sec["source_id"]})
                append_count += 1
            continue

        for p_seg in sec["segments"]:
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
                        m_seg["source"] = sec["source_id"]
                        fill_count += 1
                    break

            if not overlaps:
                merged.append({"start": ps, "end": pe, "text": p_text, "source": sec["source_id"]})
                append_count += 1

    merged.sort(key=lambda s: _parse_time(s.get("start")) or 0.0)
    merged_text = _format_segments_with_timecodes(merged)
    return {
        "markdown": merged_text,
        "stats": {
            "merged_segments": len(merged),
            "sources": len(normalized),
            "primary": primary["source_id"],
            "fill_count": fill_count,
            "append_count": append_count,
            "source_segments": {n["source_id"]: len(n["segments"]) for n in normalized},
        },
    }


async def merge_transcripts_ai_n(
    source_results: list[dict[str, Any]],
    *,
    api_key: str,
    base_url: str = "",
    model: str = "",
    prompt: str = "",
    reasoning_effort: str = "",
) -> dict[str, Any]:
    """AI merge for N sources using an OpenAI-compatible endpoint."""
    parts = []
    for sr in source_results:
        name = sr.get("source_id", "unknown")
        text = sr.get("markdown", "")
        if sr.get("segments"):
            text = _format_segments_with_timecodes(sr["segments"])
        if text:
            parts.append(f"## {name}\n\n{text}")

    if not parts:
        return {"markdown": "", "stats": {"ai_merge": True, "sources": 0}}

    system_prompt = (
        "You are a transcript merging assistant. You will receive multiple transcripts of the same audio "
        "from different sources. Your task:\n"
        "1. Merge them into a single coherent transcript.\n"
        "2. Preserve the source language exactly — do not translate.\n"
        "3. Do NOT summarize, do NOT add commentary, do NOT invent content.\n"
        "4. When the transcripts agree, keep the more accurate version.\n"
        "5. When one transcript has content the other lacks, include it.\n"
        "6. Output plain text with blank-line-separated paragraphs.\n"
    )
    if prompt:
        system_prompt += f"\nAdditional instructions: {prompt}\n"

    user_content = "\n\n".join(parts)

    effective_url = base_url.rstrip("/") or None
    kwargs: dict[str, Any] = {"api_key": api_key}
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

    return {
        "markdown": merged_text,
        "stats": {"ai_merge": True, "sources": len(source_results)},
    }


def build_raw_bundle(
    source_results: list[dict[str, Any]],
    selected_sources: list[str],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Build a raw bundle: per-source artifacts and an index/report."""
    successful = [sr for sr in source_results if sr.get("status") == "success"]
    failed = [sr for sr in source_results if sr.get("status") == "error"]
    pending = [sr for sr in source_results if sr.get("status") == "pending"]

    report_lines = ["# Transcription Raw Bundle\n"]
    report_lines.append("## Selected Sources\n")
    for sid in selected_sources:
        status = "not_run"
        for sr in source_results:
            if sr.get("source_id") == sid:
                status = sr.get("status", "pending")
                break
        report_lines.append(f"- **{sid}**: {status}")

    if successful:
        report_lines.append("\n## Completed Sources\n")
        for sr in successful:
            report_lines.append(f"### {sr.get('display_name', sr.get('source_id', 'unknown'))}\n")
            if sr.get("model"):
                report_lines.append(f"- Model: {sr['model']}")
            if sr.get("language"):
                report_lines.append(f"- Language: {sr['language']}")
            if sr.get("artifact_filename"):
                report_lines.append(f"- File: `{sr['artifact_filename']}`")
            if sr.get("warnings"):
                report_lines.append(f"- Warnings: {'; '.join(sr['warnings'])}")
            report_lines.append("")

        report_lines.append("\n## Raw Transcriptions\n")
        for sr in successful:
            transcript = str(sr.get("markdown") or "").strip()
            if not transcript:
                continue
            report_lines.append(f"### {sr.get('display_name', sr.get('source_id', 'unknown'))}\n")
            report_lines.append(transcript)
            report_lines.append("")

    if failed:
        report_lines.append("\n## Failed Sources\n")
        for sr in failed:
            errors = sr.get("errors", [])
            report_lines.append(f"- **{sr.get('source_id', 'unknown')}**: {'; '.join(errors)}")

    if warnings:
        report_lines.append("\n## Warnings\n")
        for w in warnings:
            report_lines.append(f"- {w}")

    report_lines.append(f"\n## Summary\n")
    report_lines.append(f"- Selected: {len(selected_sources)}")
    report_lines.append(f"- Completed: {len(successful)}")
    report_lines.append(f"- Failed: {len(failed)}")
    report_lines.append(f"- Pending: {len(pending)}")

    report_markdown = "\n".join(report_lines)

    artifacts = {}
    for sr in successful:
        if sr.get("artifact_filename"):
            artifacts[sr["source_id"]] = sr["artifact_filename"]

    return {
        "report_markdown": report_markdown,
        "artifacts": artifacts,
        "successful_source_ids": [sr["source_id"] for sr in successful],
        "failed_source_ids": [sr["source_id"] for sr in failed],
    }
