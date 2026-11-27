"""Dedicated archive compressor and bundler (ZIP, TAR, GZ, BZ2, XZ, ZSTD)."""

from __future__ import annotations

import bz2
import gzip
import lzma
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path

import zstandard as zstd

from common import CompressionResult, finalize_output, make_temp_path

ARCHIVE_EXTENSIONS = {
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".zst",
    ".tgz",
    ".tbz2",
    ".txz",
    ".tzst",
}

ARCHIVE_OUTPUT_FORMATS = {"zip", "tar.gz", "tar.bz2", "tar.xz", "tar.zst", "gz", "bz2", "xz", "zst"}

ARCHIVE_PRESETS = {
    "low": {"zip": 6, "gz": 6, "xz": 3, "zstd": 3},
    "medium": {"zip": 9, "gz": 9, "xz": 6, "zstd": 10},
    "high": {"zip": 9, "gz": 9, "xz": 9, "zstd": 19},
}


def get_archive_suffix(path: Path) -> str:
    """Return full compound archive suffix such as '.tar.gz' or '.tar.zst' when present."""
    name_lower = path.name.lower()
    for compound in (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst"):
        if name_lower.endswith(compound):
            return compound
    return path.suffix.lower()


def is_archive_path(path: Path) -> bool:
    """Return True if path has a supported archive or compressed-stream extension."""
    return get_archive_suffix(path) in ARCHIVE_EXTENSIONS or path.suffix.lower() in ARCHIVE_EXTENSIONS


def resolve_archive_extension(source: Path, output_format: str) -> str:
    """Resolve target archive extension from source and optional -f format."""
    if output_format != "keep":
        return f".{output_format.lower().lstrip('.')}"
    ext = get_archive_suffix(source)
    if ext == ".tar":
        return ".tar.zst"
    return ext


def _write_directory_to_archive(src_dir: Path, dest_archive: Path, fmt: str, preset: str) -> None:
    """Pack a directory tree into the requested archive format."""
    levels = ARCHIVE_PRESETS[preset]
    fmt = fmt.lower().lstrip(".")

    if fmt == "zip":
        with zipfile.ZipFile(dest_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=levels["zip"]) as zf:
            for item in sorted(src_dir.rglob("*")):
                if item.is_file():
                    zf.write(item, arcname=item.relative_to(src_dir))
        return

    if fmt in ("tar.gz", "tgz"):
        with tarfile.open(dest_archive, "w:gz", compresslevel=levels["gz"]) as tf:
            tf.add(src_dir, arcname=".")
        return

    if fmt in ("tar.bz2", "tbz2"):
        with tarfile.open(dest_archive, "w:bz2", compresslevel=9) as tf:
            tf.add(src_dir, arcname=".")
        return

    if fmt in ("tar.xz", "txz"):
        with tarfile.open(dest_archive, "w:xz", preset=levels["xz"]) as tf:
            tf.add(src_dir, arcname=".")
        return

    if fmt in ("tar.zst", "tzst"):
        cctx = zstd.ZstdCompressor(level=levels["zstd"])
        with open(dest_archive, "wb") as raw_out, cctx.stream_writer(raw_out) as zw:
            with tarfile.open(fileobj=zw, mode="w|") as tf:
                tf.add(src_dir, arcname=".")
        return

    if fmt == "tar":
        with tarfile.open(dest_archive, "w") as tf:
            tf.add(src_dir, arcname=".")
        return

    raise ValueError(f"Unsupported container format for directory archiving: {fmt}")


def _extract_container(source: Path, ext: str, extract_dir: Path) -> None:
    """Extract a ZIP or TAR* container cleanly into extract_dir."""
    if ext == ".zip":
        with zipfile.ZipFile(source, "r") as zf:
            zf.extractall(extract_dir)
        return

    if ext in (".tar.zst", ".tzst"):
        dctx = zstd.ZstdDecompressor()
        with open(source, "rb") as raw_in, dctx.stream_reader(raw_in) as zr:
            with tarfile.open(fileobj=zr, mode="r|*") as tf:
                tf.extractall(extract_dir, filter="data")
        return

    with tarfile.open(source, "r:*") as tf:
        tf.extractall(extract_dir, filter="data")


def _stream_compress_bytes(src_file: Path, dest_file: Path, fmt: str, preset: str) -> None:
    """Compress a single binary/text file into .gz, .bz2, .xz, or .zst."""
    levels = ARCHIVE_PRESETS[preset]
    fmt = fmt.lower().lstrip(".")

    with open(src_file, "rb") as fin:
        if fmt == "gz":
            with gzip.open(dest_file, "wb", compresslevel=levels["gz"]) as fout:
                shutil.copyfileobj(fin, fout)
        elif fmt == "bz2":
            with bz2.open(dest_file, "wb", compresslevel=9) as fout:
                shutil.copyfileobj(fin, fout)
        elif fmt == "xz":
            with lzma.open(dest_file, "wb", preset=levels["xz"]) as fout:
                shutil.copyfileobj(fin, fout)
        elif fmt == "zst":
            cctx = zstd.ZstdCompressor(level=levels["zstd"])
            with open(dest_file, "wb") as raw_out:
                cctx.copy_stream(fin, raw_out)
        else:
            raise ValueError(f"Unsupported stream compression format: {fmt}")


def _stream_decompress_to_file(source: Path, ext: str, out_file: Path) -> None:
    """Decompress a single-stream .gz, .bz2, .xz, or .zst file."""
    with open(out_file, "wb") as fout:
        if ext == ".gz":
            with gzip.open(source, "rb") as fin:
                shutil.copyfileobj(fin, fout)
        elif ext == ".bz2":
            with bz2.open(source, "rb") as fin:
                shutil.copyfileobj(fin, fout)
        elif ext == ".xz":
            with lzma.open(source, "rb") as fin:
                shutil.copyfileobj(fin, fout)
        elif ext == ".zst":
            dctx = zstd.ZstdDecompressor()
            with open(source, "rb") as fin:
                dctx.copy_stream(fin, fout)
        else:
            raise ValueError(f"Unsupported compressed stream extension: {ext}")


def compress_directory(
    source_dir: Path,
    dest: Path,
    preset: str = "medium",
    output_format: str = "tar.zst",
) -> CompressionResult:
    """Bundle and compress an entire directory into an archive."""
    fmt = "tar.zst" if output_format == "keep" else output_format.lower()
    if fmt not in ("zip", "tar.gz", "tgz", "tar.bz2", "tbz2", "tar.xz", "txz", "tar.zst", "tzst"):
        fmt = "tar.zst"

    raw_bytes = sum(f.stat().st_size for f in source_dir.rglob("*") if f.is_file())
    tmp_path = make_temp_path(dest, f".{fmt}")
    try:
        _write_directory_to_archive(source_dir, tmp_path, fmt, preset)
        dest.parent.mkdir(parents=True, exist_ok=True)
        compressed_bytes = tmp_path.stat().st_size
        shutil.move(str(tmp_path), str(dest))
        return CompressionResult(
            source=source_dir,
            output=dest,
            original_bytes=raw_bytes,
            compressed_bytes=compressed_bytes,
            engine=f"archive/{fmt}",
        )
    finally:
        tmp_path.unlink(missing_ok=True)


def compress_archive(
    source: Path,
    dest: Path,
    preset: str = "medium",
    output_format: str = "keep",
    keep_smaller: bool = True,
) -> CompressionResult:
    """Re-compress or convert an existing archive, or compress a single file into gz/bz2/xz/zst."""
    src_ext = get_archive_suffix(source)
    target_ext = resolve_archive_extension(source, output_format)
    target_fmt = target_ext.lstrip(".")

    container_exts = {".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".tar.zst", ".tzst"}
    stream_exts = {".gz", ".bz2", ".xz", ".zst"}

    tmp_path = make_temp_path(dest, target_ext)
    try:
        with tempfile.TemporaryDirectory(prefix="cmp_arch_") as work_dir:
            work_path = Path(work_dir)
            if src_ext in container_exts:
                extract_dir = work_path / "extracted"
                extract_dir.mkdir(parents=True, exist_ok=True)
                _extract_container(source, src_ext, extract_dir)
                _write_directory_to_archive(extract_dir, tmp_path, target_fmt, preset)
            elif src_ext in stream_exts:
                raw_file = work_path / "payload"
                _stream_decompress_to_file(source, src_ext, raw_file)
                _stream_compress_bytes(raw_file, tmp_path, target_fmt, preset)
            else:
                if target_fmt in ("zip", "tar.gz", "tar.bz2", "tar.xz", "tar.zst"):
                    stage_dir = work_path / "stage"
                    stage_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, stage_dir / source.name)
                    _write_directory_to_archive(stage_dir, tmp_path, target_fmt, preset)
                else:
                    _stream_compress_bytes(source, tmp_path, target_fmt, preset)

        allow_keep = target_ext.lower() == src_ext.lower()
        return finalize_output(
            source,
            tmp_path,
            dest,
            f"archive/{target_fmt}",
            keep_smaller=keep_smaller,
            allow_keep_original=allow_keep,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
