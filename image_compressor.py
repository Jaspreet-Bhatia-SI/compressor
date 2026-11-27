"""Dedicated image compressor using Pillow, pillow-heif, and FFmpeg (for animated GIFs).

CLI Usage Examples:
    python main.py photo.jpg                         # Compress keeping original format
    python main.py photo.heic -p medium -f avif      # Convert iPhone HEIC -> tiny AVIF
    python main.py banner.png --max-width 1920 -f webp
    python main.py avatar.jpg -t 200KB               # Auto-fit image under 200 KB
    python main.py anim.gif -p high --max-width 480  # Shrink animated GIF (palettegen)
    python main.py anim.gif -f mp4                   # Convert animated GIF -> MP4 video

Python API Example:
    from pathlib import Path
    from image_compressor import compress_image

    res = compress_image(Path("photo.heic"), Path("photo.avif"), preset="medium", output_format="avif")
    print(f"Saved {res.reduction_pct:.1f}% using {res.engine}")
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

from common import CompressionResult, finalize_output, make_temp_path

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".avif",
    ".heic",
    ".heif",
    ".gif",
    ".bmp",
    ".tiff",
    ".tif",
}

IMAGE_PRESET_QUALITY = {
    "low": 90,
    "medium": 75,
    "high": 50,
}

GIF_PRESET_FPS = {
    "low": 15,
    "medium": 12,
    "high": 8,
}


def _compress_gif_ffmpeg(
    source: Path,
    tmp_path: Path,
    preset: str,
    max_width: Optional[int],
    max_height: Optional[int],
) -> bool:
    """Optimize an animated GIF using FFmpeg's two-pass palettegen/paletteuse filter."""
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        return False

    fps = GIF_PRESET_FPS[preset]
    filters = [f"fps={fps}"]
    if max_width and max_height:
        filters.append(f"scale='min({max_width},iw)':'min({max_height},ih)':force_original_aspect_ratio=decrease:flags=lanczos")
    elif max_width:
        filters.append(f"scale='min({max_width},iw)':-1:flags=lanczos")
    elif max_height:
        filters.append(f"scale=-1:'min({max_height},ih)':flags=lanczos")

    chain = ",".join(filters)
    max_colors = {"low": 256, "medium": 160, "high": 96}[preset]
    filter_complex = (
        f"[0:v]{chain},split[a][b];"
        f"[a]palettegen=max_colors={max_colors}:stats_mode=diff[p];"
        "[b][p]paletteuse=dither=bayer:bayer_scale=3"
    )
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(source),
        "-filter_complex",
        filter_complex,
        "-loop",
        "0",
        str(tmp_path),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return proc.returncode == 0 and tmp_path.exists() and tmp_path.stat().st_size > 0


def _save_pillow_image(
    img: Image.Image,
    dest: Path,
    target_format: str,
    quality: int,
    preset: str = "medium",
) -> None:
    """Encode a Pillow image cleanly to disk using the requested format and quality."""
    fmt_map = {
        "jpg": "JPEG",
        "jpeg": "JPEG",
        "png": "PNG",
        "webp": "WEBP",
        "avif": "AVIF",
        "heic": "HEIF",
        "heif": "HEIF",
        "gif": "GIF",
        "tiff": "TIFF",
        "tif": "TIFF",
        "bmp": "BMP",
    }
    pil_fmt = fmt_map.get(target_format.lower(), "JPEG")

    save_img = img
    if pil_fmt == "JPEG" and save_img.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", save_img.size, (255, 255, 255))
        if save_img.mode == "P":
            save_img = save_img.convert("RGBA")
        background.paste(save_img, mask=save_img.split()[-1] if "A" in save_img.mode else None)
        save_img = background
    elif pil_fmt == "JPEG" and save_img.mode != "RGB":
        save_img = save_img.convert("RGB")
    elif pil_fmt in ("AVIF", "HEIF") and save_img.mode not in ("RGB", "RGBA"):
        save_img = save_img.convert("RGBA" if "A" in save_img.mode else "RGB")

    kwargs: dict = {"optimize": True}
    if pil_fmt == "JPEG":
        kwargs.update({"quality": quality, "progressive": True})
    elif pil_fmt == "WEBP":
        kwargs.update({"quality": quality, "method": 6})
    elif pil_fmt == "AVIF":
        kwargs = {"quality": quality, "speed": 6}
    elif pil_fmt == "HEIF":
        kwargs = {"quality": quality}
    elif pil_fmt == "PNG":
        kwargs["compress_level"] = 9
        if preset == "high" and save_img.mode != "P":
            save_img = save_img.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
    elif pil_fmt == "GIF":
        kwargs = {"optimize": True, "save_all": True}

    save_img.save(dest, format=pil_fmt, **kwargs)


def _resize_to_fit(
    img: Image.Image,
    max_width: Optional[int],
    max_height: Optional[int],
) -> Image.Image:
    """Downscale image preserving aspect ratio if it exceeds max bounds."""
    if not max_width and not max_height:
        return img
    w, h = img.size
    bound_w = max_width or w
    bound_h = max_height or h
    if w <= bound_w and h <= bound_h:
        return img
    copy = img.copy()
    copy.thumbnail((bound_w, bound_h), Image.Resampling.LANCZOS)
    return copy


def compress_image(
    source: Path,
    dest: Path,
    quality: Optional[int] = None,
    preset: str = "medium",
    max_width: Optional[int] = None,
    max_height: Optional[int] = None,
    output_format: str = "keep",
    target_bytes: Optional[int] = None,
    keep_smaller: bool = True,
) -> CompressionResult:
    """Compress a raster image (including HEIC, AVIF, and animated GIFs) with optional resize and target size."""
    base_quality = quality if quality is not None else IMAGE_PRESET_QUALITY[preset]
    ext = source.suffix.lstrip(".").lower() or "jpg"
    target_fmt = ext if output_format == "keep" else output_format.lower()

    tmp_path = make_temp_path(dest, f".{target_fmt}")
    best_path = tmp_path.with_suffix(f".best.{target_fmt}")

    try:
        is_gif_output = target_fmt == "gif"
        if is_gif_output and target_bytes is None and _compress_gif_ffmpeg(
            source, tmp_path, preset=preset, max_width=max_width, max_height=max_height
        ):
            allow_keep = output_format == "keep" and not max_width and not max_height
            return finalize_output(
                source,
                tmp_path,
                dest,
                f"ffmpeg/gif-{preset}",
                keep_smaller=keep_smaller,
                allow_keep_original=allow_keep,
            )

        with Image.open(source) as raw_img:
            n_frames = getattr(raw_img, "n_frames", 1)
            if n_frames > 1 and target_fmt == "webp":
                raw_img.save(
                    tmp_path,
                    format="WEBP",
                    save_all=True,
                    quality=base_quality,
                    method=6,
                )
            else:
                img = ImageOps.exif_transpose(raw_img)
                img = _resize_to_fit(img, max_width, max_height)

                if target_bytes is None:
                    _save_pillow_image(img, tmp_path, target_fmt, base_quality, preset=preset)
                else:
                    q_steps = [base_quality, 70, 55, 40, 28, 18] if target_fmt not in ("png", "gif") else [base_quality]
                    scales = [1.0, 0.85, 0.7, 0.55, 0.4]
                    met_target = False
                    best_size: Optional[int] = None

                    for scale in scales:
                        candidate_img = img
                        if scale < 1.0:
                            new_w = max(1, int(img.width * scale))
                            new_h = max(1, int(img.height * scale))
                            candidate_img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

                        for q in q_steps:
                            _save_pillow_image(
                                candidate_img,
                                tmp_path,
                                target_fmt,
                                q,
                                preset="high" if scale < 1.0 else preset,
                            )
                            cur_size = tmp_path.stat().st_size
                            if best_size is None or cur_size < best_size:
                                best_size = cur_size
                                shutil.copy2(tmp_path, best_path)
                            if cur_size <= target_bytes:
                                met_target = True
                                break
                        if met_target:
                            break

                    if best_path.exists():
                        shutil.move(str(best_path), str(tmp_path))

        allow_keep = output_format == "keep" and not max_width and not max_height
        return finalize_output(
            source,
            tmp_path,
            dest,
            f"pillow/{target_fmt}",
            keep_smaller=keep_smaller,
            allow_keep_original=allow_keep,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
        best_path.unlink(missing_ok=True)


def estimate_min_image_bytes(
    source: Path,
    output_format: str = "keep",
    max_width: Optional[int] = None,
    max_height: Optional[int] = None,
) -> int:
    """Quickly probe the smallest achievable image size for slider bounds."""
    orig_size = source.stat().st_size
    ext = source.suffix.lstrip(".").lower() or "jpg"
    target_fmt = ext if output_format == "keep" else output_format.lower()
    tmp_path = make_temp_path(source, f".min.{target_fmt}")
    try:
        if target_fmt == "gif" and _compress_gif_ffmpeg(
            source, tmp_path, preset="high", max_width=max_width, max_height=max_height
        ):
            return max(1, min(orig_size, tmp_path.stat().st_size) if output_format == "keep" else tmp_path.stat().st_size)

        with Image.open(source) as raw_img:
            img = ImageOps.exif_transpose(raw_img)
            img = _resize_to_fit(img, max_width, max_height)
            new_w = max(1, int(img.width * 0.4))
            new_h = max(1, int(img.height * 0.4))
            candidate = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            _save_pillow_image(candidate, tmp_path, target_fmt, 18, preset="high")
            probed = tmp_path.stat().st_size
            return max(1, min(orig_size, probed) if output_format == "keep" else probed)
    finally:
        tmp_path.unlink(missing_ok=True)
