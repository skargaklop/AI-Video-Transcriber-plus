<div align="center">

# AI Video Transcriber


Transcribe videos or local audio files and generate AI summaries with explicit provider control.

![Interface](en-video.png)

</div>

## Project Highlights

- Windows-first local setup and launcher flow
- Video URL and local audio file input modes
- Optional YouTube subtitle-first path
- Selectable transcription providers: Groq, Local, Local API
- Local Whisper and Parakeet support
- Separate summary step with OpenAI-compatible providers
- Transcript and summary export improvements

## Features

- Multi-platform URL support through `yt-dlp`
- Local audio file upload and processing
- Explicit provider selection for transcription
- Optional Groq-to-local fallback
- Dual local transcription: run Whisper + Parakeet concurrently on the same audio, then deterministically merge or AI-merge the results
- Optional transcript time codes
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

# Dual local transcription: run Whisper + Parakeet together
avt transcribe --url "https://youtu.be/VIDEO_ID" --dual-local

# Dual local with AI merge
avt transcribe --url "https://youtu.be/VIDEO_ID" --dual-local \
    --merge-use-ai --merge-model gpt-4o

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

Full flag reference, output schemas, and workflow patterns are in [`ai-video-transcriber/SKILL.md`](ai-video-transcriber/SKILL.md).

## Quick Start

### Prerequisites

- Windows 10 or Windows 11
- Python 3.10+
- A Groq API key if you want Groq transcription
- An API key for any OpenAI-compatible summary provider if you want AI summaries

### Recommended Windows Start

```powershell
cd D:\Projects\AI-Video-Transcriber
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
cd D:\Projects\AI-Video-Transcriber
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
5. For YouTube URLs, optionally leave `Try YouTube subtitles first` enabled.
6. Configure the selected provider:
   - `Groq`: API key, Groq model, optional language, optional prompt
   - `Local`: backend (`Whisper` or `Parakeet`), preset or custom model, optional language hint
   - `Local API`: base URL, API key if needed, model, optional language, optional prompt
7. Configure the summary provider if you want summaries.
8. Click `Transcribe`.
9. Review the transcript.
10. Click `Generate Summary` only when you want to send transcript text to the summary provider.
11. Export transcript or summary from the UI.

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
  - `D:\Projects\AI-Video-Transcriber\models`
  - `C:\Users\DELL E5570\.cache\huggingface`
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
D:\Projects\AI-Video-Transcriber\temp
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
