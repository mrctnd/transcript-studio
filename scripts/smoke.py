"""Real API smoke test. Run against a running server; accepts your own short audio."""
import argparse
import json
import time
import urllib.request
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--model", default="tiny")
    parser.add_argument("--language", default="en")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    def request(path, data=None, headers=None):
        with urllib.request.urlopen(urllib.request.Request(args.base + path, data=data, headers=headers or {}), timeout=30) as response:
            return response.read()

    print(request("/api/health").decode(), flush=True)
    boundary = "----Smoke" + uuid.uuid4().hex
    parts = []
    for key, value in {"model": args.model, "language": args.language}.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{args.audio.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode())
    parts.extend([args.audio.read_bytes(), f"\r\n--{boundary}--\r\n".encode()])
    job = json.loads(request("/api/jobs/upload", b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={boundary}"}))
    print("JOB", job["id"], flush=True)
    deadline = time.monotonic() + args.timeout
    previous = None
    while time.monotonic() < deadline:
        job = json.loads(request(f'/api/jobs/{job["id"]}'))
        status = (job["status"], job["progress"])
        if status != previous:
            print(status, job.get("message", ""), flush=True)
            previous = status
        if job["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(2)
    assert job["status"] == "completed", job
    assert job["segments"], "No speech segments found"
    for fmt in ("md", "txt", "srt", "vtt", "json"):
        exported = request(f'/api/jobs/{job["id"]}/export?format={fmt}&timestamps=true').decode("utf-8-sig")
        assert exported.strip(), fmt
        if fmt == "json":
            assert json.loads(exported)["segments"]
        if fmt == "srt":
            assert " --> " in exported and "," in exported
        if fmt == "vtt":
            assert exported.startswith("WEBVTT")
        print("EXPORT", fmt, "OK", flush=True)
    print(json.dumps({"job_id": job["id"], "text": " ".join(s["text"] for s in job["segments"]), "segments": len(job["segments"])}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
