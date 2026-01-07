"""
Tests for service/config.py
"""

from django.test import TestCase, override_settings
from media.service.config import (
    get_ytdlp_args_for_type,
    get_ffmpeg_args_for_type,
    get_media_dir,
    get_acceptable_audio_formats,
    get_acceptable_video_formats,
    get_target_audio_format,
    get_target_video_format,
    parse_ytdlp_extra_args,
)


class ConfigServiceTest(TestCase):
    """Tests for configuration adapter"""

    def test_get_ytdlp_args_audio(self):
        """Test getting yt-dlp args for audio"""
        args = get_ytdlp_args_for_type('audio')
        self.assertIsInstance(args, str)
        self.assertIn('m4a', args.lower())

    def test_get_ytdlp_args_video(self):
        """Test getting yt-dlp args for video"""
        args = get_ytdlp_args_for_type('video')
        self.assertIsInstance(args, str)
        self.assertIn('mp4', args.lower())

    def test_get_ytdlp_args_invalid(self):
        """Test getting yt-dlp args for invalid type"""
        args = get_ytdlp_args_for_type('invalid')
        self.assertEqual(args, '')

    def test_get_ffmpeg_args_audio(self):
        """Test getting ffmpeg args for audio"""
        args = get_ffmpeg_args_for_type('audio')
        self.assertIsInstance(args, str)
        self.assertIn('aac', args.lower())

    def test_get_ffmpeg_args_video(self):
        """Test getting ffmpeg args for video"""
        args = get_ffmpeg_args_for_type('video')
        self.assertIsInstance(args, str)
        self.assertIn('x264', args.lower())

    def test_get_ffmpeg_args_invalid(self):
        """Test getting ffmpeg args for invalid type"""
        args = get_ffmpeg_args_for_type('invalid')
        self.assertEqual(args, '')

    def test_get_media_dir(self):
        """Test getting media directory"""
        media_dir = get_media_dir()
        self.assertIsNotNone(media_dir)
        self.assertIn('media', str(media_dir).lower())

    def test_get_acceptable_audio_formats(self):
        """Test getting acceptable audio formats"""
        formats = get_acceptable_audio_formats()
        self.assertIsInstance(formats, list)
        self.assertIn('.mp3', formats)
        self.assertIn('.m4a', formats)

    def test_get_acceptable_video_formats(self):
        """Test getting acceptable video formats"""
        formats = get_acceptable_video_formats()
        self.assertIsInstance(formats, list)
        self.assertIn('.mp4', formats)

    def test_get_target_audio_format(self):
        """Test getting target audio format"""
        target = get_target_audio_format()
        self.assertEqual(target, '.m4a')

    def test_get_target_video_format(self):
        """Test getting target video format"""
        target = get_target_video_format()
        self.assertEqual(target, '.mp4')

    @override_settings(STASHCAST_DEFAULT_YTDLP_ARGS_AUDIO='--custom-audio-arg')
    def test_custom_ytdlp_audio_args(self):
        """Test that custom settings are respected"""
        args = get_ytdlp_args_for_type('audio')
        self.assertEqual(args, '--custom-audio-arg')

    @override_settings(STASHCAST_DEFAULT_FFMPEG_ARGS_VIDEO='-custom-video-arg')
    def test_custom_ffmpeg_video_args(self):
        """Test that custom settings are respected"""
        args = get_ffmpeg_args_for_type('video')
        self.assertEqual(args, '-custom-video-arg')


class ParseYtdlpArgsTest(TestCase):
    """Tests for parse_ytdlp_extra_args function"""

    def test_parse_empty_string(self):
        """Test parsing with empty string"""
        base_opts = {'format': 'best', 'quiet': True}
        result = parse_ytdlp_extra_args('', base_opts)
        self.assertEqual(result, {'format': 'best', 'quiet': True})

    def test_parse_none(self):
        """Test parsing with None"""
        base_opts = {'format': 'best'}
        result = parse_ytdlp_extra_args(None, base_opts)
        self.assertEqual(result, {'format': 'best'})

    def test_parse_format_long(self):
        """Test parsing --format argument"""
        base_opts = {'format': 'best', 'quiet': True}
        result = parse_ytdlp_extra_args('--format "bestaudio"', base_opts)
        self.assertEqual(result['format'], 'bestaudio')
        self.assertEqual(result['quiet'], True)

    def test_parse_format_short(self):
        """Test parsing -f (short format) argument"""
        base_opts = {'format': 'best'}
        result = parse_ytdlp_extra_args('-f bestaudio', base_opts)
        self.assertEqual(result['format'], 'bestaudio')

    def test_parse_merge_output_format(self):
        """Test parsing --merge-output-format argument"""
        base_opts = {}
        result = parse_ytdlp_extra_args('--merge-output-format mp4', base_opts)
        self.assertEqual(result['merge_output_format'], 'mp4')

    def test_parse_audio_format(self):
        """Test parsing --audio-format argument"""
        base_opts = {}
        result = parse_ytdlp_extra_args('--audio-format mp3', base_opts)
        self.assertIn('postprocessors', result)
        self.assertEqual(len(result['postprocessors']), 1)
        self.assertEqual(result['postprocessors'][0]['key'], 'FFmpegExtractAudio')
        self.assertEqual(result['postprocessors'][0]['preferredcodec'], 'mp3')

    def test_parse_complex_format_string(self):
        """Test parsing complex format with quotes and brackets"""
        base_opts = {'quiet': True}
        result = parse_ytdlp_extra_args(
            '--format "bv*[height<=720][vcodec^=avc]+ba/b[height<=720]"', base_opts
        )
        self.assertEqual(result['format'], 'bv*[height<=720][vcodec^=avc]+ba/b[height<=720]')
        self.assertEqual(result['quiet'], True)

    def test_parse_multiple_arguments(self):
        """Test parsing multiple arguments"""
        base_opts = {}
        result = parse_ytdlp_extra_args('--format bestaudio --merge-output-format mp4', base_opts)
        self.assertEqual(result['format'], 'bestaudio')
        self.assertEqual(result['merge_output_format'], 'mp4')

    def test_preserves_existing_options(self):
        """Test that existing options are preserved"""
        base_opts = {'format': 'best', 'quiet': True, 'writethumbnail': True, 'noplaylist': True}
        result = parse_ytdlp_extra_args('--format bestaudio', base_opts)
        self.assertEqual(result['format'], 'bestaudio')
        self.assertEqual(result['quiet'], True)
        self.assertEqual(result['writethumbnail'], True)
        self.assertEqual(result['noplaylist'], True)

    def test_unknown_args_ignored(self):
        """Test that unknown arguments are silently ignored"""
        base_opts = {'format': 'best'}
        result = parse_ytdlp_extra_args('--format bestaudio --unknown-arg value', base_opts)
        self.assertEqual(result['format'], 'bestaudio')
        self.assertNotIn('unknown-arg', result)

    def test_format_without_value(self):
        """Test format flag without value (should skip)"""
        base_opts = {'format': 'best'}
        result = parse_ytdlp_extra_args('--format', base_opts)
        # Should keep original format since no value provided
        self.assertEqual(result['format'], 'best')

    def test_real_world_720p_format(self):
        """Test with actual 720p format string from settings"""
        base_opts = {'quiet': True}
        result = parse_ytdlp_extra_args(
            '--format "bv*[height<=720][vcodec^=avc]+ba/b[height<=720]" --merge-output-format mp4',
            base_opts,
        )
        self.assertEqual(result['format'], 'bv*[height<=720][vcodec^=avc]+ba/b[height<=720]')
        self.assertEqual(result['merge_output_format'], 'mp4')
