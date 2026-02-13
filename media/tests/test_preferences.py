"""
Tests for the preferences page and episode limit feature.

Covers:
- check_episode_limit() function from media.tasks
- preferences_view at /admin/tools/preferences/
- stash_view episode limit enforcement at /stash/
- admin_stash_form_view episode limit enforcement at /admin/tools/add-url/
"""

from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from media.models import MediaItem

User = get_user_model()


class CheckEpisodeLimitTest(TestCase):
    """Tests for the check_episode_limit() function in media.tasks."""

    @override_settings(STASHCAST_MAX_EPISODES=0)
    def test_returns_none_when_unlimited(self):
        """When STASHCAST_MAX_EPISODES=0, no limit is enforced."""
        from media.tasks import check_episode_limit

        # Even with items present, should return None
        MediaItem.objects.create(
            source_url='http://example.com/a.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='ep-a',
            title='Episode A',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_READY,
        )
        result = check_episode_limit()
        self.assertIsNone(result)

    @override_settings(STASHCAST_MAX_EPISODES=5)
    def test_returns_none_when_below_limit(self):
        """When the READY episode count is below the limit, returns None."""
        from media.tasks import check_episode_limit

        for i in range(3):
            MediaItem.objects.create(
                source_url=f'http://example.com/{i}.mp3',
                requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
                slug=f'ep-{i}',
                title=f'Episode {i}',
                media_type=MediaItem.MEDIA_TYPE_AUDIO,
                status=MediaItem.STATUS_READY,
            )

        result = check_episode_limit()
        self.assertIsNone(result)

    @override_settings(STASHCAST_MAX_EPISODES=3)
    def test_returns_error_message_when_at_capacity(self):
        """When READY count equals the limit, returns an error message string."""
        from media.tasks import check_episode_limit

        for i in range(3):
            MediaItem.objects.create(
                source_url=f'http://example.com/{i}.mp3',
                requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
                slug=f'ep-{i}',
                title=f'Episode {i}',
                media_type=MediaItem.MEDIA_TYPE_AUDIO,
                status=MediaItem.STATUS_READY,
            )

        result = check_episode_limit()
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)
        self.assertIn('Episode limit reached', result)
        self.assertIn('3/3', result)

    @override_settings(STASHCAST_MAX_EPISODES=2)
    def test_returns_error_message_when_over_capacity(self):
        """When READY count exceeds the limit, returns an error message string."""
        from media.tasks import check_episode_limit

        for i in range(4):
            MediaItem.objects.create(
                source_url=f'http://example.com/{i}.mp3',
                requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
                slug=f'ep-{i}',
                title=f'Episode {i}',
                media_type=MediaItem.MEDIA_TYPE_AUDIO,
                status=MediaItem.STATUS_READY,
            )

        result = check_episode_limit()
        self.assertIsNotNone(result)
        self.assertIn('4/2', result)

    @override_settings(STASHCAST_MAX_EPISODES=3)
    def test_only_counts_ready_items(self):
        """Only items with STATUS_READY are counted against the limit."""
        from media.tasks import check_episode_limit

        # Create 2 READY items
        for i in range(2):
            MediaItem.objects.create(
                source_url=f'http://example.com/ready-{i}.mp3',
                requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
                slug=f'ready-{i}',
                title=f'Ready {i}',
                media_type=MediaItem.MEDIA_TYPE_AUDIO,
                status=MediaItem.STATUS_READY,
            )

        # Create items with other statuses -- these should NOT count
        MediaItem.objects.create(
            source_url='http://example.com/archived.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='archived-ep',
            title='Archived',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_ARCHIVED,
        )
        MediaItem.objects.create(
            source_url='http://example.com/error.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='error-ep',
            title='Error',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_ERROR,
        )
        MediaItem.objects.create(
            source_url='http://example.com/downloading.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='downloading-ep',
            title='Downloading',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_DOWNLOADING,
        )
        MediaItem.objects.create(
            source_url='http://example.com/prefetching.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='prefetching-ep',
            title='Prefetching',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_PREFETCHING,
        )

        # Total items: 6. READY items: 2. Limit: 3. Should be OK.
        result = check_episode_limit()
        self.assertIsNone(result)


class PreferencesViewTest(TestCase):
    """Tests for the preferences_view at /admin/tools/preferences/."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser('admin', 'admin@test.com', 'password')
        self.client.login(username='admin', password='password')

    def test_page_loads_successfully(self):
        """Preferences page returns 200 for an authenticated admin user."""
        response = self.client.get('/admin/tools/preferences/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'admin/preferences.html')

    def test_requires_authentication(self):
        """Unauthenticated requests are redirected to the login page."""
        self.client.logout()
        response = self.client.get('/admin/tools/preferences/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/admin/login/'))

    def test_shows_episode_counts(self):
        """The page displays ready, audio, video, and archived counts."""
        MediaItem.objects.create(
            source_url='http://example.com/audio1.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='audio-1',
            title='Audio 1',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_READY,
        )
        MediaItem.objects.create(
            source_url='http://example.com/video1.mp4',
            requested_type=MediaItem.REQUESTED_TYPE_VIDEO,
            slug='video-1',
            title='Video 1',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
            status=MediaItem.STATUS_READY,
        )
        MediaItem.objects.create(
            source_url='http://example.com/archived.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='archived-1',
            title='Archived 1',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_ARCHIVED,
        )

        response = self.client.get('/admin/tools/preferences/')
        self.assertEqual(response.status_code, 200)

        # Check context values
        self.assertEqual(response.context['ready_count'], 2)
        self.assertEqual(response.context['audio_count'], 1)
        self.assertEqual(response.context['video_count'], 1)
        self.assertEqual(response.context['archived_count'], 1)

    def test_shows_storage_info(self):
        """The page contains a Storage Used section."""
        response = self.client.get('/admin/tools/preferences/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Storage Used')

    def test_shows_last_download_info(self):
        """The page contains Last Download information."""
        response = self.client.get('/admin/tools/preferences/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Last Download')

    def test_shows_no_downloads_yet_when_empty(self):
        """When there are no ready items, shows 'No downloads yet'."""
        response = self.client.get('/admin/tools/preferences/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No downloads yet')

    @override_settings(STASHCAST_MAX_EPISODES=0)
    def test_shows_unlimited_when_limit_is_zero(self):
        """When STASHCAST_MAX_EPISODES=0, the page shows 'Unlimited'."""
        response = self.client.get('/admin/tools/preferences/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Unlimited')
        self.assertContains(response, 'No limit set')

    @override_settings(STASHCAST_MAX_EPISODES=3)
    def test_shows_at_limit_badge_when_at_capacity(self):
        """When at the episode limit, the page shows 'At limit' badge."""
        for i in range(3):
            MediaItem.objects.create(
                source_url=f'http://example.com/{i}.mp3',
                requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
                slug=f'limit-ep-{i}',
                title=f'Episode {i}',
                media_type=MediaItem.MEDIA_TYPE_AUDIO,
                status=MediaItem.STATUS_READY,
            )

        response = self.client.get('/admin/tools/preferences/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'At limit')

    @override_settings(STASHCAST_MAX_EPISODES=10)
    def test_shows_limit_value_and_ok_badge(self):
        """When well below the limit, shows the limit number and OK badge."""
        response = self.client.get('/admin/tools/preferences/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['max_episodes'], 10)
        self.assertContains(response, 'OK')

    def test_shows_github_link(self):
        """The page contains the GitHub project link."""
        response = self.client.get('/admin/tools/preferences/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'github.com/jonocodes/stashcast')


class StashViewEpisodeLimitTest(TestCase):
    """Tests for episode limit enforcement at /stash/."""

    def setUp(self):
        self.client = Client()
        self.user_token = settings.STASHCAST_USER_TOKEN
        self.process_media_patcher = patch('media.views.process_media')
        self.mock_process_media = self.process_media_patcher.start()

    def tearDown(self):
        self.process_media_patcher.stop()

    @override_settings(STASHCAST_MAX_EPISODES=2)
    def test_blocks_download_when_at_episode_limit(self):
        """Returns a 400 JSON error when the episode limit is reached."""
        for i in range(2):
            MediaItem.objects.create(
                source_url=f'http://example.com/{i}.mp3',
                requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
                slug=f'ep-{i}',
                title=f'Episode {i}',
                media_type=MediaItem.MEDIA_TYPE_AUDIO,
                status=MediaItem.STATUS_READY,
            )

        response = self.client.get(
            '/stash/',
            {
                'token': self.user_token,
                'url': 'http://example.com/new.mp4',
                'type': 'auto',
            },
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn('error', data)
        self.assertIn('Episode limit reached', data['error'])

    @override_settings(STASHCAST_MAX_EPISODES=5)
    def test_allows_download_when_below_limit(self):
        """Allows a download when under the episode limit."""
        MediaItem.objects.create(
            source_url='http://example.com/existing.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='existing-ep',
            title='Existing',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_READY,
        )

        response = self.client.get(
            '/stash/',
            {
                'token': self.user_token,
                'url': 'http://example.com/new.mp4',
                'type': 'auto',
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

    @override_settings(STASHCAST_MAX_EPISODES=0)
    def test_allows_download_when_limit_is_zero(self):
        """Allows downloads when STASHCAST_MAX_EPISODES=0 (unlimited)."""
        for i in range(10):
            MediaItem.objects.create(
                source_url=f'http://example.com/{i}.mp3',
                requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
                slug=f'ep-{i}',
                title=f'Episode {i}',
                media_type=MediaItem.MEDIA_TYPE_AUDIO,
                status=MediaItem.STATUS_READY,
            )

        response = self.client.get(
            '/stash/',
            {
                'token': self.user_token,
                'url': 'http://example.com/new.mp4',
                'type': 'auto',
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])


class AdminStashFormEpisodeLimitTest(TestCase):
    """Tests for episode limit enforcement at /admin/tools/add-url/."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser('admin', 'admin@test.com', 'password')
        self.client.login(username='admin', password='password')
        self.process_media_patcher = patch('media.views.process_media')
        self.mock_process_media = self.process_media_patcher.start()

    def tearDown(self):
        self.process_media_patcher.stop()

    @override_settings(STASHCAST_MAX_EPISODES=2)
    def test_blocks_post_with_error_when_at_limit(self):
        """POST is redirected with an error message when the limit is reached."""
        for i in range(2):
            MediaItem.objects.create(
                source_url=f'http://example.com/{i}.mp3',
                requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
                slug=f'ep-{i}',
                title=f'Episode {i}',
                media_type=MediaItem.MEDIA_TYPE_AUDIO,
                status=MediaItem.STATUS_READY,
            )

        response = self.client.post(
            '/admin/tools/add-url/',
            {'url': 'http://example.com/new.mp4', 'type': 'auto'},
        )
        # Should redirect back to the form
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/tools/add-url/', response.url)

        # Follow the redirect and check for the error message
        follow_response = self.client.get(response.url)
        self.assertContains(follow_response, 'Episode limit reached')

    @override_settings(STASHCAST_MAX_EPISODES=10)
    def test_allows_post_when_below_limit(self):
        """POST proceeds normally when the episode count is below the limit."""
        response = self.client.post(
            '/admin/tools/add-url/',
            {'url': 'http://example.com/new.mp4', 'type': 'auto'},
        )
        # Should redirect to the progress page (not back to the form with error)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('/admin/tools/add-url/$', response.url)
        # The process_media task should have been called
        self.mock_process_media.assert_called_once()


class StashCommandEpisodeLimitTest(TestCase):
    """Tests for episode limit enforcement in the stash management command."""

    @override_settings(STASHCAST_MAX_EPISODES=2)
    def test_blocks_stash_when_at_episode_limit(self):
        """The stash command exits with an error when the episode limit is reached."""
        from io import StringIO

        from django.core.management import call_command

        for i in range(2):
            MediaItem.objects.create(
                source_url=f'http://example.com/{i}.mp3',
                requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
                slug=f'ep-{i}',
                title=f'Episode {i}',
                media_type=MediaItem.MEDIA_TYPE_AUDIO,
                status=MediaItem.STATUS_READY,
            )

        stderr = StringIO()
        call_command('stash', 'http://example.com/new.mp3', stderr=stderr)
        self.assertIn('Episode limit reached', stderr.getvalue())

    @override_settings(STASHCAST_MAX_EPISODES=2)
    def test_blocks_stash_json_output_when_at_limit(self):
        """The stash command returns JSON error when at limit with --json flag."""
        import json
        from io import StringIO

        from django.core.management import call_command

        for i in range(3):
            MediaItem.objects.create(
                source_url=f'http://example.com/{i}.mp3',
                requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
                slug=f'ep-{i}',
                title=f'Episode {i}',
                media_type=MediaItem.MEDIA_TYPE_AUDIO,
                status=MediaItem.STATUS_READY,
            )

        stdout = StringIO()
        call_command('stash', 'http://example.com/new.mp3', '--json', stdout=stdout)
        output = json.loads(stdout.getvalue())
        self.assertEqual(output['status'], 'error')
        self.assertIn('Episode limit reached', output['error'])
        self.assertIn('3/2', output['error'])

    @override_settings(STASHCAST_MAX_EPISODES=0)
    def test_no_limit_when_max_episodes_is_zero(self):
        """The stash command does not block when STASHCAST_MAX_EPISODES=0."""
        from io import StringIO

        from django.core.management import call_command

        for i in range(5):
            MediaItem.objects.create(
                source_url=f'http://example.com/{i}.mp3',
                requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
                slug=f'ep-{i}',
                title=f'Episode {i}',
                media_type=MediaItem.MEDIA_TYPE_AUDIO,
                status=MediaItem.STATUS_READY,
            )

        stderr = StringIO()
        # This will fail for other reasons (network), but it should NOT fail
        # due to episode limit. We just check stderr doesn't mention the limit.
        call_command('stash', 'http://example.com/new.mp3', stderr=stderr)
        self.assertNotIn('Episode limit reached', stderr.getvalue())
