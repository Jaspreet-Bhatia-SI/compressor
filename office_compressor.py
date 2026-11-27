"""Dedicated Office document compressor (.docx, .pptx, .xlsx, .odt, .odp, .ods).

CLI Usage Examples:
    python main.py slides.pptx                       # Downscale & compress embedded slide media (stays editable)
    python main.py report.docx -p high --max-width 1024
    python main.py deck.pptx -f pdf -t 3MB           # Export to PDF via LibreOffice & shrink under 3 MB
    python main.py ./docs -r --type office -o ./out/

Python API Example:
    from pathlib import Path
    from office_compressor import compress_office

    res = compress_office(Path("slides.pptx"), Path("slides_compressed.pptx"), preset="medium")
    print(f"Saved {res.reduction_pct:.1f}% using {res.engine}")
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from common import CompressionResult, finalize_output, make_temp_path
from image_compressor import IMAGE_EXTENSIONS, compress_image
from pdf_compressor import compress_pdf

OFFICE_EXTENSIONS = {".docx", ".pptx", ".xlsx", ".odt", ".odp", ".ods"}

OFFICE_PRESETS = {
    "low": {"max_dim": 1920, "quality": 85},
    "medium": {"max_dim": 1280, "quality": 70},
    "high": {"max_dim": 800, "quality": 50},
}

MEDIA_IMAGE_PREFIXES = ("word/media/", "ppt/media/", "xl/media/", "Pictures/")
RECOMPRESSIBLE_MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def _convert_office_to_pdf(
    source: Path,
    dest: Path,
    preset: str,
    dpi: Optional[int],
    quality: Optional[int],
    target_bytes: Optional[int],
    keep_smaller: bool,
) -> CompressionResult:
    """Convert an Office file to PDF using LibreOffice and compress the resulting PDF."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("LibreOffice ('soffice') is required to convert Office files to PDF.")

    with tempfile.TemporaryDirectory(prefix="cmp_office_pdf_") as tmp_dir:
        tmp_dir_path = Path(tmp_dir)
        proc = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(tmp_dir_path), str(source)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        generated_pdf = tmp_dir_path / f"{source.stem}.pdf"
        if proc.returncode != 0 or not generated_pdf.exists():
            raise RuntimeError(f"LibreOffice failed to convert {source.name}: {proc.stderr.strip()}")

        return compress_pdf(
            generated_pdf,
            dest,
            preset=preset,
            dpi=dpi,
            quality=quality,
            target_bytes=target_bytes,
            keep_smaller=keep_smaller,
        )


def compress_office(
    source: Path,
    dest: Path,
    preset: str = "medium",
    quality: Optional[int] = None,
    max_width: Optional[int] = None,
    max_height: Optional[int] = None,
    dpi: Optional[int] = None,
    output_format: str = "keep",
    target_bytes: Optional[int] = None,
    keep_smaller: bool = True,
) -> CompressionResult:
    """Compress embedded images and ZIP deflation inside Office documents."""
    if output_format.lower() == "pdf":
        return _convert_office_to_pdf(source, dest, preset, dpi, quality, target_bytes, keep_smaller)

    cfg = OFFICE_PRESETS[preset]
    img_quality = quality if quality is not None else cfg["quality"]
    bound_w = max_width if max_width is not None else cfg["max_dim"]
    bound_h = max_height if max_height is not None else cfg["max_dim"]

    tmp_path = make_temp_path(dest, source.suffix.lower())
    optimized_images = 0

    try:
        with tempfile.TemporaryDirectory(prefix="cmp_office_") as work_dir:
            work_path = Path(work_dir)
            with zipfile.ZipFile(source, "r") as zin, zipfile.ZipFile(
                tmp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
            ) as zout:
                for idx, item in enumerate(zin.infolist()):
                    data = zin.read(item.filename)
                    entry_path = Path(item.filename)
                    ext = entry_path.suffix.lower()

                    is_embedded_img = (
                        not item.is_dir()
                        and any(item.filename.startswith(prefix) for prefix in MEDIA_IMAGE_PREFIXES)
                        and ext in (RECOMPRESSIBLE_MEDIA_EXTS & IMAGE_EXTENSIONS)
                    )

                    if is_embedded_img and len(data) > 0:
                        src_img = work_path / f"in_{idx}{ext}"
                        out_img = work_path / f"out_{idx}{ext}"
                        src_img.write_bytes(data)
                        try:
                            res = compress_image(
                                src_img,
                                out_img,
                                quality=img_quality,
                                preset=preset,
                                max_width=bound_w,
                                max_height=bound_h,
                                output_format="keep",
                                keep_smaller=True,
                            )
                            new_bytes = out_img.read_bytes()
                            if len(new_bytes) < len(data):
                                data = new_bytes
                                if not res.skipped_larger:
                                    optimized_images += 1
                        except Exception:
                            pass

                    zip_info = zipfile.ZipInfo(filename=item.filename, date_time=item.date_time)
                    zip_info.compress_type = zipfile.ZIP_DEFLATED
                    zip_info.external_attr = item.external_attr
                    zout.writestr(zip_info, data)

        engine = f"office-zip ({optimized_images} media img)" if optimized_images else "office-zip/deflate-9"
        return finalize_output(
            source,
            tmp_path,
            dest,
            engine,
            keep_smaller=keep_smaller,
            allow_keep_original=True,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
