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

    def handle(self, *args, **options):
        url = options['url']
        media_type = options['type']
        verbose = options['verbose']
        json_output = options['json']

        # Map type to MediaItem constants
        if media_type == 'auto':
            requested_type = MediaItem.REQUESTED_TYPE_AUTO
        elif media_type == 'audio':
            requested_type = MediaItem.REQUESTED_TYPE_AUDIO
        else:
            requested_type = MediaItem.REQUESTED_TYPE_VIDEO

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

            # Check for playlist detection during prefetch
            try:
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

            except Exception as e:
                # Handle playlist detection error
                if 'playlist' in str(e).lower():
                    error_msg = 'Error: URL appears to be a playlist, which is not supported. Please provide a direct link to a single media item.'
                    if json_output:
                        self.stdout.write(
                            json.dumps(
                                {'status': 'error', 'error': error_msg, 'guid': str(item.guid)}
                            )
                        )
                    else:
                        self.stderr.write(self.style.ERROR(error_msg))

                    # Clean up
                    item.status = MediaItem.STATUS_ERROR
                    item.error_message = str(e)
                    item.save()
                    if tmp_dir.exists():
                        shutil.rmtree(tmp_dir)

                    return

                # Re-raise other errors
                raise

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

            # Output result
            if json_output:
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

            raise
