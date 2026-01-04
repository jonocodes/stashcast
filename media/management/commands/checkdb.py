"""
Management command to check database consistency with media directories.

Verifies that:
1. Every database entry has a corresponding directory
2. Every directory has a corresponding database entry
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from pathlib import Path

from media.models import MediaItem


class Command(BaseCommand):
    help = 'Check database consistency with media directories'

    def handle(self, *args, **options):
        """Check database vs filesystem consistency"""
        media_root = Path(settings.MEDIA_ROOT)
        audio_dir = media_root / 'audio'
        video_dir = media_root / 'video'

        # Get all database items
        db_items = MediaItem.objects.all()
        db_slugs_by_type = {
            'audio': set(),
            'video': set()
        }

        for item in db_items:
            if item.media_type == MediaItem.MEDIA_TYPE_AUDIO:
                db_slugs_by_type['audio'].add(item.slug)
            elif item.media_type == MediaItem.MEDIA_TYPE_VIDEO:
                db_slugs_by_type['video'].add(item.slug)

        # Get all directories
        dir_slugs_by_type = {
            'audio': set(),
            'video': set()
        }

        if audio_dir.exists():
            for subdir in audio_dir.iterdir():
                if subdir.is_dir() and subdir.name != '.DS_Store':
                    dir_slugs_by_type['audio'].add(subdir.name)

        if video_dir.exists():
            for subdir in video_dir.iterdir():
                if subdir.is_dir() and subdir.name != '.DS_Store':
                    dir_slugs_by_type['video'].add(subdir.name)

        # Compare
        total_db_items = len(db_slugs_by_type['audio']) + len(db_slugs_by_type['video'])
        total_dirs = len(dir_slugs_by_type['audio']) + len(dir_slugs_by_type['video'])

        # Find missing directories (in DB but not on filesystem)
        missing_audio_dirs = db_slugs_by_type['audio'] - dir_slugs_by_type['audio']
        missing_video_dirs = db_slugs_by_type['video'] - dir_slugs_by_type['video']
        all_missing_dirs = missing_audio_dirs | missing_video_dirs

        # Find orphaned directories (on filesystem but not in DB)
        orphaned_audio_dirs = dir_slugs_by_type['audio'] - db_slugs_by_type['audio']
        orphaned_video_dirs = dir_slugs_by_type['video'] - db_slugs_by_type['video']
        all_orphaned_dirs = orphaned_audio_dirs | orphaned_video_dirs

        # Output results
        self.stdout.write(f"\nDatabase Consistency Check")
        self.stdout.write(f"{'=' * 50}")
        self.stdout.write(f"\nDatabase items: {total_db_items}")
        self.stdout.write(f"  - Audio: {len(db_slugs_by_type['audio'])}")
        self.stdout.write(f"  - Video: {len(db_slugs_by_type['video'])}")
        self.stdout.write(f"\nMedia directories: {total_dirs}")
        self.stdout.write(f"  - Audio: {len(dir_slugs_by_type['audio'])}")
        self.stdout.write(f"  - Video: {len(dir_slugs_by_type['video'])}")

        if not all_missing_dirs and not all_orphaned_dirs:
            self.stdout.write(self.style.SUCCESS(
                f"\n✓ All {total_db_items} database items have matching directories."
            ))
        else:
            # Missing directories
            if all_missing_dirs:
                self.stdout.write(self.style.ERROR(
                    f"\n✗ Found {len(all_missing_dirs)} database item(s) without directories:"
                ))
                if missing_audio_dirs:
                    self.stdout.write(f"  Audio ({len(missing_audio_dirs)}):")
                    for slug in sorted(missing_audio_dirs)[:10]:
                        self.stdout.write(f"    - {slug}")
                    if len(missing_audio_dirs) > 10:
                        self.stdout.write(f"    ... and {len(missing_audio_dirs) - 10} more")

                if missing_video_dirs:
                    self.stdout.write(f"  Video ({len(missing_video_dirs)}):")
                    for slug in sorted(missing_video_dirs)[:10]:
                        self.stdout.write(f"    - {slug}")
                    if len(missing_video_dirs) > 10:
                        self.stdout.write(f"    ... and {len(missing_video_dirs) - 10} more")

            # Orphaned directories
            if all_orphaned_dirs:
                self.stdout.write(self.style.WARNING(
                    f"\n⚠ Found {len(all_orphaned_dirs)} directory(ies) without database entries:"
                ))
                if orphaned_audio_dirs:
                    self.stdout.write(f"  Audio ({len(orphaned_audio_dirs)}):")
                    for slug in sorted(orphaned_audio_dirs)[:10]:
                        self.stdout.write(f"    - {slug}")
                    if len(orphaned_audio_dirs) > 10:
                        self.stdout.write(f"    ... and {len(orphaned_audio_dirs) - 10} more")

                if orphaned_video_dirs:
                    self.stdout.write(f"  Video ({len(orphaned_video_dirs)}):")
                    for slug in sorted(orphaned_video_dirs)[:10]:
                        self.stdout.write(f"    - {slug}")
                    if len(orphaned_video_dirs) > 10:
                        self.stdout.write(f"    ... and {len(orphaned_video_dirs) - 10} more")

        self.stdout.write(f"\n{'=' * 50}\n")
