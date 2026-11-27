"""Dedicated SVG vector optimizer using Scour."""

from __future__ import annotations

from pathlib import Path

from scour import scour

from common import CompressionResult, finalize_output, make_temp_path

SVG_EXTENSIONS = {".svg"}

SVG_PRESETS = {
    "low": {
        "digits": 5,
        "shorten_ids": False,
        "remove_descriptive_elements": False,
        "strip_xml_prolog": False,
        "indent_type": "space",
    },
    "medium": {
        "digits": 4,
        "shorten_ids": True,
        "remove_descriptive_elements": True,
        "strip_xml_prolog": False,
        "indent_type": "none",
    },
    "high": {
        "digits": 2,
        "shorten_ids": True,
        "remove_descriptive_elements": True,
        "strip_xml_prolog": True,
        "indent_type": "none",
    },
}


def compress_svg(
    source: Path,
    dest: Path,
    preset: str = "medium",
    keep_smaller: bool = True,
) -> CompressionResult:
    """Minify and optimize an SVG vector graphic using Scour."""
    cfg = SVG_PRESETS[preset]
    options = scour.parse_args(args=[])
    options.digits = cfg["digits"]
    options.simple_colors = True
    options.style_to_xml = True
    options.group_collapse = True
    options.group_create = False
    options.keep_editor_data = False
    options.keep_defs = False
    options.strip_comments = True
    options.strip_ids = cfg["shorten_ids"]
    options.shorten_ids = cfg["shorten_ids"]
    options.remove_metadata = True
    options.remove_descriptive_elements = cfg["remove_descriptive_elements"]
    options.strip_xml_prolog = cfg["strip_xml_prolog"]
    options.enable_viewboxing = True
    options.indent_type = cfg["indent_type"]
    options.newlines = preset == "low"

    raw_svg = source.read_text(encoding="utf-8")
    optimized_svg = scour.scourString(raw_svg, options)

    tmp_path = make_temp_path(dest, ".svg")
    try:
        tmp_path.write_text(optimized_svg, encoding="utf-8")
        return finalize_output(
            source,
            tmp_path,
            dest,
            f"scour/{preset}",
            keep_smaller=keep_smaller,
            allow_keep_original=True,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
