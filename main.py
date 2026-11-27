#!/usr/bin/env python3
"""Unified CLI entry point importing all dedicated media, document, font, and archive compressors."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table

# Ensure local modules resolve cleanly even when launched from outside this directory.
PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from archive_compressor import (  # noqa: E402
    ARCHIVE_EXTENSIONS,
    ARCHIVE_OUTPUT_FORMATS,
    compress_archive,
    compress_directory,
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

console = Console()
SUPPORTED_EXTENSIONS = (
    PDF_EXTENSIONS
    | IMAGE_EXTENSIONS
    | VIDEO_EXTENSIONS
    | AUDIO_EXTENSIONS
    | SVG_EXTENSIONS
    | OFFICE_EXTENSIONS
    | FONT_EXTENSIONS
    | ARCHIVE_EXTENSIONS
)

MEDIA_TYPE_CHOICES = ["all", "pdf", "image", "video", "audio", "svg", "office", "font", "archive"]
FORMAT_CHOICES = [
    "keep",
    "jpg",
    "jpeg",
    "png",
    "webp",
    "avif",
    "heic",
    "gif",
    "mp4",
    "webm",
    "mp3",
    "aac",
    "m4a",
    "ogg",
    "opus",
    "pdf",
    "woff",
    "woff2",
    "zip",
    "tar.gz",
    "tar.bz2",
    "tar.xz",
    "tar.zst",
    "gz",
    "bz2",
    "xz",
    "zst",
]


def _allowed_extensions(kind: str) -> set[str]:
    mapping = {
        "pdf": PDF_EXTENSIONS,
        "image": IMAGE_EXTENSIONS,
        "video": VIDEO_EXTENSIONS,
        "audio": AUDIO_EXTENSIONS,
        "svg": SVG_EXTENSIONS,
        "office": OFFICE_EXTENSIONS,
        "font": FONT_EXTENSIONS,
        "archive": ARCHIVE_EXTENSIONS,
        "all": SUPPORTED_EXTENSIONS,
    }
    return mapping[kind]


def _collect_inputs(
    inputs: tuple[Path, ...],
    recursive: bool,
    kind: str,
    output_format: str,
) -> list[Path]:
    """Expand file and directory arguments into a deduplicated list of targets."""
    allowed = _allowed_extensions(kind)
    archive_mode = output_format.lower() in ARCHIVE_OUTPUT_FORMATS
    collected: list[Path] = []
    seen: set[Path] = set()

    for raw in inputs:
        path = raw.expanduser().resolve()
        if path.is_file():
            matches = (
                archive_mode
                or path.suffix.lower() in allowed
                or (kind in ("all", "archive") and is_archive_path(path))
            )
            if matches and path not in seen:
                collected.append(path)
                seen.add(path)
        elif path.is_dir():
            if archive_mode and kind in ("all", "archive"):
                if path not in seen:
                    collected.append(path)
                    seen.add(path)
                continue
            iterator = path.rglob("*") if recursive else path.iterdir()
            for item in sorted(iterator):
                if not item.is_file():
                    continue
                if "_compressed" in item.stem or "_compressed." in item.name:
                    continue
                matches = item.suffix.lower() in allowed or (kind in ("all", "archive") and is_archive_path(item))
                if matches and item not in seen:
                    collected.append(item)
                    seen.add(item)
    return collected


def _strip_compound_stem(source: Path) -> str:
    """Return stem with compound archive extensions (.tar.gz, .tar.zst) cleanly removed."""
    ext = get_archive_suffix(source)
    if ext and source.name.lower().endswith(ext):
        return source.name[: -len(ext)]
    return source.stem


def _resolve_destination(
    source: Path,
    output: Optional[Path],
    in_place: bool,
    output_format: str,
    multi_mode: bool,
) -> Path:
    """Determine the destination path based on media type, flags, and batch mode."""
    fmt = output_format.lower()
    if source.is_dir():
        ext = ".tar.zst" if fmt == "keep" else f".{fmt.lstrip('.')}"
        if output is not None:
            out_resolved = output.expanduser().resolve()
            if multi_mode or out_resolved.is_dir() or str(output).endswith(("/", "\\")):
                out_resolved.mkdir(parents=True, exist_ok=True)
                return out_resolved / f"{source.name}{ext}"
            return out_resolved if out_resolved.suffix else out_resolved.with_suffix(ext)
        return source.with_name(f"{source.name}_compressed{ext}")

    suffix = source.suffix.lower()
    if fmt in ARCHIVE_OUTPUT_FORMATS or is_archive_path(source):
        ext = resolve_archive_extension(source, fmt)
        stem = _strip_compound_stem(source)
        orig_ext = get_archive_suffix(source)
    elif suffix in AUDIO_EXTENSIONS:
        ext = resolve_audio_extension(source, fmt)
        stem = source.stem
        orig_ext = suffix
    elif suffix in FONT_EXTENSIONS:
        ext = resolve_font_extension(source, fmt)
        stem = source.stem
        orig_ext = suffix
    elif suffix in PDF_EXTENSIONS:
        ext = source.suffix
        stem = source.stem
        orig_ext = suffix
    else:
        ext = source.suffix if fmt == "keep" else f".{fmt}"
        stem = source.stem
        orig_ext = suffix

    if in_place:
        if ext.lower() == orig_ext.lower():
            return source
        return source.with_name(f"{stem}{ext}")

    if output is not None:
        out_resolved = output.expanduser().resolve()
        if multi_mode or out_resolved.is_dir() or str(output).endswith(("/", "\\")):
            out_resolved.mkdir(parents=True, exist_ok=True)
            return out_resolved / f"{stem}{ext}"
        return out_resolved if out_resolved.suffix else out_resolved.with_suffix(ext)

    return source.with_name(f"{stem}_compressed{ext}")


def _interactive_wizard() -> tuple:
    """Prompt the user interactively when launched without file/folder arguments."""
    console.print(
        Panel.fit(
            "[bold cyan]JBSI™ All-in-One CLI Compressor[/bold cyan]  [dim]by Jaspreet Bhatia[/dim]\n"
            "[dim]PDF • Image (AVIF/HEIC/GIF) • Video • Audio • SVG • Office • Fonts • Archives[/dim]",
            border_style="cyan",
        )
    )
    raw_path = Prompt.ask("Enter file or folder path").strip().strip('"').strip("'")
    target_path = Path(raw_path).expanduser()
    if not target_path.exists():
        console.print(f"[red]Path not found:[/red] {target_path}")
        raise SystemExit(1)

    recursive = False
    kind = "all"
    output_format = "keep"
    if target_path.is_dir():
        bundle_dir = Confirm.ask("Bundle entire folder into a single compressed archive?", default=False)
        if bundle_dir:
            output_format = Prompt.ask(
                "Archive format",
                choices=["tar.zst", "zip", "tar.gz", "tar.xz"],
                default="tar.zst",
            )
        else:
            recursive = Confirm.ask("Scan subfolders recursively?", default=False)
            kind = Prompt.ask("Filter file type", choices=MEDIA_TYPE_CHOICES, default="all")

    preset = Prompt.ask("Compression preset", choices=["low", "medium", "high"], default="medium")
    target_size_raw = Prompt.ask("Max target size (e.g. 500KB, 5MB, or Enter to skip)", default="").strip()
    target_size = target_size_raw or None
    in_place = False if target_path.is_dir() and output_format != "keep" else Confirm.ask("Overwrite original file(s) in-place?", default=False)

    out_path: Optional[Path] = None
    if not in_place:
        out_raw = Prompt.ask("Output file/folder path (Enter for *_compressed next to source)", default="").strip()
        if out_raw:
            out_path = Path(out_raw)

    return (target_path,), preset, None, None, None, None, output_format, "h264", None, target_size, kind, out_path, in_place, recursive


def _render_summary(results: list[CompressionResult], failures: list[tuple[Path, str]]) -> None:
    """Print a before/after summary table."""
    table = Table(title="Compression Summary", show_lines=False, header_style="bold white on blue")
    table.add_column("File", style="cyan", no_wrap=True)
    table.add_column("Original", justify="right")
    table.add_column("Compressed", justify="right")
    table.add_column("Saved", justify="right", style="green")
    table.add_column("Engine", style="dim")
    table.add_column("Output", style="magenta")

    total_orig = 0
    total_new = 0
    for r in results:
        total_orig += r.original_bytes
        total_new += r.compressed_bytes
        pct_text = f"-{r.reduction_pct:.1f}%" if r.saved_bytes > 0 else "0.0%"
        table.add_row(
            r.source.name,
            format_size(r.original_bytes),
            format_size(r.compressed_bytes),
            f"{format_size(r.saved_bytes)} ({pct_text})" if r.saved_bytes > 0 else "kept original",
            r.engine,
            str(r.output),
        )

    console.print()
    console.print(table)

    if results:
        total_saved = total_orig - total_new
        total_pct = (total_saved / total_orig * 100.0) if total_orig else 0.0
        console.print(
            f"[bold green]Done:[/bold green] {len(results)} item(s) | "
            f"{format_size(total_orig)} -> {format_size(total_new)} "
            f"([bold]{format_size(total_saved)} saved, {total_pct:.1f}%[/bold])"
        )

    if failures:
        console.print("\n[bold red]Failures:[/bold red]")
        for path, err in failures:
            console.print(f"  - {path}: {err}")


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("inputs", nargs=-1, type=click.Path(path_type=Path))
@click.option(
    "-p",
    "--preset",
    type=click.Choice(["low", "medium", "high"], case_sensitive=False),
    default="medium",
    show_default=True,
    help="Compression strength: low (best quality), medium (balanced), high (smallest size).",
)
@click.option("-q", "--quality", type=click.IntRange(1, 100), default=None, help="Custom image/PDF/Office quality (1-100).")
@click.option("--dpi", type=click.IntRange(36, 600), default=None, help="Custom PDF image DPI.")
@click.option("--max-width", type=click.IntRange(16, 20000), default=None, help="Max image/video/Office-media width in px.")
@click.option("--max-height", type=click.IntRange(16, 20000), default=None, help="Max image/video/Office-media height in px.")
@click.option(
    "-f",
    "--format",
    "output_format",
    type=click.Choice(FORMAT_CHOICES, case_sensitive=False),
    default="keep",
    show_default=True,
    help="Convert output format (image/video/audio/office/font/archive).",
)
@click.option(
    "--video-codec",
    type=click.Choice(["h264", "h265"], case_sensitive=False),
    default="h264",
    show_default=True,
    help="Video encoder codec for MP4/MOV/MKV.",
)
@click.option("--audio-bitrate", type=click.IntRange(24, 320), default=None, help="Audio bitrate in kbps (24-320).")
@click.option("-t", "--target-size", default=None, help="Auto-fit under target size (e.g. 500KB, 5MB).")
@click.option(
    "--type",
    "kind",
    type=click.Choice(MEDIA_TYPE_CHOICES, case_sensitive=False),
    default="all",
    show_default=True,
    help="Filter asset type when compressing folders.",
)
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None, help="Output file or directory.")
@click.option("--in-place", is_flag=True, help="Replace original files in-place.")
@click.option("-r", "--recursive", is_flag=True, help="Recurse into subdirectories.")
@click.option("--allow-larger", is_flag=True, help="Keep output even if larger than original.")
def main(
    inputs: tuple[Path, ...],
    preset: str,
    quality: Optional[int],
    dpi: Optional[int],
    max_width: Optional[int],
    max_height: Optional[int],
    output_format: str,
    video_codec: str,
    audio_bitrate: Optional[int],
    target_size: Optional[str],
    kind: str,
    output: Optional[Path],
    in_place: bool,
    recursive: bool,
    allow_larger: bool,
) -> None:
    """Compress PDF, Image (AVIF/HEIC/GIF), Video, Audio, SVG, Office, Font, and Archive files."""
    if not inputs:
        (
            inputs,
            preset,
            quality,
            dpi,
            max_width,
            max_height,
            output_format,
            video_codec,
            audio_bitrate,
            target_size,
            kind,
            output,
            in_place,
            recursive,
        ) = _interactive_wizard()

    missing = [p for p in inputs if not p.expanduser().exists()]
    if missing:
        for p in missing:
            console.print(f"[red]Path does not exist:[/red] {p}")
        sys.exit(1)

    target_bytes: Optional[int] = None
    if target_size:
        try:
            target_bytes = parse_size(target_size)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            sys.exit(2)

    fmt_lower = output_format.lower()
    targets = _collect_inputs(inputs, recursive=recursive, kind=kind.lower(), output_format=fmt_lower)
    if not targets:
        console.print("[yellow]No supported files found.[/yellow]")
        sys.exit(1)

    multi_mode = len(targets) > 1
    results: list[CompressionResult] = []
    failures: list[tuple[Path, str]] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        task_id = progress.add_task("Compressing...", total=len(targets))
        for src in targets:
            progress.update(task_id, description=f"Compressing {src.name}")
            ext = src.suffix.lower()
            dest = _resolve_destination(src, output, in_place, fmt_lower, multi_mode)
            try:
                if src.is_dir():
                    res = compress_directory(src, dest, preset=preset.lower(), output_format=fmt_lower)
                elif fmt_lower in ARCHIVE_OUTPUT_FORMATS or is_archive_path(src):
                    res = compress_archive(
                        src,
                        dest,
                        preset=preset.lower(),
                        output_format=fmt_lower,
                        keep_smaller=not allow_larger,
                    )
                elif ext in PDF_EXTENSIONS:
                    res = compress_pdf(
                        src,
                        dest,
                        preset=preset.lower(),
                        dpi=dpi,
                        quality=quality,
                        target_bytes=target_bytes,
                        keep_smaller=not allow_larger,
                    )
                elif ext in OFFICE_EXTENSIONS:
                    res = compress_office(
                        src,
                        dest,
                        preset=preset.lower(),
                        quality=quality,
                        max_width=max_width,
                        max_height=max_height,
                        dpi=dpi,
                        output_format=fmt_lower,
                        target_bytes=target_bytes,
                        keep_smaller=not allow_larger,
                    )
                elif ext in SVG_EXTENSIONS:
                    res = compress_svg(src, dest, preset=preset.lower(), keep_smaller=not allow_larger)
                elif ext in FONT_EXTENSIONS:
                    res = compress_font(src, dest, output_format=fmt_lower, keep_smaller=not allow_larger)
                elif ext in VIDEO_EXTENSIONS or (ext == ".gif" and fmt_lower in ("mp4", "webm")):
                    res = compress_video(
                        src,
                        dest,
                        preset=preset.lower(),
                        codec=video_codec.lower(),
                        max_width=max_width,
                        max_height=max_height,
                        target_bytes=target_bytes,
                        keep_smaller=not allow_larger,
                    )
                elif ext in AUDIO_EXTENSIONS:
                    res = compress_audio(
                        src,
                        dest,
                        preset=preset.lower(),
                        bitrate_kbps=audio_bitrate,
                        output_format=fmt_lower,
                        target_bytes=target_bytes,
                        keep_smaller=not allow_larger,
                    )
                else:
                    res = compress_image(
                        src,
                        dest,
                        quality=quality,
                        preset=preset.lower(),
                        max_width=max_width,
                        max_height=max_height,
                        output_format=fmt_lower,
                        target_bytes=target_bytes,
                        keep_smaller=not allow_larger,
                    )
                results.append(res)
            except Exception as exc:
                failures.append((src, str(exc)))
            progress.advance(task_id)

    _render_summary(results, failures)
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
