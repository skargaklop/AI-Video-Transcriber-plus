from fastapi import FastAPI, HTTPException, Form, File, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import os
import tempfile
import asyncio
import logging
import importlib
from datetime import datetime, timezone
from pathlib import Path
import aiofiles
import uuid
import json
import re
import openai

from video_processor import VideoProcessor
from groq_transcriber import DEFAULT_GROQ_MODEL, GroqTranscriptionError, GroqURLTranscriber
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
from settings import get_credential, get_masked_settings, load_settings, save_settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# 初始化处理器
video_processor = VideoProcessor()
summarizer = Summarizer()

# 存储任务状态 - 使用文件持久化
import json
import threading

TASKS_FILE = TEMP_DIR / "tasks.json"
tasks_lock = threading.Lock()

def load_tasks():
    """加载任务状态"""
    try:
        if TASKS_FILE.exists():
            with open(TASKS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except:
        pass
    return {}

def save_tasks(tasks_data):
    """保存任务状态"""
    try:
        with tasks_lock:
            with open(TASKS_FILE, 'w', encoding='utf-8') as f:
                json.dump(tasks_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存任务状态失败: {e}")

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
            changed = True

        if task.get("summary_status") == "processing":
            task["summary_status"] = "error"
            task["summary_progress"] = 0
            task["summary_error"] = summary_error
            if task.get("status") != "error":
                task["message"] = summary_error
            changed = True

    return changed


async def broadcast_task_update(task_id: str, task_data: dict):
    """向所有连接的SSE客户端广播任务状态更新"""
    logger.info(f"广播任务更新: {task_id}, 状态: {task_data.get('status')}, 连接数: {len(sse_connections.get(task_id, []))}")
    if task_id in sse_connections:
        connections_to_remove = []
        for queue in sse_connections[task_id]:
            try:
                await queue.put(json.dumps(task_data, ensure_ascii=False))
                logger.debug(f"消息已发送到队列: {task_id}")
            except Exception as e:
                logger.warning(f"发送消息到队列失败: {e}")
                connections_to_remove.append(queue)
        
        # 移除断开的连接
        for queue in connections_to_remove:
            sse_connections[task_id].remove(queue)
        
        # 如果没有连接了，清理该任务的连接列表
        if not sse_connections[task_id]:
            del sse_connections[task_id]

# 启动时加载任务状态
tasks = load_tasks()
if _mark_incomplete_tasks_as_interrupted(tasks):
    save_tasks(tasks)
# 存储正在处理的URL，防止重复处理
processing_urls = set()
# 存储活跃的任务对象，用于控制和取消
active_tasks = {}
active_summary_tasks = {}
# 存储SSE连接，用于实时推送状态更新
sse_connections = {}

def _sanitize_title_for_filename(title: str) -> str:
    """将视频标题清洗为安全的文件名片段。"""
    if not title:
        return "untitled"
    # 仅保留字母数字、下划线、连字符与空格
    safe = re.sub(r"[^\w\-\s]", "", title)
    # 压缩空白并转为下划线
    safe = re.sub(r"\s+", "_", safe).strip("._-")
    # 最长限制，避免过长文件名问题
    return safe[:80] or "untitled"


async def _persist_uploaded_audio_file(upload: UploadFile, output_dir: Path) -> tuple[str, str, str]:
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
    if not transcript_text:
        return fallback or ""

    for line in transcript_text.splitlines():
        if "**Detected Language:**" in line:
            return line.split(":", 1)[-1].strip()
    return fallback or ""

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


def _compute_stage_position(stage_steps: list[dict[str, str]] | None, stage_code: str | None) -> tuple[int | None, int | None]:
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
    if stage_code is not None:
        task["stage_code"] = stage_code
        if stage_code != previous_stage:
            task["stage_started_at"] = _utc_now_iso()

    stage_index, stage_total = _compute_stage_position(task.get("stage_steps"), task.get("stage_code"))
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
        if (not backend_dependencies_available(local_backend) and not install_constraints["auto_install_supported"] and install_constraints["warning_code"])
        else "installing_local_backend"
    )
    stage_steps = _make_stage_steps(
        *(
            ["checking_subtitles"] if try_subtitles_first else ["subtitle_skipped"]
        ),
        *(
            ["reading_uploaded_audio"]
            if source_file_path
            else ["downloading_audio"]
        ),
        "preparing_audio",
        *([] if backend_dependencies_available(local_backend) else [dependency_stage_code]),
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
        stage_code="reading_uploaded_audio" if source_file_path else "downloading_audio",
    )

    if source_file_path:
        audio_path = source_file_path
        video_title = source_title or Path(source_file_path).stem or "uploaded-audio"
    else:
        audio_path, video_title = await video_processor.download_and_convert(url, TEMP_DIR)
    backend_audio_path = audio_path
    try:
        await _push_task_update(
            task_id,
            progress=48,
            message=f"Preparing audio for local {local_backend} transcription...",
            stage_code="preparing_audio",
        )
        backend_audio_path = ensure_backend_audio_file(audio_path, local_backend, TEMP_DIR)
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

        result = await transcriber.transcribe(backend_audio_path, language=local_language.strip())
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
                    logger.debug("Could not remove temporary local transcription file: %s", candidate)

@app.get("/")
async def read_root():
    """返回前端页面"""
    return FileResponse(str(PROJECT_ROOT / "static" / "index.html"))

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(str(PROJECT_ROOT / "static" / "favicon.svg"), media_type="image/svg+xml")

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
    api_key:  str = Form(default=""),
):
    """Proxy: fetch model list from any OpenAI-compatible API."""
    effective_key = api_key or os.getenv("OPENAI_API_KEY", "")
    effective_url = base_url.rstrip("/") or os.getenv("OPENAI_BASE_URL") or None

    if not effective_key:
        raise HTTPException(status_code=400, detail="API key is required")

    try:
        client = openai.OpenAI(api_key=effective_key, base_url=effective_url)
        resp   = await asyncio.to_thread(client.models.list)
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
    api_key:       str = Form(default=""),
    model_base_url: str = Form(default=""),
    model_id:      str = Form(default=""),
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
):
    """
    处理视频链接，返回转录任务ID。摘要在单独端点中由用户确认后生成。
    """
    source_file_path = ""
    try:
        _ = (summary_language, api_key, model_base_url, model_id)  # accepted for older clients
        # Credential fallback: form data → settings.json → env vars
        if not groq_api_key.strip():
            groq_api_key = get_credential("GROQ_API_KEY", "groq_api_key")
        normalized_url = (url or "").strip()
        using_uploaded_file = audio_file is not None and bool(getattr(audio_file, "filename", "") or "")
        if not normalized_url and not using_uploaded_file:
            raise HTTPException(status_code=400, detail="Either a video URL or a local audio file is required.")

        source_file_name = ""
        source_title = ""
        input_source_type = "url"
        if using_uploaded_file:
            source_file_path, source_file_name, source_title = await _persist_uploaded_audio_file(audio_file, TEMP_DIR)
            input_source_type = "file"

        # 检查是否已经在处理相同的URL
        if normalized_url and normalized_url in processing_urls:
            # 查找现有任务
            for tid, task in tasks.items():
                if task.get("url") == normalized_url:
                    return {"task_id": tid, "message": "该视频正在处理中，请等待..."}
            
        # 生成唯一任务ID
        task_id = str(uuid.uuid4())
        
        # 标记URL为正在处理
        if normalized_url:
            processing_urls.add(normalized_url)
        
        # 初始化任务状态
        tasks[task_id] = {
            "status": "processing",
            "progress": 0,
            "message": "Starting audio processing..." if using_uploaded_file else "开始处理视频...",
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
            "transcription_provider_requested": (transcription_provider or "groq").strip().lower(),
            "transcription_provider_used": None,
            "local_backend_used": None,
            "local_model_used": None,
            "used_local_fallback": False,
            "warnings": [],
            "summary": None,
            "summary_status": "idle",
            "summary_progress": 0,
            "summary_path": None,
            "summary_markdown_path": None,
            "summary_html_path": None,
            "summary_text_path": None,
            "error": None,
            "url": normalized_url,  # 保存URL用于去重
            "input_source_type": input_source_type,
            "source_file_name": source_file_name,
        }
        save_tasks(tasks)
        
        # 创建并跟踪异步任务
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
            )
        )
        active_tasks[task_id] = task
        
        return {"task_id": task_id, "message": "任务已创建，正在处理中..."}
        
    except HTTPException:
        if source_file_path:
            Path(source_file_path).unlink(missing_ok=True)
        raise
    except Exception as e:
        if source_file_path:
            Path(source_file_path).unlink(missing_ok=True)
        logger.error(f"处理视频时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")

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
):
    """Asynchronously process a transcription task."""
    try:
        requested_provider = (transcription_provider or "groq").strip().lower()
        if requested_provider not in {"groq", "local", "local_api"}:
            raise Exception(f"Unsupported transcription provider: {transcription_provider}")
        using_uploaded_file = bool(source_file_path)
        display_source_name = source_file_name or (Path(source_file_path).name if source_file_path else "")
        display_source_title = source_title or (Path(source_file_path).stem if source_file_path else "")

        normalized_local_backend = (local_backend or DEFAULT_LOCAL_BACKEND).strip().lower()
        if normalized_local_backend not in {"whisper", "parakeet"}:
            raise Exception(f"Unsupported local backend: {local_backend}")

        should_try_subtitles = bool(try_subtitles_first) and not using_uploaded_file
        if skip_subtitles is not None:
            should_try_subtitles = (not skip_subtitles) and not using_uploaded_file

        normalized_local_language = (local_language or "").strip()
        if normalized_local_language.lower() in {"auto", "auto-detect", "autodetect", "detect"}:
            normalized_local_language = ""
        normalized_local_api_language = (local_api_language or "").strip()
        if normalized_local_api_language.lower() in {"auto", "auto-detect", "autodetect", "detect"}:
            normalized_local_api_language = ""

        local_resolved_model_id = resolve_local_model_id(
            normalized_local_backend,
            local_model_preset,
            local_model_id,
        )

        initial_stage_flow = requested_provider
        initial_stage_steps = _make_stage_steps(
            *(
                ["checking_subtitles"]
                if should_try_subtitles
                else ["subtitle_skipped"]
            ),
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
                else ("reading_uploaded_audio" if using_uploaded_file else "subtitle_skipped")
            ),
        )
        tasks[task_id].update({
            "transcription_provider_requested": requested_provider,
            "transcription_provider_used": None,
            "local_backend_used": None,
            "local_model_used": None,
            "used_local_fallback": False,
            "warnings": [],
            "input_source_type": "file" if using_uploaded_file else "url",
            "source_file_name": display_source_name,
        })
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

        if subtitle_text:
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
                stage_steps=_make_stage_steps("checking_subtitles", "saving_transcript", "completed"),
                stage_code="saving_transcript",
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
            detected_language = local_result.get("language") or _extract_detected_language(raw_script, normalized_local_language)
            transcript_source = "local_audio_file"
            transcription_provider_used = "local"
            warnings = list(local_result.get("warnings") or [])
            local_backend_used = normalized_local_backend
            local_model_used = local_result.get("resolved_model_id") or local_resolved_model_id
        elif requested_provider == "local_api":
            if not local_api_base_url.strip():
                raise Exception("Local API base URL is required when provider is local_api.")
            if not local_api_model.strip():
                raise Exception("Local API model is required when provider is local_api.")

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
                    *(["checking_subtitles"] if should_try_subtitles else ["subtitle_skipped"]),
                    *(["reading_uploaded_audio"] if using_uploaded_file else ["downloading_audio"]),
                    "sending_local_api_audio",
                    "saving_transcript",
                    "completed",
                ),
                stage_code="reading_uploaded_audio" if using_uploaded_file else "downloading_audio",
            )

            audio_file = ""
            try:
                if using_uploaded_file:
                    audio_file = source_file_path
                    video_title = display_source_title or "uploaded-audio"
                else:
                    audio_file, video_title = await video_processor.download_and_convert(url, TEMP_DIR)
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
                        logger.debug("Could not remove temporary local API transcription file: %s", audio_file)

            raw_script = local_api_result["markdown"]
            detected_language = local_api_result.get("language") or _extract_detected_language(raw_script, normalized_local_api_language)
            transcript_source = "local_api_audio_file"
            transcription_provider_used = "local_api"
            local_model_used = local_api_model.strip()
        else:
            if not groq_api_key.strip():
                raise Exception("Groq API key is required when provider is Groq and subtitles are unavailable.")

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
                        prompt=groq_prompt.strip(),
                    )
                    transcript_source = "groq_audio_file"
                else:
                    await _push_task_update(
                        task_id,
                        progress=25,
                        message="No subtitles found; resolving audio URL for Groq...",
                        stage_flow="groq",
                        stage_steps=_make_stage_steps(
                            *(["checking_subtitles"] if should_try_subtitles else ["subtitle_skipped"]),
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
                                prompt=groq_prompt.strip(),
                            )
                            break
                        except GroqTranscriptionError as e:
                            if _is_groq_media_retrieval_error(e):
                                last_media_error = e
                                if attempt == 0:
                                    logger.warning("Groq could not read audio URL, refreshing and retrying: %s", e)
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
                                    *(["checking_subtitles"] if should_try_subtitles else ["subtitle_skipped"]),
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
                                download_for_upload = video_processor.download_audio_for_upload
                            else:
                                download_for_upload = video_processor.download_and_convert
                            audio_file, downloaded_title = await download_for_upload(url, TEMP_DIR)
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
                                prompt=groq_prompt.strip(),
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
                                    logger.debug("Could not remove temporary audio file: %s", audio_file)

                if groq_result is None:
                    raise GroqTranscriptionError(
                        _format_groq_transcription_error(
                            last_media_error or GroqTranscriptionError("Unknown Groq transcription error"),
                            retried=bool(last_media_error),
                        )
                    )
            except GroqTranscriptionError as groq_error:
                if use_local_fallback and _is_groq_error_eligible_for_local_fallback(groq_error):
                    groq_failure_for_local_fallback = groq_error
                else:
                    raise

            if groq_failure_for_local_fallback is not None:
                await _push_task_update(
                    task_id,
                    progress=78,
                    message=f"Groq failed; falling back to local {normalized_local_backend} transcription...",
                    stage_flow="groq_local_file_fallback" if using_uploaded_file else "groq_local_fallback",
                    stage_steps=_make_stage_steps(
                        *(["checking_subtitles"] if should_try_subtitles else ["subtitle_skipped"]),
                        *(
                            ["reading_uploaded_audio", "uploading_groq_audio"]
                            if using_uploaded_file
                            else ["resolving_groq_audio_url", "retrying_groq_audio_url"]
                        ),
                        "switching_to_local_fallback",
                        *(["reading_uploaded_audio"] if using_uploaded_file else ["downloading_audio"]),
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
                    stage_flow="groq_local_file_fallback" if using_uploaded_file else "groq_local_fallback",
                    try_subtitles_first=should_try_subtitles,
                    source_file_path=source_file_path,
                    source_title=display_source_title,
                )
                video_title = local_result["video_title"]
                raw_script = local_result["markdown"]
                detected_language = local_result.get("language") or _extract_detected_language(raw_script, normalized_local_language)
                transcript_source = "local_audio_file"
                transcription_provider_used = "local"
                warnings = list(local_result.get("warnings") or [])
                local_backend_used = normalized_local_backend
                local_model_used = local_result.get("resolved_model_id") or local_resolved_model_id
                used_local_fallback_flag = True
            else:
                raw_script = groq_result["markdown"]
                detected_language = groq_result.get("language") or _extract_detected_language(raw_script, groq_language)
                transcription_provider_used = "groq"

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
        }
        source_label = source_labels.get(transcript_source, transcript_source)
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
            "groq_model": groq_model if transcript_source in {"groq_audio_url", "groq_audio_file"} else None,
            "url": url,
            "source_file_name": display_source_name,
            "input_source_type": "file" if using_uploaded_file else "url",
        }
        task_result["stage_index"], task_result["stage_total"] = _compute_stage_position(
            task_result["stage_steps"],
            task_result["stage_code"],
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
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="任务不存在")

    task_data = tasks[task_id]
    transcript = task_data.get("transcript") or task_data.get("script")
    if not transcript:
        raise HTTPException(status_code=400, detail="该任务还没有可摘要的转录文本")

    normalized_format = (output_format or "markdown").strip().lower()
    if normalized_format not in {"markdown", "html", "txt", "both"}:
        raise HTTPException(status_code=400, detail="output_format must be markdown, html, txt, or both")

    normalized_summary_prompt = summary_prompt.strip() if isinstance(summary_prompt, str) else ""
    if len(normalized_summary_prompt) > 4000:
        raise HTTPException(status_code=400, detail="summary_prompt must be 4000 characters or less")

    normalized_reasoning_effort = reasoning_effort.strip().lower() if isinstance(reasoning_effort, str) else ""
    if normalized_reasoning_effort not in {"", "none", "minimal", "low", "medium", "high", "xhigh"}:
        raise HTTPException(status_code=400, detail="reasoning_effort must be none, minimal, low, medium, high, or xhigh")

    if not api_key.strip():
        api_key = get_credential("OPENAI_API_KEY", "openai_api_key")
    if not model_base_url.strip():
        model_base_url = get_credential("OPENAI_BASE_URL", "openai_base_url")

    if not api_key.strip() and not summarizer.is_available():
        tasks[task_id].update({
            "summary_status": "idle",
            "summary_error": "Summary provider API key is required.",
            "message": "Summary provider API key is required. Configure summary provider settings and try again.",
        })
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])
        raise HTTPException(
            status_code=400,
            detail="Summary provider API key is required. Configure summary provider settings and try again.",
        )

    if task_id in active_summary_tasks and not active_summary_tasks[task_id].done():
        return tasks[task_id]

    tasks[task_id].update({
        "summary_status": "processing",
        "summary_progress": 5,
        "summary_error": None,
        "message": "Generating summary...",
        "summary_language": summary_language,
        "summary_model": model_id or None,
        "summary_output_format": normalized_format,
        "summary_prompt": normalized_summary_prompt,
        "summary_reasoning_effort": normalized_reasoning_effort or None,
    })
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

        tasks[task_id].update({
            "summary_status": "processing",
            "summary_progress": 25,
            "message": "Sending transcript to summary provider...",
        })
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
            logger.info(f"дЅїз”Ёе‰Ќз«ЇжЏђдѕ›зљ„ж‘и¦ЃAPIпјЊbase_url={effective_url}, model={model_id or 'default'}")
        else:
            request_summarizer = summarizer

        summary = await request_summarizer.summarize(
            transcript,
            summary_language,
            video_title,
            custom_prompt=summary_prompt,
        )
        summary_with_source = summary.rstrip() + f"\n\nsource: {task_data.get('url', '')}\n"

        tasks[task_id].update({
            "summary_progress": 80,
            "message": "Saving summary files...",
        })
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])

        short_id = task_data.get("short_id") or task_id.replace("-", "")[:6]
        safe_title = task_data.get("safe_title") or _sanitize_title_for_filename(video_title)

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

        tasks[task_id].update({
            "summary": summary_with_source,
            "summary_status": "completed",
            "summary_progress": 100,
            "summary_language": summary_language,
            "summary_model": model_id or None,
            "summary_reasoning_effort": reasoning_effort or None,
            "summary_output_format": output_format,
            "summary_path": str(summary_markdown_path or summary_text_path) if (summary_markdown_path or summary_text_path) else None,
            "summary_markdown_path": str(summary_markdown_path) if summary_markdown_path else None,
            "summary_html_path": str(summary_html_path) if summary_html_path else None,
            "summary_text_path": str(summary_text_path) if summary_text_path else None,
            "message": "Files ready.",
        })
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])

    except Exception as e:
        logger.error(f"ж‘и¦Ѓз”џж€ђе¤±иґҐ: {e}")
        tasks[task_id].update({
            "summary_status": "error",
            "summary_error": str(e),
            "message": f"ж‘и¦Ѓз”џж€ђе¤±иґҐ: {e}",
        })
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])
    finally:
        active_summary_tasks.pop(task_id, None)


@app.get("/api/task-status/{task_id}")
async def get_task_status(task_id: str):
    """
    获取任务状态
    """
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    return tasks[task_id]

@app.get("/api/task-stream/{task_id}")
async def task_stream(task_id: str):
    """
    SSE实时任务状态流
    """
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    async def event_generator():
        # 创建任务专用的队列
        queue = asyncio.Queue()
        
        # 将队列添加到连接列表
        if task_id not in sse_connections:
            sse_connections[task_id] = []
        sse_connections[task_id].append(queue)
        
        try:
            # 立即发送当前状态
            current_task = tasks.get(task_id, {})
            yield f"data: {json.dumps(current_task, ensure_ascii=False)}\n\n"
            
            # 持续监听状态更新
            while True:
                try:
                    # 等待状态更新，超时时间30秒发送心跳
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {data}\n\n"
                    
                    # 如果任务完成或失败，结束流
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
                    # 发送心跳保持连接
                    yield f"data: {json.dumps({'type': 'heartbeat'}, ensure_ascii=False)}\n\n"
                    
        except asyncio.CancelledError:
            logger.info(f"SSE连接被取消: {task_id}")
        except Exception as e:
            logger.error(f"SSE流异常: {e}")
        finally:
            # 清理连接
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
            "Access-Control-Allow-Headers": "Cache-Control"
        }
    )

@app.get("/api/download/{filename}")
async def download_file(filename: str):
    """
    直接从temp目录下载文件（简化方案）
    """
    try:
        # 检查文件扩展名安全性
        suffix = Path(filename).suffix.lower()
        if suffix not in {'.md', '.html', '.txt'}:
            raise HTTPException(status_code=400, detail="仅支持下载.md、.html和.txt文件")
        
        # 检查文件名格式（防止路径遍历攻击）
        if '..' in filename or '/' in filename or '\\' in filename:
            raise HTTPException(status_code=400, detail="文件名格式无效")
            
        file_path = TEMP_DIR / filename
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="文件不存在")

        if suffix == ".html":
            media_type = "text/html"
        elif suffix == ".txt":
            media_type = "text/plain; charset=utf-8"
        else:
            media_type = "text/markdown"
            
        return FileResponse(
            file_path,
            filename=filename,
            media_type=media_type
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"下载文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"下载失败: {str(e)}")


@app.delete("/api/task/{task_id}")
async def delete_task(task_id: str):
    """
    取消并删除任务
    """
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    # 如果任务还在运行，先取消它
    if task_id in active_tasks:
        task = active_tasks[task_id]
        if not task.done():
            task.cancel()
            logger.info(f"任务 {task_id} 已被取消")
        del active_tasks[task_id]

    if task_id in active_summary_tasks:
        summary_task = active_summary_tasks[task_id]
        if not summary_task.done():
            summary_task.cancel()
            logger.info(f"summary task {task_id} cancelled")
        del active_summary_tasks[task_id]
    
    # 从处理URL列表中移除
    task_url = tasks[task_id].get("url")
    if task_url:
        processing_urls.discard(task_url)
    
    # 删除任务记录
    del tasks[task_id]
    save_tasks(tasks)
    return {"message": "任务已取消并删除"}

@app.get("/api/tasks/active")
async def get_active_tasks():
    """
    获取当前活跃任务列表（用于调试）
    """
    active_count = len(active_tasks)
    summary_count = len(active_summary_tasks)
    processing_count = len(processing_urls)
    return {
        "active_tasks": active_count,
        "active_summary_tasks": summary_count,
        "processing_urls": processing_count,
        "task_ids": list(active_tasks.keys())
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
