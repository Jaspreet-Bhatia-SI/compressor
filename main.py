#!/usr/bin/env python3
"""Unified CLI entry point importing all dedicated media, document, font, and archive compressors."""

from __future__ import annotations

import math
import os
import select
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, IntPrompt, Prompt
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
from audio_compressor import (  # noqa: E402
    AUDIO_EXTENSIONS,
    compress_audio,
    estimate_min_audio_bytes,
    resolve_audio_extension,
)
from common import CompressionResult, format_size, make_temp_path, parse_size, parse_target_spec  # noqa: E402
from font_compressor import FONT_EXTENSIONS, compress_font, resolve_font_extension  # noqa: E402
from image_compressor import IMAGE_EXTENSIONS, compress_image, estimate_min_image_bytes  # noqa: E402
from office_compressor import OFFICE_EXTENSIONS, compress_office  # noqa: E402
from pdf_compressor import PDF_EXTENSIONS, compress_pdf, estimate_min_pdf_bytes  # noqa: E402
from svg_compressor import SVG_EXTENSIONS, compress_svg  # noqa: E402
from video_compressor import VIDEO_EXTENSIONS, compress_video, estimate_min_video_bytes  # noqa: E402

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


def _print_cheat_sheet() -> None:
    """Print a full colorful cheat sheet with all CLI flags, formats, and usage examples."""
    console.print(
        Panel.fit(
            "[bold cyan]JBSI All-in-One CLI Compressor — Cheat Sheet[/bold cyan]  [dim]by Jaspreet Bhatia[/dim]\n"
            "[dim]Usage: python main.py <file_or_folder> [OPTIONS]   |   Run without args for interactive mode[/dim]",
            border_style="cyan",
        )
    )

    flags = Table(title="All Flags & Options", show_lines=False, header_style="bold white on blue")
    flags.add_column("Flag", style="cyan", no_wrap=True)
    flags.add_column("Values / Default", style="yellow")
    flags.add_column("What it does")

    rows = [
        ("INPUTS", "./file.pdf, ./xyz ...", "One or more files or folders (omit for interactive wizard)"),
        ("help / -h / --help", "shortcut", "Show this full cheat sheet ('help') or brief CLI syntax ('-h')"),
        ("-p, --preset", "low | medium* | high", "Compression level: low (best quality), medium (balanced), high (smallest)"),
        ("-t, --target-size", "e.g. 500KB, 45%", "Auto-tune compression to stay under size (bytes or % of original)"),
        ("-P, --percent", "1-100", "Target compressed size as % of original (e.g. -P 40 = 40% of original)"),
        ("--slider", "flag", "Check smallest possible size first, then set % with interactive slider"),
        ("-f, --format", "keep* | avif | webp | ...", "Convert format (jpg/png/webp/avif/heic/gif/mp4/webm/mp3/aac/m4a/ogg/opus/pdf/woff/woff2/zip/tar.gz/tar.bz2/tar.xz/tar.zst/gz/bz2/xz/zst)"),
        ("-q, --quality", "1-100", "Custom quality for images, PDFs, and Office embedded images"),
        ("--dpi", "36-600", "Custom image DPI inside PDFs"),
        ("--max-width", "16-20000 px", "Cap max width (images, GIFs, videos, Office media) keeping aspect ratio"),
        ("--max-height", "16-20000 px", "Cap max height (images, GIFs, videos, Office media) keeping aspect ratio"),
        ("--video-codec", "h264* | h265", "Video encoder codec (h265 yields smaller MP4/MOV/MKV files)"),
        ("--audio-bitrate", "24-320 kbps", "Custom audio bitrate in kbps"),
        ("--type", "all* | pdf | image | ...", "Filter folder scans: all, pdf, image, video, audio, svg, office, font, archive"),
        ("-o, --output", "./out/ or out.ext", "Custom output file or folder (default: *_compressed next to input)"),
        ("-r, --recursive", "flag", "Scan subfolders recursively when passing a directory like ./xyz"),
        ("--in-place", "flag", "Overwrite original files atomically instead of creating *_compressed"),
        ("--allow-larger", "flag", "Keep output even if larger than original (disables zero-bloat guard)"),
    ]
    for flag, val, desc in rows:
        flags.add_row(flag, val, desc)
    console.print(flags)

    formats = Table(title="Supported File Types", show_lines=False, header_style="bold white on dark_green")
    formats.add_column("Type (--type)", style="green", no_wrap=True)
    formats.add_column("Extensions", style="white")
    formats.add_column("Notes", style="dim")
    formats.add_row("pdf", ".pdf", "Ghostscript + PyMuPDF image downsampling")
    formats.add_row("image", ".jpg .jpeg .png .webp .avif .heic .heif .gif .bmp .tiff", "HEIC & AVIF conversion, FFmpeg palettegen for GIF")
    formats.add_row("video", ".mp4 .mov .mkv .avi .webm .m4v .flv", "FFmpeg H.264/H.265/VP9 + .gif -> .mp4/.webm")
    formats.add_row("audio", ".mp3 .wav .flac .aac .m4a .ogg .opus", "Lossless .wav/.flac default to .mp3")
    formats.add_row("svg", ".svg", "Scour vector optimizer (strips metadata & comments)")
    formats.add_row("office", ".docx .pptx .xlsx .odt .odp .ods", "Shrinks embedded media keeping file editable (or -f pdf)")
    formats.add_row("font", ".ttf .otf .woff .woff2", "FontTools + Brotli (.ttf/.otf default to .woff2)")
    formats.add_row("archive", ".zip .tar .tar.gz .tar.bz2 .tar.xz .tar.zst .gz .bz2 .xz .zst", "Re-packs archives or bundles folders (./xyz -f tar.zst)")
    console.print(formats)

    examples = (
        "[bold yellow]Interactive & Slider Mode:[/bold yellow]\n"
        "  [cyan]python main.py[/cyan]                                     # Guided interactive wizard\n"
        "  [cyan]python main.py photo.jpg --slider[/cyan]                  # Analyze min size -> interactive % slider\n"
        "  [cyan]python main.py report.pdf -P 35[/cyan]                    # Shrink directly to 35% of original size\n"
        "  [cyan]python main.py help[/cyan]                                # Show this full cheat sheet\n\n"
        "[bold yellow]PDF (pdf_compressor.py):[/bold yellow]\n"
        "  [cyan]python main.py report.pdf -t 2MB[/cyan]                   # Shrink PDF under 2 MB\n"
        "  [cyan]python main.py scan.pdf -p high --dpi 100 -q 55[/cyan]    # Custom DPI & JPEG quality\n\n"
        "[bold yellow]Images — JPG/PNG/WebP/AVIF/HEIC/GIF (image_compressor.py):[/bold yellow]\n"
        "  [cyan]python main.py photo.heic -p medium -f avif[/cyan]        # Convert iPhone HEIC -> tiny AVIF\n"
        "  [cyan]python main.py pic.png --max-width 1920 -f webp[/cyan]    # Resize + convert PNG -> WebP\n"
        "  [cyan]python main.py avatar.jpg -t 200KB[/cyan]                 # Auto-fit image under 200 KB\n"
        "  [cyan]python main.py anim.gif -p high --max-width 480[/cyan]    # Shrink animated GIF\n"
        "  [cyan]python main.py anim.gif -f mp4[/cyan]                     # Convert GIF -> tiny MP4 video\n\n"
        "[bold yellow]Video & Audio (video_compressor.py / audio_compressor.py):[/bold yellow]\n"
        "  [cyan]python main.py clip.mp4 --max-height 720 --video-codec h265[/cyan]\n"
        "  [cyan]python main.py clip.mp4 -t 10MB[/cyan]                    # Fit video under 10 MB\n"
        "  [cyan]python main.py recording.wav -p high[/cyan]               # Convert WAV -> 64kbps MP3\n"
        "  [cyan]python main.py track.flac -f opus --audio-bitrate 96[/cyan]\n\n"
        "[bold yellow]SVG, Office & Fonts (svg / office / font compressors):[/bold yellow]\n"
        "  [cyan]python main.py logo.svg -p high[/cyan]                    # Minify SVG vector\n"
        "  [cyan]python main.py slides.pptx -p medium[/cyan]               # Shrink embedded slide media cleanly\n"
        "  [cyan]python main.py deck.pptx -f pdf -t 3MB[/cyan]             # Export Office -> compressed PDF\n"
        "  [cyan]python main.py Inter.ttf[/cyan]                           # Convert TTF font -> WOFF2\n\n"
        "[bold yellow]Archives & Folder Batching (archive_compressor.py):[/bold yellow]\n"
        "  [cyan]python main.py backup.zip -f tar.zst -p high[/cyan]       # Re-pack ZIP -> ultra-tight .tar.zst\n"
        "  [cyan]python main.py ./xyz -f tar.zst[/cyan]                    # Bundle entire ./xyz folder -> .tar.zst\n"
        "  [cyan]python main.py ./xyz -r -o ./compressed/[/cyan]           # Compress all supported files in ./xyz\n"
        "  [cyan]python main.py ./xyz -r --type image -f avif[/cyan]       # Convert all folder images to AVIF\n"
        "  [cyan]python main.py ./xyz -r --in-place[/cyan]                 # Replace originals safely in-place\n"
        "\n[dim]* denotes default value[/dim]"
    )
    console.print(Panel(examples, title="Common Ways to Compress", border_style="green"))


def _estimate_min_bytes(
    src: Path,
    output_format: str = "keep",
    max_width: Optional[int] = None,
    max_height: Optional[int] = None,
) -> int:
    """Probe the smallest achievable output size for a file."""
    orig_bytes = src.stat().st_size
    ext = src.suffix.lower()
    fmt = output_format.lower()

    if fmt in ARCHIVE_OUTPUT_FORMATS or is_archive_path(src):
        probe_dest = make_temp_path(src, resolve_archive_extension(src, fmt))
        try:
            res = compress_archive(src, probe_dest, preset="high", output_format=fmt, keep_smaller=True)
            return max(1, res.compressed_bytes)
        finally:
            probe_dest.unlink(missing_ok=True)
    if ext in PDF_EXTENSIONS:
        return estimate_min_pdf_bytes(src)
    if ext in VIDEO_EXTENSIONS or (ext == ".gif" and fmt in ("mp4", "webm")):
        return estimate_min_video_bytes(src)
    if ext in AUDIO_EXTENSIONS:
        return estimate_min_audio_bytes(src)
    if ext in SVG_EXTENSIONS:
        probe_dest = make_temp_path(src, ".min.svg")
        try:
            res = compress_svg(src, probe_dest, preset="high", keep_smaller=True)
            return max(1, res.compressed_bytes)
        finally:
            probe_dest.unlink(missing_ok=True)
    if ext in OFFICE_EXTENSIONS:
        probe_dest = make_temp_path(src, f".min{ext}")
        try:
            res = compress_office(
                src,
                probe_dest,
                preset="high",
                max_width=max_width,
                max_height=max_height,
                output_format=fmt,
                keep_smaller=True,
            )
            return max(1, res.compressed_bytes)
        finally:
            probe_dest.unlink(missing_ok=True)
    if ext in FONT_EXTENSIONS:
        probe_dest = make_temp_path(src, resolve_font_extension(src, fmt))
        try:
            res = compress_font(src, probe_dest, output_format=fmt, keep_smaller=True)
            return max(1, res.compressed_bytes)
        finally:
            probe_dest.unlink(missing_ok=True)
    if ext in IMAGE_EXTENSIONS:
        return estimate_min_image_bytes(src, output_format=fmt, max_width=max_width, max_height=max_height)
    return orig_bytes


def _read_keypress(fd: int) -> str:
    """Read a single keypress (including arrow escape sequences) from raw/cbreak fd."""
    ch = os.read(fd, 1).decode("utf-8", errors="ignore")
    if ch == "\x1b":
        ready, _, _ = select.select([fd], [], [], 0.05)
        if ready:
            seq = os.read(fd, 2).decode("utf-8", errors="ignore")
            return ch + seq
    return ch


def _format_slider_line(orig_bytes: int, min_bytes: int, min_pct: int, selected_pct: int) -> str:
    """Format a compact single-line terminal slider track."""
    width = 32
    span = max(1, 100 - min_pct)
    pos = int(round(((selected_pct - min_pct) / span) * width))
    pos = max(0, min(width, pos))

    left_fill = "━" * pos
    right_track = "─" * (width - pos)
    target_est = max(min_bytes, int(orig_bytes * (selected_pct / 100.0)))
    reduction_pct = max(0.0, 100.0 - selected_pct)

    return (
        f"\r\033[K  \033[32m{min_pct:3d}%\033[0m "
        f"[\033[36m{left_fill}\033[1;37;44m●\033[0m\033[90m{right_track}\033[0m] "
        f"\033[33m100%\033[0m  "
        f"Selected: \033[1;33m{selected_pct}%\033[0m "
        f"(~{format_size(target_est)}, \033[32m-{reduction_pct:.0f}% saved\033[0m)"
    )


def _interactive_percent_slider(
    src: Path,
    output_format: str = "keep",
    max_width: Optional[int] = None,
    max_height: Optional[int] = None,
) -> int:
    """Analyze minimum achievable size, then let the user choose target % with a live slider."""
    import termios
    import tty

    orig_bytes = src.stat().st_size
    with console.status(f"[cyan]Analyzing minimum possible size for {src.name}...[/cyan]"):
        min_bytes = _estimate_min_bytes(src, output_format=output_format, max_width=max_width, max_height=max_height)

    min_pct = max(1, min(100, math.ceil((min_bytes / orig_bytes) * 100))) if orig_bytes else 100
    max_reduction = max(0, 100 - min_pct)

    console.print(
        Panel(
            f"[bold]{src.name}[/bold]\n"
            f"Original Size: [cyan]{format_size(orig_bytes)}[/cyan]   |   "
            f"Smallest Possible: [bold green]{format_size(min_bytes)} ({min_pct}% of original, -{max_reduction}% max reduction)[/bold green]\n"
            f"[dim]Controls: ←/→ or a/d (±1%)  •  ↑/↓ or [ or ] (±5%)  •  Enter = Compress  •  q/Esc = Cancel[/dim]",
            title="Interactive Size Slider",
            border_style="cyan",
        )
    )

    if min_pct >= 100:
        console.print("[yellow]File is already at its minimum practical size (100%).[/yellow]")
        return 100

    pct = max(min_pct, min(100, (min_pct + 100) // 2))
    if not sys.stdin.isatty():
        return IntPrompt.ask(
            f"Enter target % of original size ({min_pct}-100)",
            default=pct,
        )

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        sys.stdout.write(_format_slider_line(orig_bytes, min_bytes, min_pct, pct))
        sys.stdout.flush()
        while True:
            key = _read_keypress(fd)
            if key in ("\r", "\n"):
                break
            if key in ("q", "Q", "\x03", "\x1b"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                raise SystemExit(0)
            if key in ("\x1b[D", "a", "A", "-", "_"):
                pct = max(min_pct, pct - 1)
            elif key in ("\x1b[C", "d", "D", "+", "="):
                pct = min(100, pct + 1)
            elif key in ("\x1b[B", "["):
                pct = max(min_pct, pct - 5)
            elif key in ("\x1b[A", "]"):
                pct = min(100, pct + 5)
            sys.stdout.write(_format_slider_line(orig_bytes, min_bytes, min_pct, pct))
            sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        sys.stdout.write("\n")
        sys.stdout.flush()

    return pct


def _interactive_wizard() -> tuple:
    """Prompt the user interactively when launched without file/folder arguments."""
    console.print(
        Panel.fit(
            "[bold cyan]JBSI All-in-One CLI Compressor[/bold cyan]  [dim]by Jaspreet Bhatia[/dim]\n"
            "[dim]PDF • Image (AVIF/HEIC/GIF) • Video • Audio • SVG • Office • Fonts • Archives[/dim]",
            border_style="cyan",
        )
    )
    while True:
        raw_path = Prompt.ask("Enter file or folder path (or 'help' for flags & examples)").strip().strip('"').strip("'")
        if raw_path.lower() in ("help", "?"):
            _print_cheat_sheet()
            continue
        break
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

    preset = "medium"
    target_size: Optional[str] = None
    use_slider = target_path.is_file()
    if not use_slider:
        preset = Prompt.ask("Compression preset", choices=["low", "medium", "high"], default="medium")
        target_size_raw = Prompt.ask("Max target size (e.g. 500KB, 5MB, 45%, or Enter to skip)", default="").strip()
        target_size = target_size_raw or None
    in_place = False
    out_path: Optional[Path] = None

    return (target_path,), preset, None, None, None, None, output_format, "h264", None, target_size, None, use_slider, kind, out_path, in_place, recursive


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


@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog="Tip: Run 'python main.py help' for a full cheat sheet of all flags, formats, and examples.",
)
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
@click.option("-t", "--target-size", default=None, help="Auto-fit under target size (e.g. 500KB, 5MB, or 45%).")
@click.option("-P", "--percent", type=click.IntRange(1, 100), default=None, help="Target size as % of original (1-100).")
@click.option("--slider", is_flag=True, help="Analyze smallest possible size first, then pick % with an interactive slider.")
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
    percent: Optional[int],
    slider: bool,
    kind: str,
    output: Optional[Path],
    in_place: bool,
    recursive: bool,
    allow_larger: bool,
) -> None:
    """Compress PDF, Image (AVIF/HEIC/GIF), Video, Audio, SVG, Office, Font, and Archive files."""
    if len(inputs) == 1 and str(inputs[0]).lower() in ("help", "?") and not inputs[0].expanduser().exists():
        _print_cheat_sheet()
        return

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
            percent,
            slider,
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

    fmt_lower = output_format.lower()
    targets = _collect_inputs(inputs, recursive=recursive, kind=kind.lower(), output_format=fmt_lower)
    if not targets:
        console.print("[yellow]No supported files found.[/yellow]")
        sys.exit(1)

    if slider:
        if len(targets) != 1 or targets[0].is_dir():
            console.print("[yellow]--slider operates on a single file; pass one file at a time.[/yellow]")
            sys.exit(2)
        percent = _interactive_percent_slider(
            targets[0],
            output_format=fmt_lower,
            max_width=max_width,
            max_height=max_height,
        )

    fixed_target_bytes: Optional[int] = None
    pct_spec: Optional[str] = f"{percent}%" if percent is not None else None
    if target_size:
        if target_size.strip().endswith("%"):
            pct_spec = target_size.strip()
        else:
            try:
                fixed_target_bytes = parse_size(target_size)
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
                sys.exit(2)

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
            target_bytes = fixed_target_bytes
            if pct_spec is not None and src.is_file():
                try:
                    target_bytes = parse_target_spec(pct_spec, src.stat().st_size)
                except ValueError as exc:
                    failures.append((src, str(exc)))
                    progress.advance(task_id)
                    continue
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
