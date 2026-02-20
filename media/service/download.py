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
from django.conf import settings

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
    Download media using yt-dlp, with Apple Podcasts fallback.

    Args:
        url: Source URL
        resolved_type: 'audio' or 'video'
        temp_dir: Temporary directory for download (Path object or str)
        ytdlp_extra_args: Additional yt-dlp arguments from settings
        logger: Optional callable(str) for logging

    Returns:
        DownloadedFileInfo
    """
    from media.service.resolve import _is_apple_podcasts_url

    try:
        return _download_ytdlp_inner(url, resolved_type, temp_dir, ytdlp_extra_args, logger)
    except Exception:
        if _is_apple_podcasts_url(url):
            return _download_apple_podcasts(url, temp_dir, logger)
        raise


def _download_apple_podcasts(url, temp_dir, logger=None):
    """
    Fallback downloader for Apple Podcasts when yt-dlp's extractor is broken.

    Fetches the Apple Podcasts page to extract the stream URL, then downloads
    the audio file directly.
    """
    import json
    import re

    def log(message):
        if logger:
            logger(message)

    temp_dir = Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    log('yt-dlp Apple Podcasts extractor failed, using fallback downloader')

    # Fetch the page and extract the stream URL
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    pattern = r'<script [^>]*\bid=["\']serialized-server-data["\'][^>]*>(.*?)</script>'
    match = re.search(pattern, resp.text, re.DOTALL)
    if not match:
        raise Exception('Could not find serialized-server-data in Apple Podcasts page')

    raw = json.loads(match.group(1).strip())
    inner = raw['data'][0]['data']

    # Find stream URL from headerButtonItems
    stream_url = None
    for btn in inner.get('headerButtonItems', []):
        offer = btn.get('model', {}).get('playAction', {}).get('episodeOffer', {})
        if offer.get('streamUrl'):
            stream_url = offer['streamUrl']
            break

    # Also check episodeOffer in paragraph shelf
    if not stream_url:
        for shelf in inner.get('shelves', []):
            if shelf.get('contentType') == 'paragraph':
                for item in shelf.get('items', []):
                    offer = item.get('episodeOffer', {})
                    if offer.get('streamUrl'):
                        stream_url = offer['streamUrl']
                        break
                if stream_url:
                    break

    if not stream_url:
        raise Exception('Could not extract stream URL from Apple Podcasts page')

    log(f'Extracted stream URL: {stream_url[:80]}...')

    # Download the audio file directly
    out_path = temp_dir / 'download.mp3'
    download_info = download_direct(stream_url, out_path, logger=logger)

    # Also try to download the thumbnail
    thumbnail_path = None
    try:
        # Extract thumbnail from og:image meta tag
        og_match = re.search(
            r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)', resp.text
        )
        if og_match:
            thumb_url = og_match.group(1)
            thumb_path = temp_dir / 'download.jpg'
            log(f'Downloading thumbnail: {thumb_url[:80]}...')
            thumb_resp = requests.get(thumb_url, timeout=15)
            thumb_resp.raise_for_status()
            with open(thumb_path, 'wb') as f:
                f.write(thumb_resp.content)
            thumbnail_path = thumb_path
    except Exception as e:
        log(f'Thumbnail download failed (non-fatal): {e}')

    return DownloadedFileInfo(
        path=download_info.path,
        file_size=download_info.file_size,
        extension='.mp3',
        thumbnail_path=thumbnail_path,
    )


def _download_ytdlp_inner(url, resolved_type, temp_dir, ytdlp_extra_args='', logger=None):
    """Download media using yt-dlp (inner implementation)."""

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
        'subtitleslangs': [settings.STASHCAST_SUBTITLE_LANGUAGE],
        # Note: noplaylist removed to allow multi-item downloads
        # Multi-item handling is done at prefetch stage with --allow-multiple flag
        'quiet': not logger,  # Show output if logger is provided
    }

    # Enable file:// URLs if needed
    if url.startswith('file://'):
        ydl_opts['enable_file_urls'] = True

    # Add proxy if configured (needed for cloud VMs where YouTube blocks requests)
    if settings.STASHCAST_YTDLP_PROXY:
        ydl_opts['proxy'] = settings.STASHCAST_YTDLP_PROXY

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
class VideoInfo:
    """Information about a single video from prefetch."""

    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    duration_seconds: Optional[int] = None
    has_video: bool = True
    has_audio: bool = True
    webpage_url: Optional[str] = None
    extractor: Optional[str] = None
    external_id: Optional[str] = None
    # For tracking which original URL this came from (for playlists)
    source_url: Optional[str] = None
    playlist_title: Optional[str] = None


@dataclass
class BatchPrefetchResult:
    """Result from batch prefetching multiple URLs."""

    # List of all videos (playlists expanded)
    videos: List[VideoInfo]
    # Map of original URL -> error message (for failed prefetches)
    errors: Dict[str, str]


def prefetch_ytdlp_batch(
    urls: List[str],
    logger=None,
) -> BatchPrefetchResult:
    """
    Prefetch metadata for multiple URLs in a single yt-dlp session.

    Expands playlists automatically and returns info for all individual videos.
    This is the first of two yt-dlp calls in the batch process.

    Args:
        urls: List of URLs to prefetch (may include playlists)
        logger: Optional callable(str) for logging

    Returns:
        BatchPrefetchResult with video info and errors
    """

    def log(message):
        if logger:
            logger(message)

    videos: List[VideoInfo] = []
    errors: Dict[str, str] = {}

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,  # We need full info for metadata
        'ignoreerrors': True,
    }

    # Add proxy if configured (needed for cloud VMs where YouTube blocks requests)
    if settings.STASHCAST_YTDLP_PROXY:
        ydl_opts['proxy'] = settings.STASHCAST_YTDLP_PROXY

    log(f'Batch prefetching {len(urls)} URLs with yt-dlp')

    # Single yt-dlp context for all prefetch operations
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for url in urls:
            log(f'Prefetching: {url}')
            try:
                info = ydl.extract_info(url, download=False)

                if info is None:
                    errors[url] = 'No info returned'
                    continue

                # Check if this is a playlist/channel (has entries)
                if 'entries' in info:
                    playlist_title = info.get('title', 'Untitled Playlist')
                    entries = list(info.get('entries', []))
                    log(f'  Playlist detected: {playlist_title} ({len(entries)} items)')

                    for entry in entries:
                        if entry is None:
                            continue

                        # Get video URL
                        video_url = entry.get('webpage_url') or entry.get('url')
                        if not video_url:
                            continue

                        # Check for video/audio streams
                        formats = entry.get('formats', [])
                        has_video = any(f.get('vcodec') != 'none' for f in formats)
                        has_audio = any(f.get('acodec') != 'none' for f in formats)

                        # Fallback to top-level codec info
                        if not has_video and not has_audio:
                            has_video = entry.get('vcodec') not in (None, 'none')
                            has_audio = entry.get('acodec') not in (None, 'none')

                        videos.append(
                            VideoInfo(
                                url=video_url,
                                title=entry.get('title', 'Untitled'),
                                description=entry.get('description', ''),
                                author=entry.get('uploader') or entry.get('channel', ''),
                                duration_seconds=entry.get('duration'),
                                has_video=has_video if has_video or has_audio else True,
                                has_audio=has_audio if has_video or has_audio else True,
                                webpage_url=video_url,
                                extractor=entry.get('extractor', ''),
                                external_id=entry.get('id', ''),
                                source_url=url,
                                playlist_title=playlist_title,
                            )
                        )
                else:
                    # Single video
                    video_url = info.get('webpage_url') or url

                    # Check for video/audio streams
                    formats = info.get('formats', [])
                    has_video = any(f.get('vcodec') != 'none' for f in formats)
                    has_audio = any(f.get('acodec') != 'none' for f in formats)

                    # Fallback to top-level codec info
                    if not has_video and not has_audio:
                        has_video = info.get('vcodec') not in (None, 'none')
                        has_audio = info.get('acodec') not in (None, 'none')

                    videos.append(
                        VideoInfo(
                            url=video_url,
                            title=info.get('title', 'Untitled'),
                            description=info.get('description', ''),
                            author=info.get('uploader') or info.get('channel', ''),
                            duration_seconds=info.get('duration'),
                            has_video=has_video if has_video or has_audio else True,
                            has_audio=has_audio if has_video or has_audio else True,
                            webpage_url=video_url,
                            extractor=info.get('extractor', ''),
                            external_id=info.get('id', ''),
                            source_url=url,
                            playlist_title=None,
                        )
                    )
                    log(f'  Single video: {info.get("title", "Untitled")}')

            except Exception as e:
                errors[url] = str(e)
                log(f'  Error: {e}')

    log(f'Prefetch complete: {len(videos)} videos found, {len(errors)} errors')
    return BatchPrefetchResult(videos=videos, errors=errors)


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
    Download multiple URLs in a single yt-dlp call.

    This is the second of two yt-dlp calls in the batch process.
    All URLs should be individual videos (playlists already expanded).

    Args:
        urls: List of video URLs to download (no playlists)
        resolved_type: 'audio' or 'video'
        temp_dir: Base temporary directory (each URL gets a subdirectory by ID)
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

    downloads: Dict[str, DownloadedFileInfo] = {}
    errors: Dict[str, str] = {}

    # Prepare yt-dlp options
    if resolved_type == 'audio':
        format_spec = 'bestaudio/best'
    else:
        format_spec = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'

    # Use %(id)s to separate files into folders by video ID
    # We'll map IDs back to URLs after download
    ydl_opts = {
        'format': format_spec,
        'outtmpl': str(temp_dir / '%(id)s' / 'download.%(ext)s'),
        'writethumbnail': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': [settings.STASHCAST_SUBTITLE_LANGUAGE],
        'quiet': not logger,
        'ignoreerrors': True,
        'noplaylist': True,
    }

    # Add proxy if configured (needed for cloud VMs where YouTube blocks requests)
    if settings.STASHCAST_YTDLP_PROXY:
        ydl_opts['proxy'] = settings.STASHCAST_YTDLP_PROXY

    # Parse and apply extra args from settings
    ydl_opts = parse_ytdlp_extra_args(ytdlp_extra_args, ydl_opts)

    log(f'Batch downloading {len(urls)} URLs with single yt-dlp call')
    log(f'Format: {format_spec}')

    # Track URL -> ID mapping via progress hook
    url_to_id: Dict[str, str] = {}

    def progress_hook(d):
        if d['status'] in ('downloading', 'finished'):
            info = d.get('info_dict', {})
            video_id = info.get('id')
            url = info.get('webpage_url') or info.get('original_url')
            if video_id and url:
                url_to_id[url] = video_id

    ydl_opts['progress_hooks'] = [progress_hook]

    # Single download call for all URLs
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download(urls)

    log(f'Download complete, processing {len(url_to_id)} results')

    # Process downloaded files - map URLs to their downloaded content
    for url in urls:
        video_id = url_to_id.get(url)
        if not video_id:
            errors[url] = 'No video ID captured - download may have failed'
            continue

        folder = temp_dir / video_id
        if not folder.exists():
            errors[url] = f'Output folder not found: {video_id}'
            continue

        files = list(folder.iterdir())
        if not files:
            errors[url] = 'No files downloaded'
            continue

        content_files = [
            f
            for f in files
            if f.suffix in ['.mp4', '.mkv', '.webm', '.mp3', '.m4a', '.ogg', '.opus']
        ]
        if not content_files:
            errors[url] = 'No media file found after download'
            continue

        content_file = max(content_files, key=lambda f: f.stat().st_size)
        thumb_files = [f for f in files if f.suffix in ['.jpg', '.jpeg', '.png', '.webp']]
        subtitle_files = [f for f in files if f.suffix in ['.vtt', '.srt']]

        downloads[url] = DownloadedFileInfo(
            path=content_file,
            file_size=content_file.stat().st_size,
            extension=content_file.suffix,
            thumbnail_path=thumb_files[0] if thumb_files else None,
            subtitle_path=subtitle_files[0] if subtitle_files else None,
        )
        log(f'Processed: {content_file.name} ({content_file.stat().st_size} bytes)')

    log(f'Batch complete: {len(downloads)} successful, {len(errors)} failed')
    return BatchDownloadResult(downloads=downloads, errors=errors)
