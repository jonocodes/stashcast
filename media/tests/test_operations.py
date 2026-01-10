"""
Tests for media/operations.py

Tests high-level operations that can be called from views, tasks, or commands.
"""

from unittest.mock import patch

from django.test import TestCase

from media.models import MediaItem
from media.operations import stash_url


class StashUrlOperationTest(TestCase):
    """Test the stash_url operation"""

    def setUp(self):
        # Mock process_media task to prevent actual downloads
        self.process_media_patcher = patch('media.operations.process_media')
        self.mock_process_media = self.process_media_patcher.start()

    def tearDown(self):
        self.process_media_patcher.stop()

    def test_stash_url_creates_new_item(self):
        """Test that stash_url creates a new MediaItem"""
        item = stash_url('http://example.com/test.mp3', requested_type='audio', wait=False)

        self.assertIsNotNone(item)
        self.assertIsNotNone(item.guid)
        self.assertEqual(item.source_url, 'http://example.com/test.mp3')
        self.assertEqual(item.requested_type, MediaItem.REQUESTED_TYPE_AUDIO)
        self.assertEqual(item.slug, 'pending')

    def test_stash_url_enqueues_task(self):
        """Test that stash_url enqueues background task when wait=False"""
        item = stash_url('http://example.com/test.mp3', requested_type='audio', wait=False)

        # Should call process_media (not call_local)
        self.mock_process_media.assert_called_once_with(item.guid)

    def test_stash_url_runs_synchronously(self):
        """Test that stash_url runs synchronously when wait=True"""
        item = stash_url('http://example.com/test.mp3', requested_type='audio', wait=True)

        # Should call process_media.call_local
        self.mock_process_media.call_local.assert_called_once_with(item.guid)

    def test_stash_url_reuses_existing_auto(self):
        """Test that stash_url reuses existing item for same URL with auto type"""
        # Create initial item
        item1 = stash_url('http://example.com/test.mp3', requested_type='auto', wait=False)
        guid1 = item1.guid

        # Stash same URL again with auto type
        item2 = stash_url('http://example.com/test.mp3', requested_type='auto', wait=False)
        guid2 = item2.guid

        # Should reuse the same item
        self.assertEqual(guid1, guid2)
        self.assertEqual(MediaItem.objects.count(), 1)

    def test_stash_url_reuses_existing_explicit_type(self):
        """Test that stash_url reuses existing item for same URL with explicit type"""
        # Create initial item and simulate it becoming audio
        item1 = stash_url('http://example.com/test.mp3', requested_type='audio', wait=False)
        item1.media_type = MediaItem.MEDIA_TYPE_AUDIO
        item1.save()
        guid1 = item1.guid

        # Stash same URL again with audio type
        item2 = stash_url('http://example.com/test.mp3', requested_type='audio', wait=False)
        guid2 = item2.guid

        # Should reuse the same item
        self.assertEqual(guid1, guid2)
        self.assertEqual(MediaItem.objects.count(), 1)

    def test_stash_url_creates_separate_items_for_different_types(self):
        """Test that stash_url creates separate items for same URL with different types"""
        # Create audio item
        item1 = stash_url('http://example.com/content', requested_type='audio', wait=False)
        item1.media_type = MediaItem.MEDIA_TYPE_AUDIO
        item1.slug = 'content-audio'
        item1.save()

        # Create video item from same URL
        item2 = stash_url('http://example.com/content', requested_type='video', wait=False)

        # Should create separate items
        self.assertNotEqual(item1.guid, item2.guid)
        self.assertEqual(MediaItem.objects.count(), 2)

    def test_stash_url_resets_error_on_reuse(self):
        """Test that stash_url resets error status when reusing item"""
        # Create item with error
        item1 = stash_url('http://example.com/test.mp3', requested_type='auto', wait=False)
        item1.status = MediaItem.STATUS_ERROR
        item1.error_message = 'Previous error'
        item1.save()

        # Stash again
        item2 = stash_url('http://example.com/test.mp3', requested_type='auto', wait=False)

        # Should reset error state
        self.assertEqual(item2.guid, item1.guid)
        self.assertEqual(item2.status, MediaItem.STATUS_PREFETCHING)
        self.assertEqual(item2.error_message, '')

    def test_stash_url_with_logger(self):
        """Test that stash_url calls logger when provided"""
        logged_messages = []

        def test_logger(message):
            logged_messages.append(message)

        item = stash_url(
            'http://example.com/test.mp3', requested_type='audio', wait=False, logger=test_logger
        )

        # Should have logged messages
        self.assertGreater(len(logged_messages), 0)
        self.assertTrue(any('Created new item' in msg for msg in logged_messages))

    def test_stash_url_type_mapping(self):
        """Test that requested_type strings are correctly mapped to constants"""
        item_auto = stash_url('http://example.com/1.mp3', requested_type='auto', wait=False)
        self.assertEqual(item_auto.requested_type, MediaItem.REQUESTED_TYPE_AUTO)

        item_audio = stash_url('http://example.com/2.mp3', requested_type='audio', wait=False)
        self.assertEqual(item_audio.requested_type, MediaItem.REQUESTED_TYPE_AUDIO)

        item_video = stash_url('http://example.com/3.mp4', requested_type='video', wait=False)
        self.assertEqual(item_video.requested_type, MediaItem.REQUESTED_TYPE_VIDEO)

    def test_stash_url_invalid_type_defaults_to_auto(self):
        """Test that invalid requested_type defaults to auto"""
        item = stash_url('http://example.com/test.mp3', requested_type='invalid', wait=False)
        self.assertEqual(item.requested_type, MediaItem.REQUESTED_TYPE_AUTO)
