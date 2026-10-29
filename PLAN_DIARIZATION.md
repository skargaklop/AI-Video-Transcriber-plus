# Strategic Migration Plan: Native C++ ASR / ONNX & Speaker Diarization

> **Primary Architectural Directive:**
> The primary and immediate task for the local transcription engine is to **migrate usage to high-performance C++ ASR tools or ONNX runtimes**, moving away from heavyweight Python-bound audio stacks.
> Speaker diarization planning (detailed below) is subordinated to this architecture: any speaker diarization and alignment pipeline must be designed to work alongside or on top of native C++ / ONNX speech recognition backends rather than assuming a monolithic Python/PyTorch environment.

---

## Primary Task: Migration to C++ ASR Tools or ONNX

### 1. Target C++ ASR Project: `transcribe.cpp`
- **Repository**: [https://github.com/handy-computer/transcribe.cpp](https://github.com/handy-computer/transcribe.cpp)
- **Overview**:
  - Fast, accurate, cross-platform speech recognition library built in C++.
  - Broad model support: over 60 speech models.
  - Native GPU hardware acceleration: Vulkan, Metal, and CUDA.
  - High accuracy verified against standard Word Error Rate (WER) benchmarks.
  - Full compatibility with `whisper.cpp`.
  - First-class bindings available for Python, JavaScript, Rust, and Swift.
- **Migration Role**:
  - Primary candidate to provide standalone or lightweight Python-bound C++ execution for local transcription, avoiding heavy PyTorch dependencies and bypassing Python GIL bottlenecks.

### 2. Complementary Target: ONNX Runtimes
- Build on and extend the existing `onnx-asr` implementation (currently powering local Parakeet models) and evaluate ONNX ASR engines (such as `sherpa-onnx`) for portable CPU/GPU speech inference without Python package overhead.

### 3. Architectural Implications for Diarization
- Diarization remains strictly a post-transcription enrichment stage and must not re-introduce heavy runtime dependencies into the core engine.
- Alignment must operate exclusively on normalized timestamped intervals produced by the C++/ONNX transcription layer.

---

# Pyannote Speaker Diarization Implementation Plan

## Summary
Add optional pyannote-based speaker diarization as a post-transcription enrichment step, not as a new transcription provider. V1 covers both CLI and browser UI, auto-installs missing `pyannote.audio` dependencies on first diarized run, uses the existing ffmpeg resolution path, and forces diarized URL jobs onto audio-backed ASR instead of the platform-subtitle shortcut.

External default: use `pyannote/speaker-diarization-community-1`, because its model card documents local execution, offline use, and `exclusive_speaker_diarization` for easier ASR timestamp alignment: https://huggingface.co/pyannote/speaker-diarization-community-1. Pyannote install/runtime behavior should follow the current pyannote.audio package docs: https://github.com/pyannote/pyannote-audio.

## Public Interfaces
Add CLI flags to `transcribe` and `pipeline`: `--diarize`, `--diarization-model`, `--num-speakers`, `--min-speakers`, `--max-speakers`. Do not add a raw token flag to transcription commands; resolve tokens from `HUGGINGFACE_TOKEN`, then `HF_TOKEN`, then `settings.json`.

Add settings keys: `diarization_enabled`, `huggingface_token`, `diarization_model`, `diarization_num_speakers`, `diarization_min_speakers`, `diarization_max_speakers`. Mask `huggingface_token` in settings responses and add `python cli.py settings --set-huggingface-token`.

Add FastAPI form fields matching the settings keys. Add a `/api/diarization-capabilities` endpoint returning availability, runtime, auto-install support, token-configured boolean, default model, and setup warnings.

Add task metadata fields: `diarization_enabled`, `diarization_model`, `diarization_runtime`, `diarization_speakers`, `diarization_artifact`, and `diarization_error`. Final transcript text should be speaker-attributed when diarization succeeds.

## Implementation Changes
Create `backend/diarization.py` with dependency detection, auto-install, token resolution, model loading, pyannote execution, turn normalization, RTTM/JSON export, and ASR-segment alignment. Install package list should be centralized, e.g. `["pyannote.audio>=4.0.0"]`, and reused by capabilities and installer code.

Use `output.exclusive_speaker_diarization` when present; fall back to `output.speaker_diarization`. Convert pyannote annotations into `{start, end, speaker}` turns, then assign each ASR segment to the speaker with the largest timestamp overlap. Segments with no usable overlap get `UNKNOWN`.

Add a formatter that groups adjacent same-speaker ASR segments into readable speaker blocks. With `include_timecodes=true`, output `**[00:12 - 00:19] SPEAKER_00**`; without timecodes, output `**SPEAKER_00:** text`.

Refactor `process_video_task` so `diarize=true` keeps an audio file alive until after diarization. For URL + Groq, use local audio download plus Groq file transcription so pyannote and ASR use the same audio. For local/local_api/multi-source, reuse the already prepared audio and delay cleanup until speaker alignment finishes.

When `diarize=true`, set `should_try_subtitles=false` for legacy provider mode. If explicit multi-source includes `platform`, reject it with a clear validation error because v1 diarization requires audio-backed timestamped ASR segments. Also reject diarization with `merge_mode=raw` or `merge_mode=ai`; v1 supports single-source, dual-local deterministic merge, and multi-source system merge only.

Extend deterministic merge helpers to return merged timestamped segments in addition to markdown/stats, so diarization can align to the actual final system-merged transcript. Do not attempt speaker alignment against AI-merged free text.

Add progress stages and UI labels for `installing_diarization_backend`, `loading_diarization_model`, `running_diarization`, and `aligning_speakers`. In the GUI, add a Diarization settings section with enable toggle, HF token field, model field, speaker-count controls, capability/status notice, and platform-source disabling when diarization is enabled.

Write sidecar artifacts into `temp/`: `diarization_<title>_<id>.json` and `diarization_<title>_<id>.rttm`. The JSON should include model, runtime, speaker turns, aligned transcript segments, and speaker count.

Update README, CLI agent-help manifest, `.env.example`, and optional install docs. Add `[project.optional-dependencies] diarization = ["pyannote.audio>=4.0.0"]` and optionally `requirements-diarization.txt`; keep base requirements light.

## Test Plan
Add unit tests for token precedence, settings masking, CLI parser flags, pyannote dependency auto-install decision flow, speaker-turn normalization, max-overlap alignment, unknown-speaker fallback, and speaker transcript formatting.

Add mocked backend integration tests proving `diarize=true` skips subtitle-only flow, keeps audio until diarization completes, calls the diarizer after transcription/merge, writes task metadata/artifacts, and returns speaker-attributed transcript text.

Add validation tests for missing token, invalid speaker-count combinations, explicit `platform` source with diarization, `merge_mode=raw`, `merge_mode=ai`, and no timestamped ASR segments.

Add frontend/static tests for new controls, settings persistence, form fields, stage labels, capability message, and disabled platform source when diarization is enabled.

Run verification from the repo root: `python -m pytest -q`. If `HUGGINGFACE_TOKEN` is available, add an optional manual smoke test on a short local audio file using `--provider local --local-model tiny --diarize`.

## Assumptions And Defaults
Default model is `pyannote/speaker-diarization-community-1`. Speaker labels remain generic (`SPEAKER_00`) in v1; custom speaker naming is out of scope.

Auto-install means Python packages only. The Hugging Face model download still requires a valid token and accepted model terms; missing/invalid token should fail before installing packages.

Existing ffmpeg support is reused through `ensure_ffmpeg_binary`; no separate ffmpeg installer is added.

Diarization is a post-processing feature. It must not be added to `source_registry.py` as a transcription source and must not replace Groq, Whisper, Parakeet, or Local API transcription.
