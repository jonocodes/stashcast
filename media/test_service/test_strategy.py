"""
Tests for service/strategy.py
"""

from django.test import TestCase
from media.service.strategy import choose_download_strategy


class StrategyServiceTest(TestCase):
    """Tests for download strategy detection"""

    def test_direct_mp3_url(self):
        """Test direct MP3 URL detection"""
        url = 'https://example.com/audio.mp3'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'direct')

    def test_direct_mp4_url(self):
        """Test direct MP4 URL detection"""
        url = 'https://example.com/video.mp4'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'direct')

    def test_direct_m4a_url(self):
        """Test direct M4A URL detection"""
        url = 'https://example.com/audio.m4a'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'direct')

    def test_direct_webm_url(self):
        """Test direct WebM URL detection"""
        url = 'https://example.com/video.webm'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'direct')

    def test_direct_ogg_url(self):
        """Test direct OGG URL detection"""
        url = 'https://example.com/audio.ogg'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'direct')

    def test_direct_wav_url(self):
        """Test direct WAV URL detection"""
        url = 'https://example.com/audio.wav'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'direct')

    def test_direct_mkv_url(self):
        """Test direct MKV URL detection"""
        url = 'https://example.com/video.mkv'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'direct')

    def test_direct_avi_url(self):
        """Test direct AVI URL detection"""
        url = 'https://example.com/video.avi'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'direct')

    def test_direct_mov_url(self):
        """Test direct MOV URL detection"""
        url = 'https://example.com/video.mov'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'direct')

    def test_direct_flac_url(self):
        """Test direct FLAC URL detection"""
        url = 'https://example.com/audio.flac'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'direct')

    def test_direct_aac_url(self):
        """Test direct AAC URL detection"""
        url = 'https://example.com/audio.aac'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'direct')

    def test_direct_opus_url(self):
        """Test direct Opus URL detection"""
        url = 'https://example.com/audio.opus'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'direct')

    def test_direct_url_with_query_params(self):
        """Test direct URL with query parameters"""
        url = 'https://example.com/audio.mp3?token=abc123&expires=456'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'direct')

    def test_direct_url_case_insensitive(self):
        """Test that extension matching is case-insensitive"""
        url = 'https://example.com/audio.MP3'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'direct')

    def test_ytdlp_youtube_url(self):
        """Test YouTube URL uses yt-dlp"""
        url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'ytdlp')

    def test_ytdlp_vimeo_url(self):
        """Test Vimeo URL uses yt-dlp"""
        url = 'https://vimeo.com/123456789'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'ytdlp')

    def test_ytdlp_html_page(self):
        """Test HTML page URL uses yt-dlp"""
        url = 'https://example.com/page.html'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'ytdlp')

    def test_ytdlp_no_extension(self):
        """Test URL without extension uses yt-dlp"""
        url = 'https://example.com/video'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'ytdlp')

    def test_ytdlp_root_url(self):
        """Test root URL uses yt-dlp"""
        url = 'https://example.com/'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'ytdlp')

    def test_ytdlp_non_media_extension(self):
        """Test non-media extension uses yt-dlp"""
        url = 'https://example.com/page.php'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'ytdlp')

    def test_direct_url_with_path(self):
        """Test direct URL with complex path"""
        url = 'https://cdn.example.com/media/2024/01/audio/file.mp3'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'direct')

    def test_direct_url_subdomain(self):
        """Test direct URL with subdomain"""
        url = 'https://media.cdn.example.com/video.mp4'
        strategy = choose_download_strategy(url)
        self.assertEqual(strategy, 'direct')
