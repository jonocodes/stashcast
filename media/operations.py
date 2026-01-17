"""
High-level operations that can be used by views, tasks, and management commands.

This module provides testable functions that encapsulate business logic,
making it easy to test operations without going through Django views or
management commands.
"""

from pathlib import Path


from media.models import MediaItem


def stash_url(url, requested_type='auto', wait=False, logger=None):
    """
    Stash a URL for download.

    This is the core operation used by:
    - Web /stash/ endpoint
    - Management command: ./manage.py stash
    - API calls

    Args:
        url: URL to download
        requested_type: 'auto', 'audio', or 'video'
        wait: If True, run synchronously. If False, enqueue background task.
        logger: Optional callable(message) for logging

    Returns:
        MediaItem: The created or reused MediaItem instance

    Example:
        >>> item = stash_url('http://example.com/video.mp4', 'auto', wait=True)
        >>> print(item.guid)
    """
    # Convert requested_type string to MediaItem constant
    type_map = {
        'auto': MediaItem.REQUESTED_TYPE_AUTO,
        'audio': MediaItem.REQUESTED_TYPE_AUDIO,
        'video': MediaItem.REQUESTED_TYPE_VIDEO,
    }
    requested_type_const = type_map.get(requested_type, MediaItem.REQUESTED_TYPE_AUTO)

    def log(message):
        if logger:
            logger(message)

    # Check for existing item with same URL and requested type
    if requested_type == 'auto':
        # For 'auto', match with other 'auto' requests
        existing_item = MediaItem.objects.filter(
            source_url=url, requested_type=MediaItem.REQUESTED_TYPE_AUTO
        ).first()
    else:
        # For explicit types, match with items that have that media_type
        existing_item = MediaItem.objects.filter(source_url=url, media_type=requested_type).first()

    if existing_item:
        # Reuse existing item (overwrite behavior)
        item = existing_item
        item.requested_type = requested_type_const
        item.status = MediaItem.STATUS_PREFETCHING
        item.error_message = ''
        item.save()
        log(f'Reusing existing item: {item.guid}')
    else:
        # Create new item
        item = MediaItem.objects.create(
            source_url=url,
            requested_type=requested_type_const,
            slug='pending',  # Will be set during processing
        )
        log(f'Created new item: {item.guid}')

    # Process the media item
    from media.tasks import process_media

    if wait:
        # Run synchronously (blocking) - used by CLI
        log('Processing synchronously...')
        process_media.call_local(item.guid)
    else:
        # Enqueue background task - used by web
        log('Enqueued background task')
        process_media(item.guid)

    return item


def transcode_file(input_path, output_dir=None, requested_type='auto', metadata=None, logger=None):
    """
    Transcode a file without storing in database.

    This is used by the standalone fetch command for batch processing.

    Args:
        input_path: Path to input media file
        output_dir: Directory to write output (default: current directory)
        requested_type: 'auto', 'audio', or 'video'
        metadata: Optional dict with title, author, description
        logger: Optional callable(message) for logging

    Returns:
        Path: Path to output file

    Example:
        >>> output = transcode_file('input.mp4', './output', 'audio')
        >>> print(output)
        ./output/input.m4a
    """
    from media.service.transcode_service import transcode_to_target_format

    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f'Input file not found: {input_path}')

    if output_dir is None:
        output_dir = Path.cwd()
    else:
        output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    def log(message):
        if logger:
            logger(message)

    log(f'Transcoding: {input_path}')
    log(f'Output dir: {output_dir}')
    log(f'Type: {requested_type}')

    # Determine output extension and path
    from media.service.media_info import get_output_extension

    output_ext = get_output_extension(requested_type, input_path.suffix)
    output_path = output_dir / f'{input_path.stem}{output_ext}'

    # Run transcode
    transcode_to_target_format(
        input_path=input_path,
        output_path=output_path,
        resolved_type=requested_type,
        metadata=metadata or {},
        logger=log,
    )

    log(f'Output: {output_path}')
    return output_path


def generate_summary_for_item(guid, logger=None):
    """
    Generate summary for a media item from its subtitles.

    Args:
        guid: MediaItem GUID
        logger: Optional callable(message) for logging

    Returns:
        str: Generated summary text, or None if no subtitles or summary disabled

    Example:
        >>> summary = generate_summary_for_item('abc123xyz')
        >>> print(summary)
        'This video discusses...'
    """

    def log(message):
        if logger:
            logger(message)

    from media.tasks import generate_summary

    item = MediaItem.objects.get(guid=guid)

    log(f'Generating summary for: {item.title or item.guid}')

    # Run summary generation
    generate_summary(guid)

    # Refresh from database to get updated summary
    item.refresh_from_db()

    if item.summary:
        log(f'Summary generated: {len(item.summary)} characters')
    else:
        log('No summary generated (subtitles missing or summary disabled)')

    return item.summary
