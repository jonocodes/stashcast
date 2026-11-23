"""
Fill the library with a fixed, invented showcase set for marketing screenshots.

The items, covers and media come from media/fixtures/showcase/ and demo_data/, so the
result is identical on every run and contains no third-party artwork. This is what
`just site-screenshots` uses. It is destructive: with --replace it deletes every
existing media item and its files, so only point it at a throwaway data directory.
"""

import json
import shutil
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from media.models import MediaItem

FIXTURE_DIR = Path(__file__).resolve().parents[2] / 'fixtures' / 'showcase'

SUMMARY = (
    'A short extractive summary from the subtitles appears here, '
    'so you know what you saved before you press play.'
)


def load_fixture(fixture_dir=FIXTURE_DIR):
    with open(fixture_dir / 'showcase.json') as f:
        return json.load(f)


class Command(BaseCommand):
    help = 'Replace the library with the invented showcase items used for screenshots'

    def add_arguments(self, parser):
        parser.add_argument(
            '--replace',
            action='store_true',
            help='Delete all existing media items and their files first (required if any exist)',
        )

    def handle(self, *args, **options):
        existing = MediaItem.objects.count()
        if existing and not options['replace']:
            raise CommandError(
                f'{existing} media items already exist. Use a throwaway STASHCAST_DATA_DIR, '
                'or pass --replace to delete them.'
            )

        fixture = load_fixture()
        base_dir = Path(settings.BASE_DIR)
        sources = {
            'audio': base_dir / fixture['audio_source'],
            'video': base_dir / fixture['video_source'],
        }
        for path in sources.values():
            if not path.exists():
                raise CommandError(f'Missing showcase media: {path}')

        media_dir = Path(settings.STASHCAST_MEDIA_DIR)
        if options['replace']:
            for item in MediaItem.objects.all():
                if item.slug and item.slug != 'pending':
                    shutil.rmtree(media_dir / item.slug, ignore_errors=True)
            MediaItem.objects.all().delete()

        now = timezone.now()
        for entry in fixture['items']:
            self._create(entry, sources[entry['media_type']], media_dir, now)

        self.stdout.write(self.style.SUCCESS(f'Seeded {len(fixture["items"])} showcase items.'))

    def _create(self, entry, source, media_dir, now):
        slug = entry['slug']
        item_dir = media_dir / slug
        item_dir.mkdir(parents=True, exist_ok=True)

        content_name = f'content{source.suffix}'
        shutil.copy(source, item_dir / content_name)
        shutil.copy(FIXTURE_DIR / 'covers' / f'{slug}.webp', item_dir / 'thumbnail.webp')

        when = now - timedelta(hours=entry['hours_ago'])
        is_audio = entry['media_type'] == MediaItem.MEDIA_TYPE_AUDIO
        host = entry['source_url'].split('/')[2]
        item = MediaItem.objects.create(
            source_url=entry['source_url'],
            webpage_url=entry['source_url'],
            slug=slug,
            media_type=entry['media_type'],
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            status=MediaItem.STATUS_READY,
            title=entry['title'],
            author=entry['author'],
            description=f'{entry["title"]}, stashed from {host}.',
            summary=SUMMARY,
            duration_seconds=entry['duration_seconds'],
            file_size=entry['file_size'],
            mime_type='audio/mpeg' if is_audio else 'video/mp4',
            extractor=host.split('.')[0],
            content_path=content_name,
            thumbnail_path='thumbnail.webp',
            publish_date=when,
            downloaded_at=when,
        )
        # created_at is auto_now_add; backdate it so the library order looks lived-in
        MediaItem.objects.filter(pk=item.pk).update(created_at=when)
