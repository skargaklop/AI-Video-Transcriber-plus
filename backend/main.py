from fastapi import FastAPI, HTTPException, Form, File, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import os
import asyncio
import logging
import importlib
import threading
from datetime import datetime, timezone
from pathlib import Path
import aiofiles
import uuid
import json
import re
import openai

from video_processor import VideoProcessor
from groq_transcriber import (
    DEFAULT_GROQ_MODEL,
    GroqTranscriptionError,
    GroqURLTranscriber,
)
from html_export import render_summary_html
from local_api_transcriber import LocalAPITranscriber, LocalAPITranscriptionError
from local_transcription import (
    DEFAULT_LOCAL_BACKEND,
    backend_dependencies_available,
    backend_install_constraints,
    ensure_backend_audio_file,
    ensure_backend_dependencies,
    get_local_capabilities,
    LocalTranscriptionError,
    prepare_local_transcriber,
    resolve_local_model_id,
)
from summarizer import Summarizer
from transcript_formatting import format_transcript_without_timecodes
from transcript_merge import (
    merge_transcripts_ai,
    merge_transcripts_ai_n,
    merge_transcripts_deterministic,
    merge_transcripts_deterministic_n,
    resolve_merge_credentials,
    build_raw_bundle,
)
from settings import get_credential, get_masked_settings, save_settings
from source_registry import (
    SOURCE_DISPLAY_NAMES,
    VALID_SOURCES,
    normalize_source_result,
    parse_transcription_sources,
    resolve_merge_mode,
    resolve_sources_from_legacy,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _resolve_primary(successful_sources, requested_primary, warnings):
    """Resolve primary source for merge, warning if the requested one is unavailable."""
    if requested_primary:
        for sr in successful_sources:
            if sr["source_id"] == requested_primary:
                return requested_primary
        warnings.append(
            f"Primary source '{requested_primary}' was selected but failed or unavailable; "
            f"using '{successful_sources[0]['source_id']}' instead."
        )
    return successful_sources[0]["source_id"]


app = FastAPI(title="AI Video Transcriber", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Mount static files
app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "static")), name="static")

# Create temp directory
TEMP_DIR = PROJECT_ROOT / "temp"
TEMP_DIR.mkdir(exist_ok=True)

# Initialize handlers
video_processor = VideoProcessor()
summarizer = Summarizer()

# Store task state - using file persistence
TASKS_FILE = TEMP_DIR / "tasks.json"
tasks_lock = threading.Lock()


def load_tasks():
    """Load task state"""
    try:
        if TASKS_FILE.exists():
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_tasks(tasks_data):
    """Save task state"""
    try:
        with tasks_lock:
            with open(TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(tasks_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to save task state: {e}")


def _mark_unfinished_source_statuses_failed(task: dict, detail: str) -> bool:
    """Mark pending/running per-source statuses as failed when a task stops."""
    statuses = task.get("source_statuses")
    if not isinstance(statuses, list):
        return False

    changed = False
    for source in statuses:
        if not isinstance(source, dict):
            continue
        if source.get("status") in {"running", "pending"}:
            source["status"] = "failed"
            source["detail"] = detail
            changed = True
    return changed


def _mark_incomplete_tasks_as_interrupted(tasks_data):
    """Mark persisted in-flight tasks as interrupted after app restart."""
    changed = False
    interrupted_at = datetime.now(timezone.utc).isoformat()
    task_error = "Task was interrupted by app restart. Start it again."
    summary_error = "Summary job was interrupted by app restart. Generate it again."

    for task in tasks_data.values():
        if task.get("status") == "processing":
            task["status"] = "error"
            task["error"] = task_error
            task["message"] = task_error
            task["stage_code"] = "error"
            task["stage_started_at"] = interrupted_at
            _mark_unfinished_source_statuses_failed(task, task_error)
            changed = True
        elif task.get("status") == "error":
            changed = (
                _mark_unfinished_source_statuses_failed(
                    task,
                    task.get("error")
                    or task.get("message")
                    or "Task failed before this source finished.",
                )
                or changed
            )

        if task.get("summary_status") == "processing":
            task["summary_status"] = "error"
            task["summary_progress"] = 0
            task["summary_error"] = summary_error
            if task.get("status") != "error":
                task["message"] = summary_error
            changed = True

    return changed


async def broadcast_task_update(task_id: str, task_data: dict):
    """Broadcast task status updates to all connected SSE clients"""
    logger.info(
        f"Broadcasting task update: {task_id}, status: {task_data.get('status')}, connections: {len(sse_connections.get(task_id, []))}"
    )
    if task_id in sse_connections:
        connections_to_remove = []
        for queue in sse_connections[task_id]:
            try:
                await queue.put(json.dumps(task_data, ensure_ascii=False))
                logger.debug(f"Message sent to queue: {task_id}")
            except Exception as e:
                logger.warning(f"Failed to send message to queue: {e}")
                connections_to_remove.append(queue)

        # Remove disconnected connections
        for queue in connections_to_remove:
            sse_connections[task_id].remove(queue)

        # If no connections remain, clean up the task's connection list
        if not sse_connections[task_id]:
            del sse_connections[task_id]


# Load task state at startup
tasks = load_tasks()
if _mark_incomplete_tasks_as_interrupted(tasks):
    save_tasks(tasks)
# Store URLs being processed to prevent duplicates
processing_urls = set()
# Store active task objects for control and cancellation
active_tasks = {}
active_summary_tasks = {}
# Store SSE connections for real-time status updates
sse_connections = {}


def _sanitize_title_for_filename(title: str) -> str:
    """Sanitize video title to a safe filename fragment."""
    if not title:
        return "untitled"
    # Keep only alphanumeric, underscore, hyphen, and space
    safe = re.sub(r"[^\w\-\s]", "", title)
    # Compress whitespace and convert to underscore
    safe = re.sub(r"\s+", "_", safe).strip("._-")
    # Maximum length to avoid overly long filename issues
    return safe[:80] or "untitled"


async def _persist_uploaded_audio_file(
    upload: UploadFile, output_dir: Path
) -> tuple[str, str, str]:
    """Persist an uploaded local audio file to the temp directory for background processing."""
    original_name = Path(upload.filename or "uploaded-audio").name or "uploaded-audio"
    suffix = Path(original_name).suffix or ".bin"
    safe_base = _sanitize_title_for_filename(Path(original_name).stem)
    stored_name = f"upload_{uuid.uuid4().hex[:8]}_{safe_base}{suffix}"
    stored_path = output_dir / stored_name

    size = 0
    try:
        async with aiofiles.open(stored_path, "wb") as target:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                await target.write(chunk)
    finally:
        await upload.close()

    if size <= 0:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")

    display_title = Path(original_name).stem.strip() or "Uploaded Audio"
    return str(stored_path), original_name, display_title


def _source_reference_line(url: str, source_file_name: str = "") -> str:
    if url:
        return f"source: {url}"
    if source_file_name:
        return f"source: local file - {source_file_name}"
    return "source: local file"


def _markdown_to_plain_text(markdown: str) -> str:
    text = str(markdown or "").strip()
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^[ \t]*[-*_]{3,}[ \t]*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_detected_language(transcript_text: str, fallback: str = "") -> str:
    normalized_fallback = (fallback or "").strip()
    if not transcript_text:
        return normalized_fallback

    for line in transcript_text.splitlines():
        if "**Detected Language:**" in line:
            detected = line.split(":", 1)[-1].strip()
            if detected and detected.lower() not in {"unknown", "auto", "auto-detect", "autodetect"}:
                return detected
            break

    return normalized_fallback or _infer_language_from_text(transcript_text)


def _infer_language_from_text(text: str) -> str:
    """Best-effort script-based language fallback when a backend omits language."""
    if not text:
        return ""
    cyrillic = sum(1 for ch in text if "\u0400" <= ch <= "\u04ff")
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    if cjk >= 2:
        return "zh"
    if cyrillic >= 2:
        if any(ch in text for ch in "іїєґІЇЄҐ"):
            return "uk"
        return "ru"
    return ""


def _dedupe_messages(messages: list[str]) -> list[str]:
    seen = set()
    deduped: list[str] = []
    for message in messages:
        text = str(message).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _file_name_from_path(value: str) -> str:
    return Path(value).name if value else ""


GROQ_MEDIA_RETRIEVAL_PATTERNS = (
    "failed to retrieve media",
    "received status code: 302",
    "status code: 302",
    "context deadline exceeded",
)


def _is_groq_media_retrieval_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(pattern in message for pattern in GROQ_MEDIA_RETRIEVAL_PATTERNS)


def _format_groq_transcription_error(
    error: Exception,
    retried: bool = False,
    file_fallback_error: Exception | None = None,
) -> str:
    if not _is_groq_media_retrieval_error(error):
        return str(error)

    retry_note = (
        "The app retried with a fresh URL, but Groq still could not fetch it."
        if retried
        else "The app could not fetch the media URL through Groq."
    )
    fallback_note = (
        f" A local file upload fallback also failed: {file_fallback_error}."
        if file_fallback_error
        else ""
    )
    return (
        "Groq could not retrieve the temporary media URL. "
        "YouTube signed media URLs can redirect, expire, or time out from Groq's network. "
        f"{retry_note} Try again, use a video with YouTube subtitles, or use a directly accessible media URL. "
        f"Original Groq error: {error}.{fallback_note}"
    )


def _build_groq_prompt(user_prompt: str = "", video_title: str = "") -> str:
    """Add lightweight spelling context from the title to improve named entities."""
    prompt_parts: list[str] = []
    title = (video_title or "").strip()
    if title and title.lower() != "unknown":
        terms = _extract_title_glossary_terms(title)
        if terms:
            prompt_parts.append("Terms: " + "; ".join(terms) + ".")
    custom_prompt = (user_prompt or "").strip()
    if custom_prompt:
        prompt_parts.append(custom_prompt)
    return "\n\n".join(prompt_parts)


def _extract_title_glossary_terms(video_title: str) -> list[str]:
    """Extract compact model/name terms from a title for ASR spelling hints."""
    title = (video_title or "").strip()
    terms: list[str] = []

    patterns = (
        r"\bClaude\s+Opus\s+\d+(?:[.,]\d+)?\b",
        r"\bGemini\s+\d+(?:[.,]\d+)?\s+Pro\b",
        r"\bGPT[-\s]?\d+(?:[.,]\d+)?\b",
        r"\bOpenRouter\b",
        r"\bAPI\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, title, flags=re.IGNORECASE):
            term = re.sub(r"\s+", " ", match.group(0)).strip()
            term = re.sub(r"GPT\s+(\d)", r"GPT-\1", term, flags=re.IGNORECASE)
            if term.upper().startswith("GPT"):
                term = "GPT" + term[3:]
            if term not in terms:
                terms.append(term)

    if not terms:
        terms.append(title[:120])

    return terms


def _apply_title_entity_corrections(text: str, video_title: str = "") -> str:
    """Normalize common ASR variants to exact model names present in the title."""
    if not text:
        return text

    corrected = str(text)
    title = video_title or ""

    claude_match = re.search(
        r"\bClaude\s+Opus\s+\d+(?:[.,]\d+)?\b",
        title,
        flags=re.IGNORECASE,
    )
    if claude_match:
        canonical_claude = re.sub(r"\s+", " ", claude_match.group(0)).strip()
        canonical_claude = re.sub(r"(\d),(\d)", r"\1.\2", canonical_claude)
        canonical_claude_base = re.sub(
            r"\s+\d+(?:[.,]\d+)?$",
            "",
            canonical_claude,
            flags=re.IGNORECASE,
        )
        corrected = re.sub(
            r"\b(?:Clot|Cloud|Cloude)\s+Opus\s+\d+(?:[.,]\d+)?\b",
            canonical_claude,
            corrected,
            flags=re.IGNORECASE,
        )
        corrected = re.sub(
            r"\b(?:Clot|Cloud|Cloude)\s+Opus\b",
            canonical_claude_base,
            corrected,
            flags=re.IGNORECASE,
        )
        corrected = re.sub(
            r"\bКлод\s+Опус\s+\d+(?:[.,]\d+)?\b",
            canonical_claude,
            corrected,
            flags=re.IGNORECASE,
        )
        corrected = re.sub(
            r"\bКлод\s+Опус\b",
            canonical_claude_base,
            corrected,
            flags=re.IGNORECASE,
        )

    gemini_match = re.search(
        r"\bGemini\s+\d+(?:[.,]\d+)?\s+Pro\b",
        title,
        flags=re.IGNORECASE,
    )
    if gemini_match:
        canonical_gemini = re.sub(r"\s+", " ", gemini_match.group(0)).strip()
        canonical_gemini = re.sub(r"(\d),(\d)", r"\1.\2", canonical_gemini)
        corrected = re.sub(
            r"\b(?:GMini|GMI|GME|GM)\s*3[.,]?\s*1\s+Pro\b",
            canonical_gemini,
            corrected,
            flags=re.IGNORECASE,
        )
        corrected = re.sub(
            r"\b(?:GMini|GMI|GME)\b",
            "Gemini",
            corrected,
            flags=re.IGNORECASE,
        )
        corrected = re.sub(
            r"\bGM\s+31\s+Pro\b",
            canonical_gemini,
            corrected,
            flags=re.IGNORECASE,
        )

    gpt_match = re.search(r"\bGPT[-\s]?\d+(?:[.,]\d+)?\b", title, flags=re.IGNORECASE)
    if gpt_match:
        canonical_gpt = re.sub(r"GPT\s+", "GPT-", gpt_match.group(0), flags=re.IGNORECASE)
        canonical_gpt = re.sub(r"(\d),(\d)", r"\1.\2", canonical_gpt)
        canonical_gpt = "GPT" + canonical_gpt[3:]
        corrected = re.sub(
            r"\b(?:GBT|GPT)\s*-?\s*5[.,]\s*5\b",
            canonical_gpt,
            corrected,
            flags=re.IGNORECASE,
        )
        corrected = re.sub(
            r"\bGepit[-\s]?55\b",
            canonical_gpt,
            corrected,
            flags=re.IGNORECASE,
        )
        corrected = re.sub(
            r"\bGPT5\b",
            canonical_gpt.split(".")[0],
            corrected,
            flags=re.IGNORECASE,
        )

    return corrected


def _apply_title_entity_corrections_to_result(result: dict, video_title: str = "") -> dict:
    """Apply title-name normalization to markdown and raw segment text."""
    if not result:
        return result

    result["markdown"] = _apply_title_entity_corrections(
        str(result.get("markdown") or ""), video_title
    )
    raw = result.get("raw")
    if isinstance(raw, dict) and isinstance(raw.get("segments"), list):
        for segment in raw["segments"]:
            if isinstance(segment, dict) and segment.get("text"):
                segment["text"] = _apply_title_entity_corrections(
                    str(segment.get("text") or ""), video_title
                )
    return result


def _is_groq_error_eligible_for_local_fallback(error: Exception) -> bool:
    message = str(error).strip().lower()
    non_fallback_patterns = (
        "invalid api key",
        "incorrect api key",
        "unauthorized",
        "authentication",
        "forbidden",
        "unsupported model",
        "model not found",
        "malformed",
        "invalid request",
        "missing groq",
        "api key is required",
    )
    if any(pattern in message for pattern in non_fallback_patterns):
        return False
    return True


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_stage_steps(*codes: str) -> list[dict[str, str]]:
    return [{"code": code} for code in codes]


def _build_source_statuses(
    selected_sources: list[str],
    results: list[dict] | None = None,
    running_sources: list[str] | tuple[str, ...] | set[str] | None = None,
) -> list[dict[str, str]]:
    result_by_source = {
        result.get("source_id"): result
        for result in (results or [])
        if result.get("source_id")
    }
    running = set(running_sources or [])
    statuses: list[dict[str, str]] = []

    for source_id in selected_sources:
        result = result_by_source.get(source_id)
        detail = ""
        if result:
            raw_status = result.get("status", "")
            if raw_status == "success":
                status = "completed"
            elif raw_status == "error":
                status = "failed"
                detail = "; ".join(result.get("errors") or [])
            else:
                status = raw_status or "pending"
        elif source_id in running:
            status = "running"
        else:
            status = "pending"

        statuses.append(
            {
                "source_id": source_id,
                "label": SOURCE_DISPLAY_NAMES.get(
                    source_id, source_id.replace("_", " ").title()
                ),
                "status": status,
                "detail": detail,
            }
        )

    return statuses


def _format_multi_source_summary(successful_sources: list[dict]) -> str:
    parts: list[str] = []
    for source in successful_sources:
        source_id = source.get("source_id", "")
        label = source.get("display_name") or SOURCE_DISPLAY_NAMES.get(
            source_id, source_id.replace("_", " ").title()
        )
        model = str(source.get("model") or "").strip()
        parts.append(f"{label} ({model})" if model else label)
    return " + ".join(parts)


def _format_multi_source_label(merge_mode: str, source_summary: str) -> str:
    prefix_by_mode = {
        "ai": "AI-merged multi-source transcription",
        "deterministic": "System-merged multi-source transcription",
        "single_source": "Single-source transcription",
        "raw": "Raw multi-source bundle",
    }
    label = prefix_by_mode.get(merge_mode, "Multi-source transcription")
    return f"{label} ({source_summary})" if source_summary else label


def _compute_stage_position(
    stage_steps: list[dict[str, str]] | None, stage_code: str | None
) -> tuple[int | None, int | None]:
    steps = stage_steps or []
    if not steps:
        return None, None
    total = len(steps)
    if not stage_code:
        return None, total
    for index, step in enumerate(steps, start=1):
        if step.get("code") == stage_code:
            return index, total
    return None, total


async def _push_task_update(
    task_id: str,
    *,
    progress: int | None = None,
    message: str | None = None,
    status: str | None = None,
    error: str | None = None,
    stage_code: str | None = None,
    stage_flow: str | None = None,
    stage_steps: list[dict[str, str]] | None = None,
    source_statuses: list[dict[str, str]] | None = None,
) -> None:
    task = tasks[task_id]
    previous_stage = task.get("stage_code")

    if status is not None:
        task["status"] = status
    if progress is not None:
        task["progress"] = progress
    if message is not None:
        task["message"] = message
    if error is not None:
        task["error"] = error
    if stage_flow is not None:
        task["stage_flow"] = stage_flow
    if stage_steps is not None:
        task["stage_steps"] = stage_steps
    if source_statuses is not None:
        task["source_statuses"] = source_statuses
    elif status == "error":
        _mark_unfinished_source_statuses_failed(
            task, error or message or "Task failed before this source finished."
        )
    if stage_code is not None:
        task["stage_code"] = stage_code
        if stage_code != previous_stage:
            task["stage_started_at"] = _utc_now_iso()

    stage_index, stage_total = _compute_stage_position(
        task.get("stage_steps"), task.get("stage_code")
    )
    task["stage_index"] = stage_index
    task["stage_total"] = stage_total

    save_tasks(tasks)
    await broadcast_task_update(task_id, task)


async def _run_local_transcription(
    *,
    url: str,
    task_id: str,
    local_backend: str,
    local_model_preset: str,
    local_model_id: str,
    local_language: str,
    stage_flow: str = "local",
    try_subtitles_first: bool = True,
    source_file_path: str = "",
    source_title: str = "",
) -> dict:
    install_constraints = backend_install_constraints(local_backend)
    dependency_stage_code = (
        install_constraints["warning_code"]
        if (
            not backend_dependencies_available(local_backend)
            and not install_constraints["auto_install_supported"]
            and install_constraints["warning_code"]
        )
        else "installing_local_backend"
    )
    stage_steps = _make_stage_steps(
        *(["checking_subtitles"] if try_subtitles_first else ["subtitle_skipped"]),
        *(["reading_uploaded_audio"] if source_file_path else ["downloading_audio"]),
        "preparing_audio",
        *(
            []
            if backend_dependencies_available(local_backend)
            else [dependency_stage_code]
        ),
        "loading_local_model",
        "transcribing_local_audio",
        "saving_transcript",
        "completed",
    )

    await _push_task_update(
        task_id,
        progress=30,
        message=(
            f"Using uploaded audio for local {local_backend} transcription..."
            if source_file_path
            else f"Downloading audio for local {local_backend} transcription..."
        ),
        stage_flow=stage_flow,
        stage_steps=stage_steps,
        stage_code="reading_uploaded_audio"
        if source_file_path
        else "downloading_audio",
    )

    if source_file_path:
        audio_path = source_file_path
        video_title = source_title or Path(source_file_path).stem or "uploaded-audio"
    else:
        audio_path, video_title = await video_processor.download_and_convert(
            url, TEMP_DIR
        )
    backend_audio_path = audio_path
    try:
        await _push_task_update(
            task_id,
            progress=48,
            message=f"Preparing audio for local {local_backend} transcription...",
            stage_code="preparing_audio",
        )
        backend_audio_path = ensure_backend_audio_file(
            audio_path, local_backend, TEMP_DIR
        )
        resolved_model_id = resolve_local_model_id(
            local_backend,
            local_model_preset,
            local_model_id,
        )

        if not backend_dependencies_available(local_backend):
            if not install_constraints["auto_install_supported"]:
                await _push_task_update(
                    task_id,
                    progress=60,
                    message=install_constraints["message"],
                    stage_code=dependency_stage_code,
                )
                raise LocalTranscriptionError(install_constraints["message"])
            await _push_task_update(
                task_id,
                progress=60,
                message=f"Installing local {local_backend} dependencies for model {resolved_model_id}...",
                stage_code=dependency_stage_code,
            )
            await asyncio.to_thread(ensure_backend_dependencies, local_backend)

        await _push_task_update(
            task_id,
            progress=68,
            message=f"Loading local {local_backend} model: {resolved_model_id}...",
            stage_code="loading_local_model",
        )

        transcriber, resolved_model_id = await asyncio.to_thread(
            prepare_local_transcriber,
            local_backend,
            local_model_preset,
            local_model_id,
        )

        await _push_task_update(
            task_id,
            progress=82,
            message=f"Transcribing with local {local_backend} model...",
            stage_code="transcribing_local_audio",
        )

        result = await transcriber.transcribe(
            backend_audio_path, language=local_language.strip()
        )
        await _push_task_update(
            task_id,
            progress=92,
            message="Saving transcript files...",
            stage_code="saving_transcript",
        )
        result["video_title"] = video_title or "unknown"
        result["resolved_model_id"] = resolved_model_id
        result["stage_steps"] = stage_steps
        result["stage_flow"] = stage_flow
        return result
    finally:
        for candidate in {audio_path, backend_audio_path}:
            if candidate and Path(candidate).exists():
                try:
                    Path(candidate).unlink(missing_ok=True)
                except Exception:
                    logger.debug(
                        "Could not remove temporary local transcription file: %s",
                        candidate,
                    )


@app.get("/")
async def read_root():
    """Return frontend page"""
    return FileResponse(str(PROJECT_ROOT / "static" / "index.html"))


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(
        str(PROJECT_ROOT / "static" / "favicon.svg"), media_type="image/svg+xml"
    )


@app.get("/api/settings")
async def read_settings():
    """Return current settings with credentials masked."""
    return get_masked_settings()


@app.post("/api/settings")
async def update_settings(request: Request):
    """Accept JSON body, merge with existing settings, persist to settings.json."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    save_settings(data)
    return get_masked_settings()


@app.post("/api/models")
async def list_models(
    base_url: str = Form(default=""),
    api_key: str = Form(default=""),
):
    """Proxy: fetch model list from any OpenAI-compatible API."""
    effective_key = api_key or os.getenv("OPENAI_API_KEY", "")
    effective_url = base_url.rstrip("/") or os.getenv("OPENAI_BASE_URL") or None

    if not effective_key:
        raise HTTPException(status_code=400, detail="API key is required")

    try:
        client = openai.OpenAI(api_key=effective_key, base_url=effective_url)
        resp = await asyncio.to_thread(client.models.list)
        models = [{"id": m.id, "name": getattr(m, "name", m.id)} for m in resp.data]
        # Sort by id for readability
        models.sort(key=lambda x: x["id"])
        return {"data": models}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/local-model-capabilities")
async def get_local_model_capabilities():
    return get_local_capabilities(importlib)


@app.post("/api/process-video")
async def process_video(
    url: str = Form(default=""),
    audio_file: UploadFile | None = File(default=None),
    summary_language: str = Form(default="zh"),
    api_key: str = Form(default=""),
    model_base_url: str = Form(default=""),
    model_id: str = Form(default=""),
    groq_api_key: str = Form(default=""),
    groq_model: str = Form(default=DEFAULT_GROQ_MODEL),
    groq_language: str = Form(default=""),
    groq_prompt: str = Form(default=""),
    include_timecodes: bool = Form(default=False),
    transcription_provider: str = Form(default="groq"),
    try_subtitles_first: bool = Form(default=True),
    use_local_fallback: bool = Form(default=False),
    local_backend: str = Form(default=DEFAULT_LOCAL_BACKEND),
    local_model_preset: str = Form(default="base"),
    local_model_id: str = Form(default=""),
    local_language: str = Form(default=""),
    local_api_base_url: str = Form(default=""),
    local_api_key: str = Form(default=""),
    local_api_model: str = Form(default=""),
    local_api_language: str = Form(default=""),
    local_api_prompt: str = Form(default=""),
    dual_local_transcription: bool = Form(default=False),
    dual_whisper_model_preset: str = Form(default="base"),
    dual_whisper_model_id: str = Form(default=""),
    dual_parakeet_model_preset: str = Form(default=""),
    dual_parakeet_model_id: str = Form(default=""),
    merge_use_ai: bool = Form(default=False),
    merge_api_key: str = Form(default=""),
    merge_base_url: str = Form(default=""),
    merge_model: str = Form(default=""),
    merge_prompt: str = Form(default=""),
    merge_reasoning_effort: str = Form(default=""),
    transcription_sources: str = Form(default=""),
    merge_mode: str = Form(default=""),
    merge_primary_source: str = Form(default=""),
):
    """
    Process video URL, return transcription task ID. Summary is generated at a separate endpoint upon user confirmation.
    """
    # Coerce Form/File defaults when called directly (e.g. in tests) rather than via HTTP
    if not isinstance(groq_api_key, str):
        groq_api_key = ""
    if not isinstance(groq_model, str):
        groq_model = DEFAULT_GROQ_MODEL
    if not isinstance(groq_language, str):
        groq_language = ""
    if not isinstance(groq_prompt, str):
        groq_prompt = ""
    if not isinstance(include_timecodes, bool):
        include_timecodes = False
    if not isinstance(transcription_provider, str):
        transcription_provider = "groq"
    if not isinstance(try_subtitles_first, bool):
        try_subtitles_first = True
    if not isinstance(use_local_fallback, bool):
        use_local_fallback = False
    if not isinstance(local_backend, str):
        local_backend = DEFAULT_LOCAL_BACKEND
    if not isinstance(local_model_preset, str):
        local_model_preset = "base"
    if not isinstance(local_model_id, str):
        local_model_id = ""
    if not isinstance(local_language, str):
        local_language = ""
    if not isinstance(local_api_base_url, str):
        local_api_base_url = ""
    if not isinstance(local_api_key, str):
        local_api_key = ""
    if not isinstance(local_api_model, str):
        local_api_model = ""
    if not isinstance(local_api_language, str):
        local_api_language = ""
    if not isinstance(local_api_prompt, str):
        local_api_prompt = ""
    if not isinstance(dual_local_transcription, bool):
        dual_local_transcription = False
    if not isinstance(dual_whisper_model_preset, str):
        dual_whisper_model_preset = "base"
    if not isinstance(dual_whisper_model_id, str):
        dual_whisper_model_id = ""
    if not isinstance(dual_parakeet_model_preset, str):
        dual_parakeet_model_preset = ""
    if not isinstance(dual_parakeet_model_id, str):
        dual_parakeet_model_id = ""
    if not isinstance(merge_use_ai, bool):
        merge_use_ai = False
    if not isinstance(merge_api_key, str):
        merge_api_key = ""
    if not isinstance(merge_base_url, str):
        merge_base_url = ""
    if not isinstance(merge_model, str):
        merge_model = ""
    if not isinstance(merge_prompt, str):
        merge_prompt = ""
    if not isinstance(merge_reasoning_effort, str):
        merge_reasoning_effort = ""
    if not isinstance(transcription_sources, str):
        transcription_sources = ""
    if not isinstance(merge_mode, str):
        merge_mode = ""
    if not isinstance(merge_primary_source, str):
        merge_primary_source = ""
    if not isinstance(model_id, str):
        model_id = ""
    if not isinstance(summary_language, str):
        summary_language = "zh"
    if not isinstance(api_key, str):
        api_key = ""
    if not isinstance(model_base_url, str):
        model_base_url = ""

    source_file_path = ""
    try:
        _ = (
            summary_language,
            api_key,
            model_base_url,
            model_id,
        )  # accepted for older clients
        # Credential fallback: form data → settings.json → env vars
        if not groq_api_key.strip():
            groq_api_key = get_credential("GROQ_API_KEY", "groq_api_key")
        normalized_url = (url or "").strip()
        using_uploaded_file = audio_file is not None and bool(
            getattr(audio_file, "filename", "") or ""
        )
        if not normalized_url and not using_uploaded_file:
            raise HTTPException(
                status_code=400,
                detail="Either a video URL or a local audio file is required.",
            )

        source_file_name = ""
        source_title = ""
        input_source_type = "url"
        if using_uploaded_file:
            (
                source_file_path,
                source_file_name,
                source_title,
            ) = await _persist_uploaded_audio_file(audio_file, TEMP_DIR)
            input_source_type = "file"

        # Check if already processing the same URL
        if normalized_url and normalized_url in processing_urls:
            # Find existing task
            for tid, task in tasks.items():
                if task.get("url") == normalized_url:
                    return {
                        "task_id": tid,
                        "message": "This video is already being processed, please wait...",
                    }

        # Generate unique task ID
        task_id = str(uuid.uuid4())

        # Mark URL as processing
        if normalized_url:
            processing_urls.add(normalized_url)

        # Initialize task state
        tasks[task_id] = {
            "status": "processing",
            "progress": 0,
            "message": "Starting audio processing..."
            if using_uploaded_file
            else "Starting video processing...",
            "stage_flow": None,
            "stage_steps": [],
            "stage_code": None,
            "stage_started_at": None,
            "stage_index": None,
            "stage_total": None,
            "script": None,
            "transcript": None,
            "transcript_source": None,
            "transcription_source": None,
            "transcription_provider_requested": (transcription_provider or "groq")
            .strip()
            .lower(),
            "transcription_provider_used": None,
            "local_backend_used": None,
            "local_model_used": None,
            "used_local_fallback": False,
            "transcription_sources": transcription_sources if transcription_sources.strip() else "",
            "warnings": [],
            "summary": None,
            "summary_status": "idle",
            "summary_progress": 0,
            "summary_path": None,
            "summary_markdown_path": None,
            "summary_html_path": None,
            "summary_text_path": None,
            "error": None,
            "url": normalized_url,  # Save URL for deduplication
            "input_source_type": input_source_type,
            "source_file_name": source_file_name,
        }
        save_tasks(tasks)

        # Create and track async task
        task = asyncio.create_task(
            process_video_task(
                task_id=task_id,
                url=normalized_url,
                groq_api_key=groq_api_key,
                groq_model=groq_model,
                groq_language=groq_language,
                groq_prompt=groq_prompt,
                include_timecodes=include_timecodes,
                transcription_provider=transcription_provider,
                try_subtitles_first=try_subtitles_first,
                use_local_fallback=use_local_fallback,
                local_backend=local_backend,
                local_model_preset=local_model_preset,
                local_model_id=local_model_id,
                local_language=local_language,
                local_api_base_url=local_api_base_url,
                local_api_key=local_api_key,
                local_api_model=local_api_model,
                local_api_language=local_api_language,
                local_api_prompt=local_api_prompt,
                source_file_path=source_file_path,
                source_file_name=source_file_name,
                source_title=source_title,
                dual_local_transcription=dual_local_transcription,
                dual_whisper_model_preset=dual_whisper_model_preset,
                dual_whisper_model_id=dual_whisper_model_id,
                dual_parakeet_model_preset=dual_parakeet_model_preset,
                dual_parakeet_model_id=dual_parakeet_model_id,
                merge_use_ai=merge_use_ai,
                merge_api_key=merge_api_key,
                merge_base_url=merge_base_url,
                merge_model=merge_model,
                merge_prompt=merge_prompt,
                merge_reasoning_effort=merge_reasoning_effort,
                transcription_sources_raw=transcription_sources,
                merge_mode_raw=merge_mode,
                merge_primary_source=merge_primary_source,
                summary_api_key=api_key,
                summary_base_url=model_base_url,
                summary_model=model_id,
            )
        )
        active_tasks[task_id] = task

        return {"task_id": task_id, "message": "Task created, processing..."}

    except HTTPException:
        if source_file_path:
            Path(source_file_path).unlink(missing_ok=True)
        raise
    except Exception as e:
        if source_file_path:
            Path(source_file_path).unlink(missing_ok=True)
        logger.error(f"Error processing video: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


async def process_video_task(
    task_id: str,
    url: str,
    groq_api_key: str = "",
    groq_model: str = DEFAULT_GROQ_MODEL,
    groq_language: str = "",
    groq_prompt: str = "",
    include_timecodes: bool = False,
    transcription_provider: str = "groq",
    try_subtitles_first: bool = True,
    use_local_fallback: bool = False,
    local_backend: str = DEFAULT_LOCAL_BACKEND,
    local_model_preset: str = "base",
    local_model_id: str = "",
    local_language: str = "",
    local_api_base_url: str = "",
    local_api_key: str = "",
    local_api_model: str = "",
    local_api_language: str = "",
    local_api_prompt: str = "",
    source_file_path: str = "",
    source_file_name: str = "",
    source_title: str = "",
    skip_subtitles: bool | None = None,
    dual_local_transcription: bool = False,
    dual_whisper_model_preset: str = "base",
    dual_whisper_model_id: str = "",
    dual_parakeet_model_preset: str = "",
    dual_parakeet_model_id: str = "",
    merge_use_ai: bool = False,
    merge_api_key: str = "",
    merge_base_url: str = "",
    merge_model: str = "",
    merge_prompt: str = "",
    merge_reasoning_effort: str = "",
    transcription_sources_raw: str = "",
    merge_mode_raw: str = "",
    merge_primary_source: str = "",
    summary_api_key: str = "",
    summary_base_url: str = "",
    summary_model: str = "",
):
    """Asynchronously process a transcription task."""
    try:
        requested_provider = (transcription_provider or "groq").strip().lower()
        if requested_provider not in {"groq", "local", "local_api"}:
            raise Exception(
                f"Unsupported transcription provider: {transcription_provider}"
            )
        using_uploaded_file = bool(source_file_path)
        display_source_name = source_file_name or (
            Path(source_file_path).name if source_file_path else ""
        )
        display_source_title = source_title or (
            Path(source_file_path).stem if source_file_path else ""
        )

        normalized_local_backend = (
            (local_backend or DEFAULT_LOCAL_BACKEND).strip().lower()
        )
        if normalized_local_backend not in {"whisper", "parakeet"}:
            raise Exception(f"Unsupported local backend: {local_backend}")

        # Resolve transcription sources: new multi-source or legacy provider/dual.
        # Hidden/stale UI fields can submit dual_local_transcription=true even
        # when the visible provider is Groq; only honor it for the Local provider.
        effective_dual_local = bool(dual_local_transcription) and requested_provider == "local"
        multi_sources = []
        effective_merge_mode = "system"
        if transcription_sources_raw and transcription_sources_raw.strip():
            try:
                multi_sources = parse_transcription_sources(transcription_sources_raw)
            except ValueError as e:
                raise Exception(str(e))
            effective_merge_mode = resolve_merge_mode(merge_use_ai, merge_mode_raw)
        elif effective_dual_local:
            multi_sources = ["local_whisper", "local_parakeet"]
            effective_merge_mode = resolve_merge_mode(merge_use_ai, merge_mode_raw)
        else:
            multi_sources = resolve_sources_from_legacy(
                transcription_provider=requested_provider,
                dual_local_transcription=False,
                local_backend=normalized_local_backend,
            )
            effective_merge_mode = "system"

        if not multi_sources:
            raise Exception("No transcription sources selected.")

        is_new_style_source = bool(transcription_sources_raw and transcription_sources_raw.strip())
        is_multi_source = len(multi_sources) > 1 and is_new_style_source
        _effective_merge_primary = (merge_primary_source or "").strip().lower()
        if is_multi_source and effective_merge_mode == "system" and not _effective_merge_primary:
            raise Exception(
                "A primary source is required for system merge when multiple transcription sources are selected."
            )
        if (
            is_multi_source
            and effective_merge_mode == "system"
            and _effective_merge_primary
            and _effective_merge_primary not in multi_sources
        ):
            raise Exception(
                "Primary source must be one of the selected transcription sources."
            )

        is_dual_mode = effective_dual_local and not is_new_style_source
        if is_multi_source and effective_merge_mode == "ai":
            preflight_creds = resolve_merge_credentials(
                form_merge_api_key=merge_api_key,
                form_merge_base_url=merge_base_url,
                form_merge_model=merge_model,
                form_merge_prompt=merge_prompt,
                form_merge_reasoning_effort=merge_reasoning_effort,
                form_summary_api_key=summary_api_key,
                form_summary_base_url=summary_base_url,
                form_summary_model=summary_model,
            )
            if not preflight_creds["api_key"]:
                raise Exception(
                    "AI merge was requested but no API key could be resolved. "
                    "Provide a merge API key or a summary API key, or set "
                    "OPENAI_API_KEY / MERGE_API_KEY."
                )

        explicit_platform_source = (
            is_new_style_source
            and "platform" in multi_sources
            and not using_uploaded_file
        )
        should_try_subtitles = bool(try_subtitles_first) and not using_uploaded_file
        if explicit_platform_source:
            should_try_subtitles = True
        elif is_multi_source and "platform" not in multi_sources:
            should_try_subtitles = False
        elif is_dual_mode:
            should_try_subtitles = False
        if skip_subtitles is not None and not explicit_platform_source:
            should_try_subtitles = (not skip_subtitles) and not using_uploaded_file

        normalized_local_language = (local_language or "").strip()
        if normalized_local_language.lower() in {
            "auto",
            "auto-detect",
            "autodetect",
            "detect",
        }:
            normalized_local_language = ""
        normalized_local_api_language = (local_api_language or "").strip()
        if normalized_local_api_language.lower() in {
            "auto",
            "auto-detect",
            "autodetect",
            "detect",
        }:
            normalized_local_api_language = ""

        local_resolved_model_id = resolve_local_model_id(
            normalized_local_backend,
            local_model_preset,
            local_model_id,
        )

        initial_stage_flow = requested_provider
        initial_stage_steps = _make_stage_steps(
            *(["checking_subtitles"] if should_try_subtitles else ["subtitle_skipped"]),
            "saving_transcript",
            "completed",
        )

        if requested_provider == "groq":
            initial_stage_steps = _make_stage_steps(
                *(
                    ["checking_subtitles"]
                    if should_try_subtitles
                    else ["subtitle_skipped"]
                ),
                *(
                    ["reading_uploaded_audio", "uploading_groq_audio"]
                    if using_uploaded_file
                    else ["resolving_groq_audio_url", "transcribing_groq_audio"]
                ),
                "saving_transcript",
                "completed",
            )
        elif requested_provider == "local_api":
            initial_stage_steps = _make_stage_steps(
                *(
                    ["checking_subtitles"]
                    if should_try_subtitles
                    else ["subtitle_skipped"]
                ),
                *(
                    ["reading_uploaded_audio"]
                    if using_uploaded_file
                    else ["downloading_audio"]
                ),
                "sending_local_api_audio",
                "saving_transcript",
                "completed",
            )
        elif requested_provider == "local":
            initial_stage_steps = _make_stage_steps(
                *(
                    ["checking_subtitles"]
                    if should_try_subtitles
                    else ["subtitle_skipped"]
                ),
                *(
                    ["reading_uploaded_audio"]
                    if using_uploaded_file
                    else ["downloading_audio"]
                ),
                "preparing_audio",
                "loading_local_model",
                "transcribing_local_audio",
                "saving_transcript",
                "completed",
            )

        await _push_task_update(
            task_id,
            status="processing",
            progress=10,
            message=(
                "Using uploaded audio file..."
                if using_uploaded_file
                else "Checking video subtitles..."
            ),
            stage_flow=initial_stage_flow,
            stage_steps=initial_stage_steps,
            stage_code=(
                "checking_subtitles"
                if should_try_subtitles
                else (
                    "reading_uploaded_audio"
                    if using_uploaded_file
                    else "subtitle_skipped"
                )
            ),
        )
        tasks[task_id].update(
            {
                "transcription_provider_requested": requested_provider,
                "transcription_provider_used": None,
                "local_backend_used": None,
                "local_model_used": None,
                "used_local_fallback": False,
                "warnings": [],
                "input_source_type": "file" if using_uploaded_file else "url",
                "source_file_name": display_source_name,
            }
        )
        save_tasks(tasks)
        await asyncio.sleep(0.1)

        if using_uploaded_file:
            subtitle_text, sub_title, sub_lang, subtitle_source = None, None, None, None
            await _push_task_update(
                task_id,
                progress=18,
                message=f"Uploaded audio ready; using {requested_provider} transcription...",
                stage_code="reading_uploaded_audio",
            )
        elif not should_try_subtitles:
            subtitle_text, sub_title, sub_lang, subtitle_source = None, None, None, None
            await _push_task_update(
                task_id,
                progress=18,
                message=f"Subtitle stage skipped; using {requested_provider} transcription...",
                stage_code="subtitle_skipped",
            )
        else:
            subtitle_result = await video_processor.fetch_subtitles(url, TEMP_DIR)
            if len(subtitle_result) == 3:
                subtitle_text, sub_title, sub_lang = subtitle_result
                subtitle_source = "youtube_manual_subtitles"
            else:
                subtitle_text, sub_title, sub_lang, subtitle_source = subtitle_result

        warnings: list[str] = []
        local_backend_used = None
        local_model_used = None
        used_local_fallback_flag = False
        multi_source_results: list[dict] = []
        _ms_video_title: list[str] = [display_source_title or sub_title or "unknown"]
        multi_source_merge_strategy = ""

        is_single_new_style = is_new_style_source and len(multi_sources) == 1
        single_source_id = multi_sources[0] if is_single_new_style else None

        if subtitle_text and not is_multi_source and not is_single_new_style:
            video_title = sub_title or "unknown"
            raw_script = subtitle_text
            detected_language = sub_lang or _extract_detected_language(raw_script)
            transcript_source = subtitle_source or "youtube_manual_subtitles"
            transcription_provider_used = "subtitles"
            await _push_task_update(
                task_id,
                progress=70,
                message=f"Subtitles found ({detected_language or 'unknown'}); saving transcript...",
                stage_flow="subtitles",
                stage_steps=_make_stage_steps(
                    "checking_subtitles", "saving_transcript", "completed"
                ),
                stage_code="saving_transcript",
            )
        elif is_multi_source:
            ms_stage_steps = _make_stage_steps(
                *(["checking_subtitles"] if ("platform" in multi_sources and not using_uploaded_file) else ["subtitle_skipped"]),
                *(
                    ["reading_uploaded_audio"]
                    if using_uploaded_file
                    else ["downloading_audio"]
                ),
                "preparing_audio",
                "transcribing_local_audio",
                "saving_transcript",
                "completed",
            )
            await _push_task_update(
                task_id,
                progress=10,
                message=f"Multi-source transcription ({', '.join(multi_sources)}): preparing...",
                stage_flow="multi_source",
                stage_steps=ms_stage_steps,
                stage_code=(
                    "reading_uploaded_audio"
                    if using_uploaded_file
                    else (
                        "checking_subtitles"
                        if ("platform" in multi_sources and not using_uploaded_file)
                        else "downloading_audio"
                    )
                ),
                source_statuses=_build_source_statuses(
                    multi_sources,
                    running_sources=(
                        ["platform"]
                        if "platform" in multi_sources and not using_uploaded_file
                        else []
                    ),
                ),
            )

            # Record platform result
            if "platform" in multi_sources:
                if subtitle_text:
                    platform_result = normalize_source_result(
                        "platform",
                        result=_apply_title_entity_corrections_to_result(
                            {"markdown": subtitle_text, "language": sub_lang or ""},
                            _ms_video_title[0],
                        ),
                    )
                    multi_source_results.append(platform_result)
                else:
                    platform_result = normalize_source_result(
                        "platform",
                        error="Platform subtitles requested but none found.",
                    )
                    multi_source_results.append(platform_result)

            # Prepare audio for non-platform sources
            non_platform_sources = [s for s in multi_sources if s != "platform"]
            audio_path = source_file_path
            backend_audio_files: list[str] = []

            if non_platform_sources:
                try:
                    if using_uploaded_file:
                        _ms_video_title[0] = display_source_title or sub_title or "unknown"
                    else:
                        audio_path, dl_title = await video_processor.download_and_convert(
                            url, TEMP_DIR
                        )
                        if dl_title:
                            _ms_video_title[0] = dl_title

                    await _push_task_update(
                        task_id, progress=25,
                        message="Preparing audio for multi-source transcription...",
                        stage_code="preparing_audio",
                        source_statuses=_build_source_statuses(
                            multi_sources, multi_source_results
                        ),
                    )

                    # Prepare audio files per backend type
                    needed_backends = set()
                    for s in non_platform_sources:
                        if s == "local_whisper":
                            needed_backends.add("whisper")
                        elif s == "local_parakeet":
                            needed_backends.add("parakeet")
                    # groq uses the raw audio path

                    audio_for_source: dict[str, str] = {}
                    for s in non_platform_sources:
                        if s in ("local_whisper", "local_parakeet"):
                            backend = "whisper" if s == "local_whisper" else "parakeet"
                            prepped = ensure_backend_audio_file(audio_path, backend, TEMP_DIR)
                            audio_for_source[s] = prepped
                            backend_audio_files.append(prepped)
                        else:
                            audio_for_source[s] = audio_path

                    if audio_path not in backend_audio_files:
                        backend_audio_files.append(audio_path)

                    await _push_task_update(
                        task_id, progress=40,
                        message=f"Running {len(non_platform_sources)} transcription source(s)...",
                        stage_code="transcribing_local_audio",
                        source_statuses=_build_source_statuses(
                            multi_sources,
                            multi_source_results,
                            running_sources=non_platform_sources,
                        ),
                    )

                    # Build coroutines for each source
                    async def _run_source(source_id: str) -> tuple[str, dict | None, str | None]:
                        try:
                            if source_id == "groq":
                                if not groq_api_key.strip():
                                    return source_id, None, "Groq API key is required."
                                groq = GroqURLTranscriber(api_key=groq_api_key, model=groq_model)
                                if hasattr(groq, "transcribe_file"):
                                    result = await groq.transcribe_file(
                                        audio_for_source[source_id],
                                        language=groq_language.strip(),
                                        prompt=_build_groq_prompt(groq_prompt, _ms_video_title[0]),
                                    )
                                else:
                                    audio_info = await video_processor.extract_audio_url(url)
                                    if audio_info.get("title"):
                                        _ms_video_title[0] = audio_info["title"]
                                    result = await groq.transcribe_url(
                                        audio_info["audio_url"],
                                        language=groq_language.strip(),
                                        prompt=_build_groq_prompt(groq_prompt, _ms_video_title[0]),
                                    )
                                return source_id, result, None

                            elif source_id in ("local_whisper", "local_parakeet"):
                                if source_id == "local_whisper":
                                    backend = "whisper"
                                    preset = dual_whisper_model_preset or local_model_preset
                                    mid = dual_whisper_model_id
                                else:
                                    backend = "parakeet"
                                    preset = dual_parakeet_model_preset
                                    mid = dual_parakeet_model_id
                                t, resolved = await asyncio.to_thread(
                                    prepare_local_transcriber, backend, preset, mid
                                )
                                lang = normalized_local_language
                                result = await t.transcribe(audio_for_source[source_id], language=lang)
                                result["_resolved_model"] = resolved
                                return source_id, result, None

                            return source_id, None, f"Unknown source: {source_id}"
                        except Exception as e:
                            return source_id, None, str(e)

                    source_tasks = [
                        asyncio.create_task(_run_source(s))
                        for s in non_platform_sources
                    ]
                    running_source_ids = set(non_platform_sources)
                    completed_count = 0
                    total_sources = max(1, len(non_platform_sources))

                    for completed in asyncio.as_completed(source_tasks):
                        gr = await completed
                        completed_count += 1
                        if isinstance(gr, Exception):
                            warnings.append(f"Source failed: {gr}")
                            continue
                        src_id, result, error = gr
                        if error:
                            sr = normalize_source_result(src_id, error=error)
                            warnings.append(f"{src_id} failed: {error}")
                        else:
                            result = _apply_title_entity_corrections_to_result(
                                result, _ms_video_title[0]
                            )
                            sr = normalize_source_result(src_id, result=result)
                        multi_source_results.append(sr)
                        running_source_ids.discard(src_id)
                        await _push_task_update(
                            task_id,
                            progress=40 + int((completed_count / total_sources) * 35),
                            message=(
                                f"Running {len(running_source_ids)} transcription "
                                f"source(s); {completed_count}/{total_sources} finished..."
                            ),
                            stage_code="transcribing_local_audio",
                            source_statuses=_build_source_statuses(
                                multi_sources,
                                multi_source_results,
                                running_sources=running_source_ids,
                            ),
                        )
                finally:
                    for candidate in set(backend_audio_files):
                        if candidate and Path(candidate).exists():
                            try:
                                Path(candidate).unlink(missing_ok=True)
                            except Exception:
                                logger.debug("Could not remove multi-source temp file: %s", candidate)

            if multi_source_results:
                source_order = {source_id: index for index, source_id in enumerate(multi_sources)}
                multi_source_results.sort(
                    key=lambda result: source_order.get(result.get("source_id"), len(source_order))
                )

            successful_sources = [r for r in multi_source_results if r["status"] == "success"]
            failed_sources = [r for r in multi_source_results if r["status"] == "error"]

            if not successful_sources:
                errors_detail = "; ".join(
                    f"{r['source_id']}: {'; '.join(r['errors'])}" for r in failed_sources
                )
                raise Exception(f"All selected transcription sources failed. {errors_detail}")

            for r in multi_source_results:
                warnings.extend(r.get("warnings") or [])

            # Determine final output based on merge mode
            if effective_merge_mode == "raw":
                await _push_task_update(
                    task_id, progress=88,
                    message="Building raw bundle...",
                    stage_code="saving_transcript",
                    source_statuses=_build_source_statuses(
                        multi_sources, multi_source_results
                    ),
                )
                short_id = task_id.replace("-", "")[:6]
                safe_title_ms = _sanitize_title_for_filename(_ms_video_title[0])

                for sr in successful_sources:
                    fname = f"{sr['source_id']}_{safe_title_ms}_{short_id}.md"
                    async with aiofiles.open(TEMP_DIR / fname, "w", encoding="utf-8") as f:
                        await f.write(sr.get("markdown", ""))
                    sr["artifact_filename"] = fname

                bundle = build_raw_bundle(
                    multi_source_results, multi_sources, warnings
                )
                raw_script = bundle["report_markdown"]
                detected_language = successful_sources[0].get("language", "") or _extract_detected_language(raw_script)
                transcript_source = "raw_bundle"
                transcription_provider_used = "multi_source"
                local_backend_used = "multi"
                local_model_used = _format_multi_source_summary(successful_sources)
                multi_source_merge_strategy = "raw"
                video_title = _ms_video_title[0]

                dual_metadata = {
                    "sources": [r["source_id"] for r in multi_source_results],
                    "successful": [r["source_id"] for r in successful_sources],
                    "failed": [r["source_id"] for r in failed_sources],
                    "merge_mode": "raw",
                    "source_summary": local_model_used,
                    "artifacts": bundle["artifacts"],
                }

            else:
                # system or ai merge
                merge_creds = resolve_merge_credentials(
                    form_merge_api_key=merge_api_key,
                    form_merge_base_url=merge_base_url,
                    form_merge_model=merge_model,
                    form_merge_prompt=merge_prompt,
                    form_merge_reasoning_effort=merge_reasoning_effort,
                    form_summary_api_key=summary_api_key,
                    form_summary_base_url=summary_base_url,
                    form_summary_model=summary_model,
                )

                # Write per-source sidecar files
                short_id = task_id.replace("-", "")[:6]
                safe_title_ms = _sanitize_title_for_filename(_ms_video_title[0])
                for sr in successful_sources:
                    fname = f"{sr['source_id']}_{safe_title_ms}_{short_id}.md"
                    async with aiofiles.open(TEMP_DIR / fname, "w", encoding="utf-8") as f:
                        await f.write(sr.get("markdown", ""))
                    sr["artifact_filename"] = fname

                if len(successful_sources) == 1:
                    merge_result = {"markdown": successful_sources[0].get("markdown", ""), "stats": {}}
                    merge_strategy = "single_source"
                    if _effective_merge_primary and _effective_merge_primary != successful_sources[0]["source_id"]:
                        warnings.append(
                            f"Primary source '{_effective_merge_primary}' was selected but failed or unavailable; "
                            f"using '{successful_sources[0]['source_id']}' instead."
                        )
                elif effective_merge_mode == "ai" and merge_creds["api_key"]:
                    try:
                        merge_result = await merge_transcripts_ai_n(
                            successful_sources,
                            api_key=merge_creds["api_key"],
                            base_url=merge_creds["base_url"],
                            model=merge_creds["model"],
                            prompt=merge_creds["prompt"],
                            reasoning_effort=merge_creds["reasoning_effort"],
                        )
                        merge_strategy = "ai"
                    except Exception as ai_err:
                        logger.warning("AI merge failed, falling back to deterministic: %s", ai_err)
                        warnings.append(f"AI merge failed ({ai_err}); used deterministic merge.")
                        primary = _resolve_primary(successful_sources, _effective_merge_primary, warnings)
                        merge_result = merge_transcripts_deterministic_n(successful_sources, primary)
                        merge_strategy = "deterministic"
                else:
                    primary = _resolve_primary(successful_sources, _effective_merge_primary, warnings)
                    merge_result = merge_transcripts_deterministic_n(successful_sources, primary)
                    merge_strategy = "deterministic"
                    if effective_merge_mode == "ai":
                        warnings.append("AI merge requested but no credentials provided; used deterministic merge instead.")

                await _push_task_update(
                    task_id, progress=88,
                    message="Saving multi-source transcription files...",
                    stage_code="saving_transcript",
                    source_statuses=_build_source_statuses(
                        multi_sources, multi_source_results
                    ),
                )

                raw_script = merge_result["markdown"]
                detected_language = successful_sources[0].get("language", "") or _extract_detected_language(raw_script)
                transcript_source = "multi_source_merged"
                transcription_provider_used = "multi_source"
                local_backend_used = "multi"
                local_model_used = _format_multi_source_summary(successful_sources)
                multi_source_merge_strategy = merge_strategy
                video_title = _ms_video_title[0]

                dual_metadata = {
                    "sources": [r["source_id"] for r in multi_source_results],
                    "successful": [r["source_id"] for r in successful_sources],
                    "failed": [r["source_id"] for r in failed_sources],
                    "merge_mode": merge_strategy,
                    "source_summary": local_model_used,
                    "merge_stats": merge_result.get("stats", {}),
                    "artifacts": {sr["source_id"]: sr["artifact_filename"] for sr in successful_sources if sr.get("artifact_filename")},
                }

                if failed_sources:
                    warnings.extend(f"{r['source_id']} failed: {'; '.join(r.get('errors', []))}" for r in failed_sources)

        elif is_single_new_style:
            # Single source selected via new API (transcription_sources_raw)
            src_id = single_source_id
            src_result = None

            if src_id == "platform":
                if subtitle_text:
                    video_title = sub_title or "unknown"
                    _ms_video_title[0] = video_title
                    src_result = normalize_source_result(
                        "platform",
                        result=_apply_title_entity_corrections_to_result(
                            {"markdown": subtitle_text, "language": sub_lang or ""},
                            _ms_video_title[0],
                        ),
                    )
                    transcription_provider_used = "platform"
                else:
                    raise Exception("Platform subtitles requested but none found.")
            else:
                # Non-platform single source: download audio and transcribe
                ss_stage_steps = _make_stage_steps(
                    *(
                        ["reading_uploaded_audio"]
                        if using_uploaded_file
                        else ["downloading_audio"]
                    ),
                    "preparing_audio",
                    "transcribing_local_audio",
                    "saving_transcript",
                    "completed",
                )
                await _push_task_update(
                    task_id, progress=10,
                    message=f"Single-source transcription ({src_id}): preparing...",
                    stage_flow="multi_source",
                    stage_steps=ss_stage_steps,
                    stage_code=(
                        "reading_uploaded_audio" if using_uploaded_file else "downloading_audio"
                    ),
                )

                audio_path = source_file_path
                if using_uploaded_file:
                    _ms_video_title[0] = display_source_title or "unknown"
                else:
                    audio_path, dl_title = await video_processor.download_and_convert(url, TEMP_DIR)
                    if dl_title:
                        _ms_video_title[0] = dl_title

                await _push_task_update(
                    task_id, progress=25,
                    message=f"Preparing audio for {src_id}...",
                    stage_code="preparing_audio",
                )

                src_result = None
                if src_id == "groq":
                    if not groq_api_key:
                        raise Exception("Groq source selected but no API key provided.")
                    groq_transcriber = GroqURLTranscriber(groq_api_key, groq_model)
                    if using_uploaded_file or hasattr(groq_transcriber, "transcribe_file"):
                        groq_result = await groq_transcriber.transcribe_file(
                            audio_path,
                            language=groq_language,
                            prompt=_build_groq_prompt(groq_prompt, _ms_video_title[0]),
                        )
                    else:
                        extract = await video_processor.extract_audio_url(url)
                        groq_url = extract.get("audio_url", "")
                        if extract.get("title"):
                            _ms_video_title[0] = extract["title"]
                        groq_result = await groq_transcriber.transcribe_url(
                            groq_url,
                            language=groq_language,
                            prompt=_build_groq_prompt(groq_prompt, _ms_video_title[0]),
                        )
                    src_result = normalize_source_result(
                        "groq",
                        result=_apply_title_entity_corrections_to_result(
                            {
                                "markdown": groq_result.get("markdown", ""),
                                "language": groq_result.get("language", ""),
                                "raw": groq_result.get("raw", {}),
                            },
                            _ms_video_title[0],
                        ),
                    )
                    local_model_used = groq_model or "whisper-large-v3"
                    transcription_provider_used = "groq"
                    if audio_path and Path(audio_path).exists():
                        try:
                            Path(audio_path).unlink(missing_ok=True)
                        except Exception:
                            pass
                elif src_id in ("local_whisper", "local_parakeet"):
                    backend = "whisper" if src_id == "local_whisper" else "parakeet"
                    prepped = ensure_backend_audio_file(audio_path, backend, TEMP_DIR)
                    try:
                        preset = local_model_preset
                        mid = ""
                        if src_id == "local_whisper":
                            preset = dual_whisper_model_preset or local_model_preset
                            mid = dual_whisper_model_id
                        else:
                            preset = dual_parakeet_model_preset
                            mid = dual_parakeet_model_id
                        transcriber, resolved = await asyncio.to_thread(
                            prepare_local_transcriber, backend, preset, mid
                        )
                        local_result = await transcriber.transcribe(
                            prepped, language=normalized_local_language.strip()
                        )
                        src_result = normalize_source_result(
                            src_id,
                            result=_apply_title_entity_corrections_to_result(
                                {
                                    "markdown": local_result.get("markdown", ""),
                                    "language": local_result.get("language", ""),
                                    "raw": local_result.get("raw", {}),
                                },
                                _ms_video_title[0],
                            ),
                        )
                        local_model_used = resolved
                        local_backend_used = backend
                        transcription_provider_used = "local"
                    finally:
                        if prepped and Path(prepped).exists():
                            try:
                                Path(prepped).unlink(missing_ok=True)
                            except Exception:
                                pass
                        if audio_path and Path(audio_path).exists() and audio_path != source_file_path:
                            try:
                                Path(audio_path).unlink(missing_ok=True)
                            except Exception:
                                pass
                else:
                    raise Exception(f"Unsupported single source: {src_id}")

                if src_id != "platform":
                    await _push_task_update(
                        task_id, progress=88,
                        message="Saving transcription...",
                        stage_code="saving_transcript",
                    )

            if src_result is None:
                raise Exception(f"Single source '{src_id}' returned no transcript result.")

            video_title = _ms_video_title[0] or video_title
            if effective_merge_mode == "raw":
                short_id = task_id.replace("-", "")[:6]
                safe_title_ms = _sanitize_title_for_filename(video_title)
                artifact_name = f"{src_result['source_id']}_{safe_title_ms}_{short_id}.md"
                async with aiofiles.open(
                    TEMP_DIR / artifact_name, "w", encoding="utf-8"
                ) as f:
                    await f.write(src_result.get("markdown", ""))
                src_result["artifact_filename"] = artifact_name
                multi_source_results = [src_result]
                bundle = build_raw_bundle(multi_source_results, [src_id], warnings)
                raw_script = bundle["report_markdown"]
                transcript_source = "raw_bundle"
            else:
                raw_script = src_result.get("markdown", "")
                transcript_source = (
                    subtitle_source or "youtube_manual_subtitles"
                    if src_id == "platform"
                    else src_id
                )

            detected_language = src_result.get("language", "") or _extract_detected_language(raw_script)

        elif is_dual_mode and requested_provider == "local":
            dual_stage_steps = _make_stage_steps(
                "subtitle_skipped",
                *(
                    ["reading_uploaded_audio"]
                    if using_uploaded_file
                    else ["downloading_audio"]
                ),
                "preparing_audio",
                "transcribing_local_audio",
                "saving_transcript",
                "completed",
            )
            await _push_task_update(
                task_id,
                progress=10,
                message="Dual local transcription: preparing audio...",
                stage_flow="dual_local",
                stage_steps=dual_stage_steps,
                stage_code=(
                    "reading_uploaded_audio"
                    if using_uploaded_file
                    else "downloading_audio"
                ),
            )

            audio_path = source_file_path
            video_title = display_source_title or "unknown"
            if not using_uploaded_file:
                audio_path, video_title = await video_processor.download_and_convert(
                    url, TEMP_DIR
                )

            backend_audio_files = []
            try:
                await _push_task_update(
                    task_id,
                    progress=25,
                    message="Preparing audio for dual transcription...",
                    stage_code="preparing_audio",
                )
                whisper_audio = ensure_backend_audio_file(
                    audio_path, "whisper", TEMP_DIR
                )
                parakeet_audio = ensure_backend_audio_file(
                    audio_path, "parakeet", TEMP_DIR
                )
                backend_audio_files = [whisper_audio, parakeet_audio]
                if audio_path not in backend_audio_files:
                    backend_audio_files.append(audio_path)

                dual_whisper_preset = dual_whisper_model_preset or local_model_preset
                dual_whisper_mid = dual_whisper_model_id
                dual_parakeet_preset = dual_parakeet_model_preset
                dual_parakeet_mid = dual_parakeet_model_id

                await _push_task_update(
                    task_id,
                    progress=40,
                    message="Running Whisper + Parakeet concurrently...",
                    stage_code="transcribing_local_audio",
                )

                whisper_transcriber, whisper_resolved = await asyncio.to_thread(
                    prepare_local_transcriber, "whisper",
                    dual_whisper_preset, dual_whisper_mid,
                )
                parakeet_transcriber, parakeet_resolved = await asyncio.to_thread(
                    prepare_local_transcriber, "parakeet",
                    dual_parakeet_preset, dual_parakeet_mid,
                )

                dual_results = await asyncio.gather(
                    whisper_transcriber.transcribe(
                        whisper_audio, language=normalized_local_language.strip()
                    ),
                    parakeet_transcriber.transcribe(
                        parakeet_audio, language=normalized_local_language.strip()
                    ),
                    return_exceptions=True,
                )
                backend_names = ["whisper", "parakeet"]
                for i, result in enumerate(dual_results):
                    if isinstance(result, Exception):
                        raise Exception(
                            f"{backend_names[i]} transcription failed: {result}"
                        )
                whisper_result, parakeet_result = dual_results

                use_ai_merge = bool(merge_use_ai)
                merge_creds = resolve_merge_credentials(
                    form_merge_api_key=merge_api_key,
                    form_merge_base_url=merge_base_url,
                    form_merge_model=merge_model,
                    form_merge_prompt=merge_prompt,
                    form_merge_reasoning_effort=merge_reasoning_effort,
                    form_summary_api_key=summary_api_key,
                    form_summary_base_url=summary_base_url,
                    form_summary_model=summary_model,
                )

                merge_strategy = "deterministic"
                if use_ai_merge:
                    if not merge_creds["api_key"]:
                        logger.warning(
                            "AI merge requested but no credentials available; falling back to deterministic merge."
                        )
                        warnings.append("AI merge requested but no credentials provided; used deterministic merge instead.")
                    else:
                        try:
                            merge_result = await merge_transcripts_ai(
                                whisper_result,
                                parakeet_result,
                                api_key=merge_creds["api_key"],
                                base_url=merge_creds["base_url"],
                                model=merge_creds["model"],
                                prompt=merge_creds["prompt"],
                                reasoning_effort=merge_creds["reasoning_effort"],
                            )
                            merge_strategy = "ai"
                        except Exception as ai_err:
                            logger.warning(
                                "AI merge failed, falling back to deterministic: %s", ai_err
                            )
                            warnings.append(
                                f"AI merge failed ({ai_err}); used deterministic merge."
                            )
                            merge_result = merge_transcripts_deterministic(
                                whisper_result, parakeet_result
                            )

                if merge_strategy == "deterministic":
                    merge_result = merge_transcripts_deterministic(
                        whisper_result, parakeet_result
                    )

                merged_markdown = merge_result["markdown"]
                merge_stats = merge_result.get("stats", {})

                await _push_task_update(
                    task_id,
                    progress=88,
                    message="Saving dual transcription files...",
                    stage_code="saving_transcript",
                )

                short_id = task_id.replace("-", "")[:6]
                safe_title_dual = _sanitize_title_for_filename(video_title)

                whisper_sidecar = f"whisper_{safe_title_dual}_{short_id}.md"
                parakeet_sidecar = f"parakeet_{safe_title_dual}_{short_id}.md"
                async with aiofiles.open(
                    TEMP_DIR / whisper_sidecar, "w", encoding="utf-8"
                ) as f:
                    await f.write(whisper_result.get("markdown", ""))
                async with aiofiles.open(
                    TEMP_DIR / parakeet_sidecar, "w", encoding="utf-8"
                ) as f:
                    await f.write(parakeet_result.get("markdown", ""))

                raw_script = merged_markdown
                detected_language = (
                    whisper_result.get("language")
                    or parakeet_result.get("language")
                    or _extract_detected_language(merged_markdown, normalized_local_language)
                )
                transcript_source = "dual_local_merged"
                transcription_provider_used = "dual_local"
                local_backend_used = "dual"
                local_model_used = f"whisper={whisper_resolved}+parakeet={parakeet_resolved}"
                dual_metadata = {
                    "whisper_model": whisper_resolved,
                    "parakeet_model": parakeet_resolved,
                    "whisper_language": whisper_result.get("language", ""),
                    "parakeet_language": parakeet_result.get("language", ""),
                    "whisper_warnings": list(whisper_result.get("warnings") or []),
                    "parakeet_warnings": list(parakeet_result.get("warnings") or []),
                    "merge_strategy": merge_strategy,
                    "merge_stats": merge_stats,
                    "whisper_sidecar": whisper_sidecar,
                    "parakeet_sidecar": parakeet_sidecar,
                }
                warnings.extend(whisper_result.get("warnings") or [])
                warnings.extend(parakeet_result.get("warnings") or [])
            finally:
                for candidate in set(backend_audio_files):
                    if candidate and Path(candidate).exists():
                        try:
                            Path(candidate).unlink(missing_ok=True)
                        except Exception:
                            logger.debug(
                                "Could not remove dual temp file: %s", candidate
                            )

        elif requested_provider == "local":
            local_result = await _run_local_transcription(
                url=url,
                task_id=task_id,
                local_backend=normalized_local_backend,
                local_model_preset=local_model_preset,
                local_model_id=local_model_id,
                local_language=normalized_local_language,
                stage_flow="local",
                try_subtitles_first=should_try_subtitles,
                source_file_path=source_file_path,
                source_title=display_source_title,
            )
            video_title = local_result["video_title"]
            raw_script = local_result["markdown"]
            detected_language = local_result.get(
                "language"
            ) or _extract_detected_language(raw_script, normalized_local_language)
            transcript_source = "local_audio_file"
            transcription_provider_used = "local"
            warnings = list(local_result.get("warnings") or [])
            local_backend_used = normalized_local_backend
            local_model_used = (
                local_result.get("resolved_model_id") or local_resolved_model_id
            )
        elif requested_provider == "local_api":
            if not local_api_base_url.strip():
                raise Exception(
                    "Local API base URL is required when provider is local_api."
                )
            if not local_api_model.strip():
                raise Exception(
                    "Local API model is required when provider is local_api."
                )

            await _push_task_update(
                task_id,
                progress=30,
                message=(
                    "Using uploaded audio for local API transcription..."
                    if using_uploaded_file
                    else "Downloading audio for local API transcription..."
                ),
                stage_flow="local_api",
                stage_steps=_make_stage_steps(
                    *(
                        ["checking_subtitles"]
                        if should_try_subtitles
                        else ["subtitle_skipped"]
                    ),
                    *(
                        ["reading_uploaded_audio"]
                        if using_uploaded_file
                        else ["downloading_audio"]
                    ),
                    "sending_local_api_audio",
                    "saving_transcript",
                    "completed",
                ),
                stage_code="reading_uploaded_audio"
                if using_uploaded_file
                else "downloading_audio",
            )

            audio_file = ""
            try:
                if using_uploaded_file:
                    audio_file = source_file_path
                    video_title = display_source_title or "uploaded-audio"
                else:
                    (
                        audio_file,
                        video_title,
                    ) = await video_processor.download_and_convert(url, TEMP_DIR)
                await _push_task_update(
                    task_id,
                    progress=68,
                    message=f"Sending audio to local API model: {local_api_model.strip()}...",
                    stage_code="sending_local_api_audio",
                )

                local_api = LocalAPITranscriber(
                    base_url=local_api_base_url,
                    api_key=local_api_key,
                    model=local_api_model,
                )
                local_api_result = await local_api.transcribe_file(
                    audio_file,
                    language=normalized_local_api_language,
                    prompt=(local_api_prompt or "").strip(),
                )
            except LocalAPITranscriptionError:
                raise
            finally:
                if audio_file:
                    try:
                        Path(audio_file).unlink(missing_ok=True)
                    except Exception:
                        logger.debug(
                            "Could not remove temporary local API transcription file: %s",
                            audio_file,
                        )

            raw_script = local_api_result["markdown"]
            detected_language = local_api_result.get(
                "language"
            ) or _extract_detected_language(raw_script, normalized_local_api_language)
            transcript_source = "local_api_audio_file"
            transcription_provider_used = "local_api"
            local_model_used = local_api_model.strip()
        else:
            if not groq_api_key.strip():
                raise Exception(
                    "Groq API key is required when provider is Groq and subtitles are unavailable."
                )

            groq = GroqURLTranscriber(api_key=groq_api_key, model=groq_model)
            groq_result = None
            video_title = display_source_title or "unknown"
            last_media_error = None
            transcript_source = "groq_audio_url"
            groq_failure_for_local_fallback = None

            try:
                if using_uploaded_file:
                    await _push_task_update(
                        task_id,
                        progress=30,
                        message="Preparing uploaded audio for Groq transcription...",
                        stage_flow="groq_file_upload",
                        stage_steps=_make_stage_steps(
                            "reading_uploaded_audio",
                            "uploading_groq_audio",
                            "saving_transcript",
                            "completed",
                        ),
                        stage_code="reading_uploaded_audio",
                    )
                    await _push_task_update(
                        task_id,
                        progress=58,
                        message="Uploading audio file to Groq transcription...",
                        stage_code="uploading_groq_audio",
                    )
                    groq_result = await groq.transcribe_file(
                        source_file_path,
                        language=groq_language.strip(),
                        prompt=_build_groq_prompt(
                            groq_prompt, display_source_title or video_title
                        ),
                    )
                    transcript_source = "groq_audio_file"
                else:
                    await _push_task_update(
                        task_id,
                        progress=25,
                        message="No subtitles found; resolving audio URL for Groq...",
                        stage_flow="groq",
                        stage_steps=_make_stage_steps(
                            *(
                                ["checking_subtitles"]
                                if should_try_subtitles
                                else ["subtitle_skipped"]
                            ),
                            "resolving_groq_audio_url",
                            "transcribing_groq_audio",
                            "saving_transcript",
                            "completed",
                        ),
                        stage_code="resolving_groq_audio_url",
                    )

                    for attempt in range(2):
                        if attempt:
                            await _push_task_update(
                                task_id,
                                progress=42,
                                message="Groq could not read the previous audio URL; refreshing URL and retrying...",
                                stage_code="retrying_groq_audio_url",
                            )

                        audio_info = await video_processor.extract_audio_url(url)
                        video_title = audio_info.get("title") or video_title

                        await _push_task_update(
                            task_id,
                            progress=45 if attempt == 0 else 55,
                            message="Audio URL resolved; sending to Groq transcription...",
                            stage_code="transcribing_groq_audio",
                        )

                        try:
                            groq_result = await groq.transcribe_url(
                                audio_info["audio_url"],
                                language=groq_language.strip(),
                                prompt=_build_groq_prompt(groq_prompt, video_title),
                            )
                            break
                        except GroqTranscriptionError as e:
                            if _is_groq_media_retrieval_error(e):
                                last_media_error = e
                                if attempt == 0:
                                    logger.warning(
                                        "Groq could not read audio URL, refreshing and retrying: %s",
                                        e,
                                    )
                                    continue
                                break
                            raise

                    if groq_result is None and last_media_error:
                        audio_file = ""
                        try:
                            await _push_task_update(
                                task_id,
                                progress=62,
                                message="Groq could not fetch the media URL; downloading audio locally for file upload...",
                                stage_flow="groq_file_fallback",
                                stage_steps=_make_stage_steps(
                                    *(
                                        ["checking_subtitles"]
                                        if should_try_subtitles
                                        else ["subtitle_skipped"]
                                    ),
                                    "resolving_groq_audio_url",
                                    "retrying_groq_audio_url",
                                    "downloading_groq_fallback_audio",
                                    "uploading_groq_fallback_audio",
                                    "saving_transcript",
                                    "completed",
                                ),
                                stage_code="downloading_groq_fallback_audio",
                            )

                            if hasattr(video_processor, "download_audio_for_upload"):
                                download_for_upload = (
                                    video_processor.download_audio_for_upload
                                )
                            else:
                                download_for_upload = (
                                    video_processor.download_and_convert
                                )
                            audio_file, downloaded_title = await download_for_upload(
                                url, TEMP_DIR
                            )
                            video_title = downloaded_title or video_title

                            await _push_task_update(
                                task_id,
                                progress=72,
                                message="Uploading local audio file to Groq transcription...",
                                stage_code="uploading_groq_fallback_audio",
                            )

                            groq_result = await groq.transcribe_file(
                                audio_file,
                                language=groq_language.strip(),
                                prompt=_build_groq_prompt(groq_prompt, video_title),
                            )
                            transcript_source = "groq_audio_file"
                        except Exception as file_error:
                            raise GroqTranscriptionError(
                                _format_groq_transcription_error(
                                    last_media_error,
                                    retried=True,
                                    file_fallback_error=file_error,
                                )
                            ) from file_error
                        finally:
                            if audio_file:
                                try:
                                    Path(audio_file).unlink(missing_ok=True)
                                except Exception:
                                    logger.debug(
                                        "Could not remove temporary audio file: %s",
                                        audio_file,
                                    )

                if groq_result is None:
                    raise GroqTranscriptionError(
                        _format_groq_transcription_error(
                            last_media_error
                            or GroqTranscriptionError(
                                "Unknown Groq transcription error"
                            ),
                            retried=bool(last_media_error),
                        )
                    )
            except GroqTranscriptionError as groq_error:
                if use_local_fallback and _is_groq_error_eligible_for_local_fallback(
                    groq_error
                ):
                    groq_failure_for_local_fallback = groq_error
                else:
                    raise

            if groq_failure_for_local_fallback is not None:
                await _push_task_update(
                    task_id,
                    progress=78,
                    message=f"Groq failed; falling back to local {normalized_local_backend} transcription...",
                    stage_flow="groq_local_file_fallback"
                    if using_uploaded_file
                    else "groq_local_fallback",
                    stage_steps=_make_stage_steps(
                        *(
                            ["checking_subtitles"]
                            if should_try_subtitles
                            else ["subtitle_skipped"]
                        ),
                        *(
                            ["reading_uploaded_audio", "uploading_groq_audio"]
                            if using_uploaded_file
                            else ["resolving_groq_audio_url", "retrying_groq_audio_url"]
                        ),
                        "switching_to_local_fallback",
                        *(
                            ["reading_uploaded_audio"]
                            if using_uploaded_file
                            else ["downloading_audio"]
                        ),
                        "preparing_audio",
                        "loading_local_model",
                        "transcribing_local_audio",
                        "saving_transcript",
                        "completed",
                    ),
                    stage_code="switching_to_local_fallback",
                )

                local_result = await _run_local_transcription(
                    url=url,
                    task_id=task_id,
                    local_backend=normalized_local_backend,
                    local_model_preset=local_model_preset,
                    local_model_id=local_model_id,
                    local_language=normalized_local_language,
                    stage_flow="groq_local_file_fallback"
                    if using_uploaded_file
                    else "groq_local_fallback",
                    try_subtitles_first=should_try_subtitles,
                    source_file_path=source_file_path,
                    source_title=display_source_title,
                )
                video_title = local_result["video_title"]
                raw_script = local_result["markdown"]
                detected_language = local_result.get(
                    "language"
                ) or _extract_detected_language(raw_script, normalized_local_language)
                transcript_source = "local_audio_file"
                transcription_provider_used = "local"
                warnings = list(local_result.get("warnings") or [])
                local_backend_used = normalized_local_backend
                local_model_used = (
                    local_result.get("resolved_model_id") or local_resolved_model_id
                )
                used_local_fallback_flag = True
            else:
                raw_script = groq_result["markdown"]
                detected_language = groq_result.get(
                    "language"
                ) or _extract_detected_language(raw_script, groq_language)
                transcription_provider_used = "groq"

        raw_script = _apply_title_entity_corrections(raw_script or "", video_title)

        if not include_timecodes:
            raw_script = format_transcript_without_timecodes(raw_script)

        await _push_task_update(
            task_id,
            progress=92,
            message="Saving transcript files...",
            stage_code="saving_transcript",
        )

        short_id = task_id.replace("-", "")[:6]
        safe_title = _sanitize_title_for_filename(video_title)
        raw_md_filename = f"raw_{safe_title}_{short_id}.md"
        raw_md_path = TEMP_DIR / raw_md_filename
        source_reference = _source_reference_line(url, display_source_name)
        raw_content = (raw_script or "").strip() + f"\n\n{source_reference}\n"
        async with aiofiles.open(raw_md_path, "w", encoding="utf-8") as f:
            await f.write(raw_content)

        source_labels = {
            "youtube_manual_subtitles": "YouTube manual subtitles",
            "youtube_auto_subtitles": "YouTube automatic subtitles",
            "groq_audio_url": f"Groq URL transcription ({groq_model or DEFAULT_GROQ_MODEL})",
            "groq_audio_file": f"Groq file upload transcription ({groq_model or DEFAULT_GROQ_MODEL})",
            "local_audio_file": (
                f"Local {normalized_local_backend.capitalize()} transcription ({local_model_used or local_resolved_model_id})"
                if transcription_provider_used == "local"
                else "Local transcription"
            ),
            "local_api_audio_file": f"Local API transcription ({local_model_used or local_api_model.strip()})",
            "dual_local_merged": (
                f"Dual local Whisper+Parakeet transcription ({local_model_used})"
                if local_backend_used == "dual"
                else "Dual local transcription"
            ),
            "multi_source_merged": _format_multi_source_label(
                multi_source_merge_strategy, local_model_used or ""
            ),
            "raw_bundle": f"Raw bundle ({len(multi_source_results)} sources)",
        }
        source_label = source_labels.get(transcript_source, transcript_source)
        warnings = _dedupe_messages(warnings)
        warning_block = ""
        if warnings:
            warning_block = "**Warnings:** " + " | ".join(warnings) + "\n\n"
        script_with_title = (
            f"# {video_title}\n\n"
            f"**Transcription Source:** {source_label}\n\n"
            f"{warning_block}"
            f"{(raw_script or '').strip()}\n\n"
            f"{source_reference}\n"
        )

        script_filename = f"transcript_{safe_title}_{short_id}.md"
        script_path = TEMP_DIR / script_filename
        async with aiofiles.open(script_path, "w", encoding="utf-8") as f:
            await f.write(script_with_title)

        task_result = {
            "status": "completed",
            "progress": 100,
            "message": "Transcript complete. You can now generate the AI summary.",
            "stage_flow": tasks[task_id].get("stage_flow"),
            "stage_steps": tasks[task_id].get("stage_steps") or [],
            "stage_code": "completed",
            "stage_started_at": _utc_now_iso(),
            "video_title": video_title,
            "script": script_with_title,
            "transcript": script_with_title,
            "summary": None,
            "script_path": str(script_path),
            "raw_script_file": raw_md_filename,
            "summary_path": None,
            "summary_markdown_path": None,
            "summary_html_path": None,
            "summary_text_path": None,
            "summary_status": "idle",
            "summary_progress": 0,
            "short_id": short_id,
            "safe_title": safe_title,
            "detected_language": detected_language,
            "transcript_source": transcript_source,
            "transcription_source": transcript_source,
            "transcription_provider_requested": requested_provider,
            "transcription_provider_used": transcription_provider_used,
            "local_backend_used": local_backend_used,
            "local_model_used": local_model_used,
            "used_local_fallback": used_local_fallback_flag,
            "warnings": warnings,
            "groq_model": groq_model
            if transcript_source in {"groq_audio_url", "groq_audio_file"}
            else None,
            "url": url,
            "source_file_name": display_source_name,
            "input_source_type": "file" if using_uploaded_file else "url",
        }
        if is_dual_mode and locals().get("dual_metadata"):
            task_result["dual_transcription_results"] = dual_metadata
        if is_multi_source and locals().get("dual_metadata"):
            task_result["multi_source_results"] = dual_metadata
            task_result["source_statuses"] = _build_source_statuses(
                multi_sources, multi_source_results
            )
        task_result["stage_index"], task_result["stage_total"] = (
            _compute_stage_position(
                task_result["stage_steps"],
                task_result["stage_code"],
            )
        )

        tasks[task_id].update(task_result)
        save_tasks(tasks)
        logger.info(f"Task complete, broadcasting final status: {task_id}")
        await broadcast_task_update(task_id, tasks[task_id])
        logger.info(f"Final status broadcast: {task_id}")

        processing_urls.discard(url)
        if task_id in active_tasks:
            del active_tasks[task_id]
        if using_uploaded_file and source_file_path:
            Path(source_file_path).unlink(missing_ok=True)
    except GroqTranscriptionError as e:
        logger.error(f"Task {task_id} Groq transcription failed: {str(e)}")
        processing_urls.discard(url)
        if task_id in active_tasks:
            del active_tasks[task_id]
        if using_uploaded_file and source_file_path:
            Path(source_file_path).unlink(missing_ok=True)
        await _push_task_update(
            task_id,
            status="error",
            error=str(e),
            message=f"Groq transcription failed: {str(e)}",
            stage_code="error",
        )
    except Exception as e:
        logger.error(f"Task {task_id} processing failed: {str(e)}")
        processing_urls.discard(url)
        if task_id in active_tasks:
            del active_tasks[task_id]
        if using_uploaded_file and source_file_path:
            Path(source_file_path).unlink(missing_ok=True)
        await _push_task_update(
            task_id,
            status="error",
            error=str(e),
            message=f"Processing failed: {str(e)}",
            stage_code="error",
        )


@app.post("/api/summarize-transcript")
async def summarize_transcript(
    task_id: str = Form(...),
    summary_language: str = Form(default="en"),
    api_key: str = Form(default=""),
    model_base_url: str = Form(default=""),
    model_id: str = Form(default=""),
    output_format: str = Form(default="markdown"),
    summary_prompt: str = Form(default=""),
    reasoning_effort: str = Form(default=""),
):
    """
    Start a summary job only after the user confirms sending the transcript.
    """
    if not isinstance(summary_language, str):
        summary_language = "en"
    if not isinstance(api_key, str):
        api_key = ""
    if not isinstance(model_base_url, str):
        model_base_url = ""
    if not isinstance(model_id, str):
        model_id = ""
    if not isinstance(output_format, str):
        output_format = "markdown"
    if not isinstance(summary_prompt, str):
        summary_prompt = ""
    if not isinstance(reasoning_effort, str):
        reasoning_effort = ""

    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task_data = tasks[task_id]
    transcript = task_data.get("transcript") or task_data.get("script")
    if not transcript:
        raise HTTPException(
            status_code=400,
            detail="This task does not have a transcript available for summarization",
        )

    normalized_format = (output_format or "markdown").strip().lower()
    if normalized_format not in {"markdown", "html", "txt", "both"}:
        raise HTTPException(
            status_code=400, detail="output_format must be markdown, html, txt, or both"
        )

    normalized_summary_prompt = (
        summary_prompt.strip() if isinstance(summary_prompt, str) else ""
    )
    if len(normalized_summary_prompt) > 4000:
        raise HTTPException(
            status_code=400, detail="summary_prompt must be 4000 characters or less"
        )

    normalized_reasoning_effort = (
        reasoning_effort.strip().lower() if isinstance(reasoning_effort, str) else ""
    )
    if normalized_reasoning_effort not in {
        "",
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    }:
        raise HTTPException(
            status_code=400,
            detail="reasoning_effort must be none, minimal, low, medium, high, or xhigh",
        )

    if not api_key.strip():
        api_key = get_credential("OPENAI_API_KEY", "openai_api_key")
    if not model_base_url.strip():
        model_base_url = get_credential("OPENAI_BASE_URL", "openai_base_url")

    if not api_key.strip() and not summarizer.is_available():
        tasks[task_id].update(
            {
                "summary_status": "idle",
                "summary_error": "Summary provider API key is required.",
                "message": "Summary provider API key is required. Configure summary provider settings and try again.",
            }
        )
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])
        raise HTTPException(
            status_code=400,
            detail="Summary provider API key is required. Configure summary provider settings and try again.",
        )

    if task_id in active_summary_tasks and not active_summary_tasks[task_id].done():
        return tasks[task_id]

    tasks[task_id].update(
        {
            "summary_status": "processing",
            "summary_progress": 5,
            "summary_error": None,
            "message": "Generating summary...",
            "summary_language": summary_language,
            "summary_model": model_id or None,
            "summary_output_format": normalized_format,
            "summary_prompt": normalized_summary_prompt,
            "summary_reasoning_effort": normalized_reasoning_effort or None,
        }
    )
    save_tasks(tasks)
    await broadcast_task_update(task_id, tasks[task_id])

    task = asyncio.create_task(
        summarize_transcript_task(
            task_id=task_id,
            summary_language=summary_language,
            api_key=api_key,
            model_base_url=model_base_url,
            model_id=model_id,
            output_format=normalized_format,
            summary_prompt=normalized_summary_prompt,
            reasoning_effort=normalized_reasoning_effort,
        )
    )
    active_summary_tasks[task_id] = task

    return tasks[task_id]


async def summarize_transcript_task(
    task_id: str,
    summary_language: str,
    api_key: str,
    model_base_url: str,
    model_id: str,
    output_format: str,
    summary_prompt: str = "",
    reasoning_effort: str = "",
):
    try:
        task_data = tasks[task_id]
        transcript = task_data.get("transcript") or task_data.get("script")
        video_title = task_data.get("video_title") or "Video Summary"

        tasks[task_id].update(
            {
                "summary_status": "processing",
                "summary_progress": 25,
                "message": "Sending transcript to summary provider...",
            }
        )
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])

        if api_key.strip():
            effective_url = model_base_url.rstrip("/") or None
            request_summarizer = Summarizer(
                api_key=api_key,
                base_url=effective_url,
                model=model_id or None,
                reasoning_effort=reasoning_effort or None,
            )
            logger.info(
                f"дЅїз”Ёе‰Ќз«ЇжЏђдѕ›зљ„ж‘и¦ЃAPIпјЊbase_url={effective_url}, model={model_id or 'default'}"
            )
        else:
            request_summarizer = summarizer

        summary = await request_summarizer.summarize(
            transcript,
            summary_language,
            video_title,
            custom_prompt=summary_prompt,
        )
        summary_with_source = (
            summary.rstrip() + f"\n\nsource: {task_data.get('url', '')}\n"
        )

        tasks[task_id].update(
            {
                "summary_progress": 80,
                "message": "Saving summary files...",
            }
        )
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])

        short_id = task_data.get("short_id") or task_id.replace("-", "")[:6]
        safe_title = task_data.get("safe_title") or _sanitize_title_for_filename(
            video_title
        )

        summary_markdown_path = None
        summary_html_path = None
        summary_text_path = None

        if output_format in {"markdown", "both"}:
            summary_filename = f"summary_{safe_title}_{short_id}.md"
            summary_markdown_path = TEMP_DIR / summary_filename
            async with aiofiles.open(summary_markdown_path, "w", encoding="utf-8") as f:
                await f.write(summary_with_source)

        if output_format == "txt":
            summary_text_filename = f"summary_{safe_title}_{short_id}.txt"
            summary_text_path = TEMP_DIR / summary_text_filename
            async with aiofiles.open(summary_text_path, "w", encoding="utf-8") as f:
                await f.write(_markdown_to_plain_text(summary_with_source) + "\n")

        if output_format in {"html", "both"}:
            html_filename = f"summary_{safe_title}_{short_id}.html"
            summary_html_path = TEMP_DIR / html_filename
            html_content = render_summary_html(
                title=video_title,
                summary_markdown=summary_with_source,
                source_url=task_data.get("url", ""),
            )
            async with aiofiles.open(summary_html_path, "w", encoding="utf-8") as f:
                await f.write(html_content)

        tasks[task_id].update(
            {
                "summary": summary_with_source,
                "summary_status": "completed",
                "summary_progress": 100,
                "summary_language": summary_language,
                "summary_model": model_id or None,
                "summary_reasoning_effort": reasoning_effort or None,
                "summary_output_format": output_format,
                "summary_path": str(summary_markdown_path or summary_text_path)
                if (summary_markdown_path or summary_text_path)
                else None,
                "summary_markdown_path": str(summary_markdown_path)
                if summary_markdown_path
                else None,
                "summary_html_path": str(summary_html_path)
                if summary_html_path
                else None,
                "summary_text_path": str(summary_text_path)
                if summary_text_path
                else None,
                "message": "Files ready.",
            }
        )
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])

    except Exception as e:
        logger.error(f"ж‘и¦Ѓз”џж€ђе¤±иґҐ: {e}")
        tasks[task_id].update(
            {
                "summary_status": "error",
                "summary_error": str(e),
                "message": f"ж‘и¦Ѓз”џж€ђе¤±иґҐ: {e}",
            }
        )
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])
    finally:
        active_summary_tasks.pop(task_id, None)


@app.get("/api/task-status/{task_id}")
async def get_task_status(task_id: str):
    """
    Get task status
    """
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    return tasks[task_id]


@app.get("/api/task-stream/{task_id}")
async def task_stream(task_id: str):
    """
    SSE real-time task status stream
    """
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_generator():
        # Create task-specific queue
        queue = asyncio.Queue()

        # Add queue to connection list
        if task_id not in sse_connections:
            sse_connections[task_id] = []
        sse_connections[task_id].append(queue)

        try:
            # Send current state immediately
            current_task = tasks.get(task_id, {})
            yield f"data: {json.dumps(current_task, ensure_ascii=False)}\n\n"

            # Continuously monitor status updates
            while True:
                try:
                    # Wait for status updates, send heartbeat every 30 seconds timeout
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {data}\n\n"

                    # If task completes or fails, end stream
                    task_data = json.loads(data)
                    summary_status = task_data.get("summary_status")
                    if task_data.get("status") == "error":
                        break
                    if summary_status == "processing":
                        continue
                    if summary_status in ["completed", "error"]:
                        break
                    if task_data.get("status") == "completed":
                        break

                except asyncio.TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield f"data: {json.dumps({'type': 'heartbeat'}, ensure_ascii=False)}\n\n"

        except asyncio.CancelledError:
            logger.info(f"SSE connection cancelled for task {task_id}")
        except Exception as e:
            logger.error(f"SSE stream exception: {e}")
        finally:
            # Clean up connections
            if task_id in sse_connections and queue in sse_connections[task_id]:
                sse_connections[task_id].remove(queue)
                if not sse_connections[task_id]:
                    del sse_connections[task_id]

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET",
            "Access-Control-Allow-Headers": "Cache-Control",
        },
    )


@app.get("/api/download/{filename}")
async def download_file(filename: str):
    """
    Download file directly from temp directory (simplified approach)
    """
    try:
        # Check file extension safety
        suffix = Path(filename).suffix.lower()
        if suffix not in {".md", ".html", ".txt"}:
            raise HTTPException(
                status_code=400,
                detail="Only .md, .html, and .txt files are supported for download",
            )

        # Check filename format (prevent directory traversal attacks)
        if ".." in filename or "/" in filename or "\\" in filename:
            raise HTTPException(status_code=400, detail="Invalid filename format")

        file_path = TEMP_DIR / filename
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File not found")

        if suffix == ".html":
            media_type = "text/html"
        elif suffix == ".txt":
            media_type = "text/plain; charset=utf-8"
        else:
            media_type = "text/markdown"

        return FileResponse(file_path, filename=filename, media_type=media_type)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to download file: {e}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


@app.delete("/api/task/{task_id}")
async def delete_task(task_id: str):
    """
    Cancel and delete task
    """
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    # If task is still running, cancel it first
    if task_id in active_tasks:
        task = active_tasks[task_id]
        if not task.done():
            task.cancel()
            logger.info(f"Task {task_id} has been cancelled")
        del active_tasks[task_id]

    if task_id in active_summary_tasks:
        summary_task = active_summary_tasks[task_id]
        if not summary_task.done():
            summary_task.cancel()
            logger.info(f"summary task {task_id} cancelled")
        del active_summary_tasks[task_id]

    # Remove from processing URLs list
    task_url = tasks[task_id].get("url")
    if task_url:
        processing_urls.discard(task_url)

    # Delete task record
    del tasks[task_id]
    save_tasks(tasks)
    return {"message": "Task cancelled and deleted"}


@app.get("/api/tasks/active")
async def get_active_tasks():
    """
    Get current active task list (for debugging)
    """
    active_count = len(active_tasks)
    summary_count = len(active_summary_tasks)
    processing_count = len(processing_urls)
    return {
        "active_tasks": active_count,
        "active_summary_tasks": summary_count,
        "processing_urls": processing_count,
        "task_ids": list(active_tasks.keys()),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
