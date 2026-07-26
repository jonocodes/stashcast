"""
Tests for the YouTube channel auto-sync feature.

Covers the channel-listing service (URL normalization + entry parsing) and the
sync operations (dedup, group assignment, last-synced bookkeeping). yt-dlp and the
download pipeline are mocked so no network or ffmpeg work happens.
"""

from unittest.mock import patch

from django.test import TestCase, override_settings

from media.models import MediaGroup, MediaItem
from media.operations import sync_all_youtube_channels, sync_group_channel
from media.service.youtube_channel import (
    ChannelVideo,
    list_channel_videos,
    normalize_channel_url,
)


class NormalizeChannelUrlTest(TestCase):
    def test_handle_root_gets_videos_tab(self):
        self.assertEqual(
            normalize_channel_url('https://www.youtube.com/@channel'),
            'https://www.youtube.com/@channel/videos',
        )

    def test_channel_id_root_gets_videos_tab(self):
        self.assertEqual(
            normalize_channel_url('https://www.youtube.com/channel/UC123/'),
            'https://www.youtube.com/channel/UC123/videos',
        )

    def test_existing_tab_left_untouched(self):
        url = 'https://www.youtube.com/@channel/streams'
        self.assertEqual(normalize_channel_url(url), url)

    def test_playlist_left_untouched(self):
        url = 'https://www.youtube.com/playlist?list=PL123'
        self.assertEqual(normalize_channel_url(url), url)

    def test_whitespace_stripped(self):
        self.assertEqual(
            normalize_channel_url('  https://www.youtube.com/@c  '),
            'https://www.youtube.com/@c/videos',
        )


class ListChannelVideosTest(TestCase):
    def _mock_ydl(self, info):
        """Return a context-manager mock whose extract_info yields `info`."""
        mock_ydl = patch('media.service.youtube_channel.yt_dlp.YoutubeDL').start()
        self.addCleanup(patch.stopall)
        instance = mock_ydl.return_value.__enter__.return_value
        instance.extract_info.return_value = info
        return mock_ydl, instance

    def test_parses_flat_entries(self):
        info = {
            'entries': [
                {'url': 'https://www.youtube.com/watch?v=aaa', 'title': 'A', 'id': 'aaa'},
                {'url': 'https://www.youtube.com/watch?v=bbb', 'title': 'B', 'id': 'bbb'},
            ]
        }
        self._mock_ydl(info)
        videos = list_channel_videos('https://www.youtube.com/@c', max_videos=5)
        self.assertEqual([v.url for v in videos], [
            'https://www.youtube.com/watch?v=aaa',
            'https://www.youtube.com/watch?v=bbb',
        ])
        self.assertEqual(videos[0].title, 'A')

    def test_bare_id_entry_expanded_to_watch_url(self):
        info = {'entries': [{'url': 'zzz', 'title': 'Z'}]}
        self._mock_ydl(info)
        videos = list_channel_videos('https://www.youtube.com/@c')
        self.assertEqual(videos[0].url, 'https://www.youtube.com/watch?v=zzz')
        self.assertEqual(videos[0].external_id, 'zzz')

    def test_max_videos_caps_results(self):
        info = {'entries': [{'url': f'https://youtu.be/{i}', 'id': str(i)} for i in range(10)]}
        self._mock_ydl(info)
        videos = list_channel_videos('https://www.youtube.com/@c', max_videos=3)
        self.assertEqual(len(videos), 3)

    def test_nested_playlists_flattened(self):
        info = {
            'entries': [
                {'entries': [
                    {'url': 'https://www.youtube.com/watch?v=n1', 'id': 'n1'},
                    {'url': 'https://www.youtube.com/watch?v=n2', 'id': 'n2'},
                ]},
            ]
        }
        self._mock_ydl(info)
        videos = list_channel_videos('https://www.youtube.com/@c', max_videos=5)
        self.assertEqual([v.url for v in videos], [
            'https://www.youtube.com/watch?v=n1',
            'https://www.youtube.com/watch?v=n2',
        ])

    def test_single_video_info(self):
        info = {'url': 'https://www.youtube.com/watch?v=solo', 'id': 'solo', 'title': 'Solo'}
        self._mock_ydl(info)
        videos = list_channel_videos('https://www.youtube.com/watch?v=solo')
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0].external_id, 'solo')

    def test_empty_info_returns_empty(self):
        self._mock_ydl(None)
        self.assertEqual(list_channel_videos('https://www.youtube.com/@c'), [])


class SyncGroupChannelTest(TestCase):
    def setUp(self):
        # Prevent real downloads: stash_url calls process_media.
        self.process_media = patch('media.tasks.process_media').start()
        self.addCleanup(patch.stopall)
        self.group = MediaGroup.objects.create(
            name='Lekcje', youtube_channel_url='https://www.youtube.com/@lekcje'
        )

    def _patch_listing(self, videos):
        return patch(
            'media.service.youtube_channel.list_channel_videos', return_value=videos
        )

    def test_stashes_new_uploads_into_group(self):
        videos = [
            ChannelVideo(url='https://youtu.be/v1', title='One', external_id='v1'),
            ChannelVideo(url='https://youtu.be/v2', title='Two', external_id='v2'),
        ]
        with self._patch_listing(videos):
            items = sync_group_channel(self.group)

        self.assertEqual(len(items), 2)
        for item in items:
            self.assertEqual(item.group_id, self.group.pk)
            self.assertEqual(item.requested_type, MediaItem.REQUESTED_TYPE_AUDIO)
        self.assertEqual(MediaItem.objects.filter(group=self.group).count(), 2)

    def test_skips_already_present_videos(self):
        MediaItem.objects.create(
            source_url='https://youtu.be/v1',
            requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
            slug='v1',
            group=self.group,
        )
        videos = [
            ChannelVideo(url='https://youtu.be/v1', title='One'),
            ChannelVideo(url='https://youtu.be/v2', title='Two'),
        ]
        with self._patch_listing(videos):
            items = sync_group_channel(self.group)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_url, 'https://youtu.be/v2')
        self.assertEqual(MediaItem.objects.filter(group=self.group).count(), 2)

    def test_second_run_finds_nothing_new(self):
        videos = [ChannelVideo(url='https://youtu.be/v1', title='One')]
        with self._patch_listing(videos):
            first = sync_group_channel(self.group)
        with self._patch_listing(videos):
            second = sync_group_channel(self.group)

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0)

    def test_updates_last_synced_timestamp(self):
        self.assertIsNone(self.group.youtube_last_synced_at)
        with self._patch_listing([]):
            sync_group_channel(self.group)
        self.group.refresh_from_db()
        self.assertIsNotNone(self.group.youtube_last_synced_at)

    def test_group_without_channel_is_skipped(self):
        plain = MediaGroup.objects.create(name='Bez kanału')
        items = sync_group_channel(plain)
        self.assertEqual(items, [])

    def test_wait_flag_runs_synchronously(self):
        videos = [ChannelVideo(url='https://youtu.be/v1', title='One')]
        with self._patch_listing(videos):
            sync_group_channel(self.group, wait=True)
        self.process_media.call_local.assert_called_once()


class SyncAllYoutubeChannelsTest(TestCase):
    def setUp(self):
        patch('media.tasks.process_media').start()
        self.addCleanup(patch.stopall)

    def test_only_configured_groups_synced(self):
        configured = MediaGroup.objects.create(
            name='A', youtube_channel_url='https://www.youtube.com/@a'
        )
        MediaGroup.objects.create(name='B')  # no channel

        def fake_list(url, max_videos=5, logger=None):
            return [ChannelVideo(url='https://youtu.be/x', title='X')]

        with patch('media.service.youtube_channel.list_channel_videos', side_effect=fake_list):
            items = sync_all_youtube_channels()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].group_id, configured.pk)

    def test_one_failing_group_does_not_abort_others(self):
        MediaGroup.objects.create(name='Good', youtube_channel_url='https://youtube.com/@good')
        MediaGroup.objects.create(name='Bad', youtube_channel_url='https://youtube.com/@bad')

        def fake_list(url, max_videos=5, logger=None):
            if 'bad' in url:
                raise RuntimeError('boom')
            return [ChannelVideo(url='https://youtu.be/ok', title='OK')]

        with patch('media.service.youtube_channel.list_channel_videos', side_effect=fake_list):
            items = sync_all_youtube_channels()

        self.assertEqual(len(items), 1)


@override_settings(STASHCAST_YOUTUBE_SYNC_HOURS=6)
class YoutubeSyncCrontabTest(TestCase):
    def test_crontab_built_from_settings(self):
        from media.tasks import _youtube_sync_crontab

        # Should not raise and should match at hour 6, minute 0.
        cron = _youtube_sync_crontab()
        self.assertTrue(callable(cron))
