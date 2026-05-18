#!/usr/bin/env python3
"""CLI for AI Video Transcriber — transcription and summarization from the command line."""

import argparse
import asyncio
import getpass
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

_quiet_mode = False

AGENT_MANIFEST = {
    "name": "ai-video-transcriber-cli",
    "version": "1.0.0",
    "description": "CLI for video/audio transcription and AI summarization",
    "guide": "ai-video-transcriber/SKILL.md",
    "commands": {
        "transcribe": {
            "description": "Transcribe video/audio to text",
            "required_one_of": ["--url", "--file"],
            "flags": {
                "--url": {"type": "string", "description": "Video URL (YouTube, etc.)"},
                "--file": {"type": "string", "description": "Local audio/video file path"},
                "--provider": {
                    "type": "enum",
                    "values": ["groq", "local", "local_api"],
                    "default": "groq",
                },
                "--groq-api-key": {
                    "type": "string",
                    "description": "Removed — use settings, env var GROQ_API_KEY, or .env",
                    "removed": True,
                },
                "--groq-model": {"type": "string", "default": "whisper-large-v3-turbo"},
                "--language": {"type": "string", "default": "auto"},
                "--include-timecodes": {"type": "boolean", "default": False},
                "--skip-subtitles": {"type": "boolean", "default": False},
                "--local-backend": {
                    "type": "enum",
                    "values": ["whisper", "parakeet"],
                    "default": "whisper",
                },
                "--local-model": {"type": "string", "default": "base"},
                "--local-api-base-url": {"type": "string", "description": "Local API endpoint URL"},
                "--local-api-key": {"type": "string", "description": "Local API key"},
                "--local-api-model": {"type": "string", "description": "Local API model name"},
                "--local-api-language": {"type": "string", "description": "Local API language code"},
                "--local-api-prompt": {"type": "string", "description": "Local API prompt"},
                "--output": {"type": "string", "description": "Write transcript to file path"},
                "--format": {
                    "type": "enum",
                    "values": ["json", "markdown", "txt"],
                    "default": "json",
                },
                "--dual-local": {
                    "type": "boolean",
                    "default": False,
                    "description": "Run Whisper + Parakeet together (requires --provider local)",
                },
                "--dual-whisper-model-preset": {"type": "string", "default": "base"},
                "--dual-whisper-model-id": {"type": "string", "default": ""},
                "--dual-parakeet-model-preset": {"type": "string", "default": ""},
                "--dual-parakeet-model-id": {"type": "string", "default": ""},
                "--merge-use-ai": {"type": "boolean", "default": False},
                "--merge-base-url": {"type": "string", "description": "AI merge API base URL"},
                "--merge-api-key": {"type": "string", "description": "AI merge API key"},
                "--merge-model": {"type": "string", "description": "AI merge model"},
                "--merge-prompt": {"type": "string", "description": "AI merge prompt"},
                "--merge-reasoning-effort": {
                    "type": "enum",
                    "values": ["none", "minimal", "low", "medium", "high", "xhigh"],
                    "default": "",
                },
                "--source": {
                    "type": "string",
                    "description": "Comma-separated transcription sources (platform,groq,local_whisper,local_parakeet)",
                },
                "--merge-mode": {
                    "type": "enum",
                    "values": ["system", "raw", "ai"],
                    "default": "system",
                    "description": "Merge mode for multi-source transcription",
                },
                "--merge-primary-source": {
                    "type": "string",
                    "description": "Primary source for system merge (e.g. local_whisper)",
                },
            },
            "output_schema": {
                "status": "string",
                "transcript": "string",
                "video_title": "string",
                "detected_language": "string",
                "transcript_source": "string",
            },
        },
        "summarize": {
            "description": "Generate AI summary from transcript",
            "required_one_of": ["--task-id", "--transcript-file"],
            "flags": {
                "--task-id": {
                    "type": "string",
                    "description": "Task ID from a prior transcribe run",
                },
                "--transcript-file": {
                    "type": "string",
                    "description": "Path to transcript text file",
                },
                "--openai-api-key": {
                    "type": "string",
                    "description": "Removed — use settings, env var OPENAI_API_KEY, or .env",
                    "removed": True,
                },
                "--openai-base-url": {
                    "type": "string",
                    "description": "Removed — use settings, env var OPENAI_BASE_URL, or .env",
                    "removed": True,
                },
                "--model": {"type": "string", "default": "gpt-4o"},
                "--summary-language": {"type": "string", "default": "en"},
                "--output-format": {
                    "type": "enum",
                    "values": ["markdown", "html", "txt"],
                    "default": "markdown",
                },
                "--summary-output": {"type": "string", "description": "Write summary to file path"},
                "--prompt": {"type": "string", "description": "Custom summary instructions"},
                "--reasoning-effort": {
                    "type": "enum",
                    "values": [
                        "none",
                        "minimal",
                        "low",
                        "medium",
                        "high",
                        "xhigh",
                    ],
                    "default": "",
                },
            },
        },
        "pipeline": {
            "description": "Transcribe + summarize in one invocation",
            "notes": "Accepts all flags from both transcribe and summarize (except --task-id/--transcript-file, which are auto-set)",
        },
        "tasks": {
            "description": "Manage persisted task records",
            "flags": {
                "--list": {"type": "boolean", "description": "List all tasks"},
                "--get": {"type": "string", "description": "Get task by ID"},
                "--delete": {"type": "string", "description": "Delete task by ID"},
            },
        },
        "settings": {
            "description": "View and manage shared settings (settings.json)",
            "flags": {
                "--show": {"type": "boolean", "description": "Show current settings (credentials masked)"},
                "--set": {"type": "string", "description": "Set a key=value pair"},
                "--set-groq-key": {"type": "boolean", "description": "Prompt for Groq API key (no echo)"},
                "--set-openai-key": {"type": "boolean", "description": "Prompt for OpenAI API key (no echo)"},
            },
            "notes": "Configurable keys include: summary_chunk_threshold (tokens before chunked summarization, default 15000)",
        },
    },
    "exit_codes": {"0": "success", "1": "runtime error", "2": "invalid arguments"},
    "env_vars": ["GROQ_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "MERGE_API_KEY", "MERGE_BASE_URL", "MERGE_MODEL"],
    "settings_file": "settings.json",
}


def _load_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _print_progress(task_id: str, task_data: dict) -> None:
    if _quiet_mode:
        return
    progress = task_data.get("progress", 0)
    message = task_data.get("message", "")
    print(f"[{progress:>3d}%] {message}", file=sys.stderr, flush=True)


def _patch_broadcast(main_module) -> None:
    """Replace SSE broadcast with CLI-friendly stderr progress printer."""

    async def _cli_push_task_update(
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
        task = main_module.tasks[task_id]
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
        if stage_code is not None:
            task["stage_code"] = stage_code

        main_module.save_tasks(main_module.tasks)
        _print_progress(task_id, task)

    async def _cli_broadcast(task_id: str, task_data: dict) -> None:
        _print_progress(task_id, task_data)

    main_module._push_task_update = _cli_push_task_update
    main_module.broadcast_task_update = _cli_broadcast


def _resolve_api_key(flag_value: str, env_var: str) -> str:
    return (flag_value or "").strip() or os.getenv(env_var, "")


def _output_result(
    data: Any,
    *,
    output_path: str | None = None,
    fmt: str = "json",
    pretty: bool = False,
    content_key: str = "transcript",
) -> int:
    """Output result to stdout or file. Returns exit code."""
    if output_path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "json":
            content = json.dumps(data, ensure_ascii=False, indent=2)
        elif fmt == "txt":
            content = data.get(content_key, str(data)) if isinstance(data, dict) else str(data)
            content = _markdown_to_plain_text(content)
        else:
            content = data.get(content_key, str(data)) if isinstance(data, dict) else str(data)
        output.write_text(content, encoding="utf-8")
        print(f"Written to {output_path}", file=sys.stderr)
        return 0

    if pretty:
        if isinstance(data, dict):
            title = data.get("video_title", "")
            if title:
                print(f"\n# {title}\n", file=sys.stdout)
            content = data.get(content_key) or data.get("script") or ""
            print(content, file=sys.stdout)
        else:
            print(str(data), file=sys.stdout)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2), file=sys.stdout)

    return 0


def _markdown_to_plain_text(markdown: str) -> str:
    import re

    text = str(markdown or "").strip()
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^[ \t]*[-*_]{3,}[ \t]*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def _run_transcribe(args) -> dict:
    import main as backend_main
    from groq_transcriber import DEFAULT_GROQ_MODEL
    from settings import get_credential

    _patch_broadcast(backend_main)

    url = getattr(args, "url", "") or ""
    file_path = getattr(args, "file", "") or ""
    provider = getattr(args, "provider", "groq") or "groq"
    groq_api_key = get_credential("GROQ_API_KEY", "groq_api_key")
    groq_model = getattr(args, "groq_model", "") or DEFAULT_GROQ_MODEL
    language = getattr(args, "language", "") or ""
    include_timecodes = getattr(args, "include_timecodes", False)
    skip_subtitles = getattr(args, "skip_subtitles", False)
    local_backend = getattr(args, "local_backend", "whisper") or "whisper"
    local_model = getattr(args, "local_model", "base") or "base"
    local_api_base_url = getattr(args, "local_api_base_url", "") or ""
    local_api_key = getattr(args, "local_api_key", "") or ""
    local_api_model = getattr(args, "local_api_model", "") or ""
    local_api_language = getattr(args, "local_api_language", "") or ""
    local_api_prompt = getattr(args, "local_api_prompt", "") or ""
    dual_local = getattr(args, "dual_local", False)
    dual_whisper_model_preset = getattr(args, "dual_whisper_model_preset", "base") or "base"
    dual_whisper_model_id = getattr(args, "dual_whisper_model_id", "") or ""
    dual_parakeet_model_preset = getattr(args, "dual_parakeet_model_preset", "") or ""
    dual_parakeet_model_id = getattr(args, "dual_parakeet_model_id", "") or ""
    merge_use_ai = getattr(args, "merge_use_ai", False)
    merge_base_url = getattr(args, "merge_base_url", "") or ""
    merge_api_key = getattr(args, "merge_api_key", "") or ""
    merge_model = getattr(args, "merge_model", "") or ""
    merge_prompt = getattr(args, "merge_prompt", "") or ""
    merge_reasoning_effort = getattr(args, "merge_reasoning_effort", "") or ""
    source_csv = getattr(args, "source", "") or ""
    merge_mode = getattr(args, "merge_mode", "") or ""
    merge_primary_source = getattr(args, "merge_primary_source", "") or ""

    if not url and not file_path:
        return {"error": "Either --url or --file is required.", "exit_code": 2}

    if dual_local and provider != "local":
        provider = "local"

    needs_groq_key = provider == "groq"
    if source_csv:
        source_list = [s.strip() for s in source_csv.split(",") if s.strip()]
        needs_groq_key = "groq" in source_list
    if needs_groq_key and not groq_api_key:
        return {
            "error": (
                "Groq API key is required. Set it via:\n"
                "  • Environment variable: GROQ_API_KEY\n"
                "  • GUI settings panel (start the server first)\n"
                "  • CLI: python cli.py settings --set-groq-key"
            ),
            "exit_code": 1,
        }

    source_file_path = ""
    source_file_name = ""
    source_title = ""
    if file_path:
        src = Path(file_path)
        if not src.exists():
            return {"error": f"File not found: {file_path}", "exit_code": 1}
        temp_dir = PROJECT_ROOT / "temp"
        temp_dir.mkdir(exist_ok=True)
        dest = temp_dir / f"upload_{uuid.uuid4().hex[:8]}_{src.name}"
        shutil.copy2(str(src), str(dest))
        source_file_path = str(dest)
        source_file_name = src.name
        source_title = src.stem

    task_id = str(uuid.uuid4())
    backend_main.tasks[task_id] = {
        "status": "processing",
        "progress": 0,
        "message": "Starting...",
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
        "transcription_provider_requested": provider,
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
        "url": url,
        "input_source_type": "file" if file_path else "url",
        "source_file_name": source_file_name,
    }
    backend_main.save_tasks(backend_main.tasks)

    await backend_main.process_video_task(
        task_id=task_id,
        url=url,
        groq_api_key=groq_api_key,
        groq_model=groq_model,
        groq_language=language,
        groq_prompt="",
        include_timecodes=include_timecodes,
        transcription_provider=provider,
        try_subtitles_first=not skip_subtitles,
        use_local_fallback=False,
        local_backend=local_backend,
        local_model_preset=local_model,
        local_model_id="",
        local_language=language,
        local_api_base_url=local_api_base_url,
        local_api_key=local_api_key,
        local_api_model=local_api_model,
        local_api_language=local_api_language or language,
        local_api_prompt=local_api_prompt,
        source_file_path=source_file_path,
        source_file_name=source_file_name,
        source_title=source_title,
        dual_local_transcription=dual_local,
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
        transcription_sources_raw=source_csv,
        merge_mode_raw=merge_mode,
        merge_primary_source=merge_primary_source,
    )

    task_data = backend_main.tasks.get(task_id, {})
    if task_data.get("status") == "error":
        return {"error": task_data.get("error", "Unknown error"), "exit_code": 1}

    return {
        "task_id": task_id,
        "status": task_data.get("status"),
        "video_title": task_data.get("video_title"),
        "transcript": task_data.get("transcript") or task_data.get("script"),
        "detected_language": task_data.get("detected_language"),
        "transcript_source": task_data.get("transcript_source") or task_data.get("transcription_source"),
        "transcription_provider_used": task_data.get("transcription_provider_used"),
        "script_path": task_data.get("script_path"),
    }


async def _run_summarize(args) -> dict:
    import main as backend_main
    from summarizer import Summarizer
    from settings import get_credential

    _patch_broadcast(backend_main)

    task_id = getattr(args, "task_id", "") or ""
    transcript_file = getattr(args, "transcript_file", "") or ""
    openai_api_key = get_credential("OPENAI_API_KEY", "openai_api_key")
    openai_base_url = get_credential("OPENAI_BASE_URL", "openai_base_url")
    model = getattr(args, "model", "") or "gpt-4o"
    language = getattr(args, "summary_lang", "en") or "en"
    prompt = getattr(args, "prompt", "") or ""
    reasoning_effort = getattr(args, "reasoning_effort", "") or ""

    if not task_id and not transcript_file:
        return {"error": "Either --task-id or --transcript-file is required.", "exit_code": 2}

    transcript_text = ""
    video_title = "Video Summary"

    if transcript_file:
        tf = Path(transcript_file)
        if not tf.exists():
            return {"error": f"Transcript file not found: {transcript_file}", "exit_code": 1}
        transcript_text = tf.read_text(encoding="utf-8")
        video_title = tf.stem
    elif task_id:
        if task_id not in backend_main.tasks:
            return {"error": f"Task not found: {task_id}", "exit_code": 1}
        task_data = backend_main.tasks[task_id]
        transcript_text = task_data.get("transcript") or task_data.get("script") or ""
        video_title = task_data.get("video_title") or "Video Summary"
        if not transcript_text:
            return {"error": f"No transcript available for task {task_id}", "exit_code": 1}

    if not openai_api_key:
        return {
            "error": (
                "OpenAI API key is required. Set it via:\n"
                "  • Environment variable: OPENAI_API_KEY\n"
                "  • GUI settings panel (start the server first)\n"
                "  • CLI: python cli.py settings --set-openai-key"
            ),
            "exit_code": 1,
        }

    base_url = openai_base_url or None
    s = Summarizer(
        api_key=openai_api_key,
        base_url=base_url,
        model=model or None,
        reasoning_effort=reasoning_effort or None,
    )

    if not _quiet_mode:
        print("[  0%] Generating summary...", file=sys.stderr, flush=True)
    summary = await s.summarize(
        transcript_text,
        language,
        video_title,
        custom_prompt=prompt,
    )
    if not _quiet_mode:
        print("[100%] Summary complete.", file=sys.stderr, flush=True)

    result = {
        "status": "completed",
        "summary": summary,
        "video_title": video_title,
        "language": language,
    }

    if task_id:
        backend_main.tasks[task_id].update({
            "summary": summary,
            "summary_status": "completed",
            "summary_progress": 100,
            "summary_language": language,
            "summary_model": model,
        })
        backend_main.save_tasks(backend_main.tasks)
        result["task_id"] = task_id

    return result


def cmd_transcribe(args) -> dict:
    return asyncio.run(_run_transcribe(args))


def cmd_summarize(args) -> dict:
    return asyncio.run(_run_summarize(args))


def cmd_pipeline(args) -> dict:
    # Transcribe first, then feed the resulting task_id into summarize.
    # pipeline's argparse only has config flags (no --task-id/--transcript-file),
    # so we inject them dynamically between steps.
    result = asyncio.run(_run_transcribe(args))
    if result.get("exit_code"):
        return result

    setattr(args, "task_id", result["task_id"])
    setattr(args, "transcript_file", "")
    summary_result = asyncio.run(_run_summarize(args))
    if summary_result.get("exit_code"):
        return summary_result

    return {
        "task_id": result["task_id"],
        "video_title": result.get("video_title"),
        "detected_language": result.get("detected_language"),
        "transcript_source": result.get("transcript_source"),
        "transcription_provider_used": result.get("transcription_provider_used"),
        "summary": summary_result.get("summary"),
        "summary_language": summary_result.get("language"),
    }


def cmd_tasks(args) -> dict:
    import main as backend_main

    if getattr(args, "list", False):
        return {"tasks": [{"task_id": k, **v} for k, v in backend_main.tasks.items()]}

    get_id = getattr(args, "get", "") or ""
    if get_id:
        if get_id not in backend_main.tasks:
            return {"error": f"Task not found: {get_id}", "exit_code": 1}
        return backend_main.tasks[get_id]

    delete_id = getattr(args, "delete", "") or ""
    if delete_id:
        if delete_id not in backend_main.tasks:
            return {"error": f"Task not found: {delete_id}", "exit_code": 1}
        del backend_main.tasks[delete_id]
        backend_main.save_tasks(backend_main.tasks)
        return {"status": "deleted", "task_id": delete_id}

    return {"error": "One of --list, --get, or --delete is required.", "exit_code": 2}


def cmd_settings(args) -> dict:
    from settings import get_masked_settings, load_settings, mask_credential, save_settings

    if getattr(args, "show", False):
        return get_masked_settings()

    set_value = getattr(args, "set_value", "") or ""
    if set_value:
        if "=" not in set_value:
            return {"error": "--set requires key=value format (e.g. groq_model=whisper-large-v3)", "exit_code": 2}
        key, _, value = set_value.partition("=")
        key = key.strip()
        value = value.strip()
        if value.isdigit():
            value = int(value)
        elif value.lower() in ("true", "false"):
            value = value.lower() == "true"
        current = load_settings()
        if key not in current:
            return {"error": f"Unknown setting: {key}", "exit_code": 2}
        save_settings({key: value})
        return {key: mask_credential(value) if "key" in key else value}

    if getattr(args, "set_groq_key", False):
        key = getpass.getpass("Groq API key: ")
        if not key.strip():
            return {"error": "No key entered.", "exit_code": 1}
        save_settings({"groq_api_key": key.strip()})
        return {"groq_api_key": mask_credential(key.strip())}

    if getattr(args, "set_openai_key", False):
        key = getpass.getpass("OpenAI API key: ")
        if not key.strip():
            return {"error": "No key entered.", "exit_code": 1}
        save_settings({"openai_api_key": key.strip()})
        return {"openai_api_key": mask_credential(key.strip())}

    return get_masked_settings()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="AI Video Transcriber CLI — transcribe and summarize video/audio",
        epilog="Use --agent-help for machine-readable capability manifest.",
    )

    parser.add_argument(
        "--agent-help",
        action="store_true",
        help="Print machine-readable capability manifest as JSON and exit",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Human-readable output instead of JSON",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress messages on stderr",
    )

    subparsers = parser.add_subparsers(dest="command")

    # --- transcribe ---
    tr = subparsers.add_parser("transcribe", help="Transcribe video/audio to text")
    _add_transcribe_args(tr)

    # --- summarize ---
    su = subparsers.add_parser("summarize", help="Generate AI summary from transcript")
    _add_summarize_source_args(su)
    _add_summarize_config_args(su)

    # --- pipeline ---
    pl = subparsers.add_parser("pipeline", help="Transcribe + summarize in one shot")
    _add_transcribe_args(pl)
    _add_summarize_config_args(pl)

    # --- tasks ---
    ta = subparsers.add_parser("tasks", help="Manage persisted task records")
    ta.add_argument("--list", action="store_true", help="List all tasks")
    ta.add_argument("--get", metavar="ID", default="", help="Get task by ID")
    ta.add_argument("--delete", metavar="ID", default="", help="Delete task by ID")

    # --- settings ---
    se = subparsers.add_parser("settings", help="View and manage shared settings")
    se.add_argument("--show", action="store_true", help="Show current settings (credentials masked)")
    se.add_argument("--set", dest="set_value", default="", metavar="KEY=VALUE", help="Set a key=value pair")
    se.add_argument("--set-groq-key", action="store_true", help="Prompt for Groq API key (no echo)")
    se.add_argument("--set-openai-key", action="store_true", help="Prompt for OpenAI API key (no echo)")

    return parser


def _add_transcribe_args(p: argparse.ArgumentParser) -> None:
    inp = p.add_mutually_exclusive_group()
    inp.add_argument("--url", default="", help="Video URL (YouTube, etc.)")
    inp.add_argument("--file", default="", help="Local audio/video file path")

    p.add_argument("--provider", default="groq", choices=["groq", "local", "local_api"], help="Transcription provider (default: groq)")
    p.add_argument("--groq-model", default="", help="Groq model name (default: whisper-large-v3-turbo)")
    p.add_argument("--language", default="", help="Language code or 'auto' (default: auto)")
    p.add_argument("--include-timecodes", action="store_true", help="Keep timecodes in transcript")
    p.add_argument("--skip-subtitles", action="store_true", help="Skip YouTube subtitle extraction")
    p.add_argument("--local-backend", default="whisper", choices=["whisper", "parakeet"], help="Local backend (default: whisper)")
    p.add_argument("--local-model", default="base", help="Local model preset or ID (default: base)")
    p.add_argument("--local-api-base-url", default="", help="Local API endpoint URL (for provider=local_api)")
    p.add_argument("--local-api-key", default="", help="Local API key (for provider=local_api)")
    p.add_argument("--local-api-model", default="", help="Local API model name (for provider=local_api)")
    p.add_argument("--local-api-language", default="", help="Local API language code (for provider=local_api)")
    p.add_argument("--local-api-prompt", default="", help="Local API prompt (for provider=local_api)")
    p.add_argument("--output", default="", help="Write output to file path")
    p.add_argument("--format", default="json", choices=["json", "markdown", "txt"], help="Output format (default: json)")
    p.add_argument("--dual-local", action="store_true", help="Run Whisper + Parakeet together (requires --provider local)")
    p.add_argument("--dual-whisper-model-preset", default="base", help="Whisper model preset for dual mode (default: base)")
    p.add_argument("--dual-whisper-model-id", default="", help="Custom Whisper model ID for dual mode")
    p.add_argument("--dual-parakeet-model-preset", default="", help="Parakeet model preset for dual mode")
    p.add_argument("--dual-parakeet-model-id", default="", help="Custom Parakeet model ID for dual mode")
    p.add_argument("--merge-use-ai", action="store_true", help="Use AI to merge dual transcripts")
    p.add_argument("--merge-base-url", default="", help="AI merge API base URL")
    p.add_argument("--merge-api-key", default="", help="AI merge API key")
    p.add_argument("--merge-model", default="", help="AI merge model name")
    p.add_argument("--merge-prompt", default="", help="AI merge prompt")
    p.add_argument("--merge-reasoning-effort", default="", choices=["", "none", "minimal", "low", "medium", "high", "xhigh"], help="AI merge reasoning effort")
    p.add_argument("--source", default="", help="Comma-separated transcription sources (platform,groq,local_whisper,local_parakeet)")
    p.add_argument("--merge-mode", default="", choices=["", "system", "raw", "ai"], help="Merge mode for multi-source (default: system)")
    p.add_argument("--merge-primary-source", default="", help="Primary source for system merge (e.g. local_whisper)")


def _add_summarize_source_args(p: argparse.ArgumentParser) -> None:
    src = p.add_mutually_exclusive_group()
    src.add_argument("--task-id", default="", help="Task ID from a prior transcribe run")
    src.add_argument("--transcript-file", default="", help="Path to transcript text file")


def _add_summarize_config_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--model", default="", help="Model name (default: gpt-4o)")
    p.add_argument("--summary-language", default="en", dest="summary_lang", help="Summary language code (default: en)")
    p.add_argument("--output-format", default="markdown", choices=["markdown", "html", "txt"], help="Summary output format (default: markdown)")
    p.add_argument("--summary-output", default="", dest="summary_output", help="Write summary to file path")
    p.add_argument("--prompt", default="", help="Custom summary instructions")
    p.add_argument(
        "--reasoning-effort",
        default="",
        choices=["none", "minimal", "low", "medium", "high", "xhigh"],
        help="Reasoning effort for supported models",
    )


def main() -> int:
    _load_env()

    parser = build_parser()
    args = parser.parse_args()

    if args.agent_help:
        print(json.dumps(AGENT_MANIFEST, indent=2), file=sys.stdout)
        return 0

    if not args.command:
        parser.print_help(sys.stderr)
        return 2

    global _quiet_mode
    _quiet_mode = getattr(args, "quiet", False)

    result: dict
    content_key = "transcript"

    if args.command == "transcribe":
        result = cmd_transcribe(args)
    elif args.command == "summarize":
        result = cmd_summarize(args)
        content_key = "summary"
    elif args.command == "pipeline":
        result = cmd_pipeline(args)
        content_key = "summary"
    elif args.command == "tasks":
        result = cmd_tasks(args)
    elif args.command == "settings":
        result = cmd_settings(args)
    else:
        parser.print_help(sys.stderr)
        return 2

    exit_code = result.get("exit_code", 0)
    if exit_code:
        if not getattr(args, "pretty", False):
            print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stdout)
        else:
            print(f"Error: {result.get('error', 'Unknown error')}", file=sys.stderr)
        return exit_code

    if args.command == "summarize":
        out_path = getattr(args, "summary_output", "") or None
        out_fmt = getattr(args, "output_format", "markdown")
    elif args.command == "pipeline":
        out_path = getattr(args, "summary_output", "") or getattr(args, "output", "") or None
        out_fmt = getattr(args, "output_format", "markdown")
    else:
        out_path = getattr(args, "output", "") or None
        out_fmt = getattr(args, "format", "json")

    _output_result(
        result,
        output_path=out_path,
        fmt=out_fmt,
        pretty=getattr(args, "pretty", False),
        content_key=content_key,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
