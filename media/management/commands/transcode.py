"""
Django management command for transcoding media.

This is a thin CLI wrapper around the transcode_service.
"""
import json
import sys
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError

from media.service.transcode_service import transcode_url_to_dir
from media.service.resolve import PlaylistNotSupported


class Command(BaseCommand):
    help = 'Download and transcode media from URL or file path'

    def add_arguments(self, parser):
        parser.add_argument(
            'input',
            type=str,
            help='URL or file path to media'
        )
        parser.add_argument(
            '--type',
            type=str,
            default='auto',
            choices=['auto', 'audio', 'video'],
            help='Media type to download (default: auto)'
        )
        parser.add_argument(
            '--outdir',
            type=str,
            default='.',
            help='Output directory (default: current directory)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without actually downloading'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Enable verbose output'
        )
        parser.add_argument(
            '--json',
            action='store_true',
            help='Output result as JSON'
        )

    def handle(self, *args, **options):
        input_url = options['input']
        requested_type = options['type']
        outdir = options['outdir']
        dry_run = options['dry_run']
        verbose = options['verbose']
        output_json = options['json']

        # Dry run mode
        if dry_run:
            from media.service.strategy import choose_download_strategy
            from media.service.resolve import prefetch, resolve_media_type

            if not output_json:
                self.stdout.write(self.style.WARNING("DRY RUN MODE - No files will be downloaded"))
                self.stdout.write(f"Input: {input_url}")
                self.stdout.write(f"Requested type: {requested_type}")
                self.stdout.write(f"Output directory: {outdir}")

            try:
                strategy = choose_download_strategy(input_url)
                if not output_json:
                    self.stdout.write(f"Strategy: {strategy}")

                prefetch_result = prefetch(input_url, strategy, logger=None)
                resolved_type = resolve_media_type(requested_type, prefetch_result)

                if not output_json:
                    self.stdout.write(f"Title: {prefetch_result.title}")
                    self.stdout.write(f"Resolved type: {resolved_type}")
                    self.stdout.write(self.style.SUCCESS("Dry run complete"))
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
                raise CommandError(f"Playlist not supported: {e}")
            except Exception as e:
                raise CommandError(f"Dry run failed: {e}")

            return

        # Actual execution
        try:
            if not output_json and verbose:
                self.stdout.write(self.style.NOTICE(f"Transcoding: {input_url}"))

            result = transcode_url_to_dir(
                url=input_url,
                outdir=outdir,
                requested_type=requested_type,
                verbose=verbose
            )

            # Output result
            if output_json:
                # JSON output
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

                self.stdout.write(json.dumps(output, indent=2))
            else:
                # Human-readable output
                self.stdout.write(self.style.SUCCESS("✓ Transcode complete"))
                self.stdout.write(f"  URL: {result.url}")
                self.stdout.write(f"  Title: {result.title}")
                self.stdout.write(f"  Slug: {result.slug}")
                self.stdout.write(f"  Type: {result.resolved_type}")
                self.stdout.write(f"  Strategy: {result.strategy}")
                self.stdout.write(f"  Output: {result.output_path}")
                self.stdout.write(f"  Size: {result.file_size:,} bytes")
                self.stdout.write(f"  Transcoded: {'Yes' if result.transcoded else 'No'}")

                if result.thumbnail_path:
                    self.stdout.write(f"  Thumbnail: {result.thumbnail_path}")
                if result.subtitle_path:
                    self.stdout.write(f"  Subtitles: {result.subtitle_path}")

        except PlaylistNotSupported as e:
            raise CommandError(f"Playlist not supported: {e}")
        except Exception as e:
            if output_json:
                error_output = {
                    'success': False,
                    'error': str(e)
                }
                self.stdout.write(json.dumps(error_output, indent=2))
                sys.exit(1)
            else:
                raise CommandError(f"Transcode failed: {e}")
