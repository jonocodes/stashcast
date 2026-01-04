"""
Download service for media files.

Handles both direct HTTP downloads and yt-dlp downloads.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import shutil
import tempfile
import requests
import yt_dlp

from service.config import get_ytdlp_args_for_type, parse_ytdlp_extra_args


@dataclass
class DownloadedFileInfo:
    """Information about a downloaded file"""
    path: Path
    file_size: int
    extension: str
    mime_type: Optional[str] = None
    thumbnail_path: Optional[Path] = None
    subtitle_path: Optional[Path] = None


def download_file(file_path, out_path, logger=None):
    """
    Copy a local file to the output path.

    Args:
        file_path: Local file path (Path object or str)
        out_path: Output file path (Path object or str)
        logger: Optional callable(str) for logging

    Returns:
        DownloadedFileInfo
    """
    def log(message):
        if logger:
            logger(message)

    file_path = Path(file_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    log(f"Copying from: {file_path}")
    log(f"Saving to: {out_path}")

    # Copy file
    shutil.copy2(file_path, out_path)

    file_size = out_path.stat().st_size
    log(f"Copied {file_size} bytes")

    return DownloadedFileInfo(
        path=out_path,
        file_size=file_size,
        extension=out_path.suffix,
        mime_type=None
    )


def download_direct(url, out_path, logger=None):
    """
    Download media file directly via HTTP.

    Args:
        url: Direct media URL
        out_path: Output file path (Path object or str)
        logger: Optional callable(str) for logging

    Returns:
        DownloadedFileInfo
    """
    def log(message):
        if logger:
            logger(message)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    log(f"Downloading from: {url}")
    log(f"Saving to: {out_path}")

    # Download file
    response = requests.get(url, stream=True, timeout=30)
    response.raise_for_status()

    with open(out_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    file_size = out_path.stat().st_size
    mime_type = response.headers.get('content-type', 'application/octet-stream')

    log(f"Downloaded {file_size} bytes")

    return DownloadedFileInfo(
        path=out_path,
        file_size=file_size,
        extension=out_path.suffix,
        mime_type=mime_type
    )


def download_ytdlp(url, resolved_type, temp_dir, ytdlp_extra_args='', logger=None):
    """
    Download media using yt-dlp.

    Args:
        url: Source URL
        resolved_type: 'audio' or 'video'
        temp_dir: Temporary directory for download (Path object or str)
        ytdlp_extra_args: Additional yt-dlp arguments from settings
        logger: Optional callable(str) for logging

    Returns:
        DownloadedFileInfo
    """
    def log(message):
        if logger:
            logger(message)

    temp_dir = Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Prepare yt-dlp options
    # Start with fallback format specs
    if resolved_type == 'audio':
        format_spec = 'bestaudio/best'
    else:
        format_spec = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'

    temp_output = temp_dir / 'download.%(ext)s'

    ydl_opts = {
        'format': format_spec,
        'outtmpl': str(temp_output),
        'writethumbnail': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['en'],
        'noplaylist': True,
        'quiet': not logger,  # Show output if logger is provided
    }

    # Enable file:// URLs if needed
    if url.startswith('file://'):
        ydl_opts['enable_file_urls'] = True

    # Parse and apply extra args from settings
    ydl_opts = parse_ytdlp_extra_args(ytdlp_extra_args, ydl_opts)

    log(f"Downloading with yt-dlp: {url}")
    log(f"Format: {ydl_opts.get('format')}")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # Find downloaded files
    files = list(temp_dir.iterdir())
    log(f"yt-dlp created {len(files)} files")

    # Find main content file (video/audio)
    content_files = [f for f in files if f.suffix in ['.mp4', '.mkv', '.webm', '.mp3', '.m4a', '.ogg', '.opus']]
    if not content_files:
        raise Exception("No media file found after yt-dlp download")

    # Use the largest file as the main content
    content_file = max(content_files, key=lambda f: f.stat().st_size)
    log(f"Main content file: {content_file.name} ({content_file.stat().st_size} bytes)")

    # Find thumbnail
    thumb_files = [f for f in files if f.suffix in ['.jpg', '.jpeg', '.png', '.webp']]
    thumbnail_path = thumb_files[0] if thumb_files else None
    if thumbnail_path:
        log(f"Thumbnail found: {thumbnail_path.name}")

    # Find subtitles
    subtitle_files = [f for f in files if f.suffix in ['.vtt', '.srt']]
    subtitle_path = subtitle_files[0] if subtitle_files else None
    if subtitle_path:
        log(f"Subtitles found: {subtitle_path.name}")

    return DownloadedFileInfo(
        path=content_file,
        file_size=content_file.stat().st_size,
        extension=content_file.suffix,
        thumbnail_path=thumbnail_path,
        subtitle_path=subtitle_path
    )
