"""FastAPI web interface for the All-in-One CLI Compressor (ready for local or Hugging Face Spaces)."""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from archive_compressor import (  # noqa: E402
    ARCHIVE_OUTPUT_FORMATS,
    compress_archive,
    get_archive_suffix,
    is_archive_path,
    resolve_archive_extension,
)
from audio_compressor import AUDIO_EXTENSIONS, compress_audio, resolve_audio_extension  # noqa: E402
from common import CompressionResult, format_size, parse_size  # noqa: E402
from font_compressor import FONT_EXTENSIONS, compress_font, resolve_font_extension  # noqa: E402
from image_compressor import IMAGE_EXTENSIONS, compress_image  # noqa: E402
from office_compressor import OFFICE_EXTENSIONS, compress_office  # noqa: E402
from pdf_compressor import PDF_EXTENSIONS, compress_pdf  # noqa: E402
from svg_compressor import SVG_EXTENSIONS, compress_svg  # noqa: E402
from video_compressor import VIDEO_EXTENSIONS, compress_video  # noqa: E402

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "250"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
JOB_TTL_SECONDS = 900  # Clean temporary uploads after 15 minutes

JOBS_ROOT = Path(tempfile.gettempdir()) / "compressor_web_jobs"
JOBS_ROOT.mkdir(parents=True, exist_ok=True)
JOBS: dict[str, dict] = {}

app = FastAPI(title="JBSI™ All-in-One Compressor", version="2.0.0")

WEB_DIR = PROJECT_DIR / "web"
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


def _cleanup_expired_jobs() -> None:
    """Remove temporary job directories older than JOB_TTL_SECONDS."""
    now = time.time()
    expired = [jid for jid, meta in JOBS.items() if now - meta["created_at"] > JOB_TTL_SECONDS]
    for jid in expired:
        meta = JOBS.pop(jid, None)
        if meta:
            shutil.rmtree(meta["dir"], ignore_errors=True)


def _safe_filename(raw_name: Optional[str], fallback: str = "upload.bin") -> str:
    """Strip path segments and unsafe characters from uploaded filenames."""
    base = Path(raw_name or fallback).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip(".")
    return cleaned or fallback


def _resolve_web_dest(source: Path, out_dir: Path, fmt: str) -> Path:
    """Resolve clean output path for web downloads without path collisions."""
    suffix = source.suffix.lower()
    if fmt in ARCHIVE_OUTPUT_FORMATS or is_archive_path(source):
        ext = resolve_archive_extension(source, fmt)
        arch_ext = get_archive_suffix(source)
        stem = source.name[: -len(arch_ext)] if arch_ext and source.name.lower().endswith(arch_ext) else source.stem
    elif suffix in AUDIO_EXTENSIONS:
        ext = resolve_audio_extension(source, fmt)
        stem = source.stem
    elif suffix in FONT_EXTENSIONS:
        ext = resolve_font_extension(source, fmt)
        stem = source.stem
    elif suffix in PDF_EXTENSIONS:
        ext = source.suffix
        stem = source.stem
    else:
        ext = source.suffix if fmt == "keep" else f".{fmt}"
        stem = source.stem

    candidate = out_dir / f"{stem}_compressed{ext}"
    counter = 1
    while candidate.exists():
        candidate = out_dir / f"{stem}_compressed_{counter}{ext}"
        counter += 1
    return candidate


def _dispatch_compress(
    src: Path,
    dest: Path,
    preset: str,
    fmt: str,
    quality: Optional[int],
    dpi: Optional[int],
    max_width: Optional[int],
    max_height: Optional[int],
    video_codec: str,
    audio_bitrate: Optional[int],
    target_bytes: Optional[int],
    keep_smaller: bool,
) -> CompressionResult:
    """Route a file to the matching compression module."""
    ext = src.suffix.lower()
    if fmt in ARCHIVE_OUTPUT_FORMATS or is_archive_path(src):
        return compress_archive(src, dest, preset=preset, output_format=fmt, keep_smaller=keep_smaller)
    if ext in PDF_EXTENSIONS:
        return compress_pdf(
            src, dest, preset=preset, dpi=dpi, quality=quality, target_bytes=target_bytes, keep_smaller=keep_smaller
        )
    if ext in OFFICE_EXTENSIONS:
        return compress_office(
            src,
            dest,
            preset=preset,
            quality=quality,
            max_width=max_width,
            max_height=max_height,
            dpi=dpi,
            output_format=fmt,
            target_bytes=target_bytes,
            keep_smaller=keep_smaller,
        )
    if ext in SVG_EXTENSIONS:
        return compress_svg(src, dest, preset=preset, keep_smaller=keep_smaller)
    if ext in FONT_EXTENSIONS:
        return compress_font(src, dest, output_format=fmt, keep_smaller=keep_smaller)
    if ext in VIDEO_EXTENSIONS or (ext == ".gif" and fmt in ("mp4", "webm")):
        return compress_video(
            src,
            dest,
            preset=preset,
            codec=video_codec,
            max_width=max_width,
            max_height=max_height,
            target_bytes=target_bytes,
            keep_smaller=keep_smaller,
        )
    if ext in AUDIO_EXTENSIONS:
        return compress_audio(
            src,
            dest,
            preset=preset,
            bitrate_kbps=audio_bitrate,
            output_format=fmt,
            target_bytes=target_bytes,
            keep_smaller=keep_smaller,
        )
    if ext in IMAGE_EXTENSIONS:
        return compress_image(
            src,
            dest,
            quality=quality,
            preset=preset,
            max_width=max_width,
            max_height=max_height,
            output_format=fmt,
            target_bytes=target_bytes,
            keep_smaller=keep_smaller,
        )
    raise ValueError(
        f"Unsupported file extension '{ext or 'none'}'. Select an archive output format (zip/tar.zst/gz/zst) to compress arbitrary files."
    )


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Serve the interactive web compressor UI."""
    html_path = WEB_DIR / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>All-in-One Compressor API</h1><p>Open /docs for API documentation.</p>")
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/api/health")
async def health() -> dict:
    """Report server status and installed compression binaries."""
    from PIL import features

    return {
        "status": "ok",
        "max_upload_mb": MAX_UPLOAD_MB,
        "tools": {
            "ffmpeg": bool(shutil.which("ffmpeg")),
            "ghostscript": bool(shutil.which("gs")),
            "libreoffice": bool(shutil.which("soffice") or shutil.which("libreoffice")),
            "avif": bool(features.check("avif")),
            "webp": bool(features.check("webp")),
        },
    }


@app.post("/api/compress")
async def compress_endpoint(
    files: list[UploadFile] = File(...),
    preset: str = Form("medium"),
    output_format: str = Form("keep"),
    quality: Optional[int] = Form(None),
    dpi: Optional[int] = Form(None),
    max_width: Optional[int] = Form(None),
    max_height: Optional[int] = Form(None),
    video_codec: str = Form("h264"),
    audio_bitrate: Optional[int] = Form(None),
    target_size: str = Form(""),
    allow_larger: bool = Form(False),
) -> dict:
    """Compress uploaded files and return per-file metrics and download links."""
    _cleanup_expired_jobs()

    if not files:
        raise HTTPException(status_code=400, detail="Please upload at least one file.")

    preset_clean = preset.lower()
    if preset_clean not in ("low", "medium", "high"):
        raise HTTPException(status_code=400, detail="Preset must be low, medium, or high.")

    target_bytes: Optional[int] = None
    if target_size.strip():
        try:
            target_bytes = parse_size(target_size)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_ROOT / job_id
    in_dir = job_dir / "in"
    out_dir = job_dir / "out"
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    file_map: dict[str, Path] = {}
    results_payload: list[dict] = []
    errors_payload: list[dict] = []
    total_upload = 0

    try:
        for idx, upload in enumerate(files):
            safe_name = _safe_filename(upload.filename, f"file_{idx}.bin")
            src_path = in_dir / f"{idx}_{safe_name}"
            with open(src_path, "wb") as fout:
                while chunk := await upload.read(1024 * 1024):
                    total_upload += len(chunk)
                    if total_upload > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"Upload exceeds {MAX_UPLOAD_MB} MB limit.",
                        )
                    fout.write(chunk)

            # Rename back without index prefix unless name collides
            clean_src = in_dir / safe_name
            if not clean_src.exists():
                src_path.rename(clean_src)
                src_path = clean_src

            dest_path = _resolve_web_dest(src_path, out_dir, output_format.lower())
            try:
                res = _dispatch_compress(
                    src=src_path,
                    dest=dest_path,
                    preset=preset_clean,
                    fmt=output_format.lower(),
                    quality=quality,
                    dpi=dpi,
                    max_width=max_width,
                    max_height=max_height,
                    video_codec=video_codec.lower(),
                    audio_bitrate=audio_bitrate,
                    target_bytes=target_bytes,
                    keep_smaller=not allow_larger,
                )
                file_token = uuid.uuid4().hex[:10]
                file_map[file_token] = res.output
                results_payload.append(
                    {
                        "filename": safe_name,
                        "output_filename": res.output.name,
                        "original_bytes": res.original_bytes,
                        "compressed_bytes": res.compressed_bytes,
                        "original_human": format_size(res.original_bytes),
                        "compressed_human": format_size(res.compressed_bytes),
                        "saved_human": format_size(max(0, res.saved_bytes)),
                        "reduction_pct": round(res.reduction_pct, 1),
                        "engine": res.engine,
                        "skipped_larger": res.skipped_larger,
                        "download_url": f"/api/download/{job_id}/{file_token}",
                    }
                )
            except Exception as exc:
                errors_payload.append({"filename": safe_name, "error": str(exc)})
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise

    JOBS[job_id] = {"dir": job_dir, "out_dir": out_dir, "files": file_map, "created_at": time.time()}

    return {
        "job_id": job_id,
        "results": results_payload,
        "errors": errors_payload,
        "zip_url": f"/api/download-zip/{job_id}" if len(results_payload) > 1 else None,
    }


@app.get("/api/download/{job_id}/{file_token}")
async def download_file(job_id: str, file_token: str) -> FileResponse:
    """Download a single compressed file from a job."""
    _cleanup_expired_jobs()
    job = JOBS.get(job_id)
    if not job or file_token not in job["files"]:
        raise HTTPException(status_code=404, detail="File expired or not found.")
    file_path: Path = job["files"][file_token]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File no longer available.")
    return FileResponse(path=str(file_path), filename=file_path.name, media_type="application/octet-stream")


@app.get("/api/download-zip/{job_id}")
async def download_zip(job_id: str) -> FileResponse:
    """Download all compressed files in a batch job as a single ZIP archive."""
    _cleanup_expired_jobs()
    job = JOBS.get(job_id)
    if not job or not job["files"]:
        raise HTTPException(status_code=404, detail="Batch job expired or not found.")
    zip_path = job["dir"] / f"compressed_bundle_{job_id}.zip"
    if not zip_path.exists():
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for out_file in job["files"].values():
                if out_file.exists():
                    zf.write(out_file, arcname=out_file.name)
    return FileResponse(path=str(zip_path), filename="compressed_files.zip", media_type="application/zip")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "7860"))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
