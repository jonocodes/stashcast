"""
Management command to check group YouTube channels for new uploads.

Runs the same sync used by the periodic Huey task, but in the foreground. Useful
for testing a channel URL or triggering an immediate check without waiting for the
next scheduled run.

Examples:
    ./manage.py sync_youtube                 # sync all groups (enqueue downloads)
    ./manage.py sync_youtube --group lekcje  # sync a single group by slug
    ./manage.py sync_youtube --wait          # download synchronously (blocking)
    ./manage.py sync_youtube --max 10        # consider the 10 most recent uploads
"""

from django.core.management.base import BaseCommand, CommandError

from media.models import MediaGroup
from media.operations import sync_all_youtube_channels, sync_group_channel


class Command(BaseCommand):
    help = 'Check group YouTube channels for new uploads and stash them as audio'

    def add_arguments(self, parser):
        parser.add_argument(
            '--group',
            type=str,
            default=None,
            help='Sync only the group with this slug (default: all configured groups)',
        )
        parser.add_argument(
            '--wait',
            action='store_true',
            help='Download synchronously instead of enqueuing background tasks',
        )
        parser.add_argument(
            '--max',
            type=int,
            default=None,
            dest='max_videos',
            help='How many recent uploads to consider (default: STASHCAST_YOUTUBE_SYNC_MAX_VIDEOS)',
        )

    def handle(self, *args, **options):
        slug = options['group']
        wait = options['wait']
        max_videos = options['max_videos']

        def log(message):
            self.stdout.write(message)

        if slug:
            try:
                group = MediaGroup.objects.get(slug=slug)
            except MediaGroup.DoesNotExist:
                raise CommandError(f'No group with slug "{slug}"')
            if not group.youtube_channel_url:
                raise CommandError(f'Group "{group.name}" has no YouTube channel configured')
            items = sync_group_channel(group, max_videos=max_videos, wait=wait, logger=log)
        else:
            items = sync_all_youtube_channels(wait=wait, logger=log)

        self.stdout.write(self.style.SUCCESS(f'✓ Stashed {len(items)} new upload(s)'))
