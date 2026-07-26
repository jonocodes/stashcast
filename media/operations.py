"""
High-level operations that can be used by views, tasks, and management commands.

This module provides testable functions that encapsulate business logic,
making it easy to test operations without going through Django views or
management commands.
"""

from pathlib import Path


from media.models import MediaItem


def stash_url(url, requested_type='auto', wait=False, logger=None, group=None):
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
        group: Optional MediaGroup to assign the item to

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
        if group is not None:
            item.group = group
        item.save()
        log(f'Reusing existing item: {item.guid}')
    else:
        # Create new item
        item = MediaItem.objects.create(
            source_url=url,
            requested_type=requested_type_const,
            slug='pending',  # Will be set during processing
            group=group,
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


def sync_group_channel(group, max_videos=None, wait=False, logger=None):
    """
    Check a group's YouTube channel for new uploads and stash them as audio.

    A video is considered "new" when no MediaItem with its URL is already assigned
    to this group, so re-running only picks up uploads that appeared since last time.
    Downloaded items are attached to ``group`` and reuse the normal processing
    pipeline via ``stash_url``.

    Args:
        group: MediaGroup instance (must have youtube_channel_url set)
        max_videos: How many of the most recent uploads to consider. Defaults to
            settings.STASHCAST_YOUTUBE_SYNC_MAX_VIDEOS.
        wait: If True, download synchronously (used by CLI); otherwise enqueue.
        logger: Optional callable(message) for logging

    Returns:
        list[MediaItem]: The newly stashed items (empty if nothing new).
    """
    from django.conf import settings
    from django.utils import timezone

    from media.service.youtube_channel import list_channel_videos

    def log(message):
        if logger:
            logger(message)

    if not group.youtube_channel_url:
        log(f'Group "{group.name}" has no YouTube channel configured; skipping')
        return []

    if max_videos is None:
        max_videos = settings.STASHCAST_YOUTUBE_SYNC_MAX_VIDEOS

    log(f'Syncing group "{group.name}" from {group.youtube_channel_url}')
    videos = list_channel_videos(group.youtube_channel_url, max_videos=max_videos, logger=logger)

    new_items = []
    for video in videos:
        already_present = MediaItem.objects.filter(
            source_url=video.url, group=group
        ).exists()
        if already_present:
            continue
        log(f'New upload: {video.title or video.url}')
        item = stash_url(
            video.url,
            requested_type='audio',
            wait=wait,
            logger=logger,
            group=group,
        )
        new_items.append(item)

    group.youtube_last_synced_at = timezone.now()
    group.save(update_fields=['youtube_last_synced_at'])

    log(f'Group "{group.name}": {len(new_items)} new upload(s) stashed')
    return new_items


def sync_all_youtube_channels(wait=False, logger=None):
    """
    Sync every group that has a YouTube channel configured.

    Args:
        wait: If True, download synchronously; otherwise enqueue background tasks.
        logger: Optional callable(message) for logging

    Returns:
        list[MediaItem]: All newly stashed items across all groups.
    """
    from media.models import MediaGroup

    def log(message):
        if logger:
            logger(message)

    groups = MediaGroup.objects.exclude(youtube_channel_url='')
    log(f'Checking {groups.count()} group(s) with a YouTube channel')

    stashed = []
    for group in groups:
        try:
            stashed.extend(sync_group_channel(group, wait=wait, logger=logger))
        except Exception as e:
            log(f'Failed to sync group "{group.name}": {e}')
    return stashed
