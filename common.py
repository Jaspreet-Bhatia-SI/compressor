"""Shared types, size helpers, media probing, and atomic commit utilities."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class CompressionResult:
    """Outcome metrics for a single compressed file."""

    source: Path
    output: Path
    original_bytes: int
    compressed_bytes: int
    engine: str
    skipped_larger: bool = False

    @property
    def saved_bytes(self) -> int:
        return self.original_bytes - self.compressed_bytes

    @property
    def reduction_pct(self) -> float:
        if self.original_bytes == 0:
            return 0.0
        return (self.saved_bytes / self.original_bytes) * 100.0


def parse_size(size_str: str) -> int:
    """Parse a human-readable size string (e.g. '500KB', '5MB') into bytes."""
    cleaned = size_str.strip().upper()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(B|KB|K|MB|M|GB|G)?", cleaned)
    if not match:
        raise ValueError(
            f"Invalid size format '{size_str}'. Use values like '500KB', '2MB', or '1048576'."
        )
    value = float(match.group(1))
    unit = match.group(2) or "B"
    multipliers = {
        "B": 1,
        "K": 1024,
        "KB": 1024,
        "M": 1024**2,
        "MB": 1024**2,
        "G": 1024**3,
        "GB": 1024**3,
    }
    return int(value * multipliers[unit])


def format_size(num_bytes: int) -> str:
    """Format byte counts cleanly for CLI display."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} GB"


def make_temp_path(dest: Path, suffix: str) -> Path:
    """Create a safe temporary path in the destination directory for atomic replacement."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".cmp_", suffix=suffix, dir=str(dest.parent))
    os.close(fd)
    return Path(tmp_name)


def finalize_output(
    source: Path,
    tmp_path: Path,
    dest: Path,
    engine_label: str,
    keep_smaller: bool = True,
    allow_keep_original: bool = True,
) -> CompressionResult:
    """Commit temporary compressed output to dest, or keep original if output grew."""
    orig_size = source.stat().st_size
    new_size = tmp_path.stat().st_size

    if keep_smaller and allow_keep_original and new_size >= orig_size:
        if source.resolve() != dest.resolve():
            shutil.copy2(source, dest)
        tmp_path.unlink(missing_ok=True)
        return CompressionResult(
            source=source,
            output=dest,
            original_bytes=orig_size,
            compressed_bytes=orig_size,
            engine="kept original (already optimal)",
            skipped_larger=True,
        )

    shutil.move(str(tmp_path), str(dest))
    return CompressionResult(
        source=source,
        output=dest,
        original_bytes=orig_size,
        compressed_bytes=new_size,
        engine=engine_label,
    )


def probe_duration_seconds(source: Path) -> Optional[float]:
    """Return media duration in seconds using ffprobe, or None if unavailable."""
    ffprobe_bin = shutil.which("ffprobe")
    if not ffprobe_bin:
        return None
    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(source),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if proc.returncode != 0:
        return None
    try:
        dur = float(proc.stdout.strip())
        return dur if dur > 0 else None
    except ValueError:
        return None


def require_ffmpeg() -> str:
    """Return path to ffmpeg binary or raise a clear error."""
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise RuntimeError("FFmpeg is required for video/audio compression but was not found on PATH.")
    return ffmpeg_bin
