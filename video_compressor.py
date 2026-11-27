"""Dedicated video compressor using FFmpeg.

CLI Usage Examples:
    python main.py clip.mp4                          # Balanced H.264 compression (CRF 26)
    python main.py clip.mp4 --max-height 720 --video-codec h265
    python main.py demo.mov -t 10MB                  # Fit video under 10 MB via duration bitrate math
    python main.py anim.gif -f mp4                   # Convert animated GIF -> fast-start MP4
    python main.py ./videos -r --type video -f webm -o ./out/

Python API Example:
    from pathlib import Path
    from video_compressor import compress_video

    res = compress_video(Path("clip.mp4"), Path("clip_720p.mp4"), max_height=720, codec="h265")
    print(f"Saved {res.reduction_pct:.1f}% using {res.engine}")
"""

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

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv"}

VIDEO_PRESETS = {
    "low": {"crf": 20, "audio_bitrate": "128k"},
    "medium": {"crf": 26, "audio_bitrate": "96k"},
    "high": {"crf": 32, "audio_bitrate": "64k"},
}


def _build_scale_filter(max_width: Optional[int], max_height: Optional[int]) -> Optional[str]:
    """Build an FFmpeg scale filter preserving aspect ratio and even dimensions."""
    if max_width and max_height:
        return (
            f"scale='min({max_width},iw)':'min({max_height},ih)':force_original_aspect_ratio=decrease,"
            "pad=ceil(iw/2)*2:ceil(ih/2)*2"
        )
    if max_width:
        return f"scale='min({max_width},iw)':-2"
    if max_height:
        return f"scale=-2:'min({max_height},ih)'"
    return "pad=ceil(iw/2)*2:ceil(ih/2)*2"


def compress_video(
    source: Path,
    dest: Path,
    preset: str = "medium",
    codec: str = "h264",
    max_width: Optional[int] = None,
    max_height: Optional[int] = None,
    target_bytes: Optional[int] = None,
    keep_smaller: bool = True,
) -> CompressionResult:
    """Compress a video file via FFmpeg (CRF presets or calculated target bitrate)."""
    ffmpeg_bin = require_ffmpeg()
    cfg = VIDEO_PRESETS[preset]

    ext = dest.suffix.lower() or source.suffix.lower() or ".mp4"
    tmp_path = make_temp_path(dest, ext)

    vcodec = "libx265" if codec == "h265" else "libvpx-vp9" if ext == ".webm" else "libx264"
    acodec = "libopus" if ext == ".webm" else "aac"
    vf_filter = _build_scale_filter(max_width, max_height)

    try:
        cmd = [ffmpeg_bin, "-y", "-i", str(source)]
        if vf_filter:
            cmd += ["-vf", vf_filter]

        cmd += ["-c:v", vcodec, "-pix_fmt", "yuv420p"]
        engine_label: str

        if target_bytes is not None:
            duration = probe_duration_seconds(source)
            if duration:
                audio_kbps = 64
                total_kbps = max(80, int((target_bytes * 8 * 0.92) / duration / 1000))
                video_kbps = max(48, total_kbps - audio_kbps)
                cmd += [
                    "-b:v",
                    f"{video_kbps}k",
                    "-maxrate",
                    f"{int(video_kbps * 1.25)}k",
                    "-bufsize",
                    f"{video_kbps * 2}k",
                    "-c:a",
                    acodec,
                    "-b:a",
                    f"{audio_kbps}k",
                ]
                engine_label = f"ffmpeg/{vcodec} (~{video_kbps}kbps)"
            else:
                cmd += ["-crf", str(cfg["crf"]), "-preset", "medium", "-c:a", acodec, "-b:a", cfg["audio_bitrate"]]
                engine_label = f"ffmpeg/{vcodec} (crf={cfg['crf']})"
        else:
            if vcodec in ("libx264", "libx265"):
                cmd += ["-preset", "medium", "-crf", str(cfg["crf"])]
            else:
                cmd += ["-b:v", "0", "-crf", str(cfg["crf"])]
            cmd += ["-c:a", acodec, "-b:a", cfg["audio_bitrate"]]
            engine_label = f"ffmpeg/{vcodec} (crf={cfg['crf']})"

        if ext in (".mp4", ".mov", ".m4v"):
            cmd += ["-movflags", "+faststart"]

        cmd.append(str(tmp_path))
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if proc.returncode != 0 or not tmp_path.exists() or tmp_path.stat().st_size == 0:
            raise RuntimeError(f"FFmpeg video compression failed: {proc.stderr[-300:].strip()}")

        allow_keep = not max_width and not max_height and source.suffix.lower() == dest.suffix.lower()
        return finalize_output(
            source,
            tmp_path,
            dest,
            engine_label,
            keep_smaller=keep_smaller,
            allow_keep_original=allow_keep,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
