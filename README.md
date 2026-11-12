# Transcript Studio

Turn a video link or a local audio or video file into an editable, timestamped transcript. Export to Markdown, TXT, SRT, WebVTT, or JSON.

Transcript Studio runs on your computer using [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and [yt-dlp](https://github.com/yt-dlp/yt-dlp). The interface is in English. Spoken language is detected automatically by default, and you can select Turkish or another supported language manually.

## Run on Windows

Install Python 3.12 and Node.js 22 or newer, then run these commands from the repository directory:

```powershell
.\scripts\setup.ps1
.\scripts\start.ps1
```

Open [localhost:8765](http://127.0.0.1:8765). Press Ctrl+C in the server terminal to stop it. The setup script installs the locked Python and Node dependencies and builds the frontend.

## Transcribe and export

1. Paste a public media URL or select a file.
2. Choose a model and spoken language. Use `large-v3` for accuracy or a smaller model for faster processing. Add names or technical terms as vocabulary hints when needed.
3. Review and save the transcript before exporting it.

The first run for each model downloads its weights. The `large-v3` model uses several gigabytes of disk space. Transcription happens locally and requires no API key. History and model weights are stored in `data/`. The app accepts files up to 500 MiB and recordings up to two hours.

Link access depends on the source and yt-dlp. If a platform blocks a video or requires sign-in, upload a copy you can access. Check transcripts against the original audio when exact wording matters.

## Development

Start the backend and the frontend in separate terminals:

```powershell
.\.venv312\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
npm --prefix frontend run dev
```

Run the backend tests and production build:

```powershell
.\.venv312\Scripts\python.exe -m unittest backend.test_backend -v
npm --prefix frontend run build
```

FastAPI serves the production build and exposes [API documentation](http://127.0.0.1:8765/docs). The server is designed for a single local user. Keep it bound to loopback. CPU is the default. CUDA requires the libraries listed in the faster-whisper documentation.
