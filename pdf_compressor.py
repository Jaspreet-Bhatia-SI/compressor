"""Dedicated PDF compressor using Ghostscript and PyMuPDF.

CLI Usage Examples:
    python main.py document.pdf                      # Balanced compression (/ebook preset)
    python main.py scan.pdf -p high                  # Aggressive screen preset (72 DPI)
    python main.py syllabus.pdf -t 2MB               # Auto-fit PDF under 2 MB
    python main.py book.pdf --dpi 120 -q 60          # Custom image DPI & JPEG quality
    python main.py ./pdfs -r --type pdf -o ./out/    # Batch compress all PDFs in a folder

Python API Example:
    from pathlib import Path
    from pdf_compressor import compress_pdf

    res = compress_pdf(Path("report.pdf"), Path("report_compressed.pdf"), target_bytes=2 * 1024 * 1024)
    print(f"Saved {res.reduction_pct:.1f}% using {res.engine}")
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

import pymupdf

from common import CompressionResult, finalize_output, make_temp_path

PDF_EXTENSIONS = {".pdf"}

PDF_PRESET_SETTINGS = {
    "low": {"gs": "/prepress", "dpi": 300, "quality": 85},
    "medium": {"gs": "/ebook", "dpi": 150, "quality": 65},
    "high": {"gs": "/screen", "dpi": 72, "quality": 40},
}


def _run_ghostscript(source: Path, dest: Path, pdf_setting: str, dpi: int) -> bool:
    """Compress PDF using Ghostscript if available on PATH."""
    gs_bin = shutil.which("gs")
    if not gs_bin:
        return False

    cmd = [
        gs_bin,
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        f"-dPDFSETTINGS={pdf_setting}",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        "-dDetectDuplicateImages=true",
        "-dCompressFonts=true",
        "-dSubsetFonts=true",
        "-dDownsampleColorImages=true",
        f"-dColorImageResolution={dpi}",
        "-dDownsampleGrayImages=true",
        f"-dGrayImageResolution={dpi}",
        "-dDownsampleMonoImages=true",
        f"-dMonoImageResolution={dpi}",
        f"-sOutputFile={dest}",
        str(source),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return proc.returncode == 0 and dest.exists() and dest.stat().st_size > 0


def _run_pymupdf(source: Path, dest: Path, dpi: int, quality: int) -> bool:
    """Compress PDF via PyMuPDF image recompression and stream deflation."""
    doc = pymupdf.open(source)
    try:
        # PyMuPDF requires dpi_target strictly less than dpi_threshold.
        threshold = max(dpi + 1, int(dpi * 1.1))
        doc.rewrite_images(dpi_threshold=threshold, dpi_target=dpi, quality=quality)
        doc.save(dest, garbage=4, deflate=True, clean=True)
        return dest.exists() and dest.stat().st_size > 0
    finally:
        doc.close()


def compress_pdf(
    source: Path,
    dest: Path,
    preset: str = "medium",
    dpi: Optional[int] = None,
    quality: Optional[int] = None,
    target_bytes: Optional[int] = None,
    keep_smaller: bool = True,
) -> CompressionResult:
    """Compress a PDF using Ghostscript and/or PyMuPDF, selecting the smallest clean result."""
    cfg = PDF_PRESET_SETTINGS[preset]
    chosen_dpi = dpi or cfg["dpi"]
    chosen_quality = quality if quality is not None else cfg["quality"]

    tmp_best = make_temp_path(dest, ".pdf")
    tmp_gs = tmp_best.with_suffix(".gs.pdf")
    tmp_mupdf = tmp_best.with_suffix(".mu.pdf")

    try:
        if target_bytes is None:
            candidates: list[tuple[Path, str]] = []
            if _run_ghostscript(source, tmp_gs, cfg["gs"], chosen_dpi):
                candidates.append((tmp_gs, f"ghostscript ({cfg['gs']}, {chosen_dpi}dpi)"))
            if _run_pymupdf(source, tmp_mupdf, chosen_dpi, chosen_quality):
                candidates.append((tmp_mupdf, f"pymupdf ({chosen_dpi}dpi, q={chosen_quality})"))

            if not candidates:
                raise RuntimeError(f"Failed to compress PDF '{source.name}'.")

            winner_path, engine_label = min(candidates, key=lambda item: item[0].stat().st_size)
            shutil.move(str(winner_path), str(tmp_best))
        else:
            attempts = [
                ("/ebook", 150, 70),
                ("/screen", 110, 55),
                ("/screen", 85, 42),
                ("/screen", 65, 30),
                ("/screen", 50, 22),
            ]
            best_size: Optional[int] = None
            engine_label = "auto-target"
            for gs_profile, step_dpi, step_q in attempts:
                step_candidates: list[tuple[Path, str]] = []
                if _run_ghostscript(source, tmp_gs, gs_profile, step_dpi):
                    step_candidates.append((tmp_gs, f"ghostscript ({step_dpi}dpi)"))
                if _run_pymupdf(source, tmp_mupdf, step_dpi, step_q):
                    step_candidates.append((tmp_mupdf, f"pymupdf ({step_dpi}dpi, q={step_q})"))

                for c_path, c_label in step_candidates:
                    sz = c_path.stat().st_size
                    if best_size is None or sz < best_size:
                        best_size = sz
                        engine_label = c_label
                        shutil.copy2(c_path, tmp_best)

                if best_size is not None and best_size <= target_bytes:
                    break

        return finalize_output(source, tmp_best, dest, engine_label, keep_smaller=keep_smaller)
    finally:
        tmp_best.unlink(missing_ok=True)
        tmp_gs.unlink(missing_ok=True)
        tmp_mupdf.unlink(missing_ok=True)


def estimate_min_pdf_bytes(source: Path) -> int:
    """Probe the smallest achievable PDF size using aggressive downsampling."""
    orig_size = source.stat().st_size
    tmp_gs = make_temp_path(source, ".min.gs.pdf")
    tmp_mu = make_temp_path(source, ".min.mu.pdf")
    try:
        sizes = [orig_size]
        if _run_ghostscript(source, tmp_gs, "/screen", 50):
            sizes.append(tmp_gs.stat().st_size)
        if _run_pymupdf(source, tmp_mu, 50, 22):
            sizes.append(tmp_mu.stat().st_size)
        return max(1, min(sizes))
    finally:
        tmp_gs.unlink(missing_ok=True)
        tmp_mu.unlink(missing_ok=True)
