import ipaddress
import logging
import math
import os
import shutil
import socket
from pathlib import Path
from urllib.parse import urlsplit

MAX_BYTES = 500 * 1024 * 1024
MAX_DURATION = 2 * 60 * 60
SAMPLE_RATE = 16000
logger = logging.getLogger(__name__)


class JobError(Exception):
    pass


class JobCancelled(Exception):
    pass


def validate_url(value: str) -> str:
    url = value.strip()
    try:
        if any(character.isspace() or ord(character) < 32 for character in url) or "\\" in url:
            raise ValueError
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError
        if parsed.username is not None or parsed.password is not None:
            raise ValueError
        hostname = parsed.hostname.rstrip(".")
        if not hostname or "%" in hostname or hostname.lower() in {"localhost", "localhost.localdomain"}:
            raise ValueError
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        ips = [ipaddress.ip_address(entry[4][0]) for entry in addresses]
        if not ips or any(not ip.is_global or ip.is_multicast or ip.is_reserved for ip in ips):
            raise ValueError
    except (ValueError, OSError) as exc:
        raise JobError("Enter a valid public HTTP or HTTPS video URL.") from exc
    return url


class DownloadLogger:
    def debug(self, message):
        logger.debug("%s", message)

    def warning(self, message):
        logger.warning("%s", message)

    def error(self, message):
        logger.warning("%s", message)


def download_media(url, directory, report, checkpoint):
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    validate_url(url)
    rejected = None

    def match_filter(info, *, incomplete):
        nonlocal rejected
        checkpoint()
        if info.get("is_live"):
            rejected = "Live streams are unsupported."
        elif (info.get("duration") or 0) > MAX_DURATION:
            rejected = "Media must be no longer than two hours."
        elif (info.get("filesize") or info.get("filesize_approx") or 0) > MAX_BYTES:
            rejected = "Media files must be 500 MB or smaller."
        return rejected

    def progress(update):
        checkpoint()
        received = update.get("downloaded_bytes") or 0
        if received > MAX_BYTES:
            raise JobError("Media files must be 500 MB or smaller.")
        total = update.get("total_bytes") or update.get("total_bytes_estimate")
        if total:
            report("downloading", 1 + min(18, int(18 * received / total)), "Downloading video.")

    runtimes = {runtime: {} for runtime in ("deno", "node") if shutil.which(runtime)}
    options = {
        "format": "bestaudio[protocol^=http]/best[protocol^=http]/bestaudio/best",
        "outtmpl": str(directory / "source.%(ext)s"),
        "noplaylist": True,
        "playlist_items": "1",
        "match_filter": match_filter,
        "max_filesize": MAX_BYTES,
        "progress_hooks": [progress],
        "socket_timeout": 20,
        "retries": 2,
        "fragment_retries": 2,
        "hls_prefer_native": True,
        "enable_file_urls": False,
        "js_runtimes": runtimes,
        "logger": DownloadLogger(),
        "quiet": True,
        "noprogress": True,
    }
    try:
        with YoutubeDL(options) as downloader:
            result = downloader.extract_info(url, download=True)
    except DownloadError as exc:
        checkpoint()
        raise JobError(
            "The video could not be downloaded. Check that the link points to a public, "
            "supported source or upload the media file."
        ) from exc
    checkpoint()
    if rejected:
        raise JobError(rejected)
    if not result or result.get("_type") in {"playlist", "multi_video"}:
        raise JobError("Enter a link to a single video.")
    files = [
        path for path in directory.glob("source.*")
        if path.is_file() and not path.name.endswith((".part", ".ytdl"))
    ]
    if len(files) != 1:
        raise JobError("The video could not be downloaded or exceeded the 500 MB limit.")
    if files[0].stat().st_size > MAX_BYTES:
        raise JobError("Media files must be 500 MB or smaller.")
    return files[0], str(result.get("title") or url)[:500]


def decode_audio(path: Path, checkpoint):
    import av
    import numpy as np

    # Allow common media demuxers and only local I/O when parsing uploaded files.
    options = {
        "protocol_whitelist": "file",
        "format_whitelist": (
            "mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,ogg,wav,mp3,flac,aac,"
            "avi,mpeg,mpegts,asf,flv,aiff,amr,ac3,ape,wv,caf"
        ),
    }
    buffer = bytearray()

    def append_frame(converted, origin):
        samples = converted.to_ndarray().reshape(-1)
        current = len(buffer) // 4
        target = current
        if converted.pts is not None and converted.time_base is not None:
            target = round((float(converted.pts * converted.time_base) - origin) * SAMPLE_RATE)
            # Millisecond-based containers round frame timestamps. Avoid adding
            # artificial gaps for that rounding, while preserving real offsets.
            if abs(target - current) <= SAMPLE_RATE // 500:
                target = current
        if target + len(samples) > MAX_DURATION * SAMPLE_RATE:
            raise JobError("Media must be no longer than two hours.")
        if target > current:
            buffer.extend(b"\0" * ((target - current) * 4))
        elif target < current:
            samples = samples[min(len(samples), current - target):]
        buffer.extend(samples.tobytes())

    try:
        with av.open(str(path), options=options) as container:
            if not container.streams.audio:
                raise JobError("The media file has no audio track.")
            if container.duration and container.duration / av.time_base > MAX_DURATION:
                raise JobError("Media must be no longer than two hours.")
            origin = (container.start_time or 0) / av.time_base
            resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
            for frame in container.decode(audio=0):
                checkpoint()
                for converted in resampler.resample(frame):
                    append_frame(converted, origin)
                if len(buffer) > MAX_DURATION * SAMPLE_RATE * 4:
                    raise JobError("Media must be no longer than two hours.")
            for converted in resampler.resample(None):
                append_frame(converted, origin)
            if buffer and container.duration:
                total_samples = round(container.duration / av.time_base * SAMPLE_RATE)
                if total_samples > len(buffer) // 4:
                    buffer.extend(b"\0" * (total_samples * 4 - len(buffer)))
    except (av.error.FFmpegError, ValueError) as exc:
        raise JobError("The audio could not be read. Upload a valid video or audio file.") from exc
    if not buffer:
        raise JobError("The media file has no readable audio.")
    if len(buffer) > MAX_DURATION * SAMPLE_RATE * 4:
        raise JobError("Media must be no longer than two hours.")
    return np.frombuffer(buffer, dtype=np.float32)


class WhisperEngine:
    def __init__(self, models_dir):
        self.device = os.environ.get("TRANSCRIPT_DEVICE", "cpu").strip().lower()
        if self.device not in {"cpu", "cuda", "auto"}:
            self.device = "cpu"
        self.models_dir = models_dir
        self.model_name = None
        self.model = None

    def __call__(self, path, job, report, checkpoint):
        from faster_whisper import WhisperModel

        report("loading_model", 20, "Preparing audio.")
        audio = decode_audio(path, checkpoint)
        duration = len(audio) / SAMPLE_RATE
        checkpoint()
        model_name = job["model"]
        if self.model_name != model_name:
            report("loading_model", 25, "Loading the model. First use may require a download.")
            self.model_name = None
            self.model = None
            try:
                self.model = WhisperModel(
                    model_name, device=self.device,
                    compute_type="int8" if self.device == "cpu" else "default",
                    download_root=str(self.models_dir),
                )
            except Exception as exc:
                logger.exception("Could not load Whisper model %s", model_name)
                raise JobError(
                    "The model could not be loaded. Check your internet connection and free disk space "
                    "or select a smaller model."
                ) from exc
            self.model_name = model_name
        checkpoint()
        report("transcribing", 30, "Transcribing audio.")
        try:
            stream, info = self.model.transcribe(
                audio,
                language=None if job["language"] == "auto" else job["language"],
                initial_prompt=job["initial_prompt"] or None,
                word_timestamps=True,
                vad_filter=True,
            )
            segments = []
            for segment in stream:
                checkpoint()
                text = segment.text.strip()
                if text:
                    words = []
                    for word in segment.words or []:
                        words.append({
                            "start": word.start, "end": word.end, "word": word.word,
                            **({"probability": word.probability} if math.isfinite(word.probability) else {}),
                        })
                    segments.append({
                        "id": str(segment.id), "start": segment.start, "end": segment.end,
                        "text": text, "words": words,
                    })
                report("transcribing", min(98, 30 + int(68 * segment.end / duration)),
                       "Transcribing audio.")
        except JobCancelled:
            raise
        except Exception as exc:
            logger.exception("Whisper inference failed")
            raise JobError("The audio could not be transcribed. Check the language and model settings.") from exc
        warnings = [] if segments else ["No speech was detected in the media file."]
        return {"segments": segments, "duration": duration, "language": info.language, "warnings": warnings}
