import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import ACTIVE, JobEdit, Settings


class JobConflict(Exception):
    pass


class JobStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.database = data_dir / "jobs.sqlite3"
        self.media_dir = data_dir / "media"

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.database, timeout=15)) as connection, connection:
            yield connection

    def initialize(self):
        self.media_dir.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS jobs (
                       id TEXT PRIMARY KEY,
                       created_at TEXT NOT NULL,
                       status TEXT NOT NULL,
                       payload TEXT NOT NULL
                   )"""
            )
            connection.execute("CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created_at)")

    @staticmethod
    def _load(connection, job_id):
        row = connection.execute("SELECT payload FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return json.loads(row[0])

    @staticmethod
    def _save(connection, job):
        connection.execute(
            "UPDATE jobs SET status = ?, payload = ? WHERE id = ?",
            (job["status"], json.dumps(job, ensure_ascii=False, allow_nan=False), job["id"]),
        )

    def create(self, settings: Settings, *, title: str, source_url=None, upload_name=None, job_id=None):
        job = {
            "id": job_id or uuid4().hex,
            "title": title,
            "source_url": source_url,
            "source_type": "url" if source_url else "upload",
            "status": "queued",
            "progress": 0,
            "message": "Waiting in the queue.",
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": settings.model,
            "language": settings.language,
            "duration": None,
            "segments": [],
            "warnings": [],
            "initial_prompt": settings.initial_prompt,
            "upload_name": upload_name,
        }
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO jobs (id, created_at, status, payload) VALUES (?, ?, ?, ?)",
                (job["id"], job["created_at"], job["status"], json.dumps(job, ensure_ascii=False)),
            )
        return job

    def list(self):
        with self.connection() as connection:
            rows = connection.execute("SELECT payload FROM jobs ORDER BY created_at DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def get(self, job_id):
        with self.connection() as connection:
            return self._load(connection, job_id)

    def claim(self):
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            job = json.loads(row[0])
            if job["source_type"] == "url":
                job.update(status="downloading", message="Downloading video.", progress=1)
            else:
                job.update(status="loading_model", message="Preparing audio.", progress=15)
            self._save(connection, job)
            return job

    def update_active(self, job_id, **changes):
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                job = self._load(connection, job_id)
            except KeyError:
                return False
            if job["status"] not in ACTIVE:
                return False
            job.update(changes)
            self._save(connection, job)
            return True

    def recover(self):
        for job in self.list():
            if job["status"] in ACTIVE:
                self.update_active(
                    job["id"], status="failed", message="The job was interrupted.",
                    error="The application closed before the job finished. Add the source again.",
                )

    def cancel(self, job_id):
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = self._load(connection, job_id)
            was_queued = job["status"] == "queued"
            if job["status"] in ACTIVE:
                job.update(status="cancelled", message="The job was cancelled.")
                self._save(connection, job)
            elif job["status"] != "cancelled":
                raise JobConflict("Only active jobs can be cancelled.")
            return job, was_queued

    def delete(self, job_id):
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = self._load(connection, job_id)
            if job["status"] in ACTIVE:
                raise JobConflict("Cancel the job before deleting it.")
            connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    def edit(self, job_id, edit: JobEdit):
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = self._load(connection, job_id)
            if job["status"] != "completed":
                raise JobConflict("Only completed transcripts can be edited.")
            old_segments = {segment["id"]: segment for segment in job["segments"]}
            segments = []
            for segment in edit.segments:
                revised = segment.model_dump()
                original = old_segments.get(segment.id, {})
                if all(original.get(key) == value for key, value in revised.items()):
                    revised = original
                segments.append(revised)
            job["segments"] = segments
            self._save(connection, job)
            return job


# Translate only known application messages from older databases. Transcript
# text, media titles, and unfamiliar errors pass through unchanged.
_LEGACY_MESSAGES = {
    "Sırada bekliyor.": "Waiting in the queue.",
    "Video indiriliyor.": "Downloading video.",
    "Ses dosyası hazırlanıyor.": "Preparing audio.",
    "Model yükleniyor. İlk kullanımda model indirilebilir.": "Loading the model. First use may require a download.",
    "Konuşma metne dönüştürülüyor.": "Transcribing audio.",
    "Transkript hazır.": "Transcript ready.",
    "İşlem yarıda kaldı.": "The job was interrupted.",
    "İşlem iptal edildi.": "The job was cancelled.",
    "Uygulama kapatılırken işlem iptal edildi.": "The job was cancelled when the application shut down.",
    "İşlem tamamlanamadı.": "The job could not be completed.",
    "Uygulama işlem tamamlanmadan kapandı. Kaynağı tekrar ekleyin.": "The application closed before the job finished. Add the source again.",
    "Beklenmeyen bir hata oluştu. Uygulama günlüğünü kontrol edin.": "An unexpected error occurred. Check the application log.",
    "Herkese açık, geçerli bir HTTP veya HTTPS video bağlantısı girin.": "Enter a valid public HTTP or HTTPS video URL.",
    "Canlı yayınlar desteklenmiyor.": "Live streams are unsupported.",
    "Medya süresi en fazla 2 saat olabilir.": "Media must be no longer than two hours.",
    "Medya dosyası en fazla 500 MB olabilir.": "Media files must be 500 MB or smaller.",
    "Bir oynatma listesi yerine tek bir video bağlantısı girin.": "Enter a link to a single video.",
    "Video indirilemedi veya 500 MB sınırını aştı.": "The video could not be downloaded or exceeded the 500 MB limit.",
    "Medya dosyasında ses kanalı bulunamadı.": "The media file has no audio track.",
    "Ses okunamadı. Geçerli bir video veya ses dosyası yükleyin.": "The audio could not be read. Upload a valid video or audio file.",
    "Medya dosyasında okunabilir ses bulunamadı.": "The media file has no readable audio.",
    "Ses metne dönüştürülemedi. Dil ve model ayarlarını kontrol edin.": "The audio could not be transcribed. Check the language and model settings.",
    "Medya dosyasında algılanabilir konuşma bulunamadı.": "No speech was detected in the media file.",
    (
        "Video indirilemedi. Bağlantının herkese açık ve desteklenen bir kaynağa ait "
        "olduğunu kontrol edin veya medya dosyasını yükleyin."
    ): "The video could not be downloaded. Check that the link points to a public, supported source or upload the media file.",
    (
        "Model yüklenemedi. İlk kullanım için internet bağlantısını ve boş disk "
        "alanını kontrol edin veya daha küçük bir model seçin."
    ): "The model could not be loaded. Check your internet connection and free disk space or select a smaller model.",
}


def public_job(job):
    result = {key: value for key, value in job.items() if key not in {"initial_prompt", "upload_name"}}
    for field in ("message", "error"):
        if field in result:
            result[field] = _LEGACY_MESSAGES.get(result[field], result[field])
    if "warnings" in result:
        result["warnings"] = [_LEGACY_MESSAGES.get(warning, warning) for warning in result["warnings"]]
    return result
