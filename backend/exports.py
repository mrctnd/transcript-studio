import html
import json
from typing import Literal

ExportFormat = Literal["md", "txt", "srt", "vtt", "json"]


def timestamp(seconds, decimal="."):
    return format_timestamp(round(seconds * 1000), decimal)


def format_timestamp(milliseconds, decimal):
    whole_seconds, milliseconds = divmod(milliseconds, 1000)
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{decimal}{milliseconds:03d}"


def render_export(job, format: ExportFormat, timestamps: bool):
    segments = job["segments"]
    if format == "json":
        if not timestamps:
            segments = [{"id": segment["id"], "text": segment["text"]} for segment in segments]
        return json.dumps({**job, "segments": segments}, ensure_ascii=False, indent=2) + "\n", "application/json"
    if format in {"srt", "vtt"}:
        cues = []
        for segment in segments:
            decimal = "," if format == "srt" else "."
            text = "\n".join(line.strip() for line in segment["text"].splitlines() if line.strip())
            if format == "vtt":
                text = html.escape(text, quote=False)
            if not text:
                continue
            start_ms = round(segment["start"] * 1000)
            end_ms = max(start_ms + 1, round(segment["end"] * 1000))
            start = format_timestamp(start_ms, decimal)
            end = format_timestamp(end_ms, decimal)
            cue = f"{start} --> {end}\n{text}"
            cues.append(f"{len(cues) + 1}\n{cue}" if format == "srt" else cue)
        prefix = "WEBVTT\n\n" if format == "vtt" else ""
        return prefix + ("\n\n".join(cues) + "\n" if cues else ""), (
            "text/vtt" if format == "vtt" else "application/x-subrip"
        )

    lines = []
    for segment in segments:
        text = segment["text"].strip()
        if timestamps:
            mark = f'[{timestamp(segment["start"])}]'
            text = f"**{mark}** {text}" if format == "md" else f"{mark} {text}"
        if text:
            lines.append(text)
    if format == "md":
        title = html.escape(" ".join(job["title"].splitlines()), quote=False)
        return "\n\n".join([f"# {title}", *lines]) + "\n", "text/markdown"
    return "\n".join(lines) + ("\n" if lines else ""), "text/plain"
