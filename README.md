<div align="center">

<img src="assets/hero-banner.svg" alt="JBSI File Compressor & Format Converter Banner" width="100%"/>

<br/><br/>

# JBSI File Compressor & Format Converter

**Built by [Jaspreet Bhatia](https://github.com/Jaspreet-Bhatia-SI) (`JBSI`) — a modular file compression & format conversion CLI + browser tool for PDFs, images (AVIF / HEIC / WebP / GIF), videos, audio, SVGs, Office decks/docs, web fonts, and archives with an interactive size slider and zero-bloat guarantees.**

[![JBSI](https://img.shields.io/badge/Brand-JBSI-0EA5E9?style=for-the-badge)](https://github.com/Jaspreet-Bhatia-SI)
[![Author](https://img.shields.io/badge/Author-Jaspreet%20Bhatia-F59E0B?style=for-the-badge)](https://github.com/Jaspreet-Bhatia-SI)
[![Compress Online](https://img.shields.io/badge/Compress%20Online-GitHub%20Pages-0284C7?style=for-the-badge&logo=googlechrome&logoColor=white)](https://jaspreet-bhatia-si.github.io/compressor/)
[![Open in Codespaces](https://img.shields.io/badge/Real%20Terminal-Open%20in%20Codespaces-10B981?style=for-the-badge&logo=githubcodespaces&logoColor=white)](https://codespaces.new/Jaspreet-Bhatia-SI/compressor)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Formats](https://img.shields.io/badge/Formats-35%2B-818CF8?style=for-the-badge)](#supported-formats--engines)
[![License: MIT](https://img.shields.io/badge/License-MIT-64748B?style=for-the-badge)](LICENSE)

</div>

---

## Live Preview & Real Cloud Terminal

<div align="center">
  <img src="assets/terminal-demo.svg" alt="Real CLI Session Recording" width="100%"/>
  <br/><br/>
  <a href="https://codespaces.new/Jaspreet-Bhatia-SI/compressor">
    <img src="https://github.com/codespaces/badge.svg" alt="Open in GitHub Codespaces"/>
  </a>
  <p><em>Recorded from an actual <code>python main.py</code> batch run — or click <strong>Open in GitHub Codespaces</strong> above to launch a real Linux terminal with Python, FFmpeg, and Ghostscript pre-installed.</em></p>
</div>

---

## Architecture & Pipeline

Every input passes through `main.py`, routes automatically to its dedicated compressor module, runs through the **Target-Size Solver** (when `-t` is set), and commits via the **Atomic Size Guard** so originals are never corrupted or accidentally enlarged.

```mermaid
flowchart LR
    A["Input File(s) or Folder"] --> B{"main.py<br/>Router"}

    B -->|.pdf| C1["pdf_compressor.py<br/>Ghostscript + PyMuPDF"]
    B -->|.jpg .png .webp .avif<br/>.heic .gif .tiff .bmp| C2["image_compressor.py<br/>Pillow + pillow-heif + FFmpeg"]
    B -->|.mp4 .mov .mkv .webm<br/>.avi .gif→mp4| C3["video_compressor.py<br/>FFmpeg H.264 / H.265 / VP9"]
    B -->|.mp3 .wav .flac .aac<br/>.m4a .ogg .opus| C4["audio_compressor.py<br/>FFmpeg Audio"]
    B -->|.svg| C5["svg_compressor.py<br/>Scour Vector Optimizer"]
    B -->|.docx .pptx .xlsx<br/>.odt .odp .ods| C6["office_compressor.py<br/>Media Recompressor + ZIP-9"]
    B -->|.ttf .otf .woff .woff2| C7["font_compressor.py<br/>FontTools + Brotli"]
    B -->|.zip .tar.* .gz .xz .zst<br/>or Folder Bundle| C8["archive_compressor.py<br/>Zstd / XZ / Gzip / ZIP"]

    C1 & C2 & C3 & C4 & C5 & C6 & C7 & C8 --> D{"common.py<br/>Atomic Size Guard"}
    D -->|"new < orig"| E["Commit Output"]
    D -->|"new >= orig"| F["Keep Original<br/>(Zero Bloat)"]
```

### Target-Size Solver (`-t 500KB`, `-t 5MB`)

```mermaid
flowchart TD
    T["Target Size Requested (-t)"] --> M{"Media Kind"}
    M -->|PDF| P1["Step down DPI & JPEG quality<br/>until size <= target"]
    M -->|Image / AVIF / WebP| P2["Search quality steps (90→18)<br/>then resolution scales (1.0→0.4)"]
    M -->|Video / Audio| P3["Probe duration with ffprobe<br/>Calculate exact target kbps"]
    P1 & P2 & P3 --> G["Atomic Move to Destination"]
```

---

## Supported Formats & Engines

| Module | Input Formats | Output / Conversion | Engine |
| :--- | :--- | :--- | :--- |
| [`pdf_compressor.py`](pdf_compressor.py) | `.pdf` | `.pdf` | Ghostscript (`gs`) + PyMuPDF fallback |
| [`image_compressor.py`](image_compressor.py) | `.jpg` `.jpeg` `.png` `.webp` `.avif` `.heic` `.heif` `.gif` `.bmp` `.tiff` | `.jpg` `.png` `.webp` `.avif` `.heic` `.gif` | Pillow + `pillow-heif` + FFmpeg palettegen (GIF) |
| [`video_compressor.py`](video_compressor.py) | `.mp4` `.mov` `.mkv` `.avi` `.webm` `.m4v` `.flv` (+ `.gif` → video) | `.mp4` `.webm` (H.264 / H.265 / VP9) | FFmpeg |
| [`audio_compressor.py`](audio_compressor.py) | `.mp3` `.wav` `.flac` `.aac` `.m4a` `.ogg` `.opus` | `.mp3` `.aac` `.m4a` `.ogg` `.opus` | FFmpeg |
| [`svg_compressor.py`](svg_compressor.py) | `.svg` | `.svg` | Scour (metadata/comment/ID/path optimizer) |
| [`office_compressor.py`](office_compressor.py) | `.docx` `.pptx` `.xlsx` `.odt` `.odp` `.ods` | Same editable Office file, or `.pdf` via `-f pdf` | Embedded image downscaling + ZIP deflate-9 (+ LibreOffice) |
| [`font_compressor.py`](font_compressor.py) | `.ttf` `.otf` `.woff` `.woff2` | `.woff2` (default) / `.woff` | FontTools + Brotli |
| [`archive_compressor.py`](archive_compressor.py) | `.zip` `.tar` `.tar.gz` `.tgz` `.tar.bz2` `.tar.xz` `.tar.zst` `.gz` `.bz2` `.xz` `.zst` (+ folders) | `.zip` `.tar.gz` `.tar.bz2` `.tar.xz` `.tar.zst` `.gz` `.bz2` `.xz` `.zst` | Python `zipfile`/`tarfile`/`lzma` + `zstandard` |

---

## Project Structure

```text
compressor/
├── main.py                 # Unified CLI, interactive wizard, progress bar & Rich summary
├── common.py               # Shared types, size parser/formatter, ffprobe, atomic size guard
├── pdf_compressor.py       # Ghostscript + PyMuPDF compressor
├── image_compressor.py     # Pillow, AVIF, HEIC/HEIF & animated GIF compressor
├── video_compressor.py     # FFmpeg H.264 / H.265 / VP9 compressor
├── audio_compressor.py     # FFmpeg audio compressor & converter
├── svg_compressor.py       # Scour SVG vector minifier
├── office_compressor.py    # Editable Office media optimizer & PDF exporter
├── font_compressor.py      # TTF/OTF -> WOFF2 Brotli font compressor
├── archive_compressor.py   # Archive re-compressor & folder bundler
├── .devcontainer/          # One-click GitHub Codespaces terminal (Python + FFmpeg + Ghostscript)
├── docs/                   # Light-theme browser-local Web App (GitHub Pages)
├── LICENSE                 # MIT License & JBSI Trademark Notice
├── requirements.txt        # Python dependencies
└── assets/                 # Animated SVG banner & terminal demo
```

---

## Setup

```bash
git clone https://github.com/Jaspreet-Bhatia-SI/compressor.git
cd compressor
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

> **Optional system binaries:**
> - **FFmpeg** (`ffmpeg`, `ffprobe`) — required for video, audio, and palette-optimized animated GIFs.
> - **Ghostscript** (`gs`) — recommended for high-ratio PDF compression (falls back to PyMuPDF if absent).
> - **LibreOffice** (`soffice`) — only needed when converting Office files directly to PDF via `-f pdf`.

---

## Usage Examples (By Compressor)

> Every module in this repo also documents CLI + Python API examples in its header docstring. Run `python main.py help` anytime in your terminal for the built-in cheat sheet.

### Interactive Mode, Size Slider & Built-in Cheat Sheet
```bash
python main.py                                     # Launch guided interactive wizard (includes % slider)
python main.py photo.jpg --slider                  # Probe minimum possible size, then slide % (min%..100%)
python main.py report.pdf -P 35                    # Compress directly to 35% of original size (or -t 35%)
python main.py help                                # Show colorful flags, formats & examples cheat sheet
python main.py -h                                  # Show concise CLI flag syntax
```

### 1. PDF (`pdf_compressor.py`)
```bash
python main.py document.pdf                        # Balanced compression (/ebook preset, 150 DPI)
python main.py scan.pdf -p high                    # Smallest screen preset (72 DPI)
python main.py syllabus.pdf -t 2MB                 # Auto-fit PDF strictly under 2 MB
python main.py book.pdf --dpi 120 -q 60            # Custom image DPI & JPEG quality
```

### 2. Images — JPG, PNG, WebP, AVIF, HEIC, GIF (`image_compressor.py`)
```bash
python main.py photo.heic -p medium -f avif        # Convert iPhone HEIC -> tiny AVIF
python main.py banner.png --max-width 1920 -f webp # Downscale + convert PNG -> WebP
python main.py avatar.jpg -t 200KB                 # Auto-fit image under 200 KB
python main.py anim.gif -p high --max-width 480    # Optimize animated GIF (FFmpeg palettegen)
python main.py anim.gif -f mp4                     # Convert animated GIF -> lightweight MP4
```

### 3. Video (`video_compressor.py`)
```bash
python main.py clip.mp4                            # Balanced H.264 compression (CRF 26)
python main.py clip.mp4 --max-height 720 --video-codec h265
python main.py demo.mov -t 10MB                    # Auto-fit video under 10 MB via duration math
python main.py clip.avi -f webm -p high            # Convert AVI -> VP9/Opus WebM
```

### 4. Audio (`audio_compressor.py`)
```bash
python main.py recording.wav -p high               # Convert lossless WAV -> compact 64kbps MP3
python main.py track.flac -f opus --audio-bitrate 96
python main.py podcast.mp3 -t 5MB                  # Auto-fit audio under 5 MB
```

### 5. SVG Vectors (`svg_compressor.py`)
```bash
python main.py logo.svg                            # Medium Scour optimization (shorten IDs, strip metadata)
python main.py icon.svg -p high                    # Aggressive minification (2 decimal precision)
```

### 6. Office Documents (`office_compressor.py`)
```bash
python main.py slides.pptx -p medium               # Shrink embedded slide images (keeps .pptx editable!)
python main.py report.docx -p high --max-width 1024
python main.py deck.pptx -f pdf -t 3MB             # Export Office -> compressed PDF (requires LibreOffice)
```

### 7. Fonts (`font_compressor.py`)
```bash
python main.py Inter-Regular.ttf                   # Compress desktop TTF -> .woff2 (Brotli)
python main.py BrandFont.otf -f woff               # Convert OTF -> .woff
```

### 8. Archives & Folder Bundling (`archive_compressor.py`)
```bash
python main.py backup.zip -f tar.zst -p high       # Re-pack ZIP into ultra-tight .tar.zst
python main.py logs.tar                            # Compress uncompressed .tar -> .tar.zst
python main.py ./xyz -f tar.zst                    # Bundle entire ./xyz folder -> xyz_compressed.tar.zst
python main.py database.sql -f zst -p high         # Compress any single file with Zstandard
```

### 9. Batch Folder Compression (`./xyz`)
```bash
python main.py ./xyz -r -o ./compressed/           # Recursively compress all supported media into ./compressed/
python main.py ./xyz -r --type image -f avif       # Convert only images in ./xyz to AVIF
python main.py ./xyz -r --in-place                 # Safely replace originals atomically in-place
```

<details>
<summary><strong>CLI Options & Preset Reference</strong></summary>

| Flag | Default | Description |
| :--- | :--- | :--- |
| `-p, --preset` | `medium` | `low` (highest quality), `medium` (balanced), `high` (smallest file) |
| `-q, --quality` | auto | Custom quality `1–100` for images, PDFs, and Office embedded media |
| `--dpi` | auto | Custom PDF image DPI (`36–600`) |
| `--max-width` / `--max-height` | none | Downscale images, videos, GIFs, or Office embedded images preserving aspect ratio |
| `-f, --format` | `keep` | Convert format (`avif`, `webp`, `heic`, `jpg`, `png`, `gif`, `mp4`, `webm`, `mp3`, `aac`, `m4a`, `ogg`, `opus`, `pdf`, `woff2`, `woff`, `zip`, `tar.gz`, `tar.xz`, `tar.zst`, `gz`, `xz`, `zst`) |
| `--video-codec` | `h264` | `h264` or `h265` for video |
| `--audio-bitrate` | auto | Audio bitrate in kbps (`24–320`) |
| `-t, --target-size` | none | Auto-fit output under size target (`500KB`, `5MB`, or `45%`) |
| `-P, --percent` | none | Target compressed size as `%` of original (`1–100`) |
| `--slider` | `false` | Check smallest possible size first, then set `%` with an interactive arrow-key slider |
| `--type` | `all` | Filter folder scans: `all`, `pdf`, `image`, `video`, `audio`, `svg`, `office`, `font`, `archive` |
| `-o, --output` | `*_compressed` | Custom output file or directory |
| `--in-place` | `false` | Safely replace original file(s) atomically |
| `-r, --recursive` | `false` | Recurse into subdirectories |
| `--allow-larger` | `false` | Disable size-guard and keep output even if larger than source |

</details>

---

<div align="center">

**JBSI** — Designed & Built by **[Jaspreet Bhatia](https://github.com/Jaspreet-Bhatia-SI)**

*Copyright &copy; 2026 Jaspreet Bhatia (`JBSI`). Licensed under the [MIT License](LICENSE).*

</div>
