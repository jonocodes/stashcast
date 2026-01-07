"""
Metadata extraction and media type resolution.

Handles prefetching metadata and determining the actual media type.
"""

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse
from pathlib import Path
import requests
import yt_dlp

from media.service.constants import AUDIO_EXTENSIONS


class PlaylistNotSupported(Exception):
    """Raised when URL points to a playlist"""

    pass


@dataclass
class PrefetchResult:
    """Result from prefetching metadata"""

    title: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    duration_seconds: Optional[int] = None
    has_video_streams: bool = False
    has_audio_streams: bool = False
    webpage_url: Optional[str] = None
    extractor: Optional[str] = None
    external_id: Optional[str] = None
    file_extension: Optional[str] = None
    extracted_media_url: Optional[str] = None  # URL extracted from HTML


def prefetch(url, strategy, logger=None):
    """
    Fetch metadata without downloading the media file.

    Args:
        url: Source URL or file path
        strategy: 'file', 'direct', or 'ytdlp'
        logger: Optional callable(str) for logging

    Returns:
        PrefetchResult with metadata

    Raises:
        PlaylistNotSupported: If URL is a playlist
    """

    def log(message):
        if logger:
            logger(message)

    if strategy == 'file':
        return _prefetch_file(url, logger=log)
    elif strategy == 'direct':
        return _prefetch_direct(url, logger=log)
    elif strategy == 'ytdlp':
        return _prefetch_ytdlp(url, logger=log)
    else:
        raise ValueError(f'Unknown strategy: {strategy}')


def _prefetch_file(file_path, logger=None):
    """Prefetch metadata for local file path"""
    file_path = Path(file_path)
    filename = file_path.stem
    ext = file_path.suffix.lower()

    result = PrefetchResult()
    result.title = filename or 'local-media'
    result.file_extension = ext

    # Determine if it's audio or video based on extension
    audio_exts = ['.mp3', '.m4a', '.ogg', '.wav', '.aac', '.flac', '.opus']
    if ext in audio_exts:
        result.has_audio_streams = True
        result.has_video_streams = False
    else:
        result.has_video_streams = True
        result.has_audio_streams = True  # Videos usually have audio too

    if logger:
        logger(f'Local file detected: {file_path}')
        logger(f'Filename: {result.title}')
        logger(f'Extension: {ext}')

    return result


def _prefetch_direct(url, logger=None):
    """Prefetch metadata for direct media URL"""
    parsed = urlparse(url)
    filename = Path(parsed.path).stem
    ext = Path(parsed.path).suffix.lower()

    result = PrefetchResult()
    result.title = filename or 'downloaded-media'
    result.file_extension = ext

    # Determine if it's audio or video based on extension
    audio_exts = ['.mp3', '.m4a', '.ogg', '.wav', '.aac', '.flac', '.opus']
    if ext in audio_exts:
        result.has_audio_streams = True
        result.has_video_streams = False
    else:
        result.has_video_streams = True
        result.has_audio_streams = True  # Videos usually have audio too

    if logger:
        logger(f'Direct URL detected: {url}')
        logger(f'Filename: {result.title}')
        logger(f'Extension: {ext}')

    return result


def _prefetch_ytdlp(url, logger=None):
    """Prefetch metadata using yt-dlp"""
    # For HTML pages, try HTML extraction first to avoid yt-dlp issues
    from urllib.parse import urlparse

    parsed = urlparse(url)
    is_html_page = parsed.path.lower().endswith(('.html', '.htm'))

    if is_html_page:
        if logger:
            logger('Detected HTML page, trying HTML extraction first...')
        html_result = _prefetch_html(url, logger=logger)
        if html_result and html_result.extracted_media_url:
            return html_result

    # Fall back to yt-dlp for non-HTML URLs or if HTML extraction failed
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }

    # Enable file:// URLs if needed
    if url.startswith('file://'):
        ydl_opts['enable_file_urls'] = True

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            # Check for playlist
            if 'entries' in info:
                raise PlaylistNotSupported('URL is a playlist, not supported')

            result = PrefetchResult()
            result.title = info.get('title', 'Untitled')
            result.description = info.get('description', '')
            result.author = info.get('uploader', '') or info.get('channel', '')
            result.duration_seconds = info.get('duration')
            result.extractor = info.get('extractor', '')
            result.external_id = info.get('id', '')
            result.webpage_url = info.get('webpage_url', url)

            # Check for video/audio streams
            formats = info.get('formats', [])
            result.has_video_streams = any(f.get('vcodec') != 'none' for f in formats)
            result.has_audio_streams = any(f.get('acodec') != 'none' for f in formats)

            if logger:
                logger(f'yt-dlp metadata extracted: {result.title}')
                logger(f'Extractor: {result.extractor}')
                logger(
                    f'Has video: {result.has_video_streams}, Has audio: {result.has_audio_streams}'
                )

            return result

    except yt_dlp.utils.DownloadError as e:
        # Try HTML extraction as fallback
        if logger:
            logger(f'yt-dlp failed: {str(e)}, trying HTML extraction')

        return _prefetch_html(url, logger=logger)


def _prefetch_html(url, logger=None):
    """
    Extract embedded media URL from an HTML page.

    This is a fallback for pages that yt-dlp doesn't recognize.
    Looks for <audio>, <video>, and <source> tags.
    """
    try:
        from media.html_extractor import extract_media_from_html_page

        extraction = extract_media_from_html_page(url)

        if not extraction['media_url']:
            raise Exception('No embedded media found in HTML')

        if logger:
            media_type_str = 'audio' if extraction['media_type'] == 'audio' else 'video'
            logger(f'Found {media_type_str} source: {extraction["media_url"]}')

        result = PrefetchResult()
        result.title = extraction['title']
        result.webpage_url = extraction['webpage_url']
        result.extracted_media_url = extraction['media_url']
        result.has_audio_streams = extraction['media_type'] == 'audio'
        result.has_video_streams = extraction['media_type'] == 'video'

        return result

    except Exception as e:
        raise Exception(f'HTML extraction failed: {str(e)}')


def get_media_type_from_extension(extension):
    """
    Determine if a file extension is audio or video.

    Args:
        extension: File extension (e.g., '.mp3', '.mp4')

    Returns:
        str: 'audio' or 'video'
    """
    if extension.lower() in AUDIO_EXTENSIONS:
        return 'audio'
    return 'video'


def resolve_media_type(requested_type, prefetch_result):
    """
    Determine the actual media type to download.

    Args:
        requested_type: 'auto', 'audio', or 'video'
        prefetch_result: PrefetchResult from prefetch()

    Returns:
        str: 'audio' or 'video'
    """
    if requested_type in ['audio', 'video']:
        # User explicitly requested a type
        return requested_type

    # Auto-detect based on available streams
    if requested_type == 'auto':
        if prefetch_result.has_video_streams:
            return 'video'
        elif prefetch_result.has_audio_streams:
            return 'audio'
        else:
            # Ambiguous, default to video
            return 'video'

    # Invalid requested_type, default to auto behavior
    if prefetch_result.has_video_streams:
        return 'video'
    else:
        return 'audio'
