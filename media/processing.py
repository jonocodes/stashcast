"""
Django-specific media processing functions.

This module contains functions that bridge between the service layer
and Django models. These functions are used by both:
- Huey background tasks (media/tasks.py)
- CLI commands (manage.py stash)

All functions work with MediaItem model instances and handle:
- Metadata prefetching
- File downloading
- Processing (thumbnails, subtitles, metadata embedding)
- Slug generation and database updates
"""

import os
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings

from media.models import MediaItem
from media.service.download import download_direct as service_download_direct
from media.service.download import download_file as service_download_file
from media.service.download import download_ytdlp as service_download_ytdlp
# Note: add_metadata_without_transcode, process_subtitle, and process_thumbnail
# from media.service.process are no longer needed since yt-dlp handles these with
# --embed-metadata, --convert-thumbnails png, and --convert-subs vtt flags
from media.service.media_info import (
    extract_ffprobe_metadata,
    get_output_extension,
    resolve_title_from_metadata,
)
from media.service.resolve import (
    MultipleItemsDetected,
    PlaylistNotSupported,
    prefetch as service_prefetch,
    resolve_media_type,
)
from media.utils import ensure_unique_slug, generate_slug, log_prefetch_result, select_existing_item


def write_log(log_path, message):
    """Append message to log file with timestamp"""
    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'a') as f:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f'[{timestamp}] {message}\n')


def _apply_prefetch_result(item, result, log_path):
    """
    Apply a PrefetchResult to a MediaItem and persist metadata.
    """
    if result.webpage_url:
        item.webpage_url = result.webpage_url

    item.title = result.title or 'content'
    item.description = result.description or ''
    item.author = result.author or ''
    item.duration_seconds = result.duration_seconds
    item.extractor = result.extractor or ''
    item.external_id = result.external_id or ''

    item.media_type = resolve_media_type(item.requested_type, result)

    existing_item = select_existing_item(
        item.source_url,
        item.webpage_url,
        item.media_type,
        exclude_guid=item.guid,
    )

    slug = generate_slug(item.title)
    item.slug = ensure_unique_slug(slug, item.source_url, existing_item, item.media_type)
    item.log_path = 'download.log'
    item.save()

    log_prefetch_result(lambda m: write_log(log_path, m), item)


def _prefetch_with_strategy(item, strategy, log_path):
    """Shared prefetch implementation backed by service.resolve."""
    try:
        result = service_prefetch(
            item.source_url, strategy, logger=lambda m: write_log(log_path, m)
        )
    except PlaylistNotSupported as e:
        raise Exception(str(e))

    # Check for multi-item results (playlists, channels, multi-embed pages)
    if result.is_multiple:
        count = len(result.entries)
        raise MultipleItemsDetected(
            message=(
                f'Found {count} items in this URL (playlist, channel, or page with multiple '
                f'videos). Use the admin interface to confirm downloading all items, or use '
                f'CLI with --allow-multiple.'
            ),
            entries=result.entries,
            playlist_title=result.playlist_title,
        )

    _apply_prefetch_result(item, result, log_path)


def prefetch_direct(item, tmp_dir, log_path):
    """
    Prefetch metadata for direct URL.

    Args:
        item: MediaItem instance
        tmp_dir: Temporary directory path (unused, for consistency)
        log_path: Path to log file
    """
    _prefetch_with_strategy(item, 'direct', log_path)


def prefetch_file(item, tmp_dir, log_path):
    """
    Prefetch metadata for local file path.

    Args:
        item: MediaItem instance
        tmp_dir: Temporary directory path (unused, for consistency)
        log_path: Path to log file
    """
    _prefetch_with_strategy(item, 'file', log_path)


def prefetch_ytdlp(item, tmp_dir, log_path):
    """
    Prefetch metadata using yt-dlp (with HTML extraction fallback).

    Args:
        item: MediaItem instance
        tmp_dir: Temporary directory path (unused, for consistency)
        log_path: Path to log file
    """
    _prefetch_with_strategy(item, 'ytdlp', log_path)


def extract_metadata_with_ffprobe(item, file_path, log_path):
    """
    Extract metadata from media file using ffprobe.

    Extracts duration, title, artist/author, and other metadata from
    the media file itself.

    Args:
        item: MediaItem instance
        file_path: Path to the media file
        log_path: Path to log file
    """
    try:
        metadata = extract_ffprobe_metadata(file_path)
        if not metadata:
            write_log(log_path, 'ffprobe returned no metadata')
            return

        # Extract duration (in seconds)
        duration = metadata.get('duration_seconds')
        if duration:
            item.duration_seconds = duration
            write_log(log_path, f'Duration: {duration}s')

        tags = metadata.get('tags', {}) or {}

        # Title from tags (only if not extracted from HTML)
        if not item.webpage_url:
            title = tags.get('title')
            if title:
                item.title = title
                write_log(log_path, f'Title: {item.title}')

        # Artist/Author
        author = tags.get('artist') or tags.get('author')
        if author:
            item.author = author
            write_log(log_path, f'Author: {item.author}')

        album = tags.get('album')
        if album:
            write_log(log_path, f'Album: {album}')

        item.save()

    except Exception as e:
        write_log(log_path, f'Unexpected error extracting metadata: {e}')


def download_direct(item, tmp_dir, log_path):
    """
    Download media directly via HTTP.

    Downloads the file using HTTP streaming and saves it to the tmp directory
    with a fixed filename (content.mp3, content.m4a, or content.mp4).

    Args:
        item: MediaItem instance
        tmp_dir: Temporary directory path
        log_path: Path to log file
    """
    parsed = urlparse(item.source_url)
    ext = Path(parsed.path).suffix or '.mp4'

    content_ext = get_output_extension(item.media_type, ext)
    content_file = f'content{content_ext}'

    content_path = tmp_dir / content_file

    if Path(item.source_url).exists():
        download_info = service_download_file(
            item.source_url,
            content_path,
            logger=lambda msg: write_log(log_path, msg),
        )
    else:
        download_info = service_download_direct(
            item.source_url,
            content_path,
            logger=lambda msg: write_log(log_path, msg),
        )

    # Store relative path (will be valid after move to final dir)
    item.content_path = content_file
    item.file_size = download_info.file_size
    item.mime_type = download_info.mime_type or 'application/octet-stream'
    item.save()

    # Extract metadata using ffprobe
    try:
        write_log(log_path, 'Extracting metadata with ffprobe...')
        extract_metadata_with_ffprobe(item, content_path, log_path)
    except Exception as e:
        write_log(log_path, f'Could not extract metadata: {e}')


def _apply_download_info(item, tmp_dir, download_info, log_path):
    """Normalize download outputs into fixed filenames and item fields."""
    content_ext = get_output_extension(item.media_type, download_info.extension)
    content_file = f'content{content_ext}'

    dest = tmp_dir / content_file
    shutil.move(str(download_info.path), str(dest))
    item.content_path = content_file
    item.file_size = dest.stat().st_size
    write_log(log_path, f'Content renamed to: {content_file} ({item.file_size} bytes)')

    if download_info.thumbnail_path:
        thumb_dest = tmp_dir / f'thumbnail_temp{download_info.thumbnail_path.suffix}'
        shutil.move(str(download_info.thumbnail_path), str(thumb_dest))
        write_log(
            log_path, f'Thumbnail renamed to: thumbnail_temp{download_info.thumbnail_path.suffix}'
        )

    if download_info.subtitle_path:
        sub_dest = tmp_dir / f'subtitles_temp{download_info.subtitle_path.suffix}'
        shutil.move(str(download_info.subtitle_path), str(sub_dest))
        write_log(
            log_path, f'Subtitles renamed to: subtitles_temp{download_info.subtitle_path.suffix}'
        )

    item.save()


def download_ytdlp(item, tmp_dir, log_path):
    """
    Download media using yt-dlp.

    Downloads the media file, thumbnail, and subtitles using yt-dlp.
    Files are renamed to fixed names for consistency.

    Args:
        item: MediaItem instance
        tmp_dir: Temporary directory path
        log_path: Path to log file
    """
    ytdlp_args = (
        settings.STASHCAST_DEFAULT_YTDLP_ARGS_AUDIO
        if item.media_type == MediaItem.MEDIA_TYPE_AUDIO
        else settings.STASHCAST_DEFAULT_YTDLP_ARGS_VIDEO
    )

    download_info = service_download_ytdlp(
        item.source_url,
        item.media_type,
        tmp_dir,
        ytdlp_extra_args=ytdlp_args,
        logger=lambda msg: write_log(log_path, msg),
    )

    _apply_download_info(item, tmp_dir, download_info, log_path)


def process_files(item, tmp_dir, log_path):
    """
    Process downloaded files in tmp directory.

    Note: yt-dlp now handles metadata embedding, thumbnail conversion, and subtitle
    conversion automatically with --embed-metadata, --convert-thumbnails png, and
    --convert-subs vtt flags. This function now just verifies files and updates
    database paths.

    Args:
        item: MediaItem instance
        tmp_dir: Temporary directory path
        log_path: Path to log file
    """

    # Check if content file exists and update title from metadata if needed
    if item.content_path:
        content_file = tmp_dir / item.content_path
        if content_file.exists():
            # If title is still a generic fallback, try to read from media metadata
            # yt-dlp should have already embedded metadata, so check if it's there
            resolved_title = resolve_title_from_metadata(item.title, content_file)
            if resolved_title and resolved_title != item.title:
                item.title = resolved_title
                write_log(log_path, f'Updated title from embedded metadata: {resolved_title}')
                # Update slug to match the resolved title
                new_slug = generate_slug(item.title)
                if new_slug and new_slug != item.slug:
                    item.slug = ensure_unique_slug(new_slug, item.source_url, None, item.media_type)
                    write_log(log_path, f'Updated slug: {item.slug}')
                item.save()
            elif item.title in ('content', 'downloaded-media', 'untitled', None):
                filename_title = content_file.stem
                if filename_title:
                    item.title = filename_title
                    write_log(log_path, f'Updated title from filename: {filename_title}')

                # Update slug to match the resolved title
                if item.title:
                    new_slug = generate_slug(item.title)
                    if new_slug and new_slug != item.slug:
                        item.slug = ensure_unique_slug(
                            new_slug, item.source_url, None, item.media_type
                        )
                        write_log(log_path, f'Updated slug: {item.slug}')
                item.save()

            write_log(
                log_path,
                'Metadata already embedded by yt-dlp (--embed-metadata, --embed-thumbnail)',
            )

    # Look for thumbnail files - yt-dlp converts them to PNG automatically
    # Check for both thumbnail_temp* (from download.py renaming) and direct thumbnail.png
    thumb_file = None
    for pattern in ['thumbnail_temp*.png', 'thumbnail.png', 'thumbnail_temp*']:
        matches = list(tmp_dir.glob(pattern))
        if matches:
            thumb_file = matches[0]
            break

    if thumb_file and thumb_file.exists():
        # If it's not already named thumbnail.png, rename it
        if thumb_file.name != 'thumbnail.png':
            final_thumb = tmp_dir / 'thumbnail.png'
            shutil.move(str(thumb_file), str(final_thumb))
            write_log(log_path, f'Thumbnail found and renamed: {thumb_file.name} -> thumbnail.png')
        else:
            write_log(log_path, 'Thumbnail found: thumbnail.png')
        item.thumbnail_path = 'thumbnail.png'

    # Look for subtitle files - yt-dlp converts them to VTT automatically
    # Check for both subtitles_temp* (from download.py renaming) and direct subtitles.vtt
    sub_file = None
    for pattern in ['subtitles_temp*.vtt', 'subtitles.vtt', 'subtitles_temp*']:
        matches = list(tmp_dir.glob(pattern))
        if matches:
            sub_file = matches[0]
            break

    if sub_file and sub_file.exists():
        # If it's not already named subtitles.vtt, rename it
        if sub_file.name != 'subtitles.vtt':
            final_sub = tmp_dir / 'subtitles.vtt'
            shutil.move(str(sub_file), str(final_sub))
            write_log(log_path, f'Subtitles found and renamed: {sub_file.name} -> subtitles.vtt')
        else:
            write_log(log_path, 'Subtitles found: subtitles.vtt')
        item.subtitle_path = 'subtitles.vtt'
        write_log(log_path, 'Subtitles embedded in video by yt-dlp (--embed-subs for video)')

    # Determine MIME type
    if item.content_path:
        content_file = Path(item.content_path)
        if content_file.suffix == '.mp3':
            item.mime_type = 'audio/mpeg'
        elif content_file.suffix == '.m4a':
            item.mime_type = 'audio/mp4'
        elif content_file.suffix == '.mp4':
            item.mime_type = 'video/mp4'
        else:
            item.mime_type = 'application/octet-stream'

    item.save()
    write_log(log_path, 'Processing complete')
