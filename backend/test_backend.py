import http.client
import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import wave
from fractions import Fraction
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import uvicorn

from .exports import render_export
from .main import create_app
from .media import JobError, decode_audio, validate_url
from .models import Settings
from .store import JobStore, public_job


@contextmanager
def serve(app):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            until(lambda: server.started)
            yield port
        finally:
            server.should_exit = True
            thread.join(5)
            if thread.is_alive():
                raise RuntimeError("Test server did not exit")


def until(read, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = read()
        if result:
            return result
        time.sleep(0.025)
    raise AssertionError("Timed out waiting for condition")


def request(port, method, path, body=None, headers=None):
    headers = dict(headers or {})
    if isinstance(body, dict):
        headers["Content-Type"] = "application/json"
        body = json.dumps(body)
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path, body, headers)
        response = connection.getresponse()
        payload = response.read()
        if "application/json" in response.getheader("content-type", ""):
            payload = json.loads(payload)
        return response.status, payload, dict(response.getheaders())
    finally:
        connection.close()


def upload(port, name, media=b"audio"):
    boundary = "BackendTestUpload"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
        'Content-Type: audio/wav\r\n\r\n'
    ).encode() + media + (
        f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\ntiny'
        f'\r\n--{boundary}--\r\n'
    ).encode()
    return request(port, "POST", "/api/jobs/upload", body, {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    })


def wait_for_job(port, job_id, status):
    def read():
        _, job, _ = request(port, "GET", f"/api/jobs/{job_id}")
        if job["status"] == status:
            return job
        if job["status"] in {"completed", "cancelled", "failed"}:
            raise AssertionError(job)
        return None

    return until(read)


def fake_transcribe(path, job, report, checkpoint):
    assert path.read_bytes() == b"audio"
    checkpoint()
    report("transcribing", 60, "Test")
    return {
        "duration": 61.4,
        "language": "tr",
        "segments": [{
            "id": "1", "start": 59.9996, "end": 61.4, "text": "Merhaba <dünya>",
            "words": [{"start": 60.0, "end": 61.4, "word": "Merhaba"}],
        }],
        "warnings": [],
    }


class BackendTests(unittest.TestCase):
    def test_legacy_job_messages_are_translated_without_changing_transcript(self):
        stored = {
            "message": "Transkript hazır.",
            "error": None,
            "warnings": ["Medya dosyasında algılanabilir konuşma bulunamadı."],
            "title": "Transkript hazır.",
            "segments": [{"text": "Transkript hazır."}],
        }
        published = public_job(stored)
        self.assertEqual(published["message"], "Transcript ready.")
        self.assertIsNone(published["error"])
        self.assertEqual(published["warnings"], ["No speech was detected in the media file."])
        self.assertEqual(published["title"], stored["title"])
        self.assertEqual(published["segments"], stored["segments"])
        self.assertEqual(stored["message"], "Transkript hazır.")

    def test_subtitle_cues_have_positive_duration_at_millisecond_precision(self):
        job = {"segments": [{"start": 1.0001, "end": 1.0004, "text": "Merhaba"}]}
        for format, decimal in (("vtt", "."), ("srt", ",")):
            with self.subTest(format=format):
                rendered, _ = render_export(job, format, True)
                self.assertIn(f"00:00:01{decimal}000 --> 00:00:01{decimal}001", rendered)

    def test_url_validation(self):
        for url in (
            "file:///media.wav", "http://localhost/media", "http://127.1/media",
            "http://[::1]/media", "http://10.1.2.3/media", "http://169.254.169.254/",
            "https://person:password@example.com/video", "http://localhost%2e/video",
            "https://example.com\\@localhost/video", "http://[::ffff:127.0.0.1]/",
            "http://224.0.0.1/", "http://[ff02::1]/",
        ):
            with self.subTest(url=url), self.assertRaises(JobError):
                validate_url(url)
        self.assertEqual(validate_url("  https://1.1.1.1/video  "), "https://1.1.1.1/video")
        with patch("backend.media.socket.getaddrinfo", return_value=[
            (0, 0, 0, "", ("8.8.8.8", 443)), (0, 0, 0, "", ("192.168.1.2", 443)),
        ]), self.assertRaises(JobError):
            validate_url("https://mixed.example/video")

    def test_upload_edit_export_restart_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory, transcriber=fake_transcribe)
            with serve(app) as port:
                code, health, _ = request(port, "GET", "/api/health")
                self.assertEqual(code, 200)
                self.assertIn("tiny", health["models"])
                code, queued, _ = upload(port, "görüşme.wav")
                self.assertEqual(code, 201)
                self.assertEqual(queued["status"], "queued")
                job = wait_for_job(port, queued["id"], "completed")
                path = f"/api/jobs/{job['id']}"
                self.assertEqual(job["title"], "görüşme.wav")
                self.assertEqual(job["language"], "tr")
                self.assertFalse((Path(directory) / "media" / job["id"]).exists())
                self.assertEqual(request(port, "GET", path + "/export?format=srt")[1],
                                 "1\n00:01:00,000 --> 00:01:01,400\nMerhaba <dünya>\n".encode())
                self.assertIn(b"Merhaba &lt;", request(port, "GET", path + "/export?format=vtt")[1])
                self.assertIn(b"[00:01:00.000]", request(port, "GET", path + "/export?format=txt")[1])
                self.assertNotIn(b"[00:", request(port, "GET", path + "/export?format=md&timestamps=false")[1])
                self.assertEqual(request(port, "GET", path + "/export?format=json&timestamps=false")[1]["segments"],
                                 [{"id": "1", "text": "Merhaba <dünya>"}])
                changed = {"id": "1", "start": 60, "end": 61.4, "text": "Düzeltilmiş"}
                self.assertEqual(request(port, "PATCH", path, {"segments": [changed, changed]})[0], 422)
                code, revised, _ = request(port, "PATCH", path, {"segments": [changed]})
                self.assertEqual(code, 200)
                self.assertEqual(revised["segments"], [changed])
            with serve(create_app(directory, transcriber=fake_transcribe)) as port:
                self.assertEqual(request(port, "GET", "/api/jobs")[1][0]["segments"], [changed])
                self.assertEqual(request(port, "DELETE", path)[0], 204)
                self.assertEqual(request(port, "GET", path)[0], 404)

    def test_single_worker_cancel_queued_and_running(self):
        entered = threading.Event()
        release = threading.Event()

        def busy_transcriber(path, job, report, checkpoint):
            report("transcribing", 50, "Test")
            entered.set()
            while not release.wait(0.025):
                checkpoint()
            return fake_transcribe(path, job, report, checkpoint)

        with tempfile.TemporaryDirectory() as directory, serve(
            create_app(directory, transcriber=busy_transcriber)
        ) as port:
            try:
                first = upload(port, "first.wav")[1]
                self.assertTrue(entered.wait(5))
                second = upload(port, "second.wav")[1]
                first_path = f"/api/jobs/{first['id']}"
                second_path = f"/api/jobs/{second['id']}"
                self.assertEqual(request(port, "GET", second_path)[1]["status"], "queued")
                self.assertEqual(request(port, "DELETE", first_path)[0], 409)
                self.assertEqual(request(port, "GET", first_path + "/export")[0], 409)
                self.assertEqual(request(port, "POST", second_path + "/cancel")[1]["status"], "cancelled")
                self.assertEqual(request(port, "POST", first_path + "/cancel")[1]["status"], "cancelled")
                until(lambda: not list((Path(directory) / "media").iterdir()))
                self.assertEqual(request(port, "GET", first_path)[1]["status"], "cancelled")
            finally:
                release.set()

    def test_url_error_recovery_and_request_validation(self):
        def fail_download(url, directory, report, checkpoint):
            raise JobError("The media source is unavailable.")

        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory))
            store.initialize()
            previous = store.create(Settings(), title="Kesilen iş", source_url="https://1.1.1.1/")
            with serve(create_app(directory, downloader=fail_download, transcriber=fake_transcribe)) as port:
                self.assertEqual(request(port, "GET", f"/api/jobs/{previous['id']}")[1]["status"], "failed")
                valid = {"url": "https://1.1.1.1/video", "model": "tiny"}
                self.assertEqual(request(port, "POST", "/api/jobs", valid, {"Origin": "https://outside.example"})[0],
                                 403)
                self.assertEqual(request(port, "GET", "/api/jobs", headers={"Host": "outside.example"})[0], 403)
                self.assertEqual(request(port, "POST", "/api/jobs", {"url": "http://127.0.0.1"})[0], 422)
                self.assertEqual(upload(port, "empty.wav", b"")[0], 422)
                with patch("backend.main.MAX_BYTES", 10):
                    self.assertEqual(upload(port, "large.wav", b"12345678901")[0], 413)
                code, queued, _ = request(port, "POST", "/api/jobs", valid)
                self.assertEqual(code, 201)
                failed = wait_for_job(port, queued["id"], "failed")
                self.assertEqual(failed["error"], "The media source is unavailable.")
                self.assertFalse(list((Path(directory) / "media").iterdir()))

    def test_second_process_does_not_recover_or_clean_live_jobs(self):
        entered = threading.Event()
        release = threading.Event()

        def busy_transcriber(path, job, report, checkpoint):
            report("transcribing", 50, "Test")
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Test did not release worker")
            return fake_transcribe(path, job, report, checkpoint)

        script = """
import sys
from pathlib import Path
from backend.store import JobStore
from backend.worker import JobWorker
worker = JobWorker(JobStore(Path(sys.argv[1])), None, None)
try:
    worker.start()
except RuntimeError:
    sys.exit(75)
else:
    worker.close()
"""
        with tempfile.TemporaryDirectory() as directory, serve(
            create_app(directory, transcriber=busy_transcriber)
        ) as port:
            job_id = upload(port, "active.wav")[1]["id"]
            try:
                self.assertTrue(entered.wait(5))
                result = subprocess.run([sys.executable, "-c", script, directory], timeout=5)
                self.assertEqual(result.returncode, 75)
                self.assertEqual(request(port, "GET", f"/api/jobs/{job_id}")[1]["status"], "transcribing")
                self.assertTrue((Path(directory) / "media" / job_id / "upload.wav").is_file())
            finally:
                release.set()
            wait_for_job(port, job_id, "completed")

    def test_real_pyav_decode_and_duration_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.wav"
            with wave.open(str(path), "wb") as wav:
                wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                wav.writeframes(b"\x00\x00" * 16000)
            self.assertEqual(len(decode_audio(path, lambda: None)), 32000)
            with patch("backend.media.MAX_DURATION", 1), self.assertRaisesRegex(JobError, "no longer than two hours"):
                decode_audio(path, lambda: None)

    def test_delayed_audio_preserves_video_timeline(self):
        import av
        import numpy as np

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "delayed.mkv"
            with av.open(str(path), "w") as container:
                video = container.add_stream("ffv1", rate=10)
                video.width, video.height, video.pix_fmt = 16, 16, "yuv420p"
                audio = container.add_stream("pcm_s16le", rate=16000)
                audio.layout = "mono"
                for index in range(31):
                    frame = av.VideoFrame.from_ndarray(np.zeros((16, 16, 3), dtype=np.uint8), format="rgb24")
                    frame.pts, frame.time_base = index, Fraction(1, 10)
                    for packet in video.encode(frame):
                        container.mux(packet)
                for packet in video.encode(None):
                    container.mux(packet)
                frame = av.AudioFrame.from_ndarray(np.full((1, 16000), 8192, dtype=np.int16), format="s16", layout="mono")
                frame.sample_rate = 16000
                frame.pts, frame.time_base = 32000, Fraction(1, 16000)
                for packet in audio.encode(frame):
                    container.mux(packet)
                for packet in audio.encode(None):
                    container.mux(packet)
            decoded = decode_audio(path, lambda: None)
            self.assertEqual(len(decoded), 49600)
            self.assertTrue(np.all(decoded[:32000] == 0))
            self.assertTrue(np.allclose(decoded[32000:48000], 0.25))
            self.assertTrue(np.all(decoded[48000:] == 0))


if __name__ == "__main__":
    unittest.main()
