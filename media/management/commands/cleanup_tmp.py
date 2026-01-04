"""
Management command to clean up abandoned tmp directories.

Finds and removes tmp-{guid} directories that were left behind
due to failed downloads or worker crashes.
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from pathlib import Path
from datetime import timedelta
import shutil

from media.models import MediaItem


class Command(BaseCommand):
    help = 'Clean up abandoned tmp-{guid} directories from failed downloads'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Delete tmp directories without confirmation'
        )
        parser.add_argument(
            '--max-age',
            type=int,
            default=60,
            help='Maximum age in minutes before considering tmp directory abandoned (default: 60)'
        )

    def handle(self, *args, **options):
        """Find and clean up abandoned tmp directories"""
        dry_run = options['dry_run']
        force = options['force']
        max_age_minutes = options['max_age']

        audio_dir = Path(settings.STASHCAST_AUDIO_DIR)
        video_dir = Path(settings.STASHCAST_VIDEO_DIR)

        # Find all tmp-* directories
        tmp_dirs = []

        if audio_dir.exists():
            tmp_dirs.extend([(d, 'audio') for d in audio_dir.glob('tmp-*') if d.is_dir()])

        if video_dir.exists():
            tmp_dirs.extend([(d, 'video') for d in video_dir.glob('tmp-*') if d.is_dir()])

        if not tmp_dirs:
            self.stdout.write(self.style.SUCCESS("No tmp directories found"))
            return

        # Filter by age
        now = timezone.now()
        max_age = timedelta(minutes=max_age_minutes)
        old_tmp_dirs = []

        for tmp_dir, media_type in tmp_dirs:
            # Get directory modification time
            mtime = tmp_dir.stat().st_mtime
            dir_age = now - timezone.datetime.fromtimestamp(mtime, tz=timezone.get_current_timezone())

            if dir_age > max_age:
                # Extract GUID from directory name (tmp-{guid})
                guid = tmp_dir.name[4:]  # Remove 'tmp-' prefix

                # Check if there's a corresponding database entry
                try:
                    item = MediaItem.objects.get(guid=guid)
                    status_info = f"DB: {item.get_status_display()}"
                except MediaItem.DoesNotExist:
                    item = None
                    status_info = "DB: No record"

                old_tmp_dirs.append({
                    'path': tmp_dir,
                    'media_type': media_type,
                    'guid': guid,
                    'age': dir_age,
                    'item': item,
                    'status_info': status_info
                })

        if not old_tmp_dirs:
            self.stdout.write(self.style.SUCCESS(
                f"Found {len(tmp_dirs)} tmp director{'ies' if len(tmp_dirs) != 1 else 'y'}, "
                f"but none are older than {max_age_minutes} minutes"
            ))
            return

        # Display findings
        self.stdout.write(f"\nFound {len(old_tmp_dirs)} abandoned tmp director{'ies' if len(old_tmp_dirs) != 1 else 'y'}:")
        self.stdout.write(f"{'=' * 80}")

        total_size = 0
        for info in old_tmp_dirs:
            # Calculate directory size
            dir_size = sum(f.stat().st_size for f in info['path'].rglob('*') if f.is_file())
            total_size += dir_size

            age_str = str(info['age']).split('.')[0]  # Remove microseconds
            size_mb = dir_size / (1024 * 1024)

            self.stdout.write(
                f"\n{info['media_type']:5} | {info['path'].name:40} | "
                f"Age: {age_str:15} | Size: {size_mb:6.1f} MB"
            )
            self.stdout.write(f"        {info['status_info']}")

            # Show log preview if available
            log_file = info['path'] / 'download.log'
            if log_file.exists():
                try:
                    with open(log_file, 'r') as f:
                        lines = f.readlines()
                        if lines:
                            last_line = lines[-1].strip()
                            if last_line:
                                self.stdout.write(f"        Last log: {last_line[:60]}...")
                except:
                    pass

        self.stdout.write(f"\n{'=' * 80}")
        self.stdout.write(f"Total size: {total_size / (1024 * 1024):.1f} MB\n")

        # Handle deletion
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"\nDRY RUN: Would delete {len(old_tmp_dirs)} director{'ies' if len(old_tmp_dirs) != 1 else 'y'}"
            ))
            self.stdout.write("Run without --dry-run to actually delete")
            return

        # Confirm deletion
        if not force:
            response = input(f"\nDelete these {len(old_tmp_dirs)} director{'ies' if len(old_tmp_dirs) != 1 else 'y'}? [y/N]: ")
            if response.lower() != 'y':
                self.stdout.write("Cancelled")
                return

        # Delete directories
        deleted_count = 0
        for info in old_tmp_dirs:
            try:
                shutil.rmtree(info['path'])
                self.stdout.write(self.style.SUCCESS(f"✓ Deleted: {info['path'].name}"))
                deleted_count += 1

                # If database entry exists and is in error/pending state, we might want to keep it
                # for now we just leave the DB record as-is

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ Failed to delete {info['path'].name}: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"\n✓ Deleted {deleted_count} of {len(old_tmp_dirs)} tmp director{'ies' if deleted_count != 1 else 'y'}"
        ))
