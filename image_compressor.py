"""Dedicated image compressor using Pillow."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

from common import CompressionResult, finalize_output, make_temp_path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp", ".tiff", ".tif"}

IMAGE_PRESET_QUALITY = {
    "low": 90,
    "medium": 75,
    "high": 50,
}


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
    elif pil_fmt == "AVIF" and save_img.mode not in ("RGB", "RGBA"):
        save_img = save_img.convert("RGBA" if "A" in save_img.mode else "RGB")

    kwargs: dict = {"optimize": True}
    if pil_fmt == "JPEG":
        kwargs.update({"quality": quality, "progressive": True})
    elif pil_fmt == "WEBP":
        kwargs.update({"quality": quality, "method": 6})
    elif pil_fmt == "AVIF":
        kwargs = {"quality": quality, "speed": 6}
    elif pil_fmt == "PNG":
        kwargs["compress_level"] = 9
        if preset == "high" and save_img.mode != "P":
            save_img = save_img.quantize(colors=256, method=Image.Quantize.FASTOCTREE)

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
    """Compress a raster image with optional resize, format conversion, and target size."""
    base_quality = quality if quality is not None else IMAGE_PRESET_QUALITY[preset]
    ext = source.suffix.lstrip(".").lower() or "jpg"
    target_fmt = ext if output_format == "keep" else output_format.lower()

    tmp_path = make_temp_path(dest, f".{target_fmt}")
    best_path = tmp_path.with_suffix(f".best.{target_fmt}")

    try:
        with Image.open(source) as raw_img:
            img = ImageOps.exif_transpose(raw_img)
            img = _resize_to_fit(img, max_width, max_height)

            if target_bytes is None:
                _save_pillow_image(img, tmp_path, target_fmt, base_quality, preset=preset)
            else:
                q_steps = [base_quality, 70, 55, 40, 28, 18] if target_fmt != "png" else [base_quality]
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
