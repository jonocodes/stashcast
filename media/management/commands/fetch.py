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
        parser.add_argument(
            '--auto-select',
            action='store_true',
            help='For Spotify URLs, automatically select the first search result',
        )

    def handle(self, *args, **options):
        input_url = options['input']
        requested_type = options['type']
        outdir = options['outdir']
        dry_run = options['dry_run']
        verbose = options['verbose']
        output_json = options['json']
        allow_multiple = options['allow_multiple']
        auto_select = options['auto_select']

        # Check for multiple items BEFORE doing anything else
        strategy = choose_download_strategy(input_url)

        # Handle Spotify URLs
        if strategy == 'spotify':
            self._handle_spotify_url(
                input_url, outdir, requested_type, verbose, output_json, dry_run, auto_select
            )
            return

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

        # Single item flow
        self._transcode_single_url(input_url, outdir, requested_type, verbose, output_json)

    def _transcode_single_url(
        self, input_url, outdir, requested_type, verbose, output_json, title_override=None
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

    def _handle_spotify_url(
        self, input_url, outdir, requested_type, verbose, output_json, dry_run, auto_select
    ):
        """Handle Spotify URLs by searching alternative platforms."""
        from media.service.spotify import resolve_spotify_url

        if not output_json:
            self.stdout.write(
                self.style.WARNING('Spotify URL detected - searching for alternatives...')
            )

        try:
            resolution = resolve_spotify_url(input_url, max_results=5, search_all=True)
        except Exception as e:
            if output_json:
                self.stdout.write(json.dumps({'success': False, 'error': str(e)}))
            else:
                self.stderr.write(self.style.ERROR(f'Failed to resolve Spotify URL: {e}'))
            sys.exit(1)

        if not output_json:
            self.stdout.write(f'  Title: {resolution.spotify_metadata.title}')
            self.stdout.write(f'  Search query: {resolution.search_query}')
            self.stdout.write('')

        if not resolution.all_results:
            if output_json:
                self.stdout.write(
                    json.dumps(
                        {
                            'success': False,
                            'error': 'No alternative sources found',
                            'spotify_title': resolution.spotify_metadata.title,
                            'search_query': resolution.search_query,
                        }
                    )
                )
            else:
                self.stderr.write(self.style.ERROR('No alternative sources found on any platform.'))
            sys.exit(1)

        # Dry run - just show what we found
        if dry_run:
            if output_json:
                self.stdout.write(
                    json.dumps(
                        {
                            'dry_run': True,
                            'spotify_url': input_url,
                            'spotify_title': resolution.spotify_metadata.title,
                            'search_query': resolution.search_query,
                            'results': [
                                {
                                    'platform': r.platform,
                                    'url': r.url,
                                    'title': r.title,
                                    'channel': r.channel,
                                    'duration_seconds': r.duration_seconds,
                                }
                                for r in resolution.all_results
                            ],
                        },
                        indent=2,
                    )
                )
            else:
                self.stdout.write(self.style.WARNING('DRY RUN - showing search results:'))
                self._print_spotify_results(resolution.all_results)
            return

        # Auto-select first result
        if auto_select:
            selected = resolution.all_results[0]
            if not output_json:
                self.stdout.write(f'Auto-selecting: [{selected.platform}] {selected.title}')
            self._transcode_single_url(selected.url, outdir, requested_type, verbose, output_json)
            return

        # Interactive selection
        if output_json:
            # For JSON mode without auto-select, return results for external handling
            self.stdout.write(
                json.dumps(
                    {
                        'success': False,
                        'error': 'Spotify URL requires selection. Use --auto-select or choose from results.',
                        'spotify_title': resolution.spotify_metadata.title,
                        'search_query': resolution.search_query,
                        'results': [
                            {
                                'platform': r.platform,
                                'url': r.url,
                                'title': r.title,
                                'channel': r.channel,
                                'duration_seconds': r.duration_seconds,
                            }
                            for r in resolution.all_results
                        ],
                    },
                    indent=2,
                )
            )
            sys.exit(1)

        # Interactive CLI selection
        self._print_spotify_results(resolution.all_results)
        self.stdout.write('')
        self.stdout.write('Enter number to download, or "q" to quit:')

        try:
            choice = input('> ').strip()
            if choice.lower() == 'q':
                self.stdout.write('Cancelled.')
                return

            idx = int(choice) - 1
            if idx < 0 or idx >= len(resolution.all_results):
                self.stderr.write(self.style.ERROR(f'Invalid choice: {choice}'))
                sys.exit(1)

            selected = resolution.all_results[idx]
            self.stdout.write(f'\nDownloading: [{selected.platform}] {selected.title}')
            self._transcode_single_url(selected.url, outdir, requested_type, verbose, output_json)

        except (ValueError, EOFError):
            self.stderr.write(
                self.style.ERROR('Invalid input. Use --auto-select for non-interactive mode.')
            )
            sys.exit(1)

    def _print_spotify_results(self, results):
        """Print Spotify search results grouped by platform."""
        current_platform = None
        idx = 1

        for result in results:
            if result.platform != current_platform:
                current_platform = result.platform
                platform_name = {
                    'youtube': 'YouTube',
                    'soundcloud': 'SoundCloud',
                    'dailymotion': 'Dailymotion',
                    'podcast_index': 'Podcast RSS',
                }.get(current_platform, current_platform)
                self.stdout.write(self.style.MIGRATE_HEADING(f'\n  {platform_name}:'))

            duration = ''
            if result.duration_seconds:
                mins = result.duration_seconds // 60
                secs = result.duration_seconds % 60
                duration = f' [{mins}:{secs:02d}]'

            channel = f' - {result.channel}' if result.channel else ''
            self.stdout.write(f'    {idx}. {result.title}{channel}{duration}')
            idx += 1
