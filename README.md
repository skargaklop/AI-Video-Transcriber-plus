<div align="center">

# AI Video Transcriber


Transcribe videos or local audio files, combine multiple transcription sources, and generate AI summaries with explicit provider control.

![Interface](en-video.png)

</div>

## Project Highlights

- Windows-first local setup and launcher flow
- Video URL and local audio file input modes
- Optional YouTube subtitle-first path
- Selectable transcription providers: Groq, Local, Local API
- Multi-source transcription across platform subtitles, Groq Whisper, local Whisper, and local Parakeet
- Local Whisper and Parakeet model selection inside the Multi-Source workflow
- Separate summary step with OpenAI-compatible providers
- Transcript and summary export improvements

## Features

- Multi-platform URL support through `yt-dlp`
- Local audio file upload and processing
- Explicit provider selection for single-source transcription
- Optional Groq-to-local fallback
- Multi-source transcription: run any combination of platform subtitles, Groq Whisper, local Whisper, and local Parakeet concurrently where possible
- Multi-source output modes: deterministic system merge, raw source bundle, or AI merge through an OpenAI-compatible endpoint
- Optional transcript time codes
- Separate model fetching for summary and AI-merge providers
- Custom summary prompt plus summary language control
- Summary provider model selection and reasoning selection when supported
- UI export to MD, TXT, and PDF
- Generated summary artifact formats: Markdown, HTML, TXT, or Markdown + HTML

## CLI Usage

A command-line interface is available for scripting, CI, and agent use.

```bash
# Set credentials first (one-time, prompted with no echo)
python cli.py settings --set-groq-key
python cli.py settings --set-openai-key

# Show current settings (credentials masked)
python cli.py settings --show

# Transcribe a video URL (local Whisper, no API key needed)
avt transcribe --url "https://youtu.be/VIDEO_ID" --provider local

# Transcribe with Groq (key from settings.json or GROQ_API_KEY env var)
avt transcribe --url "https://youtu.be/VIDEO_ID" --provider groq

# Transcribe a local audio file
avt transcribe --file recording.mp3 --provider groq

# Multi-source: platform subtitles + Groq + local Parakeet, raw bundle output
avt transcribe --url "https://youtu.be/VIDEO_ID" \
    --source platform,groq,local_parakeet --merge-mode raw

# Multi-source: local Whisper + local Parakeet with deterministic merge
avt transcribe --url "https://youtu.be/VIDEO_ID" \
    --provider local --source local_whisper,local_parakeet \
    --merge-mode system --merge-primary-source local_whisper \
    --dual-whisper-model-preset large-v3 \
    --dual-parakeet-model-preset nvidia/parakeet-tdt-0.6b-v3

# Multi-source with AI merge through an OpenAI-compatible endpoint
avt transcribe --url "https://youtu.be/VIDEO_ID" \
    --source platform,groq,local_parakeet \
    --merge-mode ai --merge-base-url https://api.openai.com/v1 \
    --merge-api-key sk-... --merge-model gpt-4o

# Summarize a completed transcription
avt summarize --task-id "TASK_ID" --summary-language en

# Transcribe + summarize in one step
avt pipeline --url "https://youtu.be/VIDEO_ID" \
    --provider groq --summary-language en

# List / inspect / delete tasks
avt tasks --list
avt tasks --get "TASK_ID"
avt tasks --delete "TASK_ID"

# Machine-readable capability manifest (for AI agents)
avt --agent-help
```

The `avt` command is registered on PATH when you run `start_windows.bat` and accept the PATH prompt (or manually via `pip install -e .` from the project root). If not on PATH, use `python cli.py` instead.

Full flag reference, output schemas, and workflow patterns are in the skill definition at `ai-video-transcriber/SKILL.md`.

## Quick Start

### Prerequisites

- Windows 10 or Windows 11
- Python 3.10+
- A Groq API key if you want Groq transcription
- An API key for any OpenAI-compatible summary provider if you want AI summaries

### Recommended Windows Start

From the repository root:

```powershell
.\start_windows.bat
```

`start_windows.bat` supports explicit virtual-environment modes:

```powershell
.\start_windows.bat --venv auto   # default: use .venv if present, otherwise current Python
.\start_windows.bat --venv on     # create/use .venv and install dependencies there
.\start_windows.bat --venv off    # use the current Python interpreter without .venv
```

### Manual Start

```powershell
py -3 -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python start.py --prod
```

After startup, open:

```text
http://localhost:8001
```

Use `--prod` for long jobs so hot reload does not interrupt the SSE progress stream.

## Usage

1. Choose the source mode:
   - `Video URL`
   - `Local audio file`
2. If you use a video URL, paste the URL.
3. Open `AI Settings`.
4. Choose the transcription provider:
   - `Groq`
   - `Local`
   - `Local API`
5. For YouTube URLs, optionally leave `Try YouTube subtitles first` enabled for single-source flows.
6. Configure the selected provider:
   - `Groq`: API key, Groq model, optional language, optional prompt
   - `Local`: backend (`Whisper` or `Parakeet`), preset or custom model, optional language hint
   - `Local API`: base URL, API key if needed, model, optional language, optional prompt
7. To run concurrent transcription, enable `Multi-Source Transcription` and select any sources:
   - `Platform subtitles`
   - `Groq Whisper`
   - `Local Whisper`
   - `Local Parakeet`
8. If `Local Whisper` or `Local Parakeet` is selected in Multi-Source, choose its model in that same Multi-Source section.
9. Choose the Multi-Source merge mode:
   - `System merge (deterministic)`: choose a required primary source when two or more sources are selected.
   - `Raw bundle`: keep separate successful and failed source outputs for manual review.
   - `AI merge`: merge through a separate OpenAI-compatible endpoint, API key, and model.
10. Configure the summary provider if you want summaries.
11. Click `Transcribe`.
12. Review the transcript.
13. Click `Generate Summary` only when you want to send transcript text to the summary provider.
14. Export transcript or summary from the UI.

## Transcription Providers

### Groq

- Best when you want cloud transcription
- Supports direct file upload and URL-based flows
- Can fall back to the selected local backend on eligible failures

### Local

- `Whisper` runs through `faster-whisper`
- `Parakeet` runs through `onnx-asr`
- The app downloads the selected local model on first use

### Local API

- Uses an OpenAI-compatible speech-to-text API exposed by another local or remote server
- Useful when you run ASR outside this app

## Multi-Source Transcription

Multi-Source Transcription is the main workflow for concurrent transcription. It replaces the old separate Dual Local UI.

Available sources:

| Source ID | UI label | Notes |
| --- | --- | --- |
| `platform` | Platform subtitles | Uses platform subtitles when available, especially YouTube subtitles |
| `groq` | Groq Whisper | Uses Groq transcription; URL jobs may retry by uploading downloaded audio when media URL retrieval fails |
| `local_whisper` | Local Whisper | Uses the selected local Whisper preset or custom model |
| `local_parakeet` | Local Parakeet | Uses the selected local Parakeet preset or custom model |

Merge modes:

| Mode | Behavior |
| --- | --- |
| `system` | Deterministic merge. Requires an explicit primary source when two or more sources are selected. If the selected primary source fails, the app warns and falls back to the first successful source. |
| `raw` | No merge. The result shows selected, completed, failed, and pending sources, plus per-source artifact files. |
| `ai` | Sends successful source transcripts to an OpenAI-compatible merge endpoint using the configured merge API base URL, API key, and model. |

The CLI still supports `--dual-local` for backward compatibility. In the browser UI, use Multi-Source with `Local Whisper` and `Local Parakeet` selected instead.

## Summary Providers

- Any OpenAI-compatible API base URL
- API key can be entered directly in the UI
- Model list can be fetched from the provider
- Custom summary prompt is appended to the summary request
- Summary language is appended automatically

## Project Structure

```text
AI-Video-Transcriber/
|-- backend/
|   |-- main.py
|   |-- settings.py
|   |-- groq_transcriber.py
|   |-- local_transcription.py
|   |-- parakeet_transcriber.py
|   |-- local_api_transcriber.py
|   |-- source_registry.py
|   |-- transcript_merge.py
|   `-- summarizer.py
|-- static/
|   |-- index.html
|   `-- app.js
|-- tests/
|-- models/
|-- temp/
|-- start.py
|-- start_windows.bat
|-- settings.json    (auto-created, gitignored)
|-- .env             (gitignored)
`-- requirements.txt
```

## Environment Variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `HOST` | Bind host | `0.0.0.0` |
| `PORT` | HTTP port | `8001` |
| `GROQ_API_KEY` | Groq transcription API key | unset |
| `OPENAI_API_KEY` | Optional default summary API key | unset |
| `OPENAI_BASE_URL` | Optional default summary API base URL | set in `start.py` if missing |

Credentials can be configured via environment variables, `.env` file, the browser UI settings panel, or the CLI (`python cli.py settings --set-groq-key`). All methods write to `settings.json`, which is shared between GUI and CLI.

## Local Model Notes

- Whisper is usually the lighter local choice.
- Parakeet on CPU can be much slower and heavier on RAM.
- First use can take time because dependencies and model files may be downloaded.
- Local model files and caches may appear in:
  - `models/` (relative to the repository root)
  - `~/.cache/huggingface` (or `%USERPROFILE%\.cache\huggingface` on Windows)
  - Python package and pip cache directories under the user profile

## Troubleshooting

### Transcription looks stuck

- Run in production mode: `python start.py --prod`
- For local models, first-use install/download can take a while
- CPU Parakeet can be slow enough to look frozen if the audio is long

### Parakeet uses too much RAM

That is possible on CPU workloads. Prefer Whisper locally if RAM pressure matters more than trying Parakeet.

### Groq cannot retrieve the media URL

Signed media URLs can expire or redirect. Retry the job, use subtitle-first mode, or use a local file instead.

### Where are local files saved

Temporary task files are kept under:

```text
temp/
```

Model caches may also consume space outside the repo, especially under the Hugging Face cache.

## Contributing

1. Create a feature branch
2. Make the change
3. Run the relevant checks for the area you touched
4. Open a pull request with a clear description

## Acknowledgments

- [FastAPI](https://fastapi.tiangolo.com/)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [Groq](https://groq.com/)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [onnx-asr](https://github.com/istupakov/onnx-asr)
