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
from media.service.process import (
    add_metadata_without_transcode,
    process_subtitle,
    process_thumbnail,
)
from media.service.media_info import extract_ffprobe_metadata, get_title_from_metadata
from media.service.resolve import (
    PlaylistNotSupported,
    prefetch as service_prefetch,
    resolve_media_type,
)
from media.utils import ensure_unique_slug, generate_slug


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
    Returns the original URL if an embedded media URL was extracted.
    """
    original_url = None

    if result.extracted_media_url:
        original_url = item.source_url
        item.source_url = result.extracted_media_url
        item.webpage_url = result.webpage_url or original_url
        write_log(log_path, f'HTML extractor found media: {item.source_url}')
        write_log(log_path, f'Original page: {item.webpage_url}')
    elif result.webpage_url:
        item.webpage_url = result.webpage_url

    item.title = result.title or 'content'
    item.description = result.description or ''
    item.author = result.author or ''
    item.duration_seconds = result.duration_seconds
    item.extractor = result.extractor or ''
    item.external_id = result.external_id or ''

    item.media_type = resolve_media_type(item.requested_type, result)

    if original_url:
        existing_item = (
            MediaItem.objects.filter(webpage_url=original_url, media_type=item.media_type)
            .exclude(guid=item.guid)
            .first()
        )
        slug_source = original_url
    else:
        existing_item = (
            MediaItem.objects.filter(source_url=item.source_url, media_type=item.media_type)
            .exclude(guid=item.guid)
            .first()
        )
        slug_source = item.source_url

    slug = generate_slug(item.title)
    item.slug = ensure_unique_slug(slug, slug_source, existing_item, item.media_type)
    item.log_path = 'download.log'
    item.save()

    write_log(log_path, f'Title: {item.title}')
    write_log(log_path, f'Media type: {item.media_type}')
    write_log(log_path, f'Slug: {item.slug}')
    if item.duration_seconds:
        write_log(log_path, f'Duration: {item.duration_seconds}s')

    return original_url


def _prefetch_with_strategy(item, strategy, log_path):
    """Shared prefetch implementation backed by service.resolve."""
    try:
        result = service_prefetch(
            item.source_url, strategy, logger=lambda m: write_log(log_path, m)
        )
    except PlaylistNotSupported as e:
        raise Exception(str(e))

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


def extract_media_from_html(url):
    """
    Extract embedded media URL from an HTML page.

    This is a fallback for pages that yt-dlp doesn't recognize.
    Looks for <audio>, <video>, and <source> tags.

    Args:
        url: URL of the HTML page

    Returns:
        tuple: (media_url, media_type, title) or (None, None, None) if no media found
    """
    try:
        from media.html_extractor import extract_media_from_html_page

        result = extract_media_from_html_page(url)
        return (result['media_url'], result['media_type'], result['title'])

    except Exception:
        # Return None if extraction fails
        return (None, None, None)


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

    if item.media_type == MediaItem.MEDIA_TYPE_AUDIO:
        content_file = 'content.mp3' if ext == '.mp3' else 'content.m4a'
    else:
        content_file = 'content.mp4'

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

    if item.media_type == MediaItem.MEDIA_TYPE_AUDIO:
        content_file = 'content.mp3' if download_info.extension == '.mp3' else 'content.m4a'
    else:
        content_file = 'content.mp4'

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


def process_files(item, tmp_dir, log_path):
    """
    Process downloaded files in tmp directory.

    - Embeds metadata into content file
    - Converts thumbnail to PNG
    - Converts subtitles to VTT
    - Sets MIME type
    - Transcodes if needed (with progress tracking)

    Args:
        item: MediaItem instance
        tmp_dir: Temporary directory path
        log_path: Path to log file
    """

    # Add metadata to content file
    if item.content_path:
        content_file = tmp_dir / item.content_path
        if content_file.exists():
            # If title is still a generic fallback, try to read from media metadata
            if item.title in ('content', 'downloaded-media', 'untitled', None):
                meta_title = get_title_from_metadata(content_file)
                if meta_title:
                    item.title = meta_title
                    write_log(log_path, f'Updated title from media metadata: {meta_title}')
                else:
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

            # Create metadata dict
            metadata = {}
            if item.title:
                metadata['title'] = item.title
            if item.author:
                metadata['author'] = item.author
            if item.description:
                metadata['description'] = item.description

            # If we have metadata, embed it using the centralized service
            if metadata:
                try:
                    # Use proper extension for temp file so ffmpeg can detect format
                    temp_file = (
                        content_file.parent / f'{content_file.stem}_tmp{content_file.suffix}'
                    )

                    # Use centralized metadata embedding from service.process
                    add_metadata_without_transcode(
                        content_file,
                        temp_file,
                        metadata=metadata,
                        logger=lambda msg: write_log(log_path, msg),
                    )

                    # Replace original with metadata-embedded version
                    if temp_file.exists():
                        temp_file.replace(content_file)
                        write_log(log_path, 'Metadata embedded successfully')
                except Exception as e:
                    write_log(
                        log_path,
                        f'Metadata embedding error: {type(e).__name__}: {str(e)}',
                    )
                    # Clean up temp file if it exists
                    if 'temp_file' in locals() and temp_file.exists():
                        temp_file.unlink()

    # Process thumbnail
    for thumb_file in tmp_dir.glob('thumbnail_temp*'):
        png_path = tmp_dir / 'thumbnail.png'
        try:
            # Use centralized thumbnail processing
            process_thumbnail(thumb_file, png_path, logger=lambda msg: write_log(log_path, msg))
            item.thumbnail_path = 'thumbnail.png'
            thumb_file.unlink()
        except Exception as e:
            write_log(log_path, f'Thumbnail conversion failed: {e}')

    # Process subtitles - convert to VTT
    for sub_file in tmp_dir.glob('subtitles_temp*'):
        vtt_path = tmp_dir / 'subtitles.vtt'
        try:
            # Use centralized subtitle processing
            process_subtitle(sub_file, vtt_path, logger=lambda msg: write_log(log_path, msg))
            item.subtitle_path = 'subtitles.vtt'
            sub_file.unlink()
        except Exception as e:
            write_log(log_path, f'Subtitle processing failed: {e}')

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
