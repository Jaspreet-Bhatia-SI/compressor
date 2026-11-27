"""Dedicated font compressor using FontTools and Brotli (WOFF2 / WOFF)."""

from __future__ import annotations

from pathlib import Path

from fontTools.ttLib import TTFont

from common import CompressionResult, finalize_output, make_temp_path

FONT_EXTENSIONS = {".ttf", ".otf", ".woff", ".woff2"}


def resolve_font_extension(source: Path, output_format: str) -> str:
    """Resolve target font extension, defaulting desktop TTF/OTF fonts to compressed WOFF2."""
    fmt = output_format.lower()
    if fmt != "keep":
        return f".{fmt}"
    if source.suffix.lower() in (".ttf", ".otf"):
        return ".woff2"
    return source.suffix.lower() or ".woff2"


def compress_font(
    source: Path,
    dest: Path,
    output_format: str = "keep",
    keep_smaller: bool = True,
) -> CompressionResult:
    """Compress or convert a font to WOFF2 (Brotli) or WOFF using FontTools."""
    target_ext = resolve_font_extension(source, output_format)
    target_flavor = target_ext.lstrip(".").lower()
    if target_flavor not in ("woff2", "woff"):
        target_flavor = None

    tmp_path = make_temp_path(dest, target_ext)
    try:
        font = TTFont(str(source))
        try:
            font.flavor = target_flavor
            font.save(str(tmp_path))
        finally:
            font.close()

        engine = f"fonttools/{target_flavor or 'sfnt'}"
        allow_keep = target_ext.lower() == source.suffix.lower()
        return finalize_output(
            source,
            tmp_path,
            dest,
            engine,
            keep_smaller=keep_smaller,
            allow_keep_original=allow_keep,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
