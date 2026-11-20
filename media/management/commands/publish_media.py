"""
Publish existing local media items to the configured S3-compatible bucket.

Use this once after enabling STASHCAST_S3_BUCKET to backfill items downloaded before,
or to retry items whose publish step failed. Items whose content file is no longer on
local disk are assumed to be published already and are skipped.
"""

from django.core.management.base import BaseCommand, CommandError

from media.models import MediaItem
from media.storage import publish_item, remote_enabled


class Command(BaseCommand):
    help = 'Publish local media items (READY and ARCHIVED) to the configured S3 bucket'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='List what would be published')
        parser.add_argument('--slug', help='Only publish the item with this slug')

    def handle(self, *args, **options):
        if not remote_enabled():
            raise CommandError('Remote storage is not configured (set STASHCAST_S3_BUCKET).')

        items = MediaItem.objects.filter(
            status__in=[MediaItem.STATUS_READY, MediaItem.STATUS_ARCHIVED]
        ).exclude(content_path='')
        if options['slug']:
            items = items.filter(slug=options['slug'])

        published = skipped = failed = 0
        for item in items.order_by('created_at'):
            content = item.get_absolute_content_path()
            if not content or not content.exists():
                skipped += 1
                continue

            if options['dry_run']:
                self.stdout.write(f'Would publish: {item.slug}')
                published += 1
                continue

            try:
                publish_item(item)
                published += 1
                self.stdout.write(self.style.SUCCESS(f'Published: {item.slug}'))
            except Exception as e:
                failed += 1
                self.stderr.write(self.style.ERROR(f'Failed: {item.slug}: {e}'))

        verb = 'Would publish' if options['dry_run'] else 'Published'
        self.stdout.write(
            f'{verb} {published}, skipped {skipped} (no local content), failed {failed}'
        )
        if failed:
            raise CommandError(f'{failed} item(s) failed to publish')
