"""
Tests for the media groups feature.

Covers the MediaGroup model, group filtering in the grid/list views, per-group
RSS feeds, the feed-links listing, and group selection on the stash form.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from media.models import MediaGroup, MediaItem

User = get_user_model()


def _ready_item(slug, title, group=None, media_type=MediaItem.MEDIA_TYPE_VIDEO):
    return MediaItem.objects.create(
        source_url=f'http://example.com/{slug}',
        requested_type=MediaItem.REQUESTED_TYPE_AUTO,
        slug=slug,
        title=title,
        media_type=media_type,
        status=MediaItem.STATUS_READY,
        group=group,
    )


class MediaGroupModelTest(TestCase):
    def test_slug_generated_from_name(self):
        group = MediaGroup.objects.create(name='Lekcje')
        self.assertEqual(group.slug, 'lekcje')

    def test_slug_unique_when_names_collide_on_base(self):
        MediaGroup.objects.create(name='Kitchen')
        # Different name that slugifies to the same base
        second = MediaGroup.objects.create(name='Kitchen!')
        self.assertEqual(second.slug, 'kitchen-2')

    def test_slug_falls_back_when_unslugifiable(self):
        group = MediaGroup.objects.create(name='!!!')
        self.assertTrue(group.slug.startswith('group'))

    def test_item_count_only_counts_ready(self):
        group = MediaGroup.objects.create(name='Other')
        _ready_item('r1', 'Ready One', group=group)
        MediaItem.objects.create(
            source_url='http://example.com/x',
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            slug='pending-one',
            status=MediaItem.STATUS_DOWNLOADING,
            group=group,
        )
        self.assertEqual(group.item_count, 1)

    def test_group_set_null_on_delete(self):
        group = MediaGroup.objects.create(name='Temp')
        item = _ready_item('r2', 'Item', group=group)
        group.delete()
        item.refresh_from_db()
        self.assertIsNone(item.group)


class GroupFilterViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser('admin', 'admin@test.com', 'password')
        self.client.login(username='admin', password='password')
        self.lekcje = MediaGroup.objects.create(name='Lekcje')
        _ready_item('grouped', 'Grouped Item', group=self.lekcje)
        _ready_item('loose', 'Loose Item', group=None)

    def test_grid_filter_by_group_slug(self):
        response = self.client.get('/admin/tools/grid/?group=lekcje')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Grouped Item')
        self.assertNotContains(response, 'Loose Item')

    def test_grid_filter_ungrouped(self):
        response = self.client.get('/admin/tools/grid/?group=none')
        self.assertContains(response, 'Loose Item')
        self.assertNotContains(response, 'Grouped Item')

    def test_list_filter_by_group_slug(self):
        response = self.client.get('/admin/tools/list/?group=lekcje')
        self.assertContains(response, 'Grouped Item')
        self.assertNotContains(response, 'Loose Item')

    def test_group_dropdown_rendered(self):
        response = self.client.get('/admin/tools/grid/')
        self.assertContains(response, 'value="lekcje"')


class GroupFeedTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.lekcje = MediaGroup.objects.create(name='Lekcje')
        self.inne = MediaGroup.objects.create(name='Inne')
        _ready_item('in-lekcje', 'Lesson Video', group=self.lekcje)
        _ready_item('in-inne', 'Other Video', group=self.inne)
        _ready_item('no-group', 'Ungrouped Video', group=None)

    def test_group_feed_contains_only_group_items(self):
        response = self.client.get('/feeds/group/lekcje.xml')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('Lesson Video', body)
        self.assertNotIn('Other Video', body)
        self.assertNotIn('Ungrouped Video', body)

    def test_group_feed_title(self):
        response = self.client.get('/feeds/group/lekcje.xml')
        self.assertIn('StashCast', response.content.decode())
        self.assertIn('Lekcje', response.content.decode())

    def test_unknown_group_feed_returns_404(self):
        response = self.client.get('/feeds/group/does-not-exist.xml')
        self.assertEqual(response.status_code, 404)

    def test_static_feeds_still_work(self):
        # Regression: refactor to obj-based feeds must not break existing feeds.
        response = self.client.get('/feeds/video.xml')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('Lesson Video', body)
        self.assertIn('Other Video', body)


class FeedLinksGroupsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser('admin', 'admin@test.com', 'password')
        self.client.login(username='admin', password='password')

    def test_feed_links_lists_group_feed(self):
        MediaGroup.objects.create(name='Kuchnia')
        response = self.client.get('/admin/tools/feeds/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Kuchnia')
        self.assertContains(response, '/feeds/group/kuchnia.xml')

    def test_feed_links_empty_state(self):
        response = self.client.get('/admin/tools/feeds/')
        self.assertContains(response, 'No groups yet')


class StashFormGroupTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser('admin', 'admin@test.com', 'password')
        self.client.login(username='admin', password='password')

    def test_form_renders_group_selector(self):
        MediaGroup.objects.create(name='Lekcje')
        response = self.client.get('/admin/tools/add-url/')
        self.assertContains(response, 'name="group"')
        self.assertContains(response, 'name="new_group"')
        self.assertContains(response, 'Lekcje')

    @patch('media.views.process_media_batch')
    def test_bulk_submit_creates_and_assigns_new_group(self, mock_batch):
        self.client.post(
            '/admin/tools/add-url/',
            {
                'type': 'auto',
                'new_group': 'Kuchnia',
                'bulk_urls': 'http://example.com/a\nhttp://example.com/b',
            },
        )
        group = MediaGroup.objects.get(name='Kuchnia')
        items = MediaItem.objects.filter(source_url__startswith='http://example.com/')
        self.assertEqual(items.count(), 2)
        for item in items:
            self.assertEqual(item.group_id, group.pk)

    @patch('media.views.process_media_batch')
    def test_bulk_submit_assigns_existing_group(self, mock_batch):
        group = MediaGroup.objects.create(name='Inne')
        self.client.post(
            '/admin/tools/add-url/',
            {
                'type': 'auto',
                'group': str(group.pk),
                'bulk_urls': 'http://example.com/c',
            },
        )
        item = MediaItem.objects.get(source_url='http://example.com/c')
        self.assertEqual(item.group_id, group.pk)

    @patch('media.views.process_media_batch')
    def test_new_group_takes_precedence_over_selected(self, mock_batch):
        existing = MediaGroup.objects.create(name='Inne')
        self.client.post(
            '/admin/tools/add-url/',
            {
                'type': 'auto',
                'group': str(existing.pk),
                'new_group': 'Lekcje',
                'bulk_urls': 'http://example.com/d',
            },
        )
        item = MediaItem.objects.get(source_url='http://example.com/d')
        self.assertEqual(item.group.name, 'Lekcje')
