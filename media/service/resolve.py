"""
Metadata extraction and media type resolution.

Handles prefetching metadata and determining the actual media type.
"""

from dataclasses import dataclass, field
from typing import Optional, List
from urllib.parse import urlparse
from pathlib import Path
import yt_dlp
from django.conf import settings

from media.service.media_info import get_streams_from_extension
from media.service.constants import MEDIA_EXTENSIONS


class PlaylistNotSupported(Exception):
    """Raised when URL points to a playlist/multi-file and allow_multiple is False"""

    pass


class MultipleItemsDetected(Exception):
    """
    Raised when multiple items are detected and allow_multiple is False.

    Includes information about the entries for display to users.
    """

    def __init__(self, message: str, entries: list, playlist_title: Optional[str] = None):
        super().__init__(message)
        self.entries = entries
        self.playlist_title = playlist_title
        self.count = len(entries)


@dataclass
class EntryInfo:
    """Information about a single entry in a multi-item result"""

    url: str
    title: Optional[str] = None
    duration_seconds: Optional[int] = None
    thumbnail_url: Optional[str] = None


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
    # Multi-item support
    entries: List[EntryInfo] = field(default_factory=list)
    is_multiple: bool = False
    playlist_title: Optional[str] = None


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
    result.has_audio_streams, result.has_video_streams = get_streams_from_extension(ext)

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
    result.has_audio_streams, result.has_video_streams = get_streams_from_extension(ext)

    if logger:
        logger(f'Direct URL detected: {url}')
        logger(f'Filename: {result.title}')
        logger(f'Extension: {ext}')

    return result


def _prefetch_ytdlp(url, logger=None):
    """Prefetch metadata using yt-dlp"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }

    # Enable file:// URLs if needed
    if url.startswith('file://'):
        ydl_opts['enable_file_urls'] = True

    # Add cookies file if configured (needed for cloud VMs where YouTube blocks requests)
    if settings.STASHCAST_YTDLP_COOKIES_FILE:
        ydl_opts['cookiefile'] = settings.STASHCAST_YTDLP_COOKIES_FILE

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

        result = PrefetchResult()

        # Check for playlist/multi-item result
        if 'entries' in info:
            entries_list = list(info.get('entries', []))
            result.is_multiple = True
            result.playlist_title = info.get('title', 'Untitled Playlist')

            # Extract info for each entry
            for entry in entries_list:
                if entry is None:
                    continue
                # Determine the best URL for this entry
                # For generic extractor with embedded media, 'url' is the direct media URL
                # For platforms like YouTube, 'webpage_url' is the video page URL
                entry_url = entry.get('url', '')
                entry_webpage_url = entry.get('webpage_url', '')

                # Prefer direct media URL if it ends with a media extension
                if entry_url and any(entry_url.lower().endswith(ext) for ext in MEDIA_EXTENSIONS):
                    best_url = entry_url
                elif entry_webpage_url:
                    best_url = entry_webpage_url
                else:
                    best_url = entry_url

                entry_info = EntryInfo(
                    url=best_url,
                    title=entry.get('title', 'Untitled'),
                    duration_seconds=entry.get('duration'),
                    thumbnail_url=entry.get('thumbnail'),
                )
                result.entries.append(entry_info)

            # Use playlist metadata for the result
            result.title = result.playlist_title
            result.description = info.get('description', '')
            result.author = info.get('uploader', '') or info.get('channel', '')
            result.extractor = info.get('extractor', '')
            result.webpage_url = info.get('webpage_url', url)

            if logger:
                logger(f'Multi-item URL detected: {result.playlist_title}')
                logger(f'Found {len(result.entries)} items')

            return result

        # Single item result
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

        # Fallback: check top-level codec info (used by some extractors like ApplePodcasts)
        if not result.has_video_streams and not result.has_audio_streams:
            result.has_video_streams = info.get('vcodec') not in (None, 'none')
            result.has_audio_streams = info.get('acodec') not in (None, 'none')

        if logger:
            logger(f'yt-dlp metadata extracted: {result.title}')
            logger(f'Extractor: {result.extractor}')
            logger(f'Has video: {result.has_video_streams}, Has audio: {result.has_audio_streams}')

        return result


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


def check_multiple_items(prefetch_result, allow_multiple=False, source='cli'):
    """
    Check if prefetch result contains multiple items and handle accordingly.

    Args:
        prefetch_result: PrefetchResult from prefetch()
        allow_multiple: If True, allow multiple items
        source: Source of the request for actionable error messages
                ('cli', 'api', 'admin')

    Raises:
        MultipleItemsDetected: If multiple items found and not allowed
    """
    if not prefetch_result.is_multiple:
        return

    count = len(prefetch_result.entries)

    if allow_multiple:
        return

    # Build actionable error message based on source
    if source == 'cli':
        action_hint = 'Run again with --allow-multiple to download all items.'
    elif source == 'api':
        action_hint = (
            'Add allow_multiple=true parameter to proceed, or use the admin interface to confirm.'
        )
    else:  # admin or other
        action_hint = 'Use the confirmation page to proceed with all items.'

    message = (
        f'Found {count} items in this URL (playlist, channel, or page with multiple videos). '
        f'{action_hint}'
    )

    raise MultipleItemsDetected(
        message=message,
        entries=prefetch_result.entries,
        playlist_title=prefetch_result.playlist_title,
    )
