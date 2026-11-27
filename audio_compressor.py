"""Dedicated audio compressor using FFmpeg."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from common import (
    CompressionResult,
    finalize_output,
    make_temp_path,
    probe_duration_seconds,
    require_ffmpeg,
)

AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".opus"}

AUDIO_PRESET_BITRATE = {
    "low": 192,
    "medium": 128,
    "high": 64,
}


def resolve_audio_extension(source: Path, output_format: str) -> str:
    """Resolve target audio extension, converting uncompressed WAV/FLAC to MP3 by default."""
    if output_format != "keep":
        return f".{output_format.lower()}"
    if source.suffix.lower() in (".wav", ".flac"):
        return ".mp3"
    return source.suffix.lower() or ".mp3"


def compress_audio(
    source: Path,
    dest: Path,
    preset: str = "medium",
    bitrate_kbps: Optional[int] = None,
    output_format: str = "keep",
    target_bytes: Optional[int] = None,
    keep_smaller: bool = True,
) -> CompressionResult:
    """Compress an audio file via FFmpeg using preset bitrates or calculated target bitrate."""
    ffmpeg_bin = require_ffmpeg()
    chosen_kbps = bitrate_kbps or AUDIO_PRESET_BITRATE[preset]

    if target_bytes is not None:
        duration = probe_duration_seconds(source)
        if duration:
            # Leave ~6% headroom for container/metadata overhead.
            calc_kbps = int((target_bytes * 8 * 0.94) / duration / 1000)
            chosen_kbps = max(24, min(320, calc_kbps))

    ext = dest.suffix.lower() or resolve_audio_extension(source, output_format)
    codec_map = {
        ".mp3": "libmp3lame",
        ".aac": "aac",
        ".m4a": "aac",
        ".ogg": "libvorbis",
        ".opus": "libopus",
    }
    acodec = codec_map.get(ext, "libmp3lame")
    tmp_path = make_temp_path(dest, ext)

    try:
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(source),
            "-vn",
            "-c:a",
            acodec,
            "-b:a",
            f"{chosen_kbps}k",
            str(tmp_path),
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if proc.returncode != 0 or not tmp_path.exists() or tmp_path.stat().st_size == 0:
            raise RuntimeError(f"FFmpeg audio compression failed: {proc.stderr[-300:].strip()}")

        allow_keep = source.suffix.lower() == dest.suffix.lower()
        return finalize_output(
            source,
            tmp_path,
            dest,
            f"ffmpeg/{acodec} ({chosen_kbps}kbps)",
            keep_smaller=keep_smaller,
            allow_keep_original=allow_keep,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
