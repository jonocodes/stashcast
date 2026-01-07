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
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
import yt_dlp
from django.conf import settings
from django.utils import timezone

from media.models import MediaItem
from media.progress_tracker import update_progress
from media.service.config import parse_ytdlp_extra_args
from media.service.process import (
    add_metadata_without_transcode,
    get_existing_metadata,
    process_subtitle,
    process_thumbnail,
)
from media.service.resolve import get_media_type_from_extension
from media.utils import ensure_unique_slug, generate_slug


def write_log(log_path, message):
    """Append message to log file with timestamp"""
    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'a') as f:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f'[{timestamp}] {message}\n')


def prefetch_direct(item, tmp_dir, log_path):
    """
    Prefetch metadata for direct URL.

    For direct media URLs, we use the filename as the title and
    determine the media type from the file extension.

    Args:
        item: MediaItem instance
        tmp_dir: Temporary directory path (unused, for consistency)
        log_path: Path to log file
    """
    # For direct URLs, use the filename as title
    parsed = urlparse(item.source_url)
    filename = Path(parsed.path).stem
    item.title = filename or 'downloaded-media'

    # Resolve media type based on extension
    if item.requested_type == MediaItem.REQUESTED_TYPE_AUTO:
        extension = Path(parsed.path).suffix
        media_type = get_media_type_from_extension(extension)
        item.media_type = media_type
    else:
        item.media_type = item.requested_type

    # Generate slug
    existing = (
        MediaItem.objects.filter(source_url=item.source_url, media_type=item.media_type)
        .exclude(guid=item.guid)
        .first()
    )
    slug = generate_slug(item.title)
    item.slug = ensure_unique_slug(slug, item.source_url, existing, item.media_type)

    # Set log path (relative) - will be in final directory after move
    item.log_path = 'download.log'

    item.save()
    write_log(log_path, f'Title: {item.title}')
    write_log(log_path, f'Media type: {item.media_type}')
    write_log(log_path, f'Slug: {item.slug}')


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
    Prefetch metadata using yt-dlp.

    Extracts title, description, author, duration, and other metadata
    from the URL using yt-dlp. Falls back to HTML extraction if yt-dlp fails.

    Args:
        item: MediaItem instance
        tmp_dir: Temporary directory path (unused, for consistency)
        log_path: Path to log file
    """
    # For HTML pages, try HTML extraction first to avoid yt-dlp issues
    from urllib.parse import urlparse

    parsed = urlparse(item.source_url)
    is_html_page = parsed.path.lower().endswith(('.html', '.htm'))

    if is_html_page:
        write_log(log_path, 'Detected HTML page, trying HTML extraction first...')
        media_url, detected_media_type, extracted_title = extract_media_from_html(item.source_url)

        if media_url:
            # Found embedded media - treat as direct download
            write_log(log_path, f'Found embedded media: {media_url}')

            # Update the source URL to the extracted media URL
            original_url = item.source_url
            item.source_url = media_url
            item.webpage_url = original_url

            # Determine media type
            if item.requested_type == MediaItem.REQUESTED_TYPE_AUTO:
                item.media_type = detected_media_type
            else:
                item.media_type = item.requested_type

            # Use extracted title from HTML
            item.title = extracted_title

            # Generate slug
            existing = (
                MediaItem.objects.filter(webpage_url=original_url, media_type=item.media_type)
                .exclude(guid=item.guid)
                .first()
            )
            slug = generate_slug(item.title)
            item.slug = ensure_unique_slug(slug, original_url, existing, item.media_type)

            # Set log path (relative) - will be in final directory after move
            item.log_path = 'download.log'

            item.save()
            write_log(log_path, f'HTML extractor found media: {media_url}')
            write_log(log_path, f'Original page: {original_url}')
            write_log(log_path, f'Title: {item.title}')
            write_log(log_path, f'Media type: {item.media_type}')
            write_log(log_path, f'Slug: {item.slug}')
            return  # Early return - don't use yt-dlp

    # Fall back to yt-dlp for non-HTML URLs or if HTML extraction failed
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(item.source_url, download=False)

            # Check for playlist
            if 'entries' in info:
                raise Exception('fetching playlist not supported')

            # Extract metadata
            item.title = info.get('title', 'Untitled')
            item.description = info.get('description', '')
            item.author = info.get('uploader', '') or info.get('channel', '')
            item.duration_seconds = info.get('duration')
            item.extractor = info.get('extractor', '')
            item.external_id = info.get('id', '')
            item.webpage_url = info.get('webpage_url', item.source_url)

            # Parse upload date
            if info.get('upload_date'):
                try:
                    upload_date = datetime.strptime(info['upload_date'], '%Y%m%d')
                    item.publish_date = timezone.make_aware(upload_date)
                except:
                    pass

            # Resolve media type
            if item.requested_type == MediaItem.REQUESTED_TYPE_AUTO:
                # Check if video streams exist
                formats = info.get('formats', [])
                has_video = any(f.get('vcodec') != 'none' for f in formats)
                item.media_type = (
                    MediaItem.MEDIA_TYPE_VIDEO if has_video else MediaItem.MEDIA_TYPE_AUDIO
                )
            else:
                item.media_type = item.requested_type

            # Generate slug
            existing = (
                MediaItem.objects.filter(source_url=item.source_url, media_type=item.media_type)
                .exclude(guid=item.guid)
                .first()
            )
            slug = generate_slug(item.title)
            item.slug = ensure_unique_slug(slug, item.source_url, existing, item.media_type)

            # Set log path (relative) - will be in final directory after move
            item.log_path = 'download.log'

            item.save()
            write_log(log_path, f'Extracting metadata from: {item.source_url}')
            write_log(log_path, f'Title: {item.title}')
            write_log(log_path, f'Media type: {item.media_type}')
            write_log(log_path, f'Slug: {item.slug}')
            write_log(log_path, f'Duration: {item.duration_seconds}s')

    except Exception as e:
        # Try HTML extractor as fallback
        write_log(log_path, f'yt-dlp extraction failed: {str(e)}')
        write_log(log_path, 'Attempting to extract media from HTML...')

        media_url, detected_media_type, extracted_title = extract_media_from_html(item.source_url)

        if media_url:
            # Found embedded media - treat as direct download
            write_log(log_path, f'Found embedded media: {media_url}')

            # Update the source URL to the extracted media URL
            original_url = item.source_url
            item.source_url = media_url
            item.webpage_url = original_url

            # Determine media type
            if item.requested_type == MediaItem.REQUESTED_TYPE_AUTO:
                item.media_type = detected_media_type
            else:
                item.media_type = item.requested_type

            # Use extracted title from HTML
            item.title = extracted_title

            # Generate slug
            existing = (
                MediaItem.objects.filter(webpage_url=original_url, media_type=item.media_type)
                .exclude(guid=item.guid)
                .first()
            )
            slug = generate_slug(item.title)
            item.slug = ensure_unique_slug(slug, original_url, existing, item.media_type)

            # Set log path (relative) - will be in final directory after move
            item.log_path = 'download.log'

            item.save()
            write_log(log_path, f'HTML extractor found media: {media_url}')
            write_log(log_path, f'Original page: {original_url}')
            write_log(log_path, f'Title: {item.title}')
            write_log(log_path, f'Media type: {item.media_type}')
            write_log(log_path, f'Slug: {item.slug}')
        else:
            # No media found in HTML either
            write_log(log_path, 'No embedded media found in HTML')
            raise Exception(f'yt-dlp failed and no embedded media found: {str(e)}')


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
    import json

    try:
        # Run ffprobe to get JSON metadata
        result = subprocess.run(
            [
                'ffprobe',
                '-v',
                'quiet',
                '-print_format',
                'json',
                '-show_format',
                '-show_streams',
                str(file_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        metadata = json.loads(result.stdout)

        # Extract duration (in seconds)
        if 'format' in metadata and 'duration' in metadata['format']:
            duration = float(metadata['format']['duration'])
            item.duration_seconds = int(duration)
            write_log(log_path, f'Duration: {int(duration)}s')

        # Extract title from format tags
        if 'format' in metadata and 'tags' in metadata['format']:
            tags = metadata['format']['tags']

            # Title (try various tag names)
            # Only update title if webpage_url is not set (i.e., not extracted from HTML)
            if not item.webpage_url:
                for tag_name in ['title', 'Title', 'TITLE']:
                    if tag_name in tags:
                        item.title = tags[tag_name]
                        write_log(log_path, f'Title: {item.title}')
                        break

            # Artist/Author (try various tag names)
            for tag_name in ['artist', 'Artist', 'ARTIST', 'author', 'Author']:
                if tag_name in tags:
                    item.author = tags[tag_name]
                    write_log(log_path, f'Author: {item.author}')
                    break

            # Album (could be useful)
            for tag_name in ['album', 'Album', 'ALBUM']:
                if tag_name in tags:
                    write_log(log_path, f'Album: {tags[tag_name]}')
                    break

        item.save()

    except subprocess.CalledProcessError as e:
        write_log(log_path, f'ffprobe error: {e}')
    except json.JSONDecodeError as e:
        write_log(log_path, f'Could not parse ffprobe output: {e}')
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
    # Determine file extension
    parsed = urlparse(item.source_url)
    ext = Path(parsed.path).suffix or '.mp4'

    # Determine content filename (relative)
    if item.media_type == MediaItem.MEDIA_TYPE_AUDIO:
        if ext == '.mp3':
            content_file = 'content.mp3'
        else:
            content_file = 'content.m4a'
    else:
        content_file = 'content.mp4'

    # Download to tmp directory
    content_path = tmp_dir / content_file

    write_log(log_path, f'Downloading to: {content_path}')

    # Download file
    response = requests.get(item.source_url, stream=True)
    response.raise_for_status()

    with open(content_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    # Store relative path (will be valid after move to final dir)
    item.content_path = content_file
    item.file_size = content_path.stat().st_size
    item.mime_type = response.headers.get('content-type', 'application/octet-stream')
    item.save()

    write_log(log_path, f'Downloaded {item.file_size} bytes')

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
    # Prepare yt-dlp options
    # Use simpler format specs that work better with HTML extraction
    # These fallback to 'best' which works with generic HTML5 video/audio elements
    if item.media_type == MediaItem.MEDIA_TYPE_AUDIO:
        format_spec = 'bestaudio/best'
        ytdlp_args = settings.STASHCAST_DEFAULT_YTDLP_ARGS_AUDIO
    else:
        # More lenient format spec that falls back gracefully for HTML extraction
        format_spec = 'bestvideo+bestaudio/best'
        ytdlp_args = settings.STASHCAST_DEFAULT_YTDLP_ARGS_VIDEO

    # Download directly to tmp directory
    temp_output = tmp_dir / 'download.%(ext)s'

    # Progress hook for yt-dlp
    def progress_hook(d):
        if d['status'] == 'downloading':
            # Extract download progress
            if 'downloaded_bytes' in d and 'total_bytes' in d:
                total = d['total_bytes']
                downloaded = d['downloaded_bytes']
                progress = int((downloaded / total) * 100)
                # Map to 10-40% range (PREFETCHING is 0-10%, DOWNLOADING is 10-40%)
                mapped_progress = 10 + int((progress / 100) * 30)
                update_progress(item.guid, MediaItem.STATUS_DOWNLOADING, mapped_progress)
        elif d['status'] == 'finished':
            # Download complete
            update_progress(item.guid, MediaItem.STATUS_DOWNLOADING, 40)

    ydl_opts = {
        'format': format_spec,
        'outtmpl': str(temp_output),
        'writethumbnail': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['en'],
        'noplaylist': True,
        'quiet': False,
        'progress_hooks': [progress_hook],
    }

    # Parse and apply extra args from settings
    ydl_opts = parse_ytdlp_extra_args(ytdlp_args, ydl_opts)

    write_log(log_path, f'Downloading with yt-dlp: {item.source_url}')
    write_log(log_path, f'Format: {ydl_opts.get("format")}')

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([item.source_url])

    # Rename files to fixed names
    files = list(tmp_dir.glob('download.*'))
    write_log(log_path, f'Downloaded {len(files)} files from yt-dlp')

    # Find main content file
    content_files = [
        f for f in files if f.suffix in ['.mp4', '.mkv', '.webm', '.mp3', '.m4a', '.ogg']
    ]
    if content_files:
        # Use the largest file as the main content
        downloaded_file = max(content_files, key=lambda f: f.stat().st_size)

        if item.media_type == MediaItem.MEDIA_TYPE_AUDIO:
            if downloaded_file.suffix == '.mp3':
                content_file = 'content.mp3'
            else:
                content_file = 'content.m4a'
        else:
            content_file = 'content.mp4'

        dest = tmp_dir / content_file
        shutil.move(str(downloaded_file), str(dest))
        item.content_path = content_file
        item.file_size = dest.stat().st_size
        write_log(log_path, f'Content renamed to: {content_file} ({item.file_size} bytes)')

    # Find and save thumbnail
    thumb_files = [
        f
        for f in files
        if f.suffix in ['.jpg', '.jpeg', '.png', '.webp'] and 'thumbnail' not in f.stem
    ]
    if not thumb_files:
        thumb_files = [f for f in files if f.suffix in ['.jpg', '.jpeg', '.png', '.webp']]

    if thumb_files:
        downloaded_file = thumb_files[0]
        dest = tmp_dir / f'thumbnail_temp{downloaded_file.suffix}'
        shutil.move(str(downloaded_file), str(dest))
        write_log(log_path, f'Thumbnail renamed to: thumbnail_temp{downloaded_file.suffix}')

    # Find and save subtitles
    subtitle_files = [f for f in files if f.suffix in ['.vtt', '.srt']]
    if subtitle_files:
        downloaded_file = subtitle_files[0]
        dest = tmp_dir / f'subtitles_temp{downloaded_file.suffix}'
        shutil.move(str(downloaded_file), str(dest))
        write_log(log_path, f'Subtitles renamed to: subtitles_temp{downloaded_file.suffix}')

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
                media_meta = get_existing_metadata(content_file)
                meta_title = media_meta.get('title')
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
