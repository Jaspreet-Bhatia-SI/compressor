# All-in-One CLI Compressor (PDF • Image • Video • Audio)

Modular command-line compressor for **PDF**, **Images**, **Video**, and **Audio** with a dedicated module per media type.

## Project Structure

- `main.py` — Main CLI entry point importing all compressors
- `common.py` — Shared types, size parser/formatter, atomic output helper, and `ffprobe` utilities
- `pdf_compressor.py` — PDF compressor (Ghostscript + PyMuPDF)
- `image_compressor.py` — Image compressor (Pillow: JPG, PNG, WebP, AVIF, BMP, TIFF)
- `video_compressor.py` — Video compressor (FFmpeg: MP4, MOV, MKV, AVI, WebM — H.264/H.265)
- `audio_compressor.py` — Audio compressor (FFmpeg: MP3, AAC, M4A, WAV, FLAC, OGG, OPUS)
- `requirements.txt` — Python dependencies (`click`, `Pillow`, `PyMuPDF`, `rich`)

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

> **System dependencies:** [FFmpeg](https://ffmpeg.org/) (`ffmpeg` / `ffprobe`) is required for video and audio compression, and [Ghostscript](https://www.ghostscript.com/) (`gs`) enhances PDF compression (falls back to PyMuPDF if absent).

## Usage Examples

```bash
# Interactive mode
python main.py

# Compress a PDF (medium preset -> document_compressed.pdf)
python main.py document.pdf

# Compress a PDF under 2 MB
python main.py syllabus.pdf -t 2MB

# Compress & convert an image to WebP or AVIF
python main.py photo.jpg -p high -f webp
python main.py photo.jpg -p medium -f avif

# Compress a video to 720p max height using H.265
python main.py clip.mp4 --max-height 720 --video-codec h265

# Compress a video under 10 MB
python main.py clip.mp4 -t 10MB

# Compress an audio recording to 64kbps MP3
python main.py recording.wav -p high

# Batch compress only videos in a folder into ./out/
python main.py ./media --type video -o ./out/
```
