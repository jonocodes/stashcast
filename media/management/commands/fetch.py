"""
Django management command for fetching media.

Downloads media from a URL or local file, optionally transcoding to
podcast-compatible formats (MP3/M4A for audio, MP4 for video).

This is a standalone CLI tool - it does NOT add items to the database.
Use 'stash' command instead if you want to add media to your feed.
"""

import json
import sys
from django.core.management.base import BaseCommand, CommandError

from media.service.transcode_service import transcode_url_to_dir
from media.service.resolve import (
    PlaylistNotSupported,
    MultipleItemsDetected,
    SpotifyUrlDetected,
    prefetch,
    check_multiple_items,
)
from media.service.strategy import choose_download_strategy


class Command(BaseCommand):
    help = 'Fetch media from URL and convert to podcast-compatible format (not added to feed)'

    def add_arguments(self, parser):
        parser.add_argument('input', type=str, help='URL or file path to media')
        parser.add_argument(
            '--type',
            type=str,
            default='auto',
            choices=['auto', 'audio', 'video'],
            help='Media type to download (default: auto)',
        )
        parser.add_argument(
            '--outdir', type=str, default='.', help='Output directory (default: current directory)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without actually downloading',
        )
        parser.add_argument('--verbose', action='store_true', help='Enable verbose output')
        parser.add_argument('--json', action='store_true', help='Output result as JSON')
        parser.add_argument(
            '--allow-multiple',
            action='store_true',
            help='Allow downloading multiple items from playlists or pages with multiple videos',
        )

    def handle(self, *args, **options):
        input_url = options['input']
        requested_type = options['type']
        outdir = options['outdir']
        dry_run = options['dry_run']
        verbose = options['verbose']
        output_json = options['json']
        allow_multiple = options['allow_multiple']

        # Check for multiple items BEFORE doing anything else
        strategy = choose_download_strategy(input_url)

        # Note: Spotify URLs are handled via SpotifyUrlDetected exception
        # raised by transcode_url_to_dir in _transcode_single_url

        if strategy == 'ytdlp':
            try:
                prefetch_result = prefetch(input_url, strategy, logger=None)
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
                        result = self._transcode_single_url(
                            entry.url,
                            outdir,
                            requested_type,
                            verbose,
                            output_json,
                            title_override=entry.title,
                        )
                        if result:
                            results.append(result)

                    # Output summary
                    if output_json:
                        self.stdout.write(json.dumps({'success': True, 'items': results}, indent=2))
                    else:
                        self.stdout.write(self.style.SUCCESS(f'\n✓ Completed {len(results)} items'))
                    return

            except MultipleItemsDetected as e:
                error_msg = str(e)
                if output_json:
                    self.stdout.write(
                        json.dumps(
                            {
                                'success': False,
                                'error': error_msg,
                                'count': e.count,
                                'playlist_title': e.playlist_title,
                            }
                        )
                    )
                    sys.exit(1)
                else:
                    self.stderr.write(self.style.ERROR(f'\nError: {error_msg}'))
                    if e.playlist_title:
                        self.stderr.write(f'  Playlist: {e.playlist_title}')
                    self.stderr.write(f'  Items found: {e.count}')
                    # Show first few items
                    for entry in e.entries[:5]:
                        self.stderr.write(f'    - {entry.title}')
                    if e.count > 5:
                        self.stderr.write(f'    ... and {e.count - 5} more')
                return

        # Dry run mode
        if dry_run:
            from media.service.resolve import resolve_media_type

            if not output_json:
                self.stdout.write(self.style.WARNING('DRY RUN MODE - No files will be downloaded'))
                self.stdout.write(f'Input: {input_url}')
                self.stdout.write(f'Requested type: {requested_type}')
                self.stdout.write(f'Output directory: {outdir}')

            try:
                if not output_json:
                    self.stdout.write(f'Strategy: {strategy}')

                prefetch_result = prefetch(input_url, strategy, logger=None)
                resolved_type = resolve_media_type(requested_type, prefetch_result)

                if not output_json:
                    self.stdout.write(f'Title: {prefetch_result.title}')
                    self.stdout.write(f'Resolved type: {resolved_type}')
                    self.stdout.write(self.style.SUCCESS('Dry run complete'))
                else:
                    result = {
                        'dry_run': True,
                        'input': input_url,
                        'strategy': strategy,
                        'title': prefetch_result.title,
                        'requested_type': requested_type,
                        'resolved_type': resolved_type,
                    }
                    self.stdout.write(json.dumps(result, indent=2))

            except PlaylistNotSupported as e:
                raise CommandError(f'Playlist not supported: {e}')
            except Exception as e:
                raise CommandError(f'Dry run failed: {e}')

            return

        # Single item flow - SpotifyUrlDetected exception handled inside
        self._transcode_single_url(
            input_url,
            outdir,
            requested_type,
            verbose,
            output_json,
        )

    def _transcode_single_url(
        self,
        input_url,
        outdir,
        requested_type,
        verbose,
        output_json,
        title_override=None,
    ):
        """Transcode a single URL and return result dict for JSON output."""
        try:
            if not output_json and verbose:
                self.stdout.write(self.style.NOTICE(f'Transcoding: {input_url}'))

            result = transcode_url_to_dir(
                url=input_url,
                outdir=outdir,
                requested_type=requested_type,
                verbose=verbose,
                title_override=title_override,
            )

            # Build result dict
            output = {
                'success': True,
                'url': result.url,
                'strategy': result.strategy,
                'requested_type': result.requested_type,
                'resolved_type': result.resolved_type,
                'title': result.title,
                'slug': result.slug,
                'output_path': str(result.output_path),
                'file_size': result.file_size,
                'transcoded': result.transcoded,
            }

            if result.thumbnail_path:
                output['thumbnail_path'] = str(result.thumbnail_path)
            if result.subtitle_path:
                output['subtitle_path'] = str(result.subtitle_path)

            # Output result
            if output_json:
                self.stdout.write(json.dumps(output, indent=2))
            else:
                # Human-readable output
                self.stdout.write(self.style.SUCCESS('✓ Transcode complete'))
                self.stdout.write(f'  URL: {result.url}')
                self.stdout.write(f'  Title: {result.title}')
                self.stdout.write(f'  Slug: {result.slug}')
                self.stdout.write(f'  Type: {result.resolved_type}')
                self.stdout.write(f'  Output: {result.output_path}')
                self.stdout.write(f'  Size: {result.file_size:,} bytes')
                if result.duration_seconds:
                    mins = result.duration_seconds // 60
                    secs = result.duration_seconds % 60
                    self.stdout.write(f'  Duration: {mins}:{secs:02d}')
                self.stdout.write(f'  Transcoded: {"Yes" if result.transcoded else "No"}')

                if result.thumbnail_path:
                    self.stdout.write(f'  Thumbnail: {result.thumbnail_path}')
                if result.subtitle_path:
                    self.stdout.write(f'  Subtitles: {result.subtitle_path}')

            return output

        except SpotifyUrlDetected:
            # Spotify URL detected - use shared selection logic
            from media.service.spotify import select_spotify_alternative

            try:
                selected_url = select_spotify_alternative(input_url, logger=self.stdout.write)
                return self._transcode_single_url(
                    selected_url, outdir, requested_type, verbose, output_json
                )
            except ValueError as e:
                self.stderr.write(self.style.ERROR(str(e)))
                return None
        except PlaylistNotSupported as e:
            if output_json:
                error_output = {'success': False, 'error': f'Playlist not supported: {e}'}
                self.stdout.write(json.dumps(error_output, indent=2))
            else:
                self.stderr.write(self.style.ERROR(f'Playlist not supported: {e}'))
            return None
        except Exception as e:
            if output_json:
                error_output = {'success': False, 'error': str(e)}
                self.stdout.write(json.dumps(error_output, indent=2))
            else:
                self.stderr.write(self.style.ERROR(f'Transcode failed: {e}'))
            return None
