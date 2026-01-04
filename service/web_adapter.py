"""
Web adapter for Django integration.

Bridges between Django models (media.models.MediaItem) and the service layer,
allowing the web app to use the same core logic as the CLI.
"""
from pathlib import Path
from django.utils import timezone

from service.transcode_service import transcode_url_to_dir
from service.config import get_audio_dir, get_video_dir


def process_media_item(item, log_callback=None):
    """
    Process a MediaItem using the service layer.

    This is the main entry point for web app processing. It:
    1. Calls the service layer to download and process media
    2. Updates the MediaItem with results
    3. Manages status transitions

    Args:
        item: MediaItem instance to process
        log_callback: Optional function(message) for logging

    Returns:
        TranscodeResult from service layer

    Raises:
        Exception: If processing fails (caller should handle and update item.status)
    """
    # Determine output directory based on media type
    base_dir = item.get_base_dir()
    base_dir.mkdir(parents=True, exist_ok=True)

    # Update status to PREFETCHING
    item.status = item.STATUS_PREFETCHING
    item.save()

    # Call service layer to do all the work
    result = transcode_url_to_dir(
        url=item.source_url,
        outdir=base_dir,
        requested_type=item.requested_type or 'auto',
        verbose=log_callback is not None
    )

    # Map service layer results back to MediaItem fields
    item.title = result.title
    item.slug = result.slug
    item.media_type = result.resolved_type

    # Store relative paths (filename only, relative to base_dir)
    item.content_path = result.output_path.name

    if result.thumbnail_path:
        item.thumbnail_path = result.thumbnail_path.name

    if result.subtitle_path:
        item.subtitle_path = result.subtitle_path.name

    # Set file metadata
    item.file_size = result.file_size

    # Determine MIME type from extension
    ext = result.output_path.suffix.lower()
    mime_type_map = {
        '.mp3': 'audio/mpeg',
        '.m4a': 'audio/mp4',
        '.mp4': 'video/mp4',
        '.webm': 'video/webm',
        '.ogg': 'audio/ogg',
    }
    item.mime_type = mime_type_map.get(ext, 'application/octet-stream')

    # Mark as ready
    item.status = item.STATUS_READY
    item.downloaded_at = timezone.now()
    item.save()

    return result


def get_media_directory(media_type):
    """
    Get the media directory for a given type.

    Args:
        media_type: 'audio' or 'video'

    Returns:
        Path: Directory path for the media type
    """
    if media_type == 'audio':
        return Path(get_audio_dir())
    elif media_type == 'video':
        return Path(get_video_dir())
    else:
        # Default to video directory
        return Path(get_video_dir())
