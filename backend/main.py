import os
import re
import shutil
from contextlib import asynccontextmanager
from importlib.util import find_spec
from pathlib import Path
from urllib.parse import quote, urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from python_multipart.exceptions import FormParserError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from .exports import ExportFormat, render_export
from .media import MAX_BYTES, MAX_DURATION, JobError, WhisperEngine, download_media, validate_url
from .models import MODELS, JobEdit, Settings, URLJob
from .store import JobConflict, JobStore, public_job
from .worker import JobWorker

ROOT = Path(__file__).resolve().parent.parent
HOSTS = {"localhost", "127.0.0.1", "::1"}
DEV_ORIGINS = {
    f"http://{host}:{port}"
    for host in ("localhost", "127.0.0.1", "[::1]")
    for port in (4173, 5173, 8000)
}
REQUEST_OVERHEAD = 128 * 1024


def host_identity(authority, scheme):
    try:
        parsed = urlsplit(f"{scheme}://{authority}")
        if (parsed.hostname in HOSTS and not parsed.username and parsed.password is None
                and not parsed.path and not parsed.query and not parsed.fragment):
            return parsed.hostname, parsed.port or (443 if scheme == "https" else 80)
    except ValueError:
        pass
    return None


def save_upload(upload, path):
    size = 0
    with path.open("xb") as target:
        while chunk := upload.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_BYTES:
                raise HTTPException(413, "Media files must be 500 MB or smaller.")
            target.write(chunk)
    if size == 0:
        raise HTTPException(422, "Choose a media file that is not empty.")


def create_app(data_dir=None, *, downloader=download_media, transcriber=None):
    store = JobStore(Path(data_dir or os.environ.get("TRANSCRIPT_DATA_DIR", ROOT / "data")))
    engine = WhisperEngine(store.data_dir / "models")

    @asynccontextmanager
    async def lifespan(_app):
        worker = JobWorker(store, downloader, transcriber or engine)
        worker.start()
        _app.state.worker = worker
        try:
            yield
        finally:
            worker.close()

    app = FastAPI(title="Transcript Studio", lifespan=lifespan)

    @app.middleware("http")
    async def require_local_request(request: Request, call_next):
        host = host_identity(request.headers.get("host", ""), request.url.scheme)
        if host is None:
            return JSONResponse({"detail": "Transcript Studio accepts only local connections."}, 403)
        if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            origin = request.headers.get("origin")
            if origin:
                try:
                    parsed = urlsplit(origin)
                    same_origin = (
                        parsed.scheme == request.url.scheme and not parsed.path and not parsed.query
                        and not parsed.fragment and host_identity(parsed.netloc, parsed.scheme) == host
                    )
                except ValueError:
                    same_origin = False
                if not same_origin and origin not in DEV_ORIGINS:
                    return JSONResponse({"detail": "This origin cannot make changes."}, 403)
            elif request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "This origin cannot make changes."}, 403)
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware, allow_origins=sorted(DEV_ORIGINS),
        allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type"],
        expose_headers=["Content-Disposition"],
    )

    @app.exception_handler(KeyError)
    async def job_missing(_request, _exc):
        return JSONResponse({"detail": "Job not found."}, 404)

    @app.exception_handler(JobConflict)
    async def job_conflict(_request, exc):
        return JSONResponse({"detail": str(exc)}, 409)

    @app.exception_handler(RequestValidationError)
    async def bad_request(_request, _exc):
        return JSONResponse({"detail": "Check the submitted fields."}, 422)

    @app.get("/api/health")
    def health():
        dependencies = {
            "faster_whisper": find_spec("faster_whisper") is not None,
            "yt_dlp": find_spec("yt_dlp") is not None,
            "yt_dlp_ejs": find_spec("yt_dlp_ejs") is not None,
            "pyav": find_spec("av") is not None,
            "ffmpeg": shutil.which("ffmpeg") is not None,
            "node": shutil.which("node") is not None,
            "deno": shutil.which("deno") is not None,
        }
        return {
            "status": "ok" if all(dependencies[key] for key in ("faster_whisper", "yt_dlp", "pyav"))
            else "degraded",
            "engine": "faster-whisper",
            "device": engine.device,
            "models": MODELS,
            "dependencies": dependencies,
            "max_file_size": MAX_BYTES,
            "max_duration": MAX_DURATION,
        }

    @app.get("/api/jobs")
    def list_jobs():
        return [public_job(job) for job in store.list()]

    @app.post("/api/jobs", status_code=201)
    def create_url_job(settings: URLJob, request: Request):
        try:
            url = validate_url(settings.url)
        except JobError as exc:
            raise HTTPException(422, str(exc)) from exc
        job = store.create(settings, title=urlsplit(url).hostname, source_url=url)
        request.app.state.worker.wakeup.set()
        return public_job(job)

    @app.post("/api/jobs/upload", status_code=201)
    async def create_upload_job(request: Request):
        if not request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
            raise HTTPException(415, "Send the file as multipart form data.")
        content_length = request.headers.get("content-length", "")
        if content_length.isdecimal() and int(content_length) > MAX_BYTES + REQUEST_OVERHEAD:
            raise HTTPException(413, "Media files must be 500 MB or smaller.")
        exceeded = False

        async def bounded_stream():
            nonlocal exceeded
            received = 0
            async for chunk in request.stream():
                received += len(chunk)
                if received > MAX_BYTES + REQUEST_OVERHEAD:
                    exceeded = True
                    raise MultiPartException("Media files must be 500 MB or smaller.")
                yield chunk

        parser = MultiPartParser(
            request.headers, bounded_stream(), max_files=1, max_fields=3, max_part_size=8192,
        )
        try:
            form = await parser.parse()
        except MultiPartException as exc:
            if exceeded:
                raise HTTPException(413, "Media files must be 500 MB or smaller.") from exc
            raise HTTPException(422, "The upload form could not be read.") from exc
        except FormParserError as exc:
            raise HTTPException(422, "The upload form could not be read.") from exc
        job_id = uuid4().hex
        directory = store.media_dir / job_id
        try:
            upload = form.get("file")
            if not isinstance(upload, UploadFile) or not upload.filename:
                raise HTTPException(422, "Choose a video or audio file.")
            try:
                settings = Settings.model_validate({
                    key: form[key] for key in ("model", "language", "initial_prompt") if key in form
                })
            except ValidationError as exc:
                raise HTTPException(422, "Check the model, language, and context settings.") from exc
            title = re.split(r"[/\\]", upload.filename)[-1][:500] or "Media file"
            suffix = Path(title).suffix.lower()
            upload_name = f"upload{suffix}" if re.fullmatch(r"\.[a-z0-9]{1,12}", suffix) else "upload"
            directory.mkdir()
            await run_in_threadpool(save_upload, upload, directory / upload_name)
            job = await run_in_threadpool(
                store.create, settings, title=title, upload_name=upload_name, job_id=job_id,
            )
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        finally:
            await form.close()
        request.app.state.worker.wakeup.set()
        return public_job(job)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        return public_job(store.get(job_id))

    @app.patch("/api/jobs/{job_id}")
    def edit_job(job_id: str, edit: JobEdit):
        return public_job(store.edit(job_id, edit))

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        job, was_queued = store.cancel(job_id)
        if was_queued:
            shutil.rmtree(store.media_dir / job["id"], ignore_errors=True)
        return public_job(job)

    @app.delete("/api/jobs/{job_id}", status_code=204)
    def delete_job(job_id: str):
        store.delete(job_id)
        return Response(status_code=204)

    @app.get("/api/jobs/{job_id}/export")
    def export_job(job_id: str, format: ExportFormat = "md", timestamps: bool = True):
        job = public_job(store.get(job_id))
        if job["status"] != "completed":
            raise JobConflict("Wait for transcription to finish before exporting.")
        body, media_type = render_export(job, format, timestamps)
        name = re.sub(r'[^\w .-]', "-", Path(job["title"]).stem, flags=re.UNICODE).strip(" .-")[:120]
        name = name or "transcript"
        disposition = f"attachment; filename=transcript.{format}; filename*=UTF-8''{quote(name)}.{format}"
        return Response(body, media_type=media_type, headers={"Content-Disposition": disposition})

    @app.api_route("/api/{unknown:path}", methods=["GET", "POST", "PATCH", "DELETE"])
    def missing_api(unknown: str):
        raise HTTPException(404, "API route not found.")

    frontend = ROOT / "frontend" / "dist"
    if (frontend / "index.html").is_file():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")

    return app


app = create_app()
