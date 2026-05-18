# Consolidate Dual Local Into Multi-Source Transcription

## Summary

Remove the separate Dual Local transcription UI and make Whisper + Parakeet concurrency available only through Multi-Source Transcription. The user enables Multi-Source, checks `Local Whisper` and/or `Local Parakeet`, then configures each selected local source’s model inside the Multi-Source section.

Legacy backend/API support for `dual_local_transcription=true` stays for compatibility, but the UI stops exposing or saving that separate mode.

## Key Changes

- **UI consolidation**
  - Remove the `Run Whisper + Parakeet together` checkbox and the separate Dual Local block from the Local provider section.
  - Remove the separate Dual Local merge settings block because Multi-Source already owns merge mode, primary source, raw bundle, and AI merge settings.
  - Keep single Local provider mode simple: one backend selector, one local model preset/custom model, and language hint for normal single-source local transcription.

- **Multi-Source local model controls**
  - When `Enable multi-source transcription` is checked:
    - show provider checkboxes.
    - if `Local Whisper` is checked, show `Whisper Model` and optional custom Whisper model controls.
    - if `Local Parakeet` is checked, show `Parakeet Model` and optional custom Parakeet model controls.
  - Reuse the existing dual-local model fields internally if practical, but rename/move them conceptually under Multi-Source.
  - Hide disabled/unselected local source model controls so the user sees only selected source configuration.

- **Request behavior**
  - If Multi-Source is disabled, submit no `transcription_sources`; use the selected top-level provider normally.
  - If Multi-Source is enabled, submit `transcription_sources` from checked providers.
  - Submit `dual_whisper_model_preset`, `dual_whisper_model_id`, `dual_parakeet_model_preset`, and `dual_parakeet_model_id` as model configuration for multi-source local sources.
  - Always submit `dual_local_transcription=false` from the UI; backend legacy support remains but UI no longer uses it.

- **Backend compatibility**
  - Keep existing backend support for legacy `dual_local_transcription=true` so older CLI/API callers do not break.
  - Ensure Multi-Source `["local_whisper","local_parakeet"]` uses the same model preset/custom model parameters that Dual Local used.
  - Treat Multi-Source as the canonical path for concurrent local transcription in UI-facing behavior and tests.

## Test Plan

- Add/adjust frontend static tests:
  - Dual Local checkbox/block is no longer present in `static/index.html`.
  - Multi-Source contains conditional model controls for `Local Whisper` and `Local Parakeet`.
  - UI submit path sends `transcription_sources` for selected multi-source providers and does not send `dual_local_transcription=true`.
  - When Multi-Source is disabled, checked/stale provider boxes are ignored.

- Add/adjust backend tests:
  - `transcription_sources=["local_whisper","local_parakeet"]` runs both local sources concurrently and respects selected Whisper/Parakeet model settings.
  - Legacy `dual_local_transcription=true` still works for API compatibility.
  - Stale `dual_local_transcription=true` with non-local provider remains ignored.

- Run validation:
  - `python -m pytest -q tests\test_multi_source.py`
  - `python -m pytest -q`
  - `python -m py_compile backend\main.py backend\settings.py backend\source_registry.py backend\transcript_merge.py cli.py`
  - `node --check static\app.js`
  - Browser check: enable Multi-Source, select Local Whisper + Local Parakeet, verify only Multi-Source controls appear and status cards show both sources.

## Assumptions

- Multi-Source is now the only UI path for concurrent transcription.
- Legacy Dual Local API/CLI behavior must remain backward compatible.
- Existing Whisper/Parakeet model preset options are reused; no new model schema is introduced.
- Multi-Source merge settings replace Dual Local merge settings completely.
