"""
Tests for service/spotify.py
"""

from django.test import TestCase

from media.service.spotify import (
    is_spotify_url,
    get_spotify_type,
    get_spotify_id,
    build_search_query,
    SpotifyMetadata,
)


class SpotifyUrlDetectionTest(TestCase):
    """Tests for Spotify URL detection"""

    def test_is_spotify_url_episode(self):
        """Test detection of Spotify episode URL"""
        url = 'https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk'
        self.assertTrue(is_spotify_url(url))

    def test_is_spotify_url_show(self):
        """Test detection of Spotify show URL"""
        url = 'https://open.spotify.com/show/2mTUnDkuKUkhiueKcVWoP0'
        self.assertTrue(is_spotify_url(url))

    def test_is_spotify_url_track(self):
        """Test detection of Spotify track URL"""
        url = 'https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT'
        self.assertTrue(is_spotify_url(url))

    def test_is_spotify_url_album(self):
        """Test detection of Spotify album URL"""
        url = 'https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy'
        self.assertTrue(is_spotify_url(url))

    def test_is_spotify_url_not_spotify(self):
        """Test that non-Spotify URLs are not detected"""
        urls = [
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'https://example.com/audio.mp3',
            'https://soundcloud.com/artist/track',
        ]
        for url in urls:
            self.assertFalse(is_spotify_url(url))


class SpotifyTypeDetectionTest(TestCase):
    """Tests for Spotify content type detection"""

    def test_get_spotify_type_episode(self):
        """Test episode type detection"""
        url = 'https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk'
        self.assertEqual(get_spotify_type(url), 'episode')

    def test_get_spotify_type_show(self):
        """Test show type detection"""
        url = 'https://open.spotify.com/show/2mTUnDkuKUkhiueKcVWoP0'
        self.assertEqual(get_spotify_type(url), 'show')

    def test_get_spotify_type_track(self):
        """Test track type detection"""
        url = 'https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT'
        self.assertEqual(get_spotify_type(url), 'track')

    def test_get_spotify_type_album(self):
        """Test album type detection"""
        url = 'https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy'
        self.assertEqual(get_spotify_type(url), 'album')

    def test_get_spotify_type_unknown(self):
        """Test unknown URL type returns None"""
        url = 'https://open.spotify.com/user/12345'
        self.assertIsNone(get_spotify_type(url))


class SpotifyIdExtractionTest(TestCase):
    """Tests for Spotify ID extraction"""

    def test_get_spotify_id_episode(self):
        """Test episode ID extraction"""
        url = 'https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk'
        self.assertEqual(get_spotify_id(url), '4rOoJ6Egrf8K2IrywzwOMk')

    def test_get_spotify_id_with_query_params(self):
        """Test ID extraction with query parameters"""
        url = 'https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk?si=abc123'
        self.assertEqual(get_spotify_id(url), '4rOoJ6Egrf8K2IrywzwOMk')

    def test_get_spotify_id_track(self):
        """Test track ID extraction"""
        url = 'https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT'
        self.assertEqual(get_spotify_id(url), '4cOdK2wGLETKBW3PvgPWqT')


class SearchQueryBuildingTest(TestCase):
    """Tests for YouTube search query building"""

    def test_build_search_query_episode(self):
        """Test search query for podcast episode"""
        metadata = SpotifyMetadata(
            title='Episode 100: The Big Interview',
            author='The Best Podcast',
            spotify_url='https://open.spotify.com/episode/abc123',
            spotify_type='episode',
            spotify_id='abc123',
        )
        query = build_search_query(metadata)
        self.assertIn('Episode 100', query)
        self.assertIn('The Best Podcast', query)
        self.assertIn('podcast', query)

    def test_build_search_query_episode_already_has_podcast(self):
        """Test that 'podcast' is not added if already in title"""
        metadata = SpotifyMetadata(
            title='My Podcast Episode 100',
            author='The Show',
            spotify_url='https://open.spotify.com/episode/abc123',
            spotify_type='episode',
            spotify_id='abc123',
        )
        query = build_search_query(metadata)
        # Should only have one instance of podcast-related word
        self.assertEqual(query.lower().count('podcast'), 1)

    def test_build_search_query_track(self):
        """Test search query for music track"""
        metadata = SpotifyMetadata(
            title='Never Gonna Give You Up',
            author='Rick Astley',
            spotify_url='https://open.spotify.com/track/abc123',
            spotify_type='track',
            spotify_id='abc123',
        )
        query = build_search_query(metadata)
        self.assertIn('Never Gonna Give You Up', query)
        self.assertIn('Rick Astley', query)
        # Should not add 'podcast' for tracks
        self.assertNotIn('podcast', query.lower())

    def test_build_search_query_no_author(self):
        """Test search query when author is not available"""
        metadata = SpotifyMetadata(
            title='Some Episode Title',
            author=None,
            spotify_url='https://open.spotify.com/episode/abc123',
            spotify_type='episode',
            spotify_id='abc123',
        )
        query = build_search_query(metadata)
        self.assertIn('Some Episode Title', query)

    def test_build_search_query_cleans_special_characters(self):
        """Test that special characters are cleaned from query"""
        metadata = SpotifyMetadata(
            title='Episode #100: "The Interview" (Part 1)',
            author=None,
            spotify_url='https://open.spotify.com/episode/abc123',
            spotify_type='episode',
            spotify_id='abc123',
        )
        query = build_search_query(metadata)
        # Should not have quotes or parentheses
        self.assertNotIn('"', query)
        self.assertNotIn('(', query)
        self.assertNotIn(')', query)


class StrategyIntegrationTest(TestCase):
    """Tests for Spotify strategy in choose_download_strategy"""

    def test_spotify_url_returns_spotify_strategy(self):
        """Test that Spotify URLs return 'spotify' strategy"""
        from media.service.strategy import choose_download_strategy

        urls = [
            'https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk',
            'https://open.spotify.com/show/2mTUnDkuKUkhiueKcVWoP0',
            'https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT',
            'https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy',
        ]

        for url in urls:
            strategy = choose_download_strategy(url)
            self.assertEqual(strategy, 'spotify', f'Failed for URL: {url}')

    def test_youtube_url_still_returns_ytdlp(self):
        """Test that YouTube URLs still return 'ytdlp' strategy"""
        from media.service.strategy import choose_download_strategy

        url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'ytdlp')
