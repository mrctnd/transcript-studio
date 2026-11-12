import logging
import os
import shutil
import threading
import time

from .media import JobCancelled, JobError

logger = logging.getLogger(__name__)


def lock_data_directory(directory):
    directory.mkdir(parents=True, exist_ok=True)
    lock = (directory / "instance.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        lock.close()
        raise RuntimeError("Another Transcript Studio process is using this data directory.") from exc
    return lock


class JobWorker:
    def __init__(self, store, downloader, transcriber):
        self.store = store
        self.downloader = downloader
        self.transcriber = transcriber
        self.wakeup = threading.Event()
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self.run, name="transcription-worker", daemon=True)

    def start(self):
        self.data_lock = lock_data_directory(self.store.data_dir)
        try:
            self.store.initialize()
            self.store.recover()
            for path in self.store.media_dir.iterdir():
                if path.is_dir() and len(path.name) == 32 and all(c in "0123456789abcdef" for c in path.name):
                    shutil.rmtree(path, ignore_errors=True)
            self.thread.start()
        except BaseException:
            self.data_lock.close()
            raise

    def close(self):
        self.stopping.set()
        self.wakeup.set()
        self.thread.join(timeout=3)

    def run(self):
        try:
            while not self.stopping.is_set():
                self.wakeup.clear()
                job = self.store.claim()
                if job is None:
                    self.wakeup.wait(timeout=2)
                    continue
                self.process(job)
        finally:
            self.data_lock.close()

    def process(self, job):
        job_id = job["id"]
        directory = self.store.media_dir / job_id
        last_status = job["status"]
        last_progress = job["progress"]
        last_write = 0.0
        last_checkpoint = 0.0

        def checkpoint():
            nonlocal last_checkpoint
            if self.stopping.is_set():
                raise JobCancelled
            now = time.monotonic()
            if now - last_checkpoint >= 0.15:
                last_checkpoint = now
                if self.store.get(job_id)["status"] == "cancelled":
                    raise JobCancelled

        def report(status, progress, message):
            nonlocal last_status, last_progress, last_write
            now = time.monotonic()
            if status == last_status and (progress <= last_progress or now - last_write < 0.5):
                return
            if not self.store.update_active(job_id, status=status, progress=progress, message=message):
                raise JobCancelled
            last_status, last_progress, last_write = status, progress, now

        result = None
        try:
            checkpoint()
            if job["source_type"] == "url":
                directory.mkdir(exist_ok=True)
                path, title = self.downloader(job["source_url"], directory, report, checkpoint)
                self.store.update_active(job_id, title=title)
            else:
                path = directory / job["upload_name"]
            checkpoint()
            transcript = self.transcriber(path, job, report, checkpoint)
            checkpoint()
            result = {"status": "completed", "progress": 100, "message": "Transcript ready.", **transcript}
        except (JobCancelled, KeyError):
            if self.stopping.is_set():
                result = {
                    "status": "cancelled", "message": "The job was cancelled when the application shut down.",
                }
        except JobError as exc:
            result = {"status": "failed", "message": "The job could not be completed.", "error": str(exc)}
        except Exception:
            logger.exception("Job %s failed", job_id)
            result = {
                "status": "failed", "message": "The job could not be completed.",
                "error": "An unexpected error occurred. Check the application log.",
            }
        finally:
            shutil.rmtree(directory, ignore_errors=True)
        if result is not None:
            self.store.update_active(job_id, **result)
