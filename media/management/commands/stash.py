"""
Management command to stash media from a URL (foreground execution).

This command performs the same pipeline as the web app but runs synchronously
in the foreground without using Huey. Useful for CLI workflows and debugging.
"""

import json
import shutil
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone

from media.models import MediaItem
from media.processing import (
    write_log,
    prefetch_file,
    prefetch_direct,
    prefetch_ytdlp,
    download_direct,
    download_ytdlp,
    process_files,
)
from media.service.strategy import choose_download_strategy
from media.service.resolve import (
    prefetch,
    MultipleItemsDetected,
    check_multiple_items,
)


class Command(BaseCommand):
    help = 'Stash media from a URL (foreground execution, no Huey)'

    def add_arguments(self, parser):
        parser.add_argument('url', type=str, help='URL to stash')
        parser.add_argument(
            '--type',
            type=str,
            choices=['auto', 'audio', 'video'],
            default='auto',
            help='Media type (default: auto)',
        )
        parser.add_argument('--verbose', action='store_true', help='Verbose output')
        parser.add_argument('--json', action='store_true', help='JSON output')
        parser.add_argument(
            '--allow-multiple',
            action='store_true',
            help='Allow downloading multiple items from playlists or pages with multiple videos',
        )

    def handle(self, *args, **options):
        url = options['url']
        media_type = options['type']
        verbose = options['verbose']
        json_output = options['json']
        allow_multiple = options['allow_multiple']

        # Map type to MediaItem constants
        if media_type == 'auto':
            requested_type = MediaItem.REQUESTED_TYPE_AUTO
        elif media_type == 'audio':
            requested_type = MediaItem.REQUESTED_TYPE_AUDIO
        else:
            requested_type = MediaItem.REQUESTED_TYPE_VIDEO

        # First, check for special URL types BEFORE creating any MediaItem
        strategy = choose_download_strategy(url)

        # Handle Spotify URLs - search for alternatives and select
        if strategy == 'spotify':
            from media.service.spotify import select_spotify_alternative

            try:
                url = select_spotify_alternative(url, logger=self.stdout.write)
            except ValueError as e:
                self.stderr.write(self.style.ERROR(str(e)))
                return
            strategy = choose_download_strategy(url)

        if strategy == 'ytdlp':
            try:
                prefetch_result = prefetch(url, strategy, logger=None)
                if prefetch_result.is_multiple:
                    check_multiple_items(
                        prefetch_result, allow_multiple=allow_multiple, source='cli'
                    )

                    # If we get here, allow_multiple is True - process each entry
                    if verbose:
                        self.stdout.write(
                            f'Processing {len(prefetch_result.entries)} items from: '
                            f'{prefetch_result.playlist_title}'
                        )

                    results = []
                    for i, entry in enumerate(prefetch_result.entries):
                        if verbose:
                            self.stdout.write(
                                f'\n[{i + 1}/{len(prefetch_result.entries)}] {entry.title}'
                            )
                        result = self._process_single_url(
                            entry.url, requested_type, verbose, json_output
                        )
                        if result:
                            results.append(result)

                    # Output summary
                    if json_output:
                        self.stdout.write(
                            json.dumps({'status': 'success', 'items': results}, indent=2)
                        )
                    else:
                        self.stdout.write(self.style.SUCCESS(f'\n✓ Completed {len(results)} items'))
                    return

            except MultipleItemsDetected as e:
                error_msg = str(e)
                if json_output:
                    self.stdout.write(
                        json.dumps(
                            {
                                'status': 'error',
                                'error': error_msg,
                                'count': e.count,
                                'playlist_title': e.playlist_title,
                            }
                        )
                    )
                else:
                    self.stderr.write(self.style.ERROR(f'\nError: {error_msg}'))
                    if e.playlist_title:
                        self.stderr.write(f'  Playlist: {e.playlist_title}')
                    self.stderr.write(f'  Items found: {e.count}')
                    # Show first few items
                    for i, entry in enumerate(e.entries[:5]):
                        self.stderr.write(f'    - {entry.title}')
                    if e.count > 5:
                        self.stderr.write(f'    ... and {e.count - 5} more')
                return

        # Single item flow - proceed with original logic
        self._process_single_url(url, requested_type, verbose, json_output)

    def _process_single_url(self, url, requested_type, verbose, json_output):
        """Process a single URL and return result dict for JSON output."""
        # Check if this URL already exists with this requested type
        existing_item = MediaItem.objects.filter(
            source_url=url, requested_type=requested_type
        ).first()

        if existing_item:
            # Reuse existing item (will overwrite files)
            item = existing_item
            item.status = MediaItem.STATUS_PREFETCHING
            item.error_message = ''
            item.save()
            if verbose:
                self.stdout.write(f'Reusing existing item: {item.guid}')
        else:
            # Create new item
            item = MediaItem.objects.create(
                source_url=url, requested_type=requested_type, status=MediaItem.STATUS_PREFETCHING
            )
            if verbose:
                self.stdout.write(f'Created new item: {item.guid}')

        # Determine base media directory (don't know slug yet)
        media_base = Path(settings.STASHCAST_MEDIA_DIR)
        media_base.mkdir(parents=True, exist_ok=True)

        # Create tmp directory with GUID
        tmp_dir = media_base / f'tmp-{item.guid}'
        tmp_dir.mkdir(exist_ok=True)

        # Create log file
        log_path = tmp_dir / 'download.log'

        # Logger function for verbose output
        def log(message):
            write_log(log_path, message)
            if verbose:
                self.stdout.write(message)

        try:
            log('=== TASK STARTED ===')
            log(f'GUID: {item.guid}')
            log(f'URL: {item.source_url}')
            log(f'Requested type: {item.requested_type}')
            log(f'Tmp directory: {tmp_dir}')

            # PREFETCHING
            log('=== PREFETCHING ===')

            # Determine download strategy
            strategy = choose_download_strategy(item.source_url)
            is_direct = strategy in ('direct', 'file')

            # Prefetch metadata
            if is_direct:
                # Direct download - minimal metadata
                if Path(item.source_url).exists():
                    prefetch_file(item, tmp_dir, log_path)
                else:
                    prefetch_direct(item, tmp_dir, log_path)
            else:
                # Use yt-dlp to extract metadata (may fallback to HTML extractor)
                prefetch_ytdlp(item, tmp_dir, log_path)

                # Re-check if URL is now direct (HTML extractor may have found direct media)
                item.refresh_from_db()
                strategy = choose_download_strategy(item.source_url)
                is_direct = strategy in ('direct', 'file')

            log(f'Direct media URL: {is_direct}')

            # DOWNLOADING
            item.status = MediaItem.STATUS_DOWNLOADING
            item.save()
            log('=== DOWNLOADING ===')

            if is_direct:
                download_direct(item, tmp_dir, log_path)
            else:
                download_ytdlp(item, tmp_dir, log_path)

            # PROCESSING
            item.status = MediaItem.STATUS_PROCESSING
            item.save()
            log('=== PROCESSING ===')

            process_files(item, tmp_dir, log_path)

            # Move from tmp directory to final slug-based directory
            log('=== MOVING TO FINAL DIRECTORY ===')
            final_dir = item.get_base_dir()
            final_dir.parent.mkdir(parents=True, exist_ok=True)

            # If final directory exists, remove it (overwrite behavior)
            if final_dir.exists():
                log(f'Removing existing directory: {final_dir}')
                shutil.rmtree(final_dir)

            # Move tmp directory to final location
            shutil.move(str(tmp_dir), str(final_dir))
            log(f'Moved to: {final_dir}')

            # Update log_path to new location
            log_path = final_dir / 'download.log'

            # READY
            item.status = MediaItem.STATUS_READY
            item.downloaded_at = timezone.now()
            item.save()
            log('=== READY ===')
            log(f'Completed successfully: {item.title}')

            # Build result dict (used for both JSON output and multi-item mode)
            result = {
                'status': 'success',
                'guid': str(item.guid),
                'slug': item.slug,
                'title': item.title,
                'media_type': item.media_type,
                'directory': str(final_dir),
                'content_path': str(item.get_absolute_content_path())
                if item.content_path
                else None,
                'file_size': item.file_size,
                'duration_seconds': item.duration_seconds,
            }

            # Output result
            if json_output:
                self.stdout.write(json.dumps(result, indent=2))
            else:
                self.stdout.write(self.style.SUCCESS('✓ Stash complete'))
                self.stdout.write(f'  URL: {url}')
                self.stdout.write(f'  Title: {item.title}')
                self.stdout.write(f'  Slug: {item.slug}')
                self.stdout.write(f'  Type: {item.media_type}')
                self.stdout.write(f'  GUID: {item.guid}')
                if item.content_path:
                    self.stdout.write(f'  Output: {item.get_absolute_content_path()}')
                if item.file_size:
                    self.stdout.write(f'  Size: {item.file_size:,} bytes')
                if item.duration_seconds:
                    mins = item.duration_seconds // 60
                    secs = item.duration_seconds % 60
                    self.stdout.write(f'  Duration: {mins}:{secs:02d}')
                self.stdout.write(f'  Directory: {final_dir}')

            return result

        except Exception as e:
            # ERROR
            item.status = MediaItem.STATUS_ERROR
            item.error_message = str(e)
            item.save()

            if log_path:
                write_log(log_path, '=== ERROR ===')
                write_log(log_path, f'Error: {str(e)}')

            # Clean up tmp directory on error
            if tmp_dir and tmp_dir.exists():
                if verbose:
                    self.stdout.write(f'Cleaning up tmp directory: {tmp_dir}')
                try:
                    shutil.rmtree(tmp_dir)
                except Exception as cleanup_error:
                    if verbose:
                        self.stdout.write(f'Failed to clean up tmp: {cleanup_error}')

            # Output error
            if json_output:
                self.stdout.write(
                    json.dumps({'status': 'error', 'error': str(e), 'guid': str(item.guid)})
                )
            else:
                self.stderr.write(self.style.ERROR(f'\n✗ Error: {str(e)}'))
                self.stderr.write(f'  GUID: {item.guid}')
                if log_path and log_path.exists():
                    self.stderr.write(f'  Log: {log_path}')

            # Return None instead of raising to allow multi-item mode to continue
            return None
