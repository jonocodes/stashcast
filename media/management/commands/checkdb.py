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

        # Get all database items
        db_items = MediaItem.objects.all()
        db_slugs = set(item.slug for item in db_items)

        # Get all directories (excluding temp and hidden dirs)
        dir_slugs = set()
        if media_root.exists():
            for subdir in media_root.iterdir():
                if (
                    subdir.is_dir()
                    and subdir.name != '.DS_Store'
                    and not subdir.name.startswith('tmp-')
                ):
                    dir_slugs.add(subdir.name)

        # Compare
        total_db_items = len(db_items)
        total_dirs = len(dir_slugs)

        # Find missing directories (in DB but not on filesystem)
        all_missing_dirs = db_slugs - dir_slugs

        # Find orphaned directories (on filesystem but not in DB)
        all_orphaned_dirs = dir_slugs - db_slugs

        # Output results
        self.stdout.write('\nDatabase Consistency Check')
        self.stdout.write(f'{"=" * 50}')
        self.stdout.write(f'\nDatabase items: {total_db_items}')
        self.stdout.write(f'\nMedia directories: {total_dirs}')

        if not all_missing_dirs and not all_orphaned_dirs:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n✓ All {total_db_items} database items have matching directories.'
                )
            )
        else:
            # Missing directories
            if all_missing_dirs:
                self.stdout.write(
                    self.style.ERROR(
                        f'\n✗ Found {len(all_missing_dirs)} database item(s) without directories:'
                    )
                )
                for slug in sorted(all_missing_dirs)[:10]:
                    self.stdout.write(f'    - {slug}')
                if len(all_missing_dirs) > 10:
                    self.stdout.write(f'    ... and {len(all_missing_dirs) - 10} more')

            # Orphaned directories
            if all_orphaned_dirs:
                self.stdout.write(
                    self.style.WARNING(
                        f'\n⚠ Found {len(all_orphaned_dirs)} directory(ies) without database entries:'
                    )
                )
                for slug in sorted(all_orphaned_dirs)[:10]:
                    self.stdout.write(f'    - {slug}')
                if len(all_orphaned_dirs) > 10:
                    self.stdout.write(f'    ... and {len(all_orphaned_dirs) - 10} more')

        self.stdout.write(f'\n{"=" * 50}\n')
