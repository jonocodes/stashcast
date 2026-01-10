"""
Download service for media files.

Handles both direct HTTP downloads and yt-dlp downloads.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, List
import shutil
import requests
import yt_dlp

from media.service.config import parse_ytdlp_extra_args


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

    log(f'Copying from: {file_path}')
    log(f'Saving to: {out_path}')

    # Copy file
    shutil.copy2(file_path, out_path)

    file_size = out_path.stat().st_size
    log(f'Copied {file_size} bytes')

    return DownloadedFileInfo(
        path=out_path, file_size=file_size, extension=out_path.suffix, mime_type=None
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

    log(f'Downloading from: {url}')
    log(f'Saving to: {out_path}')

    # Download file
    response = requests.get(url, stream=True, timeout=30)
    response.raise_for_status()

    with open(out_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    file_size = out_path.stat().st_size
    mime_type = response.headers.get('content-type', 'application/octet-stream')

    log(f'Downloaded {file_size} bytes')

    return DownloadedFileInfo(
        path=out_path, file_size=file_size, extension=out_path.suffix, mime_type=mime_type
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
        # Note: noplaylist removed to allow multi-item downloads
        # Multi-item handling is done at prefetch stage with --allow-multiple flag
        'quiet': not logger,  # Show output if logger is provided
    }

    # Enable file:// URLs if needed
    if url.startswith('file://'):
        ydl_opts['enable_file_urls'] = True

    # Parse and apply extra args from settings
    ydl_opts = parse_ytdlp_extra_args(ytdlp_extra_args, ydl_opts)

    log(f'Downloading with yt-dlp: {url}')
    log(f'Format: {ydl_opts.get("format")}')

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # Find downloaded files
    files = list(temp_dir.iterdir())
    log(f'yt-dlp created {len(files)} files')

    # Find main content file (video/audio)
    content_files = [
        f for f in files if f.suffix in ['.mp4', '.mkv', '.webm', '.mp3', '.m4a', '.ogg', '.opus']
    ]
    if not content_files:
        raise Exception('No media file found after yt-dlp download')

    # Use the largest file as the main content
    content_file = max(content_files, key=lambda f: f.stat().st_size)
    log(f'Main content file: {content_file.name} ({content_file.stat().st_size} bytes)')

    # Find thumbnail
    thumb_files = [f for f in files if f.suffix in ['.jpg', '.jpeg', '.png', '.webp']]
    thumbnail_path = thumb_files[0] if thumb_files else None
    if thumbnail_path:
        log(f'Thumbnail found: {thumbnail_path.name}')

    # Find subtitles
    subtitle_files = [f for f in files if f.suffix in ['.vtt', '.srt']]
    subtitle_path = subtitle_files[0] if subtitle_files else None
    if subtitle_path:
        log(f'Subtitles found: {subtitle_path.name}')

    return DownloadedFileInfo(
        path=content_file,
        file_size=content_file.stat().st_size,
        extension=content_file.suffix,
        thumbnail_path=thumbnail_path,
        subtitle_path=subtitle_path,
    )


def _url_hash(url: str) -> str:
    """Generate a short hash for a URL to use as folder name."""
    return hashlib.md5(url.encode()).hexdigest()[:12]


@dataclass
class BatchDownloadResult:
    """Result from batch downloading multiple URLs."""

    # Map of URL -> DownloadedFileInfo (for successful downloads)
    downloads: Dict[str, DownloadedFileInfo]
    # Map of URL -> error message (for failed downloads)
    errors: Dict[str, str]


def download_ytdlp_batch(
    urls: List[str],
    resolved_type: str,
    temp_dir,
    ytdlp_extra_args: str = '',
    logger=None,
) -> BatchDownloadResult:
    """
    Download multiple URLs using a single yt-dlp process.

    This leverages yt-dlp's built-in rate limiting and backoff handling
    for multiple URLs, which is more efficient than spawning separate
    processes for each URL.

    Args:
        urls: List of URLs to download
        resolved_type: 'audio' or 'video'
        temp_dir: Base temporary directory (each URL gets a subdirectory)
        ytdlp_extra_args: Additional yt-dlp arguments from settings
        logger: Optional callable(str) for logging

    Returns:
        BatchDownloadResult with successful downloads and errors
    """

    def log(message):
        if logger:
            logger(message)

    temp_dir = Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Track which URL is currently being processed and results
    url_to_folder: Dict[str, Path] = {}
    downloads: Dict[str, DownloadedFileInfo] = {}
    errors: Dict[str, str] = {}

    # Create folder for each URL based on hash
    for url in urls:
        folder = temp_dir / _url_hash(url)
        folder.mkdir(parents=True, exist_ok=True)
        url_to_folder[url] = folder

    # Prepare yt-dlp options
    if resolved_type == 'audio':
        format_spec = 'bestaudio/best'
    else:
        format_spec = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'

    # Track current URL being downloaded via progress hook
    current_url = {'url': None, 'folder': None}

    def progress_hook(d):
        if d['status'] == 'downloading':
            # Extract the original URL from info_dict
            info = d.get('info_dict', {})
            url = info.get('original_url') or info.get('webpage_url')
            if url and url in url_to_folder:
                current_url['url'] = url
                current_url['folder'] = url_to_folder[url]

    # Use a custom output template that puts files in URL-specific folders
    # We'll use the progress hook to determine which folder to use
    ydl_opts = {
        'format': format_spec,
        'writethumbnail': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['en'],
        'quiet': not logger,
        'progress_hooks': [progress_hook],
        'ignoreerrors': True,  # Continue on errors
        # Path template - each URL downloads to its hashed folder
        'paths': {'home': str(temp_dir)},
    }

    # Parse and apply extra args from settings
    ydl_opts = parse_ytdlp_extra_args(ytdlp_extra_args, ydl_opts)

    log(f'Batch downloading {len(urls)} URLs with yt-dlp')
    log(f'Format: {format_spec}')

    # Download each URL to its own folder
    # We process one at a time to ensure proper folder separation
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for url in urls:
            folder = url_to_folder[url]
            # Update output template for this URL's folder
            ydl.params['outtmpl'] = {'default': str(folder / 'download.%(ext)s')}

            log(f'Downloading: {url}')
            try:
                ydl.download([url])

                # Find downloaded files in this folder
                files = list(folder.iterdir())
                if not files:
                    errors[url] = 'No files downloaded'
                    continue

                # Find main content file
                content_files = [
                    f
                    for f in files
                    if f.suffix in ['.mp4', '.mkv', '.webm', '.mp3', '.m4a', '.ogg', '.opus']
                ]
                if not content_files:
                    errors[url] = 'No media file found after download'
                    continue

                content_file = max(content_files, key=lambda f: f.stat().st_size)

                # Find thumbnail
                thumb_files = [f for f in files if f.suffix in ['.jpg', '.jpeg', '.png', '.webp']]
                thumbnail_path = thumb_files[0] if thumb_files else None

                # Find subtitles
                subtitle_files = [f for f in files if f.suffix in ['.vtt', '.srt']]
                subtitle_path = subtitle_files[0] if subtitle_files else None

                downloads[url] = DownloadedFileInfo(
                    path=content_file,
                    file_size=content_file.stat().st_size,
                    extension=content_file.suffix,
                    thumbnail_path=thumbnail_path,
                    subtitle_path=subtitle_path,
                )
                log(f'Downloaded: {content_file.name} ({content_file.stat().st_size} bytes)')

            except Exception as e:
                errors[url] = str(e)
                log(f'Error downloading {url}: {e}')

    log(f'Batch complete: {len(downloads)} successful, {len(errors)} failed')

    return BatchDownloadResult(downloads=downloads, errors=errors)
