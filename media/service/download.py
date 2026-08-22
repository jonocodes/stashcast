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

from media.service.config import (
    merge_extractor_args,
    parse_cookies_from_browser,
    parse_impersonate_target,
    parse_js_runtimes,
    parse_ytdlp_extra_args,
)


@dataclass
class DownloadedFileInfo:
    """Information about a downloaded file"""

    path: Path
    file_size: int
    extension: str
    mime_type: Optional[str] = None
    thumbnail_path: Optional[Path] = None
    subtitle_path: Optional[Path] = None


def apply_network_opts(ydl_opts, logger=None):
    """
    Apply the network-related settings shared by every yt-dlp call.

    Covers proxy, cookies and retry behaviour so that a fix configured once
    applies to prefetch, single downloads and batch downloads alike.

    Args:
        ydl_opts: yt-dlp options dict (modified in place)
        logger: Optional callable(str) for logging

    Returns:
        dict: The updated options dict
    """

    def log(message):
        if logger:
            logger(message)

    # Proxy (needed for cloud VMs where YouTube blocks datacenter IP ranges)
    if settings.STASHCAST_YTDLP_PROXY:
        ydl_opts['proxy'] = settings.STASHCAST_YTDLP_PROXY

    # Cookies from a logged-in session: the most reliable fix for 403 Forbidden
    cookies_file = settings.STASHCAST_YTDLP_COOKIES_FILE
    if cookies_file:
        if Path(cookies_file).is_file():
            ydl_opts['cookiefile'] = cookies_file
            log(f'Using cookies file: {cookies_file}')
        else:
            log(f'WARNING: cookies file not found, ignoring: {cookies_file}')

    if settings.STASHCAST_YTDLP_COOKIES_FROM_BROWSER:
        ydl_opts['cookiesfrombrowser'] = parse_cookies_from_browser(
            settings.STASHCAST_YTDLP_COOKIES_FROM_BROWSER
        )
        log(f'Using browser cookies: {settings.STASHCAST_YTDLP_COOKIES_FROM_BROWSER}')

    # JavaScript runtime override (yt-dlp finds 'deno' on PATH on its own)
    if settings.STASHCAST_YTDLP_JS_RUNTIMES:
        ydl_opts['js_runtimes'] = parse_js_runtimes(settings.STASHCAST_YTDLP_JS_RUNTIMES)

    # Browser TLS/HTTP fingerprint (requires curl_cffi to be installed)
    if settings.STASHCAST_YTDLP_IMPERSONATE:
        ydl_opts['impersonate'] = parse_impersonate_target(settings.STASHCAST_YTDLP_IMPERSONATE)

    # Retries: expiring stream URLs and rate limits often surface as a one-off 403
    ydl_opts.setdefault('retries', settings.STASHCAST_YTDLP_RETRIES)
    ydl_opts.setdefault('fragment_retries', settings.STASHCAST_YTDLP_FRAGMENT_RETRIES)
    ydl_opts.setdefault('extractor_retries', settings.STASHCAST_YTDLP_EXTRACTOR_RETRIES)

    return ydl_opts


def _is_forbidden_error(exc):
    """Return True when the exception looks like an HTTP 403 from the media host."""
    message = str(exc)
    return '403' in message or 'Forbidden' in message


def _player_client_chain():
    """
    Return the YouTube player clients to try, in order.

    The literal 'default' means "leave the choice to yt-dlp"; every other entry is
    applied as --extractor-args youtube:player_client=<client>.
    """
    clients = [
        client.strip()
        for client in (settings.STASHCAST_YTDLP_PLAYER_CLIENTS or '').split(',')
        if client.strip()
    ]
    return clients or ['default']


def _has_explicit_player_client(ydl_opts):
    """True when the user already pinned a player_client via extra args."""
    return bool(ydl_opts.get('extractor_args', {}).get('youtube', {}).get('player_client'))


def run_ytdlp_with_fallback(build_opts, run, url_label='', logger=None):
    """
    Run a yt-dlp operation, retrying with alternative YouTube player clients on 403.

    YouTube hands out stream URLs that are tied to the player client used during
    extraction. When the chosen client's URLs require a PO token the extraction
    still succeeds but the actual media download fails with 403 Forbidden. Retrying
    with a different client (and a cleared player cache) works around it.

    Args:
        build_opts: Callable returning a fresh yt-dlp options dict per attempt
        run: Callable(ydl_opts) performing the work and returning its result
        url_label: Optional string describing what is being downloaded (for logs)
        logger: Optional callable(str) for logging

    Returns:
        Whatever `run` returns.
    """

    def log(message):
        if logger:
            logger(message)

    clients = _player_client_chain()
    last_error = None

    for attempt, client in enumerate(clients):
        ydl_opts = build_opts()

        # Never override an explicit player_client coming from the settings
        if _has_explicit_player_client(ydl_opts):
            if attempt > 0:
                break
        elif client != 'default':
            merge_extractor_args(ydl_opts, {'youtube': {'player_client': [client]}})

        if attempt > 0:
            # Stale cached player JS is another source of 403s.
            # rm_cachedir is a CLI-only flag, so the cache has to be cleared by hand.
            with yt_dlp.YoutubeDL({'quiet': True}) as cache_ydl:
                cache_ydl.cache.remove()
            log(
                f'Retry {attempt}/{len(clients) - 1} after 403 Forbidden'
                f' using player_client={client}' + (f' for {url_label}' if url_label else '')
            )

        try:
            return run(ydl_opts)
        except Exception as e:
            if not _is_forbidden_error(e):
                raise
            last_error = e
            log(f'Attempt {attempt + 1} failed with 403 Forbidden: {e}')

    raise last_error


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

    def build_opts():
        ydl_opts = {
            'format': format_spec,
            'outtmpl': str(temp_output),
            'writethumbnail': True,
            'writesubtitles': settings.STASHCAST_WRITE_SUBTITLES,
            'writeautomaticsub': settings.STASHCAST_WRITE_AUTOMATION_SUBTITLES,
            'subtitleslangs': [settings.STASHCAST_SUBTITLE_LANGUAGE],
            # Note: noplaylist removed to allow multi-item downloads
            # Multi-item handling is done at prefetch stage with --allow-multiple flag
            'quiet': not logger,  # Show output if logger is provided
        }

        # Enable file:// URLs if needed
        if url.startswith('file://'):
            ydl_opts['enable_file_urls'] = True

        # Proxy, cookies and retry settings shared by all yt-dlp calls
        apply_network_opts(ydl_opts, logger=logger)

        # Parse and apply extra args from settings
        return parse_ytdlp_extra_args(ytdlp_extra_args, ydl_opts)

    log(f'Downloading with yt-dlp {yt_dlp.version.__version__}: {url}')
    log(f'Format: {build_opts().get("format")}')

    # temp_dir is shared with the caller (it holds download.log and any prefetch
    # artefacts), so only files this function creates may be cleaned up on a retry
    preexisting = {f.name for f in temp_dir.iterdir()}

    def run(ydl_opts):
        # Drop leftovers from a failed attempt so a retry cannot resume a
        # partial file that belongs to a different format
        for leftover in temp_dir.iterdir():
            if leftover.name not in preexisting and leftover.is_file():
                leftover.unlink()

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

    run_ytdlp_with_fallback(build_opts, run, url_label=url, logger=logger)

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

    # Proxy, cookies and retry settings shared by all yt-dlp calls
    apply_network_opts(ydl_opts, logger=logger)

    log(f'Batch prefetching {len(urls)} URLs with yt-dlp {yt_dlp.version.__version__}')

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
        'writesubtitles': settings.STASHCAST_WRITE_SUBTITLES,
        'writeautomaticsub': settings.STASHCAST_WRITE_AUTOMATION_SUBTITLES,
        'subtitleslangs': [settings.STASHCAST_SUBTITLE_LANGUAGE],
        'quiet': not logger,
        'ignoreerrors': True,
        'noplaylist': True,
    }

    # Proxy, cookies and retry settings shared by all yt-dlp calls
    apply_network_opts(ydl_opts, logger=logger)

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

    # Single download call for all URLs.
    # ignoreerrors keeps one broken URL from aborting the batch, so a 403 shows up
    # as a missing output folder rather than an exception. Failed URLs are retried
    # below with the alternative player clients.
    with yt_dlp.YoutubeDL(dict(ydl_opts)) as ydl:
        ydl.download(urls)

    log(f'Download complete, processing {len(url_to_id)} results')

    def has_media(url):
        """True when the URL produced a usable media file on disk."""
        video_id = url_to_id.get(url)
        if not video_id:
            return False
        folder = temp_dir / video_id
        if not folder.exists():
            return False
        return any(
            f.suffix in ['.mp4', '.mkv', '.webm', '.mp3', '.m4a', '.ogg', '.opus']
            for f in folder.iterdir()
        )

    # Retry whatever did not produce a file, one alternative player client per round.
    # Skipped when the settings already pin a player_client explicitly.
    fallback_clients = [] if _has_explicit_player_client(ydl_opts) else _player_client_chain()[1:]
    for client in fallback_clients:
        failed = [url for url in urls if not has_media(url)]
        if not failed:
            break

        log(f'Retrying {len(failed)} failed URLs with player_client={client}')
        retry_opts = dict(ydl_opts)
        retry_opts['extractor_args'] = {}
        merge_extractor_args(retry_opts, ydl_opts.get('extractor_args', {}))
        merge_extractor_args(retry_opts, {'youtube': {'player_client': [client]}})

        # rm_cachedir is a CLI-only flag, so the cache has to be cleared by hand
        with yt_dlp.YoutubeDL({'quiet': True}) as cache_ydl:
            cache_ydl.cache.remove()

        with yt_dlp.YoutubeDL(retry_opts) as ydl:
            ydl.download(failed)

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
