# Multi-Source Transcription Expansion Plan

## Summary

Expand `PLAN_DOUBLE_TRANSCRIPTION.md` from a Whisper + Parakeet dual-mode feature into a generalized multi-source transcription feature.

The user can select any non-empty combination of four transcription sources:

- `platform`: platform-provided transcript, starting with YouTube subtitles/captions through the existing subtitle path
- `groq`: Groq Whisper API transcription
- `local_whisper`: local Whisper transcription
- `local_parakeet`: local Nvidia Parakeet transcription

Each selected source runs independently, with local/API model sources running concurrently after media preparation. The user then chooses one output mode:

- `system`: deterministic merge using a user-selected primary transcript
- `raw`: no merge; return a raw bundle with per-source transcripts and an index/report
- `ai`: merge with an OpenAI-compatible LLM endpoint

## Public Interfaces

- Add `transcription_sources` as the new canonical request setting. Accept a JSON array string such as `["platform","groq","local_whisper"]`, with CSV fallback for CLI/manual callers.
- Add `merge_mode`: `system`, `raw`, or `ai`.
- Add `merge_primary_source`, required when `merge_mode=system` and at least two sources succeed.
- Keep backward compatibility:
  - Existing single-provider requests map to one source.
  - Existing dual-local flag maps to `["local_whisper","local_parakeet"]`.
  - Existing merge model/API key/base URL fields continue to work for AI merge.
- Source failures use partial-success behavior: if at least one selected source succeeds, the job completes with warnings. If all selected sources fail, the job fails.
- If the selected system primary source fails, fall back to the first successful selected source and record a warning.

## Implementation Changes

- Replace the current dual-only orchestration with a source registry:
  - `platform` calls the existing subtitle/platform transcript path and must not short-circuit other selected sources.
  - `groq` uses the existing Groq transcription path.
  - `local_whisper` uses the existing local Whisper path.
  - `local_parakeet` uses the current Parakeet path.
- Normalize every source result into the same internal shape: source id, display name, status, warnings/errors, plain text, timestamped segments, language/model metadata, and artifact filenames.
- Generalize `transcript_merge.py` from two-input merge to N-source merge:
  - `system` merge aligns source segments against the user-selected primary timeline.
  - It preserves primary wording unless another source fills an empty/low-confidence span.
  - It preserves timestamps and source provenance metadata.
  - A single successful source bypasses merge and becomes the final transcript unless `raw` mode was selected.
- Add raw-bundle output:
  - Write one artifact per successful source.
  - Write an index/report listing selected sources, completed sources, failed sources, warnings, model metadata, and file names.
  - Set the main task transcript to the raw-bundle index/report, not a synthesized transcript.
- Update the UI:
  - Replace the provider/dual-local mental model with a source checkbox group.
  - Show source-specific settings only when the matching source is enabled.
  - Add merge mode selection: System, Raw Bundle, AI Merge.
  - For System mode with multiple sources, require a primary-source selector.
  - Results view should expose raw per-source transcripts even when a merged transcript is produced.
- Update CLI:
  - Add repeatable `--source` or equivalent CSV support.
  - Add `--merge-mode`.
  - Add `--merge-primary-source`.
  - Preserve existing `--provider` and dual-local flags as compatibility aliases.

## Test Plan

- Unit-test source parsing: JSON array, CSV fallback, invalid source id, empty source list.
- Test backward compatibility: old Groq/local provider requests and old dual-local flag map to the new source list.
- Test platform + model behavior: selecting `platform` plus another source does not stop after subtitles are found.
- Test partial success: failed platform/Groq/local source records warning and job completes if another source succeeds.
- Test all-failed behavior: job fails with clear per-source error details.
- Test system merge:
  - requires primary source when multiple sources succeed;
  - uses the selected primary timeline;
  - falls back with warning if the primary failed;
  - handles one-source success without unnecessary merge.
- Test raw mode: creates per-source artifacts and raw index/report without calling deterministic or AI merge.
- Test AI merge: sends all successful source transcripts to the OpenAI-compatible merge client and respects merge-specific credentials/fallbacks.
- Test frontend static behavior: selected sources, merge mode, and primary source persist and submit correctly.
- Final verification command:
  `Set-Location -LiteralPath 'D:\Projects\AI-Video-Transcriber'; python -m pytest -q`

## Assumptions

- “Platform transcript” means the current subtitle/caption extraction path first, with YouTube as the initial supported platform and room for other platforms later.
- The user-selected deterministic primary source is the required system-merge base.
- Raw mode completes the task with a raw bundle and index/report, not an empty final result.
- Partial success is the default: unavailable selected sources should not discard useful transcripts from other successful sources.
