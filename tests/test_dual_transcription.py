import asyncio
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import main  # noqa: E402
import transcript_merge  # noqa: E402
from settings import DEFAULT_SETTINGS  # noqa: E402


class TranscriptMergeTests(unittest.TestCase):
    def test_normalize_extracts_timestamped_segments(self):
        result = {
            "raw": {
                "segments": [
                    {"start": "00:00", "end": "00:05", "text": "Hello"},
                    {"start": "00:05", "end": "00:10", "text": "World"},
                ]
            }
        }
        normalized = transcript_merge.normalize_transcription_result(result, "whisper")
        self.assertEqual(len(normalized["segments"]), 2)
        self.assertEqual(normalized["segments"][0]["text"], "Hello")
        self.assertEqual(normalized["source"], "whisper")

    def test_normalize_falls_back_to_paragraph_chunks(self):
        result = {"raw": {"text": "Para one\n\nPara two"}}
        normalized = transcript_merge.normalize_transcription_result(result, "parakeet")
        self.assertEqual(len(normalized["segments"]), 2)
        self.assertIsNone(normalized["segments"][0]["start"])

    def test_normalize_empty_result(self):
        result = {"raw": {}}
        normalized = transcript_merge.normalize_transcription_result(result, "whisper")
        self.assertEqual(normalized["segments"], [])

    def test_deterministic_merge_whisper_primary(self):
        whisper = {
            "raw": {
                "segments": [
                    {"start": "00:00", "end": "00:05", "text": "Hello"},
                    {"start": "00:05", "end": "00:10", "text": "World"},
                ]
            }
        }
        parakeet = {
            "raw": {
                "segments": [
                    {"start": "00:00", "end": "00:05", "text": "Hello"},
                    {"start": "00:05", "end": "00:10", "text": "World"},
                ]
            }
        }
        merged = transcript_merge.merge_transcripts_deterministic(whisper, parakeet)
        self.assertIn("Hello", merged["markdown"])
        self.assertIn("World", merged["markdown"])
        self.assertEqual(merged["stats"]["whisper_segments"], 2)

    def test_deterministic_merge_includes_parakeet_text_for_empty_whisper_spans(self):
        whisper = {
            "raw": {
                "segments": [
                    {"start": "00:00", "end": "00:05", "text": ""},
                    {"start": "00:05", "end": "00:10", "text": "World"},
                ]
            }
        }
        parakeet = {
            "raw": {
                "segments": [
                    {"start": "00:00", "end": "00:05", "text": "Filled by parakeet"},
                    {"start": "00:05", "end": "00:10", "text": "World"},
                ]
            }
        }
        merged = transcript_merge.merge_transcripts_deterministic(whisper, parakeet)
        self.assertIn("Filled by parakeet", merged["markdown"])
        self.assertIn("World", merged["markdown"])
        self.assertGreaterEqual(merged["stats"]["parakeet_fill_count"], 1)

    def test_deterministic_merge_includes_parakeet_only_spans(self):
        whisper = {
            "raw": {
                "segments": [
                    {"start": "00:00", "end": "00:05", "text": "Whisper only"},
                ]
            }
        }
        parakeet = {
            "raw": {
                "segments": [
                    {"start": "00:00", "end": "00:05", "text": "Overlapping"},
                    {"start": "00:10", "end": "00:15", "text": "Parakeet only span"},
                ]
            }
        }
        merged = transcript_merge.merge_transcripts_deterministic(whisper, parakeet)
        self.assertIn("Parakeet only span", merged["markdown"])
        self.assertGreaterEqual(merged["stats"]["parakeet_append_count"], 1)

    def test_deterministic_merge_no_timestamps_falls_back_to_paragraph(self):
        whisper = {"raw": {"text": "Whisper text"}}
        parakeet = {"raw": {"text": "Parakeet text"}}
        merged = transcript_merge.merge_transcripts_deterministic(whisper, parakeet)
        self.assertIn("Whisper text", merged["markdown"])
        self.assertIn("Parakeet text", merged["markdown"])

    def test_deterministic_merge_empty_both(self):
        merged = transcript_merge.merge_transcripts_deterministic(
            {"raw": {}}, {"raw": {}}
        )
        self.assertEqual(merged["markdown"], "")

    def test_deterministic_merge_only_whisper(self):
        whisper = {
            "raw": {"segments": [{"start": "00:00", "end": "00:05", "text": "Only whisper"}]}
        }
        merged = transcript_merge.merge_transcripts_deterministic(whisper, {"raw": {}})
        self.assertIn("Only whisper", merged["markdown"])
        self.assertEqual(merged["stats"]["parakeet_segments"], 0)

    def test_deterministic_merge_only_parakeet(self):
        parakeet = {
            "raw": {"segments": [{"start": "00:00", "end": "00:05", "text": "Only parakeet"}]}
        }
        merged = transcript_merge.merge_transcripts_deterministic({"raw": {}}, parakeet)
        self.assertIn("Only parakeet", merged["markdown"])
        self.assertEqual(merged["stats"]["whisper_segments"], 0)


class DualModeContractTests(unittest.TestCase):
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
        self.temp_dir = PROJECT_ROOT / "temp" / "test_dual"
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

    def _make_fake_processor(self, title="Dual Test Video"):
        class FakeVideoProcessor:
            async def fetch_subtitles(self, url, output_dir):
                raise AssertionError("subtitles should be skipped in dual mode")

            async def download_and_convert(self, url, output_dir):
                audio_path = output_dir / "dual_test.m4a"
                audio_path.write_bytes(b"fake dual audio")
                return str(audio_path), title

        return FakeVideoProcessor()

    def _make_fake_transcriber(self, text_prefix):
        class FakeTranscriber:
            async def transcribe(self, audio_path, language=""):
                return {
                    "markdown": f"# Video Transcription\n\n## Transcription Content\n\n{text_prefix} transcription",
                    "language": "en",
                    "warnings": [],
                    "runtime": "cpu",
                    "timestamps_supported": True,
                    "model": f"{text_prefix}-model",
                }
        return FakeTranscriber()

    def test_dual_mode_runs_both_backends_and_merges(self):
        main.video_processor = self._make_fake_processor()
        task_id = "dual-both-test"
        url = "https://youtu.be/dual-both"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        def fake_prepare(backend, preset="", model_id=""):
            return self._make_fake_transcriber(backend), f"{backend}-resolved"

        with patch.object(main, "prepare_local_transcriber", side_effect=fake_prepare), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True):
            asyncio.run(
                main.process_video_task(
                    task_id,
                    url,
                    transcription_provider="local",
                    try_subtitles_first=True,
                    local_backend="whisper",
                    dual_local_transcription=True,
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["transcription_provider_used"], "dual_local")
        self.assertEqual(task["transcript_source"], "dual_local_merged")
        self.assertEqual(task["local_backend_used"], "dual")
        self.assertIn("whisper", task["local_model_used"])
        self.assertIn("parakeet", task["local_model_used"])
        self.assertIn("whisper transcription", task["transcript"])
        self.assertIn("parakeet transcription", task["transcript"])
        self.assertIsNotNone(task.get("dual_transcription_results"))
        self.assertEqual(
            task["dual_transcription_results"]["merge_strategy"], "deterministic"
        )

    def test_dual_mode_rejects_non_local_provider(self):
        task_id = "dual-reject-test"
        main.tasks[task_id] = {"status": "processing", "url": ""}
        main.processing_urls.clear()

        asyncio.run(
            main.process_video_task(
                task_id,
                "",
                transcription_provider="groq",
                dual_local_transcription=True,
            )
        )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "error")
        self.assertIn("local", task["error"].lower())

    def test_dual_mode_skips_subtitles_even_when_enabled(self):
        main.video_processor = self._make_fake_processor()
        task_id = "dual-skip-subs"
        url = "https://youtu.be/dual-skip-subs"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        def fake_prepare(backend, preset="", model_id=""):
            return self._make_fake_transcriber(backend), f"{backend}-resolved"

        with patch.object(main, "prepare_local_transcriber", side_effect=fake_prepare), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True):
            asyncio.run(
                main.process_video_task(
                    task_id,
                    url,
                    transcription_provider="local",
                    try_subtitles_first=True,
                    dual_local_transcription=True,
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "completed")

    def test_dual_mode_strips_timecodes_when_disabled(self):
        main.video_processor = self._make_fake_processor()
        task_id = "dual-no-timecodes"
        url = "https://youtu.be/dual-no-timecodes"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        def fake_prepare(backend, preset="", model_id=""):
            return self._make_fake_transcriber(backend), f"{backend}-resolved"

        with patch.object(main, "prepare_local_transcriber", side_effect=fake_prepare), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True):
            asyncio.run(
                main.process_video_task(
                    task_id,
                    url,
                    transcription_provider="local",
                    dual_local_transcription=True,
                    include_timecodes=False,
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "completed")
        self.assertNotIn("[00:", task["transcript"])


class DualSettingsTests(unittest.TestCase):
    def test_default_settings_include_dual_fields(self):
        self.assertIn("dual_local_transcription", DEFAULT_SETTINGS)
        self.assertIn("dual_whisper_model_preset", DEFAULT_SETTINGS)
        self.assertIn("dual_parakeet_model_preset", DEFAULT_SETTINGS)
        self.assertIn("merge_use_ai", DEFAULT_SETTINGS)
        self.assertIn("merge_api_key", DEFAULT_SETTINGS)
        self.assertIn("merge_base_url", DEFAULT_SETTINGS)
        self.assertIn("merge_model", DEFAULT_SETTINGS)
        self.assertIn("merge_prompt", DEFAULT_SETTINGS)
        self.assertIn("merge_reasoning_effort", DEFAULT_SETTINGS)

    def test_dual_settings_round_trip(self):
        from settings import save_settings, load_settings, SETTINGS_FILE
        import json

        original = json.loads(SETTINGS_FILE.read_text(encoding="utf-8")) if SETTINGS_FILE.exists() else {}

        try:
            save_settings({
                "dual_local_transcription": True,
                "dual_whisper_model_preset": "small",
                "merge_use_ai": True,
                "merge_model": "gpt-4o",
            })
            loaded = load_settings()
            self.assertTrue(loaded["dual_local_transcription"])
            self.assertEqual(loaded["dual_whisper_model_preset"], "small")
            self.assertTrue(loaded["merge_use_ai"])
            self.assertEqual(loaded["merge_model"], "gpt-4o")
        finally:
            if SETTINGS_FILE.exists():
                save_settings(original)

    def test_merge_api_key_is_masked(self):
        from settings import get_masked_settings, save_settings, load_settings, SETTINGS_FILE
        import json

        original = json.loads(SETTINGS_FILE.read_text(encoding="utf-8")) if SETTINGS_FILE.exists() else {}

        try:
            save_settings({"merge_api_key": "sk-test-key-12345678"})
            masked = get_masked_settings()
            self.assertEqual(masked["merge_api_key"], "sk-t...5678")
        finally:
            if SETTINGS_FILE.exists():
                save_settings(original)


class ResolveMergeCredentialsTests(unittest.TestCase):
    def test_form_fields_take_precedence(self):
        creds = transcript_merge.resolve_merge_credentials(
            form_merge_api_key="form-key",
            form_merge_base_url="https://form.example.com",
            form_merge_model="form-model",
        )
        self.assertEqual(creds["api_key"], "form-key")
        self.assertEqual(creds["base_url"], "https://form.example.com")
        self.assertEqual(creds["model"], "form-model")

    def test_falls_back_to_summary_credentials(self):
        empty_defaults = {k: "" for k in DEFAULT_SETTINGS}
        with patch.dict("os.environ", {}, clear=True):
            with patch("settings.load_settings", return_value=empty_defaults):
                creds = transcript_merge.resolve_merge_credentials(
                    form_summary_api_key="summary-key",
                    form_summary_base_url="https://summary.example.com",
                    form_summary_model="summary-model",
                )
                self.assertEqual(creds["api_key"], "summary-key")
                self.assertEqual(creds["base_url"], "https://summary.example.com")
                self.assertEqual(creds["model"], "summary-model")

    def test_empty_when_nothing_provided(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch("settings.load_settings", return_value={k: "" for k in DEFAULT_SETTINGS}):
                creds = transcript_merge.resolve_merge_credentials()
                self.assertEqual(creds["api_key"], "")


class FrontendDualTests(unittest.TestCase):
    def test_frontend_includes_dual_i18n_keys(self):
        app_js = (PROJECT_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("dual_local_transcription", app_js)
        self.assertIn("dual_whisper_model", app_js)
        self.assertIn("dual_parakeet_model", app_js)
        self.assertIn("merge_settings", app_js)
        self.assertIn("merge_use_ai", app_js)
        self.assertIn("mode_dual_local", app_js)

    def test_frontend_persists_merge_reasoning_effort_in_local_settings(self):
        app_js = (PROJECT_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("this.mergeReasoningEffortSelect,", app_js)
        self.assertIn("mergeReasoningEffort: this.mergeReasoningEffortSelect?.value || ''", app_js)
        self.assertIn(
            "if (s.mergeReasoningEffort && this.mergeReasoningEffortSelect) this.mergeReasoningEffortSelect.value = s.mergeReasoningEffort;",
            app_js,
        )
        self.assertIn("merge_reasoning_effort", app_js)

    def test_frontend_sends_dual_form_fields(self):
        app_js = (PROJECT_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("dual_local_transcription", app_js)
        self.assertIn("dual_whisper_model_preset", app_js)
        self.assertIn("merge_use_ai", app_js)
        self.assertIn("merge_api_key", app_js)

    def test_index_html_has_dual_elements(self):
        index_html = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="dualLocalInput"', index_html)
        self.assertIn('id="dualWhisperModelPresetSelect"', index_html)
        self.assertIn('id="dualParakeetModelPresetSelect"', index_html)
        self.assertIn('id="mergeUseAiInput"', index_html)
        self.assertIn('id="mergeApiKeyInput"', index_html)
        self.assertIn('id="mergeReasoningEffortSelect"', index_html)


class TimestampAlignmentTests(unittest.TestCase):
    def test_mmss_timestamps_parsed_and_aligned(self):
        """Parakeet MM:SS timestamps should overlap with matching Whisper floats."""
        whisper = {
            "raw": {
                "segments": [
                    {"start": 0.0, "end": 5.0, "text": "Whisper segment"},
                    {"start": 5.0, "end": 10.0, "text": "Another segment"},
                ]
            }
        }
        parakeet = {
            "raw": {
                "segments": [
                    {"start": "00:00", "end": "00:05", "text": "Parakeet overlap"},
                    {"start": "00:05", "end": "00:10", "text": "Parakeet overlap two"},
                ]
            }
        }
        merged = transcript_merge.merge_transcripts_deterministic(whisper, parakeet)
        self.assertIn("Whisper segment", merged["markdown"])
        self.assertIn("Another segment", merged["markdown"])
        self.assertEqual(merged["stats"]["parakeet_append_count"], 0)

    def test_timecodes_preserved_in_merged_output(self):
        """Merged output should include timecodes when timestamps are present."""
        whisper = {
            "raw": {
                "segments": [
                    {"start": 0.0, "end": 5.0, "text": "Hello"},
                    {"start": 5.0, "end": 10.0, "text": "World"},
                ]
            }
        }
        parakeet = {"raw": {"segments": []}}
        merged = transcript_merge.merge_transcripts_deterministic(whisper, parakeet)
        self.assertIn("[00:00 - 00:05]", merged["markdown"])
        self.assertIn("[00:05 - 00:10]", merged["markdown"])
        self.assertIn("Hello", merged["markdown"])
        self.assertIn("World", merged["markdown"])

    def test_timecodes_stripped_when_no_timestamps(self):
        """No timecodes should appear when segments lack timestamps."""
        whisper = {"raw": {"text": "Plain text"}}
        parakeet = {"raw": {"text": "More text"}}
        merged = transcript_merge.merge_transcripts_deterministic(whisper, parakeet)
        self.assertNotIn("[", merged["markdown"])
        self.assertIn("Plain text", merged["markdown"])


class EmptySpanFillTests(unittest.TestCase):
    def test_empty_whisper_segment_filled_by_parakeet(self):
        """Empty Whisper segments with timestamps should be filled from Parakeet."""
        whisper = {
            "raw": {
                "segments": [
                    {"start": 0.0, "end": 5.0, "text": ""},
                    {"start": 5.0, "end": 10.0, "text": "World"},
                ]
            }
        }
        parakeet = {
            "raw": {
                "segments": [
                    {"start": "00:00", "end": "00:05", "text": "Filled from parakeet"},
                    {"start": "00:05", "end": "00:10", "text": "World"},
                ]
            }
        }
        merged = transcript_merge.merge_transcripts_deterministic(whisper, parakeet)
        self.assertIn("Filled from parakeet", merged["markdown"])
        self.assertGreaterEqual(merged["stats"]["parakeet_fill_count"], 1)
        self.assertIn("World", merged["markdown"])


class MaskedCredentialTests(unittest.TestCase):
    def test_masked_merge_key_not_in_html(self):
        """Masked merge key values should not be written into input fields."""
        app_js = (PROJECT_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("merge_api_key.includes('...')", app_js)

    def test_frontend_has_merge_reasoning_control(self):
        index_html = (PROJECT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="mergeReasoningEffortSelect"', index_html)


class CredentialFallbackTests(unittest.TestCase):
    def test_summary_model_fallback_in_merge_creds(self):
        """resolve_merge_credentials should fall back to summary_model setting."""
        empty_defaults = {k: "" for k in DEFAULT_SETTINGS}
        with patch.dict("os.environ", {}, clear=True):
            with patch("settings.load_settings", return_value={**empty_defaults, "summary_model": "summary-fallback-model"}):
                creds = transcript_merge.resolve_merge_credentials()
                self.assertEqual(creds["model"], "summary-fallback-model")

    def test_form_summary_fields_take_precedence_over_settings(self):
        """Form summary fields should take precedence over settings."""
        empty_defaults = {k: "" for k in DEFAULT_SETTINGS}
        with patch.dict("os.environ", {}, clear=True):
            with patch("settings.load_settings", return_value=empty_defaults):
                creds = transcript_merge.resolve_merge_credentials(
                    form_summary_api_key="form-summary-key",
                    form_summary_model="form-summary-model",
                )
                self.assertEqual(creds["api_key"], "form-summary-key")
                self.assertEqual(creds["model"], "form-summary-model")


class DualBackendErrorTests(unittest.TestCase):
    def test_dual_mode_reports_backend_on_failure(self):
        """When one backend fails in dual mode, the error should name the backend."""
        main.video_processor = None
        task_id = "dual-error-test"
        url = "https://youtu.be/dual-error"
        main.tasks[task_id] = {"status": "processing", "url": url}
        main.processing_urls.add(url)

        class FailingWhisper:
            async def transcribe(self, audio_path, language=""):
                raise RuntimeError("whisper crashed")

        class OkParakeet:
            async def transcribe(self, audio_path, language=""):
                return {
                    "markdown": "parakeet result",
                    "language": "en",
                    "warnings": [],
                    "runtime": "cpu",
                    "timestamps_supported": True,
                    "model": "parakeet",
                }

        def fake_prepare(backend, preset="", model_id=""):
            if backend == "whisper":
                return FailingWhisper(), "whisper-resolved"
            return OkParakeet(), "parakeet-resolved"

        class FakeProcessor:
            async def download_and_convert(self, url, output_dir):
                audio_path = output_dir / "test.m4a"
                audio_path.write_bytes(b"fake")
                return str(audio_path), "Test Video"

        main.video_processor = FakeProcessor()

        with patch.object(main, "prepare_local_transcriber", side_effect=fake_prepare), \
             patch.object(main, "ensure_backend_audio_file", side_effect=lambda path, backend, output_dir: path), \
             patch.object(main, "backend_dependencies_available", return_value=True):
            asyncio.run(
                main.process_video_task(
                    task_id,
                    url,
                    transcription_provider="local",
                    dual_local_transcription=True,
                )
            )

        task = main.tasks[task_id]
        self.assertEqual(task["status"], "error")
        self.assertIn("whisper", task["error"].lower())

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
        self.temp_dir = PROJECT_ROOT / "temp" / "test_dual_err"
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


if __name__ == "__main__":
    unittest.main()
