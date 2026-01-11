"""
Tests for admin views (grid, list, item detail, progress, SSE).

These views require authentication and provide the admin interface for managing media.
"""

import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from media.models import MediaItem

User = get_user_model()


class AdminGridViewTest(TestCase):
    """Test the grid view (/admin/tools/grid/)"""

    def setUp(self):
        self.client = Client()
        # Create superuser for authentication
        self.user = User.objects.create_superuser('admin', 'admin@test.com', 'password')
        self.client.login(username='admin', password='password')

    def test_grid_view_loads(self):
        """Test that grid view page loads successfully"""
        response = self.client.get('/admin/tools/grid/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'admin/grid_view.html')

    def test_grid_view_shows_ready_items(self):
        """Test that grid view shows READY items"""
        item = MediaItem.objects.create(
            source_url='http://example.com/test.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='test-audio',
            title='Test Audio',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_READY,
        )

        response = self.client.get('/admin/tools/grid/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Audio')

    def test_grid_view_hides_non_ready_items(self):
        """Test that grid view hides non-READY items"""
        MediaItem.objects.create(
            source_url='http://example.com/test.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='pending',
            title='Pending Item',
            status=MediaItem.STATUS_DOWNLOADING,
        )

        response = self.client.get('/admin/tools/grid/')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Pending Item')

    def test_grid_view_filter_audio(self):
        """Test filtering grid view by audio type"""
        MediaItem.objects.create(
            source_url='http://example.com/audio.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='test-audio',
            title='Audio Item',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_READY,
        )
        MediaItem.objects.create(
            source_url='http://example.com/video.mp4',
            requested_type=MediaItem.REQUESTED_TYPE_VIDEO,
            slug='test-video',
            title='Video Item',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
            status=MediaItem.STATUS_READY,
        )

        response = self.client.get('/admin/tools/grid/?type=audio')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Audio Item')
        self.assertNotContains(response, 'Video Item')

    def test_grid_view_filter_video(self):
        """Test filtering grid view by video type"""
        MediaItem.objects.create(
            source_url='http://example.com/audio.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='test-audio',
            title='Audio Item',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_READY,
        )
        MediaItem.objects.create(
            source_url='http://example.com/video.mp4',
            requested_type=MediaItem.REQUESTED_TYPE_VIDEO,
            slug='test-video',
            title='Video Item',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
            status=MediaItem.STATUS_READY,
        )

        response = self.client.get('/admin/tools/grid/?type=video')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Audio Item')
        self.assertContains(response, 'Video Item')

    def test_grid_view_requires_authentication(self):
        """Test that grid view requires login"""
        self.client.logout()
        response = self.client.get('/admin/tools/grid/')
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/admin/login/'))


class AdminListViewTest(TestCase):
    """Test the list view (/admin/tools/list/)"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser('admin', 'admin@test.com', 'password')
        self.client.login(username='admin', password='password')

    def test_list_view_loads(self):
        """Test that list view page loads successfully"""
        response = self.client.get('/admin/tools/list/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'admin/list_view.html')

    def test_list_view_shows_ready_items(self):
        """Test that list view shows READY items"""
        item = MediaItem.objects.create(
            source_url='http://example.com/test.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='test-audio',
            title='Test Audio',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_READY,
        )

        response = self.client.get('/admin/tools/list/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Audio')

    def test_list_view_shows_metadata(self):
        """Test that list view shows item metadata"""
        item = MediaItem.objects.create(
            source_url='http://example.com/test.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='test-audio',
            title='Test Audio',
            description='Test description',
            author='Test Author',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_READY,
            duration_seconds=180,
        )

        response = self.client.get('/admin/tools/list/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Audio')
        # Description might be truncated, so just check title and author appear
        self.assertContains(response, 'Test Author')

    def test_list_view_filter_audio(self):
        """Test filtering list view by audio type"""
        MediaItem.objects.create(
            source_url='http://example.com/audio.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='test-audio',
            title='Audio Item',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_READY,
        )
        MediaItem.objects.create(
            source_url='http://example.com/video.mp4',
            requested_type=MediaItem.REQUESTED_TYPE_VIDEO,
            slug='test-video',
            title='Video Item',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
            status=MediaItem.STATUS_READY,
        )

        response = self.client.get('/admin/tools/list/?type=audio')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Audio Item')
        self.assertNotContains(response, 'Video Item')


class AdminItemDetailViewTest(TestCase):
    """Test the item detail view (/admin/tools/item/<guid>/)"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser('admin', 'admin@test.com', 'password')
        self.client.login(username='admin', password='password')

    def test_item_detail_view_loads_audio(self):
        """Test that item detail page loads for audio"""
        item = MediaItem.objects.create(
            source_url='http://example.com/test.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='test-audio',
            title='Test Audio',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_READY,
            content_path='content.mp3',
        )

        response = self.client.get(f'/admin/tools/item/{item.guid}/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'admin/item_detail.html')
        self.assertContains(response, 'Test Audio')

    def test_item_detail_view_loads_video(self):
        """Test that item detail page loads for video"""
        item = MediaItem.objects.create(
            source_url='http://example.com/test.mp4',
            requested_type=MediaItem.REQUESTED_TYPE_VIDEO,
            slug='test-video',
            title='Test Video',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
            status=MediaItem.STATUS_READY,
            content_path='content.mp4',
        )

        response = self.client.get(f'/admin/tools/item/{item.guid}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Video')

    def test_item_detail_view_shows_player(self):
        """Test that item detail shows audio/video player"""
        item = MediaItem.objects.create(
            source_url='http://example.com/test.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='test-audio',
            title='Test Audio',
            media_type=MediaItem.MEDIA_TYPE_AUDIO,
            status=MediaItem.STATUS_READY,
            content_path='content.mp3',
        )

        response = self.client.get(f'/admin/tools/item/{item.guid}/')
        self.assertEqual(response.status_code, 200)
        # Should contain audio or video tag
        self.assertIn(b'<audio', response.content)

    def test_item_detail_view_shows_thumbnail(self):
        """Test that item detail shows thumbnail if available"""
        item = MediaItem.objects.create(
            source_url='http://example.com/test.mp4',
            requested_type=MediaItem.REQUESTED_TYPE_VIDEO,
            slug='test-video',
            title='Test Video',
            media_type=MediaItem.MEDIA_TYPE_VIDEO,
            status=MediaItem.STATUS_READY,
            content_path='content.mp4',
            thumbnail_path='thumbnail.jpg',
        )

        response = self.client.get(f'/admin/tools/item/{item.guid}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'thumbnail.jpg')

    def test_item_detail_view_404_for_invalid_guid(self):
        """Test that invalid GUID returns 404"""
        response = self.client.get('/admin/tools/item/invalid-guid-xyz/')
        self.assertEqual(response.status_code, 404)

    def test_item_detail_view_requires_authentication(self):
        """Test that item detail requires login"""
        item = MediaItem.objects.create(
            source_url='http://example.com/test.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='test-audio',
            title='Test Audio',
            status=MediaItem.STATUS_READY,
        )

        self.client.logout()
        response = self.client.get(f'/admin/tools/item/{item.guid}/')
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/admin/login/'))


class StashProgressViewTest(TestCase):
    """Test the progress view (/stash/<guid>/progress/)"""

    def setUp(self):
        self.client = Client()

    def test_progress_page_loads(self):
        """Test that progress page loads"""
        item = MediaItem.objects.create(
            source_url='http://example.com/test.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='pending',
            status=MediaItem.STATUS_DOWNLOADING,
        )

        response = self.client.get(f'/stash/{item.guid}/progress/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'media/stash_progress.html')

    def test_progress_page_shows_guid(self):
        """Test that progress page contains the GUID"""
        item = MediaItem.objects.create(
            source_url='http://example.com/test.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='pending',
            status=MediaItem.STATUS_DOWNLOADING,
        )

        response = self.client.get(f'/stash/{item.guid}/progress/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, item.guid)

    def test_progress_page_404_for_invalid_guid(self):
        """Test that invalid GUID returns 404"""
        response = self.client.get('/stash/invalid-guid-xyz/progress/')
        self.assertEqual(response.status_code, 404)


class SSEStatusStreamTest(TestCase):
    """Test the SSE endpoint (/stash/<guid>/status-stream/)"""

    def setUp(self):
        self.client = Client()

    def test_sse_endpoint_returns_stream(self):
        """Test that SSE endpoint returns correct response type and headers"""
        # Create item that's already READY so stream terminates immediately
        item = MediaItem.objects.create(
            source_url='http://example.com/test.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='test-audio',
            title='Test Audio',
            status=MediaItem.STATUS_READY,
        )

        response = self.client.get(f'/stash/{item.guid}/stream/')

        # Verify response type and headers
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/event-stream')
        self.assertEqual(response['Cache-Control'], 'no-cache')
        self.assertEqual(response['X-Accel-Buffering'], 'no')

    def test_sse_endpoint_returns_valid_data(self):
        """Test that SSE endpoint returns valid event data"""
        # Create item that's already READY so we can check the data format
        item = MediaItem.objects.create(
            source_url='http://example.com/test.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='test-audio',
            title='Test Audio',
            status=MediaItem.STATUS_READY,
        )

        response = self.client.get(f'/stash/{item.guid}/stream/')

        # Get first event from stream
        chunks = list(response.streaming_content)
        self.assertGreater(len(chunks), 0)

        first_event = chunks[0].decode()

        # Verify SSE format: "data: {...}\n\n"
        self.assertTrue(first_event.startswith('data: '))
        # Extract JSON data (remove "data: " prefix and whitespace)
        json_str = first_event[6:].strip()
        data = json.loads(json_str)

        # Verify expected fields
        self.assertEqual(data['status'], 'ready')
        self.assertEqual(data['title'], 'Test Audio')
        self.assertTrue(data['is_ready'])
        self.assertFalse(data['has_error'])

    def test_sse_endpoint_completes_on_ready(self):
        """Test that SSE stream completes when item is READY"""
        item = MediaItem.objects.create(
            source_url='http://example.com/test.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='test-audio',
            title='Test Audio',
            status=MediaItem.STATUS_READY,
        )

        response = self.client.get(f'/stash/{item.guid}/stream/')

        # Get all events
        chunks = list(response.streaming_content)

        # Should have at least 2 chunks: data event + complete event
        self.assertGreaterEqual(len(chunks), 2)

        # Last chunk should be completion event
        last_event = chunks[-1].decode()
        self.assertIn('event: complete', last_event)

    def test_sse_endpoint_completes_on_error(self):
        """Test that SSE stream completes when item has ERROR"""
        item = MediaItem.objects.create(
            source_url='http://example.com/test.mp3',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='pending',
            title='Test Audio',
            status=MediaItem.STATUS_ERROR,
            error_message='Test error',
        )

        response = self.client.get(f'/stash/{item.guid}/stream/')

        # Get all events
        chunks = list(response.streaming_content)

        # Should complete quickly with error
        self.assertGreater(len(chunks), 0)

        # First data event should show error
        first_event = chunks[0].decode()
        json_str = first_event[6:].strip()
        data = json.loads(json_str)

        self.assertEqual(data['status'], 'error')
        self.assertTrue(data['has_error'])
        self.assertEqual(data['error_message'], 'Test error')

    def test_sse_endpoint_handles_missing_item(self):
        """Test that SSE gracefully handles deleted items"""
        response = self.client.get('/stash/nonexistent-guid/stream/')

        chunks = list(response.streaming_content)

        # Should yield error event
        self.assertGreater(len(chunks), 0)
        first_chunk = chunks[0].decode()
        self.assertIn('event: error', first_chunk)
        self.assertIn('Item not found', first_chunk)
