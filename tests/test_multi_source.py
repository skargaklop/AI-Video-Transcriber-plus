"""Tests for multi-source transcription feature."""

import asyncio
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import main  # noqa: E402
import transcript_merge  # noqa: E402
import source_registry  # noqa: E402
from settings import DEFAULT_SETTINGS  # noqa: E402


class SourceParsingTests(unittest.TestCase):
    def test_parse_json_array(self):
        result = source_registry.parse_transcription_sources('["groq","local_whisper"]')
        self.assertEqual(result, ["groq", "local_whisper"])

    def test_parse_csv(self):
        result = source_registry.parse_transcription_sources("groq, local_parakeet")
        self.assertEqual(result, ["groq", "local_parakeet"])

    def test_parse_single(self):
        result = source_registry.parse_transcription_sources("groq")
        self.assertEqual(result, ["groq"])

    def test_parse_list_input(self):
        result = source_registry.parse_transcription_sources(["platform", "groq"])
        self.assertEqual(result, ["platform", "groq"])

    def test_parse_empty(self):
        result = source_registry.parse_transcription_sources("")
        self.assertEqual(result, [])

    def test_parse_none(self):
        result = source_registry.parse_transcription_sources(None)
        self.assertEqual(result, [])

    def test_parse_deduplication(self):
        result = source_registry.parse_transcription_sources('["groq","groq","local_whisper"]')
        self.assertEqual(result, ["groq", "local_whisper"])

    def test_parse_invalid_source_raises(self):
        with self.assertRaises(ValueError) as ctx:
            source_registry.parse_transcription_sources("invalid_source")
        self.assertIn("invalid_source", str(ctx.exception))

    def test_parse_invalid_json_raises(self):
        with self.assertRaises(ValueError):
            source_registry.parse_transcription_sources("[not json")

    def test_parse_valid_sources_list(self):
        self.assertEqual(source_registry.VALID_SOURCES, ("platform", "groq", "local_whisper", "local_parakeet"))


class LegacyMappingTests(unittest.TestCase):
    def test_groq_provider_maps_to_groq(self):
        result = source_registry.resolve_sources_from_legacy(transcription_provider="groq")
        self.assertEqual(result, ["groq"])

    def test_local_whisper_maps(self):
        result = source_registry.resolve_sources_from_legacy(
            transcription_provider="local", local_backend="whisper"
        )
        self.assertEqual(result, ["local_whisper"])

    def test_local_parakeet_maps(self):
        result = source_registry.resolve_sources_from_legacy(
            transcription_provider="local", local_backend="parakeet"
        )
        self.assertEqual(result, ["local_parakeet"])

    def test_dual_local_maps(self):
        result = source_registry.resolve_sources_from_legacy(
            dual_local_transcription=True
        )
        self.assertEqual(result, ["local_whisper", "local_parakeet"])

    def test_default_maps_to_groq(self):
        result = source_registry.resolve_sources_from_legacy()
        self.assertEqual(result, ["groq"])


class MergeModeTests(unittest.TestCase):
    def test_default_is_system(self):
        self.assertEqual(source_registry.resolve_merge_mode(), "system")

    def test_ai_flag_maps(self):
        self.assertEqual(source_registry.resolve_merge_mode(merge_use_ai=True), "ai")

    def test_explicit_mode_overrides_flag(self):
        self.assertEqual(source_registry.resolve_merge_mode(merge_use_ai=True, merge_mode="raw"), "raw")

    def test_all_valid_modes(self):
        for mode in ("system", "raw", "ai"):
            self.assertEqual(source_registry.resolve_merge_mode(merge_mode=mode), mode)


class NormalizeSourceResultTests(unittest.TestCase):
    def test_success_result(self):
        result = source_registry.normalize_source_result(
            "groq",
            result={"markdown": "Hello", "language": "en", "raw": {}},
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["markdown"], "Hello")
        self.assertEqual(result["language"], "en")

    def test_error_result(self):
        result = source_registry.normalize_source_result("groq", error="API failed")
        self.assertEqual(result["status"], "error")
        self.assertIn("API failed", result["errors"])

    def test_pending_result(self):
        result = source_registry.normalize_source_result("groq")
        self.assertEqual(result["status"], "pending")

    def test_segments_extracted(self):
        result = source_registry.normalize_source_result(
            "local_whisper",
            result={
                "markdown": "Text",
                "raw": {
                    "segments": [
                        {"start": 0.0, "end": 5.0, "text": "Hello"},
                        {"start": 5.0, "end": 10.0, "text": "World"},
                    ]
                },
            },
        )
        self.assertEqual(len(result["segments"]), 2)
        self.assertEqual(result["segments"][0]["text"], "Hello")


class NSourceDeterministicMergeTests(unittest.TestCase):
    def test_single_source_passthrough(self):
        sources = [{"source_id": "groq", "segments": [{"start": 0.0, "end": 5.0, "text": "Hello"}], "has_timestamps": True, "text": ""}]
        result = transcript_merge.merge_transcripts_deterministic_n(sources)
        self.assertIn("Hello", result["markdown"])
        self.assertEqual(result["stats"]["sources"], 1)

    def test_two_sources_with_primary(self):
        sources = [
            {"source_id": "local_whisper", "segments": [{"start": 0.0, "end": 5.0, "text": "Hello"}, {"start": 5.0, "end": 10.0, "text": ""}], "has_timestamps": True, "text": ""},
            {"source_id": "local_parakeet", "segments": [{"start": 0.0, "end": 5.0, "text": "Hello"}, {"start": 5.0, "end": 10.0, "text": "World"}], "has_timestamps": True, "text": ""},
        ]
        result = transcript_merge.merge_transcripts_deterministic_n(sources, primary_source_id="local_whisper")
        self.assertIn("Hello", result["markdown"])
        self.assertIn("World", result["markdown"])
        self.assertGreaterEqual(result["stats"]["fill_count"], 1)

    def test_empty_sources(self):
        result = transcript_merge.merge_transcripts_deterministic_n([])
        self.assertEqual(result["markdown"], "")

    def test_no_timestamps_fallback(self):
        sources = [
            {"source_id": "groq", "segments": [], "has_timestamps": False, "markdown": "Groq text"},
            {"source_id": "local_whisper", "segments": [], "has_timestamps": False, "markdown": "Whisper text"},
        ]
        result = transcript_merge.merge_transcripts_deterministic_n(sources)
        self.assertIn("Groq text", result["markdown"])
        self.assertIn("Whisper text", result["markdown"])

    def test_primary_fallback_to_first(self):
        sources = [
            {"source_id": "groq", "segments": [{"start": 0.0, "end": 5.0, "text": "Hello"}], "has_timestamps": True, "text": ""},
            {"source_id": "local_whisper", "segments": [{"start": 10.0, "end": 15.0, "text": "World"}], "has_timestamps": True, "text": ""},
        ]
        result = transcript_merge.merge_transcripts_deterministic_n(sources, primary_source_id="nonexistent")
        self.assertIn("Hello", result["markdown"])
        self.assertIn("World", result["markdown"])
        self.assertEqual(result["stats"]["primary"], "groq")


class RawBundleTests(unittest.TestCase):
    def test_build_raw_bundle(self):
        sources = [
            {"source_id": "groq", "display_name": "Groq", "status": "success", "markdown": "Hello from Groq", "warnings": [], "errors": [], "model": "whisper-large-v3", "artifact_filename": "groq_test.md"},
            {"source_id": "local_whisper", "display_name": "Local Whisper", "status": "error", "markdown": "", "warnings": [], "errors": ["Model load failed"], "model": "", "artifact_filename": ""},
        ]
        bundle = transcript_merge.build_raw_bundle(sources, ["groq", "local_whisper"])
        self.assertIn("groq_test.md", bundle["report_markdown"])
        self.assertIn("Raw Transcriptions", bundle["report_markdown"])
        self.assertIn("Hello from Groq", bundle["report_markdown"])
        self.assertEqual(bundle["successful_source_ids"], ["groq"])
        self.assertEqual(bundle["failed_source_ids"], ["local_whisper"])
        self.assertEqual(bundle["artifacts"]["groq"], "groq_test.md")

    def test_empty_bundle(self):
        bundle = transcript_merge.build_raw_bundle([], [])
        self.assertIn("Selected: 0", bundle["report_markdown"])


class SettingsTests(unittest.TestCase):
    def test_new_settings_in_defaults(self):
        self.assertIn("transcription_sources", DEFAULT_SETTINGS)
        self.assertIn("multi_source_enabled", DEFAULT_SETTINGS)
        self.assertIn("merge_mode", DEFAULT_SETTINGS)
        self.assertIn("merge_primary_source", DEFAULT_SETTINGS)

    def test_new_settings_round_trip(self):
        from settings import save_settings, load_settings, SETTINGS_FILE

        original = json.loads(SETTINGS_FILE.read_text(encoding="utf-8")) if SETTINGS_FILE.exists() else {}
        try:
            save_settings({
                "transcription_sources": '["groq","local_whisper"]',
                "merge_mode": "raw",
                "merge_primary_source": "groq",
            })
            loaded = load_settings()
            self.assertEqual(loaded["transcription_sources"], '["groq","local_whisper"]')
            self.assertEqual(loaded["merge_mode"], "raw")
            self.assertEqual(loaded["merge_primary_source"], "groq")
        finally:
            if SETTINGS_FILE.exists():
                save_settings(original)


class MultiSourceOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self._old_tasks = main.tasks
        self._old_processing_urls = main.processing_urls
        self._old_active_tasks = main.active_tasks
        self._old_active_summary_tasks = main.active_summary_tasks
        self._old_video_processor = main.video_processor
        self._old_temp_dir = main.TEMP_DIR

        main.tasks = {}
        main.processing_urls = set()
        main.active_tasks = {}
        main.active_summary_tasks = {}
        self.temp_dir = PROJECT_ROOT / "temp" / "test_multi_source"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        main.TEMP_DIR = self.temp_dir

    def tearDown(self):
        main.tasks = self._old_tasks
        main.processing_urls = self._old_processing_urls
        main.active_tasks = self._old_active_tasks
        main.active_summary_tasks = self._old_active_summary_tasks
        main.video_processor = self._old_video_processor
        main.TEMP_DIR = self._old_temp_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_fake_processor(self, title="Multi Source Video"):
        class FakeVideoProcessor:
            async def fetch_subtitles(self, url, output_dir):
                return None, title, None, None

            async def download_and_convert(self, url, output_dir):
                audio_path = output_dir / "multi_test.m4a"
                audio_path.write_bytes(b"fake audio")
                return str(audio_path), title

            async def extract_audio_url(self, url):
                return {
                    "title": title,
                    "audio_url": "https://media.example/multi.m4a",
                }

        return FakeVideoProcessor()

    def _make_fake_transcriber(self, text_prefix):
        class FakeTranscriber:
            async def transcribe(self, audio_path, language=""):
                return {
                    "markdown": f"# Transcription\n\n{text_prefix} text",
                    "language": "en",
                    "warnings": [],
                    "raw": {
                        "segments": [
                            {"start": 0.0, "end": 5.0, "text": f"{text_prefix} text"},
                        ]
                    },
                    "model": f"{text_prefix}-model",
                }
        return FakeTranscriber()

    def test_multi_source_whisper_parakeet_system_merge(self):
        main.video_processor = self._make_fake_processor()
        task_id = "multi-wp-test"
        url = "https://youtu.be/multi-wp"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        def fake_prepare(backend, preset="", model_id=""):
            return self._make_fake_transcriber(backend), f"{backend}-resolved"

        with patch.object(main, "prepare_local_transcriber", side_effect=fake_prepare), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_sources_raw='["local_whisper","local_parakeet"]',
                    merge_mode_raw="system",
                    merge_primary_source="local_whisper",
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["transcription_provider_used"], "multi_source")
        self.assertEqual(task["transcript_source"], "multi_source_merged")
        self.assertIn("whisper", task["local_model_used"])
        self.assertIn("parakeet", task["local_model_used"])
        self.assertIsNotNone(task.get("multi_source_results"))

    def test_multi_source_running_update_exposes_concurrent_source_statuses(self):
        main.video_processor = self._make_fake_processor()
        task_id = "multi-status-test"
        url = "https://youtu.be/multi-status"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)
        observed_statuses = []
        original_push_task_update = main._push_task_update

        def fake_prepare(backend, preset="", model_id=""):
            return self._make_fake_transcriber(backend), f"{backend}-resolved"

        async def fake_push(task_id_arg, **kwargs):
            if "source_statuses" in kwargs:
                observed_statuses.append(kwargs["source_statuses"])
            await original_push_task_update(task_id_arg, **kwargs)

        with patch.object(main, "prepare_local_transcriber", side_effect=fake_prepare), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True), \
             patch.object(main, "_push_task_update", side_effect=fake_push):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_sources_raw='["platform","local_whisper","local_parakeet"]',
                    merge_mode_raw="system",
                    merge_primary_source="local_whisper",
                )
            )

        running_updates = [
            statuses for statuses in observed_statuses
            if {s["source_id"]: s["status"] for s in statuses}.get("local_whisper") == "running"
        ]
        self.assertTrue(running_updates)
        running_map = {s["source_id"]: s["status"] for s in running_updates[0]}
        self.assertEqual(running_map["local_whisper"], "running")
        self.assertEqual(running_map["local_parakeet"], "running")
        self.assertEqual(running_map["platform"], "failed")

    def test_multi_source_updates_fast_finished_source_while_slow_source_runs(self):
        main.video_processor = self._make_fake_processor()
        task_id = "multi-incremental-status-test"
        url = "https://youtu.be/multi-incremental-status"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)
        observed_statuses = []
        original_push_task_update = main._push_task_update

        class SlowTranscriber:
            async def transcribe(self, audio_path, language=""):
                await asyncio.sleep(0.05)
                return {
                    "markdown": "# Transcription\n\nslow local text",
                    "language": "en",
                    "warnings": [],
                    "raw": {
                        "segments": [
                            {"start": 0.0, "end": 5.0, "text": "slow local text"},
                        ]
                    },
                    "model": "slow-local-model",
                }

        class FastFailingGroq:
            async def transcribe_url(self, audio_url, language="", prompt=""):
                raise RuntimeError("failed to retrieve media: received status code: 302")

        def fake_prepare(backend, preset="", model_id=""):
            return SlowTranscriber(), f"{backend}-resolved"

        async def fake_push(task_id_arg, **kwargs):
            if "source_statuses" in kwargs:
                observed_statuses.append(kwargs["source_statuses"])
            await original_push_task_update(task_id_arg, **kwargs)

        with patch.object(main, "GroqURLTranscriber", return_value=FastFailingGroq()), \
             patch.object(main, "prepare_local_transcriber", side_effect=fake_prepare), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True), \
             patch.object(main, "_push_task_update", side_effect=fake_push):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_sources_raw='["groq","local_parakeet"]',
                    merge_mode_raw="raw",
                    groq_api_key="gsk-test",
                )
            )

        incremental_updates = [
            statuses for statuses in observed_statuses
            if {s["source_id"]: s["status"] for s in statuses}.get("groq") == "failed"
            and {s["source_id"]: s["status"] for s in statuses}.get("local_parakeet") == "running"
        ]
        self.assertTrue(incremental_updates)

    def test_interrupted_task_marks_running_sources_failed(self):
        tasks = {
            "interrupted": {
                "status": "processing",
                "source_statuses": [
                    {"source_id": "platform", "status": "completed", "detail": ""},
                    {"source_id": "groq", "status": "running", "detail": ""},
                    {"source_id": "local_parakeet", "status": "pending", "detail": ""},
                ],
            }
        }

        changed = main._mark_incomplete_tasks_as_interrupted(tasks)

        self.assertTrue(changed)
        statuses = {
            item["source_id"]: item
            for item in tasks["interrupted"]["source_statuses"]
        }
        self.assertEqual(statuses["platform"]["status"], "completed")
        self.assertEqual(statuses["groq"]["status"], "failed")
        self.assertEqual(statuses["local_parakeet"]["status"], "failed")
        self.assertIn("interrupted", statuses["groq"]["detail"])

    def test_existing_error_task_marks_running_sources_failed_on_startup(self):
        tasks = {
            "failed": {
                "status": "error",
                "error": "Processing failed.",
                "source_statuses": [
                    {"source_id": "groq", "status": "running", "detail": ""},
                    {"source_id": "local_parakeet", "status": "running", "detail": ""},
                ],
            }
        }

        changed = main._mark_incomplete_tasks_as_interrupted(tasks)

        self.assertTrue(changed)
        for item in tasks["failed"]["source_statuses"]:
            self.assertEqual(item["status"], "failed")
            self.assertEqual(item["detail"], "Processing failed.")

    def test_multi_source_groq_uses_file_upload_when_audio_is_available(self):
        main.video_processor = self._make_fake_processor()
        task_id = "multi-groq-file-direct-test"
        url = "https://youtu.be/multi-groq-file-direct"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        class FileOnlyGroq:
            def __init__(self):
                self.url_calls = 0
                self.file_calls = 0

            async def transcribe_url(self, audio_url, language="", prompt=""):
                self.url_calls += 1
                raise AssertionError("multi-source Groq should use the downloaded audio file")

            async def transcribe_file(self, audio_path, language="", prompt=""):
                self.file_calls += 1
                return {
                    "markdown": "# Transcription\n\nGroq file text",
                    "language": "en",
                    "warnings": [],
                    "raw": {
                        "segments": [
                            {"start": 0.0, "end": 5.0, "text": "Groq file text"},
                        ]
                    },
                    "model": "whisper-large-v3",
                }

        fake_groq = FileOnlyGroq()

        def fake_prepare(backend, preset="", model_id=""):
            return self._make_fake_transcriber(backend), f"{backend}-resolved"

        with patch.object(main, "GroqURLTranscriber", return_value=fake_groq), \
             patch.object(main, "prepare_local_transcriber", side_effect=fake_prepare), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_sources_raw='["groq","local_parakeet"]',
                    merge_mode_raw="raw",
                    groq_api_key="gsk-test",
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(fake_groq.url_calls, 0)
        self.assertEqual(fake_groq.file_calls, 1)
        status_by_source = {
            item["source_id"]: item["status"]
            for item in task.get("source_statuses", [])
        }
        self.assertEqual(status_by_source["groq"], "completed")
        self.assertIn("Groq file text", task["transcript"])
        self.assertNotIn("groq failed", " ".join(task.get("warnings") or []))

    def test_multi_source_groq_starts_before_local_model_prepare_finishes(self):
        main.video_processor = self._make_fake_processor()
        task_id = "multi-groq-start-order-test"
        url = "https://youtu.be/multi-groq-start-order"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)
        events = []

        class FastGroq:
            async def transcribe_file(self, audio_path, language="", prompt=""):
                events.append("groq_start")
                return {
                    "markdown": "# Transcription\n\nGroq text",
                    "language": "en",
                    "warnings": [],
                    "raw": {
                        "segments": [
                            {"start": 0.0, "end": 5.0, "text": "Groq text"},
                        ]
                    },
                    "model": "whisper-large-v3",
                }

        def slow_prepare(backend, preset="", model_id=""):
            events.append("prepare_start")
            import time
            time.sleep(0.05)
            events.append("prepare_done")
            return self._make_fake_transcriber(backend), f"{backend}-resolved"

        with patch.object(main, "GroqURLTranscriber", return_value=FastGroq()), \
             patch.object(main, "prepare_local_transcriber", side_effect=slow_prepare), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_sources_raw='["groq","local_parakeet"]',
                    merge_mode_raw="raw",
                    groq_api_key="gsk-test",
                )
            )

        self.assertIn("groq_start", events)
        self.assertIn("prepare_done", events)
        self.assertLess(events.index("groq_start"), events.index("prepare_done"))

    def test_multi_source_groq_prompt_includes_video_title_spelling_context(self):
        main.video_processor = self._make_fake_processor(
            title="Claude Opus 4.7 vs Gemini 3.1 Pro vs GPT-5.5"
        )
        task_id = "multi-groq-title-prompt-test"
        url = "https://youtu.be/multi-groq-title-prompt"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)
        prompts = []

        class PromptRecordingGroq:
            async def transcribe_url(self, audio_url, language="", prompt=""):
                prompts.append(prompt)
                return {
                    "markdown": "# Transcription\n\nClaude Opus text",
                    "language": "en",
                    "warnings": [],
                    "raw": {
                        "segments": [
                            {"start": 0.0, "end": 5.0, "text": "Claude Opus text"},
                        ]
                    },
                    "model": "whisper-large-v3",
                }

            async def transcribe_file(self, audio_path, language="", prompt=""):
                prompts.append(prompt)
                return {
                    "markdown": "# Transcription\n\nClaude Opus text",
                    "language": "en",
                    "warnings": [],
                    "raw": {
                        "segments": [
                            {"start": 0.0, "end": 5.0, "text": "Claude Opus text"},
                        ]
                    },
                    "model": "whisper-large-v3",
                }

        with patch.object(main, "GroqURLTranscriber", return_value=PromptRecordingGroq()), \
             patch.object(main, "backend_dependencies_available", return_value=True):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_sources_raw='["groq"]',
                    merge_mode_raw="raw",
                    groq_api_key="gsk-test",
                    groq_prompt="Prefer exact model names.",
                )
            )

        self.assertTrue(prompts)
        self.assertIn("Terms:", prompts[0])
        self.assertIn("Claude Opus 4.7", prompts[0])
        self.assertIn("GPT-5.5", prompts[0])
        self.assertIn("Prefer exact model names.", prompts[0])
        self.assertNotIn("Use exact spelling", prompts[0])

    def test_title_entity_corrections_normalize_common_asr_name_errors(self):
        title = "БИТВА ТИТАНОВ! Claude Opus 4.7 vs Gemini 3.1 Pro vs GPT-5.5"
        text = (
            "Clot Opus 4.7, GBT 5.5 and GMini 3.1 Pro. "
            "Клод Опус is between GMI, Gepit-55 and GPT 5.5."
        )

        corrected = main._apply_title_entity_corrections(text, title)

        self.assertIn("Claude Opus 4.7", corrected)
        self.assertIn("Gemini 3.1 Pro", corrected)
        self.assertIn("GPT-5.5", corrected)
        self.assertNotIn("Clot", corrected)
        self.assertNotIn("GBT", corrected)
        self.assertNotIn("Gepit", corrected)
        self.assertNotIn("GMini", corrected)
        self.assertNotIn("GMI", corrected)
        self.assertNotIn("Клод Опус", corrected)

    def test_explicit_platform_source_fetches_subtitles_even_when_legacy_flag_is_off(self):
        class FakeVideoProcessor:
            def __init__(self):
                self.subtitle_calls = 0

            async def fetch_subtitles(self, url, output_dir):
                self.subtitle_calls += 1
                return (
                    "# Video Transcription\n\n**Detected Language:** ru\n\nPlatform subtitle text",
                    "Platform Explicit",
                    "ru",
                    "youtube_auto_subtitles",
                )

            async def download_and_convert(self, url, output_dir):
                audio_path = output_dir / "explicit_platform.m4a"
                audio_path.write_bytes(b"fake audio")
                return str(audio_path), "Platform Explicit"

            async def extract_audio_url(self, url):
                return {
                    "title": "Platform Explicit",
                    "audio_url": "https://media.example/platform-explicit.m4a",
                }

        main.video_processor = FakeVideoProcessor()
        task_id = "multi-explicit-platform-test"
        url = "https://youtu.be/explicit-platform"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        def fake_prepare(backend, preset="", model_id=""):
            return self._make_fake_transcriber(backend), f"{backend}-resolved"

        with patch.object(main, "prepare_local_transcriber", side_effect=fake_prepare), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    try_subtitles_first=False,
                    transcription_sources_raw='["platform","local_parakeet"]',
                    merge_mode_raw="raw",
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(main.video_processor.subtitle_calls, 1)
        status_by_source = {
            item["source_id"]: item["status"]
            for item in task.get("source_statuses", [])
        }
        self.assertEqual(status_by_source["platform"], "completed")
        self.assertNotIn(
            "Platform subtitles requested but none found.",
            " ".join(task.get("warnings") or []),
        )

    def test_ai_merge_transcript_source_label_is_human_readable(self):
        class FakeVideoProcessor:
            async def fetch_subtitles(self, url, output_dir):
                return (
                    "# Video Transcription\n\n**Detected Language:** ru\n\nPlatform text",
                    "AI Label",
                    "ru",
                    "youtube_auto_subtitles",
                )

            async def download_and_convert(self, url, output_dir):
                audio_path = output_dir / "ai_label.m4a"
                audio_path.write_bytes(b"fake audio")
                return str(audio_path), "AI Label"

        async def fake_ai_merge(sources, **kwargs):
            return {"markdown": "AI merged text", "stats": {"ai_merge": True}}

        main.video_processor = FakeVideoProcessor()
        task_id = "multi-ai-label-test"
        url = "https://youtu.be/multi-ai-label"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        def fake_prepare(backend, preset="", model_id=""):
            return self._make_fake_transcriber(backend), "nvidia/parakeet-tdt-0.6b-v3"

        with patch.object(main, "prepare_local_transcriber", side_effect=fake_prepare), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True), \
             patch.object(main, "merge_transcripts_ai_n", side_effect=fake_ai_merge):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_sources_raw='["platform","local_parakeet"]',
                    merge_mode_raw="ai",
                    merge_api_key="sk-test",
                    merge_base_url="https://api.example/v1",
                    merge_model="merge-model",
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task.get("multi_source_results", {}).get("merge_mode"), "ai")
        self.assertIn(
            "AI-merged multi-source transcription",
            task["transcript"],
        )
        self.assertIn("Platform subtitles + Local Parakeet", task["transcript"])
        self.assertNotIn("platform=+", task["transcript"])

    def test_multi_source_raw_bundle(self):
        main.video_processor = self._make_fake_processor()
        task_id = "multi-raw-test"
        url = "https://youtu.be/multi-raw"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        def fake_prepare(backend, preset="", model_id=""):
            return self._make_fake_transcriber(backend), f"{backend}-resolved"

        with patch.object(main, "prepare_local_transcriber", side_effect=fake_prepare), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_sources_raw='["local_whisper","local_parakeet"]',
                    merge_mode_raw="raw",
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["transcript_source"], "raw_bundle")
        self.assertIn("Raw Bundle", task["transcript"])
        self.assertIsNotNone(task.get("multi_source_results"))

    def test_multi_source_all_failed(self):
        main.video_processor = self._make_fake_processor()
        task_id = "multi-fail-test"
        url = "https://youtu.be/multi-fail"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        class FailingTranscriber:
            async def transcribe(self, audio_path, language=""):
                raise RuntimeError("transcription engine crashed")

        def fake_prepare(backend, preset="", model_id=""):
            return FailingTranscriber(), f"{backend}-resolved"

        with patch.object(main, "prepare_local_transcriber", side_effect=fake_prepare), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_sources_raw='["local_whisper","local_parakeet"]',
                    merge_mode_raw="system",
                    merge_primary_source="local_whisper",
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "error")
        self.assertIn("failed", task["error"].lower())

    def test_backward_compat_dual_local_still_works(self):
        main.video_processor = self._make_fake_processor()
        task_id = "compat-dual-test"
        url = "https://youtu.be/compat-dual"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        def fake_prepare(backend, preset="", model_id=""):
            return self._make_fake_transcriber(backend), f"{backend}-resolved"

        with patch.object(main, "prepare_local_transcriber", side_effect=fake_prepare), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_provider="local",
                    dual_local_transcription=True,
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["transcription_provider_used"], "dual_local")
        self.assertEqual(task["transcript_source"], "dual_local_merged")

    def test_backward_compat_single_groq(self):
        class FakeVideoProcessor:
            async def fetch_subtitles(self, url, output_dir):
                return None, "Compat Groq", None, None

            async def extract_audio_url(self, url):
                return {"title": "Compat Groq", "audio_url": "https://media.example/compat.m4a"}

        class FakeGroq:
            async def transcribe_url(self, audio_url, language="", prompt=""):
                return {"markdown": "Compat groq text", "language": "en"}

        main.video_processor = FakeVideoProcessor()
        task_id = "compat-groq-test"
        url = "https://youtu.be/compat-groq"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        with patch.object(main, "GroqURLTranscriber", return_value=FakeGroq()):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_provider="groq",
                    groq_api_key="gsk-test",
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["transcription_provider_used"], "groq")

    def test_stale_dual_local_flag_is_ignored_for_groq_provider(self):
        class FakeVideoProcessor:
            async def fetch_subtitles(self, url, output_dir):
                return None, "Compat Groq Stale Dual", None, None

            async def extract_audio_url(self, url):
                return {
                    "title": "Compat Groq Stale Dual",
                    "audio_url": "https://media.example/compat-stale-dual.m4a",
                }

        class FakeGroq:
            async def transcribe_url(self, audio_url, language="", prompt=""):
                return {"markdown": "Compat groq text", "language": "en"}

        main.video_processor = FakeVideoProcessor()
        task_id = "compat-groq-stale-dual-test"
        url = "https://youtu.be/compat-groq-stale-dual"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        with patch.object(main, "GroqURLTranscriber", return_value=FakeGroq()):
            asyncio.run(
                main.process_video_task(
                    task_id,
                    url,
                    transcription_provider="groq",
                    dual_local_transcription=True,
                    groq_api_key="gsk-test",
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["transcription_provider_used"], "groq")
        self.assertNotIn("Dual local transcription requires", task.get("error") or "")

    def test_multi_source_invalid_source_string_raises(self):
        task_id = "invalid-source-test"
        main.tasks[task_id] = {"status": "processing", "url": ""}
        main.processing_urls.clear()

        asyncio.run(
            main.process_video_task(
                task_id, "",
                transcription_sources_raw='["nonexistent_source"]',
            )
        )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "error")


class CLISourceArgsTests(unittest.TestCase):
    def test_cli_parser_accepts_source_args(self):
        sys.path.insert(0, str(PROJECT_ROOT))
        from cli import build_parser
        parser = build_parser()
        args = parser.parse_args([
            "transcribe", "--url", "https://youtu.be/test",
            "--source", "groq,local_whisper",
            "--merge-mode", "system",
            "--merge-primary-source", "groq",
        ])
        self.assertEqual(args.source, "groq,local_whisper")
        self.assertEqual(args.merge_mode, "system")
        self.assertEqual(args.merge_primary_source, "groq")


class FrontendMultiSourceTests(unittest.TestCase):
    def test_frontend_includes_multi_source_i18n(self):
        app_js = (PROJECT_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("multi_source_section", app_js)
        self.assertIn("transcription_sources_label", app_js)
        self.assertIn("merge_mode_label", app_js)
        self.assertIn("merge_primary_source", app_js)
        self.assertIn("source-checkbox", app_js)
        self.assertIn("_getSelectedSources", app_js)
        self.assertIn("_syncMultiSourceSettings", app_js)

    def test_index_html_has_source_checkboxes(self):
        index_html = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="multiSourceEnabledInput"', index_html)
        self.assertIn('data-i18n="multi_source_enable"', index_html)
        self.assertIn('id="sourceCheckboxes"', index_html)
        self.assertIn('id="mergeModeSelect"', index_html)
        self.assertIn('id="mergePrimarySourceSelect"', index_html)
        self.assertIn('value="platform"', index_html)
        self.assertIn('value="groq"', index_html)
        self.assertIn('value="local_whisper"', index_html)
        self.assertIn('value="local_parakeet"', index_html)

    def test_checkbox_container_excluded_from_hide_toggle(self):
        app_js = (PROJECT_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("ms-source-picker", app_js)

    def test_checkbox_container_has_picker_class(self):
        index_html = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("ms-source-picker", index_html)

    def test_primary_source_always_sent(self):
        app_js = (PROJECT_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("fd.append('merge_primary_source', msPrimary)", app_js)

    def test_primary_source_auto_option_removed(self):
        index_html = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("Auto (first selected)", index_html)
        self.assertNotIn('data-i18n="merge_primary_auto"', index_html)

    def test_frontend_blocks_system_merge_without_primary(self):
        app_js = (PROJECT_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("A primary source is required for system merge.", app_js)
        self.assertIn("msMergeMode === 'system' && msSources.length > 1 && !msPrimary", app_js)

    def test_frontend_requires_high_level_multi_source_flag(self):
        app_js = (PROJECT_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("multiSourceEnabledInput", app_js)
        self.assertIn("if (!this.multiSourceEnabledInput?.checked) return []", app_js)
        self.assertIn("Select at least one transcription source or disable multi-source transcription.", app_js)
        self.assertIn("multi_source_enabled", app_js)

    def test_frontend_renders_concurrent_source_statuses(self):
        app_js = (PROJECT_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        index_html = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="sourceStatusPanel"', index_html)
        self.assertIn("_renderSourceStatuses", app_js)
        self.assertIn("source-status-card", app_js)
        self.assertIn("source_status_running", app_js)

    def test_frontend_polls_task_status_while_sse_is_open(self):
        app_js = (PROJECT_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        index_html = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("statusPollTimer", app_js)
        self.assertIn("_startStatusPolling", app_js)
        self.assertIn("_handleTaskUpdate(task)", app_js)
        self.assertIn("fetch(`${this.apiBase}/task-status/${this.currentTaskId}`)", app_js)
        self.assertIn("app.js?v=20260518-multi-source-gate", index_html)

    def test_frontend_does_not_submit_stale_dual_local_for_groq(self):
        app_js = (PROJECT_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("if (!isLocal && this.dualLocalInput?.checked)", app_js)
        self.assertIn("this.dualLocalInput.checked = false", app_js)
        self.assertIn("transcriptionProvider === 'local' && msSources.length === 0", app_js)
        self.assertIn("fd.append('dual_local_transcription', dualLocal ? 'true' : 'false')", app_js)

    def test_settings_panel_height_allows_expanded_multi_source_controls(self):
        index_html = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn(".settings-body.open", index_html)
        self.assertIn("max-height: 5000px", index_html)
        self.assertIn("overflow: visible", index_html)

    def test_merge_ai_models_can_be_fetched_from_models_endpoint(self):
        app_js = (PROJECT_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        index_html = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="msMergeFetchModelsBtn"', index_html)
        self.assertIn('id="msMergeFetchStatus"', index_html)
        self.assertIn("_fetchMergeModels", app_js)
        self.assertIn("fetch(`${this.apiBase}/models`", app_js)
        self.assertIn("this.msMergeModelInput.appendChild(opt)", app_js)


class SingleSourceNewAPITests(unittest.TestCase):
    """Regression: single-source via new transcription_sources_raw API."""

    def setUp(self):
        self._old_tasks = main.tasks
        self._old_processing_urls = main.processing_urls
        self._old_active_tasks = main.active_tasks
        self._old_active_summary_tasks = main.active_summary_tasks
        self._old_video_processor = main.video_processor
        self._old_temp_dir = main.TEMP_DIR

        main.tasks = {}
        main.processing_urls = set()
        main.active_tasks = {}
        main.active_summary_tasks = {}
        self.temp_dir = PROJECT_ROOT / "temp" / "test_single_source"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        main.TEMP_DIR = self.temp_dir

    def tearDown(self):
        main.tasks = self._old_tasks
        main.processing_urls = self._old_processing_urls
        main.active_tasks = self._old_active_tasks
        main.active_summary_tasks = self._old_active_summary_tasks
        main.video_processor = self._old_video_processor
        main.TEMP_DIR = self._old_temp_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_fake_processor(self, title="Single Source Video"):
        class FakeVideoProcessor:
            async def fetch_subtitles(self, url, output_dir):
                return None, title, None, None

            async def download_and_convert(self, url, output_dir):
                audio_path = output_dir / "single_test.m4a"
                audio_path.write_bytes(b"fake audio")
                return str(audio_path), title

            async def extract_audio_url(self, url):
                return {
                    "title": title,
                    "audio_url": "https://media.example/single.m4a",
                }

        return FakeVideoProcessor()

    def _make_fake_transcriber(self, text):
        class FakeTranscriber:
            async def transcribe(self, audio_path, language=""):
                return {
                    "markdown": f"# Transcription\n\n{text}",
                    "language": "en",
                    "warnings": [],
                    "raw": {"segments": [{"start": 0.0, "end": 5.0, "text": text}]},
                    "model": "test-model",
                }
        return FakeTranscriber()

    def test_single_local_whisper_via_new_api(self):
        main.video_processor = self._make_fake_processor()
        task_id = "single-whisper-test"
        url = "https://youtu.be/single-whisper"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        with patch.object(main, "prepare_local_transcriber", return_value=(self._make_fake_transcriber("whisper text"), "whisper-base")), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_sources_raw='["local_whisper"]',
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "completed")
        self.assertIn("whisper text", task["transcript"])
        self.assertEqual(task["transcript_source"], "local_whisper")

    def test_single_local_parakeet_via_new_api(self):
        main.video_processor = self._make_fake_processor()
        task_id = "single-parakeet-test"
        url = "https://youtu.be/single-parakeet"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        with patch.object(main, "prepare_local_transcriber", return_value=(self._make_fake_transcriber("parakeet text"), "parakeet-tdt")), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_sources_raw='["local_parakeet"]',
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "completed")
        self.assertIn("parakeet text", task["transcript"])
        self.assertEqual(task["transcript_source"], "local_parakeet")

    def test_single_groq_via_new_api(self):
        class FakeVideoProcessor:
            async def fetch_subtitles(self, url, output_dir):
                return None, "Single Groq", None, None

            async def download_and_convert(self, url, output_dir):
                audio_path = output_dir / "single_groq.m4a"
                audio_path.write_bytes(b"fake audio")
                return str(audio_path), "Single Groq"

            async def extract_audio_url(self, url):
                return {"title": "Single Groq", "audio_url": "https://media.example/single.m4a"}

        class FakeGroq:
            async def transcribe_url(self, audio_url, language="", prompt=""):
                return {"markdown": "Single groq result", "language": "en"}

        main.video_processor = FakeVideoProcessor()
        task_id = "single-groq-test"
        url = "https://youtu.be/single-groq"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        with patch.object(main, "GroqURLTranscriber", return_value=FakeGroq()):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_sources_raw='["groq"]',
                    groq_api_key="gsk-test",
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["transcription_provider_used"], "groq")
        self.assertEqual(task["transcript_source"], "groq")

    def test_single_groq_url_input_uses_downloaded_file_when_supported(self):
        main.video_processor = self._make_fake_processor(title="Single Groq File")
        task_id = "single-groq-url-file-test"
        url = "https://youtu.be/single-groq-url-file"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        class FakeGroq:
            def __init__(self):
                self.file_calls = []
                self.url_calls = []

            async def transcribe_file(self, audio_path, language="", prompt=""):
                self.file_calls.append((audio_path, language, prompt))
                return {"markdown": "Single groq file result", "language": "en"}

            async def transcribe_url(self, audio_url, language="", prompt=""):
                self.url_calls.append((audio_url, language, prompt))
                raise AssertionError("single-source Groq URL input should use downloaded file")

        fake_groq = FakeGroq()
        with patch.object(main, "GroqURLTranscriber", return_value=fake_groq):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_sources_raw='["groq"]',
                    groq_api_key="gsk-test",
                    groq_prompt="Prefer exact names.",
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(len(fake_groq.file_calls), 1)
        self.assertEqual(fake_groq.url_calls, [])
        self.assertIn("Single Groq File", fake_groq.file_calls[0][2])
        self.assertIn("Prefer exact names.", fake_groq.file_calls[0][2])
        self.assertIn("Single groq file result", task["transcript"])

    def test_single_groq_uploaded_file_via_new_api_uses_file_path(self):
        class FakeVideoProcessor:
            async def fetch_subtitles(self, url, output_dir):
                return None, "Single Groq Upload", None, None

        class FakeGroq:
            def __init__(self):
                self.file_calls = []
                self.url_calls = []

            async def transcribe_file(self, audio_path, language="", prompt=""):
                self.file_calls.append((audio_path, language, prompt))
                return {"markdown": "Single groq upload result", "language": "en"}

            async def transcribe_url(self, audio_url, language="", prompt=""):
                self.url_calls.append((audio_url, language, prompt))
                return {"markdown": "wrong path", "language": "en"}

        main.video_processor = FakeVideoProcessor()
        task_id = "single-groq-upload-test"
        audio_path = self.temp_dir / "single_groq_upload.wav"
        audio_path.write_bytes(b"fake audio")
        main.tasks[task_id] = {"status": "processing", "url": ""}

        fake_groq = FakeGroq()
        with patch.object(main, "GroqURLTranscriber", return_value=fake_groq):
            asyncio.run(
                main.process_video_task(
                    task_id, "",
                    transcription_sources_raw='["groq"]',
                    groq_api_key="gsk-test",
                    source_file_path=str(audio_path),
                    source_file_name="single_groq_upload.wav",
                    source_title="Single Groq Upload",
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["transcript_source"], "groq")
        self.assertEqual(len(fake_groq.file_calls), 1)
        self.assertEqual(fake_groq.url_calls, [])
        self.assertIn("Single groq upload result", task["transcript"])

    def test_single_local_whisper_raw_bundle_respects_merge_mode(self):
        main.video_processor = self._make_fake_processor()
        task_id = "single-whisper-raw-bundle-test"
        url = "https://youtu.be/single-whisper-raw"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        with patch.object(main, "prepare_local_transcriber", return_value=(self._make_fake_transcriber("whisper raw"), "whisper-base")), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_sources_raw='["local_whisper"]',
                    merge_mode_raw="raw",
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["transcript_source"], "raw_bundle")
        self.assertIn("Raw Bundle", task["transcript"])
        self.assertIn("local_whisper", task["transcript"])

    def test_single_platform_no_subtitles_raises(self):
        class FakeVideoProcessor:
            async def fetch_subtitles(self, url, output_dir):
                return None, "No Subs", None, None

        main.video_processor = FakeVideoProcessor()
        task_id = "single-platform-nosubs-test"
        url = "https://youtu.be/single-platform-nosubs"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        asyncio.run(
            main.process_video_task(
                task_id, url,
                transcription_sources_raw='["platform"]',
            )
        )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "error")
        self.assertIn("platform", task["error"].lower())


class MissingPlatformRecordingTests(unittest.TestCase):
    """Regression: missing platform should be recorded as failed source."""

    def setUp(self):
        self._old_tasks = main.tasks
        self._old_processing_urls = main.processing_urls
        self._old_active_tasks = main.active_tasks
        self._old_active_summary_tasks = main.active_summary_tasks
        self._old_video_processor = main.video_processor
        self._old_temp_dir = main.TEMP_DIR

        main.tasks = {}
        main.processing_urls = set()
        main.active_tasks = {}
        main.active_summary_tasks = {}
        self.temp_dir = PROJECT_ROOT / "temp" / "test_missing_platform"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        main.TEMP_DIR = self.temp_dir

    def tearDown(self):
        main.tasks = self._old_tasks
        main.processing_urls = self._old_processing_urls
        main.active_tasks = self._old_active_tasks
        main.active_summary_tasks = self._old_active_summary_tasks
        main.video_processor = self._old_video_processor
        main.TEMP_DIR = self._old_temp_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_missing_platform_recorded_as_failed_in_multi_source(self):
        class FakeVideoProcessor:
            async def fetch_subtitles(self, url, output_dir):
                return None, "No Subs Video", None, None

            async def download_and_convert(self, url, output_dir):
                audio_path = output_dir / "noplat.m4a"
                audio_path.write_bytes(b"fake audio")
                return str(audio_path), "No Subs Video"

            async def extract_audio_url(self, url):
                return {"title": "No Subs Video", "audio_url": "https://media.example/noplat.m4a"}

        main.video_processor = FakeVideoProcessor()
        task_id = "missing-plat-test"
        url = "https://youtu.be/missing-plat"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        class FakeGroq:
            async def transcribe_url(self, audio_url, language="", prompt=""):
                return {"markdown": "Groq result", "language": "en"}

        with patch.object(main, "GroqURLTranscriber", return_value=FakeGroq()):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_sources_raw='["platform","groq"]',
                    merge_mode_raw="system",
                    merge_primary_source="groq",
                    groq_api_key="gsk-test",
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "completed")
        ms_meta = task.get("multi_source_results", {})
        self.assertIn("platform", ms_meta.get("failed", []))

    def test_partial_success_deduplicates_failed_source_warnings_and_detects_cyrillic(self):
        class FakeVideoProcessor:
            async def fetch_subtitles(self, url, output_dir):
                return None, "Russian Partial", None, None

            async def download_and_convert(self, url, output_dir):
                audio_path = output_dir / "partial_ru.m4a"
                audio_path.write_bytes(b"fake audio")
                return str(audio_path), "Russian Partial"

            async def extract_audio_url(self, url):
                return {"title": "Russian Partial", "audio_url": "https://media.example/partial_ru.m4a"}

        class FailingGroq:
            async def transcribe_url(self, audio_url, language="", prompt=""):
                raise RuntimeError("context deadline exceeded")

        class RussianParakeet:
            async def transcribe(self, audio_path, language=""):
                return {
                    "markdown": "Страшно! Очень страшно",
                    "language": "",
                    "warnings": ["Parakeet is running on CPU and may be slow."],
                    "raw": {
                        "segments": [
                            {"start": 0.0, "end": 3.0, "text": "Страшно! Очень страшно"}
                        ]
                    },
                    "model": "nvidia/parakeet-tdt-0.6b-v3",
                }

        main.video_processor = FakeVideoProcessor()
        task_id = "partial-ru-test"
        url = "https://youtu.be/partial-ru"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        with patch.object(main, "GroqURLTranscriber", return_value=FailingGroq()), \
             patch.object(main, "prepare_local_transcriber", return_value=(RussianParakeet(), "nvidia/parakeet-tdt-0.6b-v3")), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_sources_raw='["platform","groq","local_parakeet"]',
                    merge_mode_raw="system",
                    merge_primary_source="groq",
                    groq_api_key="gsk-test",
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["detected_language"], "ru")
        warnings_text = " | ".join(task.get("warnings", []))
        self.assertEqual(warnings_text.count("groq failed: context deadline exceeded"), 1)
        self.assertEqual(warnings_text.count("platform failed: Platform subtitles requested but none found."), 1)
        self.assertIn("Primary source 'groq' was selected but failed or unavailable", warnings_text)


class PrimarySourceEnforcementTests(unittest.TestCase):
    """Regression: primary source warning when selected but unavailable."""

    def setUp(self):
        self._old_tasks = main.tasks
        self._old_processing_urls = main.processing_urls
        self._old_active_tasks = main.active_tasks
        self._old_active_summary_tasks = main.active_summary_tasks
        self._old_video_processor = main.video_processor
        self._old_temp_dir = main.TEMP_DIR

        main.tasks = {}
        main.processing_urls = set()
        main.active_tasks = {}
        main.active_summary_tasks = {}
        self.temp_dir = PROJECT_ROOT / "temp" / "test_primary"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        main.TEMP_DIR = self.temp_dir

    def tearDown(self):
        main.tasks = self._old_tasks
        main.processing_urls = self._old_processing_urls
        main.active_tasks = self._old_active_tasks
        main.active_summary_tasks = self._old_active_summary_tasks
        main.video_processor = self._old_video_processor
        main.TEMP_DIR = self._old_temp_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_unavailable_primary_source_warns(self):
        class FakeVideoProcessor:
            async def fetch_subtitles(self, url, output_dir):
                return None, "Primary Test", None, None

            async def download_and_convert(self, url, output_dir):
                audio_path = output_dir / "primary.m4a"
                audio_path.write_bytes(b"fake audio")
                return str(audio_path), "Primary Test"

        main.video_processor = FakeVideoProcessor()
        task_id = "primary-warn-test"
        url = "https://youtu.be/primary-warn"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        def fake_prepare(backend, preset="", model_id=""):
            return _make_transcriber(f"{backend} text"), f"{backend}-resolved"

        with patch.object(main, "prepare_local_transcriber", side_effect=fake_prepare), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_sources_raw='["local_whisper","local_parakeet"]',
                    merge_mode_raw="system",
                    merge_primary_source="local_parakeet",
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "completed")
        ms_meta = task.get("multi_source_results", {})
        self.assertEqual(ms_meta.get("merge_mode"), "deterministic")
        self.assertEqual(ms_meta.get("merge_stats", {}).get("primary"), "local_parakeet")

    def test_system_merge_requires_primary_source(self):
        class FakeVideoProcessor:
            async def fetch_subtitles(self, url, output_dir):
                return None, "Primary Required", None, None

            async def download_and_convert(self, url, output_dir):
                audio_path = output_dir / "primary_required.m4a"
                audio_path.write_bytes(b"fake audio")
                return str(audio_path), "Primary Required"

        main.video_processor = FakeVideoProcessor()
        task_id = "primary-required-test"
        url = "https://youtu.be/primary-required"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        def fake_prepare(backend, preset="", model_id=""):
            return _make_transcriber(f"{backend} text"), f"{backend}-resolved"

        with patch.object(main, "prepare_local_transcriber", side_effect=fake_prepare), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_sources_raw='["local_whisper","local_parakeet"]',
                    merge_mode_raw="system",
                    merge_primary_source="",
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "error")
        self.assertIn("primary source", task["error"].lower())

    def test_system_merge_primary_must_be_selected_source(self):
        class FakeVideoProcessor:
            async def fetch_subtitles(self, url, output_dir):
                return None, "Primary Selected", None, None

            async def download_and_convert(self, url, output_dir):
                audio_path = output_dir / "primary_selected.m4a"
                audio_path.write_bytes(b"fake audio")
                return str(audio_path), "Primary Selected"

        main.video_processor = FakeVideoProcessor()
        task_id = "primary-selected-test"
        url = "https://youtu.be/primary-selected"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        def fake_prepare(backend, preset="", model_id=""):
            return _make_transcriber(f"{backend} text"), f"{backend}-resolved"

        with patch.object(main, "prepare_local_transcriber", side_effect=fake_prepare), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True):
            asyncio.run(
                main.process_video_task(
                    task_id, url,
                    transcription_sources_raw='["local_whisper","local_parakeet"]',
                    merge_mode_raw="system",
                    merge_primary_source="groq",
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "error")
        self.assertIn("selected transcription sources", task["error"].lower())


class RawBundleNotRunStatusTests(unittest.TestCase):
    """Regression: selected-but-not-run sources show 'not_run' in raw bundle."""

    def test_missing_selected_source_shows_not_run(self):
        sources = [
            {"source_id": "groq", "display_name": "Groq", "status": "success", "markdown": "Hello", "warnings": [], "errors": [], "model": "", "artifact_filename": "groq.md"},
        ]
        bundle = transcript_merge.build_raw_bundle(sources, ["groq", "local_whisper"])
        self.assertIn("not_run", bundle["report_markdown"])
        self.assertIn("local_whisper", bundle["report_markdown"])


class CLISourceBypassGroqKeyTests(unittest.TestCase):
    """Regression: --source local_whisper should not require Groq key."""

    def test_source_local_whisper_no_groq_key(self):
        import argparse
        sys.path.insert(0, str(PROJECT_ROOT))
        from cli import _run_transcribe
        args = argparse.Namespace(
            url="https://youtu.be/test-no-groq",
            file=None,
            provider="groq",
            groq_api_key="",
            groq_model="",
            language="",
            local_backend="whisper",
            local_model="base",
            local_api_base_url="",
            local_api_key="",
            local_api_model="",
            local_api_language="",
            local_api_prompt="",
            dual_local=False,
            dual_whisper_model_preset="base",
            dual_whisper_model_id="",
            dual_parakeet_model_preset="",
            dual_parakeet_model_id="",
            merge_use_ai=False,
            merge_base_url="",
            merge_api_key="",
            merge_model="",
            merge_prompt="",
            merge_reasoning_effort="",
            source="local_whisper",
            merge_mode="",
            merge_primary_source="",
            skip_subtitles=False,
            include_timecodes=True,
        )
        result = asyncio.run(_run_transcribe(args))
        # Should NOT be the Groq key error; the task may fail for other reasons
        # (no real backend), but the key validation gate should be bypassed.
        if isinstance(result, dict) and "error" in result:
            self.assertNotIn("Groq API key", result["error"])


def _make_transcriber(text_prefix):
    class FakeTranscriber:
        async def transcribe(self, audio_path, language=""):
            return {
                "markdown": f"# Transcription\n\n{text_prefix} text",
                "language": "en",
                "warnings": [],
                "raw": {
                    "segments": [
                        {"start": 0.0, "end": 5.0, "text": f"{text_prefix} text"},
                    ]
                },
                "model": f"{text_prefix}-model",
            }
    return FakeTranscriber()


if __name__ == "__main__":
    unittest.main()
