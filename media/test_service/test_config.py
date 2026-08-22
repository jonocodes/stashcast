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
    merge_extractor_args,
    parse_cookies_from_browser,
    parse_extractor_args,
    parse_impersonate_target,
    parse_js_runtimes,
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


class ExtractorArgsTest(TestCase):
    """Tests for --extractor-args parsing (YouTube 403 workarounds)"""

    def test_parse_single_key(self):
        """Test parsing one key with one value"""
        result = parse_extractor_args('youtube:player_client=tv')
        self.assertEqual(result, {'youtube': {'player_client': ['tv']}})

    def test_parse_multiple_values(self):
        """Test parsing one key with a comma-separated value list"""
        result = parse_extractor_args('youtube:player_client=tv,web_safari')
        self.assertEqual(result, {'youtube': {'player_client': ['tv', 'web_safari']}})

    def test_parse_multiple_keys(self):
        """Test parsing several semicolon-separated keys"""
        result = parse_extractor_args('youtube:player_client=tv;formats=missing_pot')
        self.assertEqual(
            result,
            {'youtube': {'player_client': ['tv'], 'formats': ['missing_pot']}},
        )

    def test_merge_keeps_other_extractors(self):
        """Test that merging does not drop args of a different extractor"""
        base_opts = {'extractor_args': {'generic': {'impersonate': ['chrome']}}}
        merge_extractor_args(base_opts, {'youtube': {'player_client': ['tv']}})
        self.assertEqual(base_opts['extractor_args']['generic'], {'impersonate': ['chrome']})
        self.assertEqual(base_opts['extractor_args']['youtube'], {'player_client': ['tv']})

    def test_merge_overrides_same_key(self):
        """Test that merging the same key replaces its value"""
        base_opts = {'extractor_args': {'youtube': {'player_client': ['web']}}}
        merge_extractor_args(base_opts, {'youtube': {'player_client': ['tv']}})
        self.assertEqual(base_opts['extractor_args']['youtube']['player_client'], ['tv'])

    def test_extractor_args_via_extra_args(self):
        """Test that --extractor-args reaches the yt-dlp options dict"""
        result = parse_ytdlp_extra_args(
            '--format bestaudio --extractor-args "youtube:player_client=tv,mweb"',
            {'quiet': True},
        )
        self.assertEqual(result['format'], 'bestaudio')
        self.assertEqual(result['extractor_args']['youtube']['player_client'], ['tv', 'mweb'])


class NetworkArgsTest(TestCase):
    """Tests for the network-related yt-dlp arguments used against 403 errors"""

    def test_cookies_file(self):
        """Test that --cookies maps to cookiefile"""
        result = parse_ytdlp_extra_args('--cookies /data/cookies.txt', {})
        self.assertEqual(result['cookiefile'], '/data/cookies.txt')

    def test_cookies_from_browser_simple(self):
        """Test parsing a browser name without a profile"""
        self.assertEqual(parse_cookies_from_browser('firefox'), ('firefox', None, None, None))

    def test_cookies_from_browser_with_profile(self):
        """Test parsing a browser name with a profile"""
        self.assertEqual(
            parse_cookies_from_browser('chrome:Default'), ('chrome', 'Default', None, None)
        )

    def test_cookies_from_browser_with_keyring(self):
        """Test parsing a browser name with a keyring"""
        self.assertEqual(
            parse_cookies_from_browser('chrome+gnomekeyring:Profile 1'),
            ('chrome', 'Profile 1', 'GNOMEKEYRING', None),
        )

    def test_user_agent_and_referer(self):
        """Test that header overrides end up in http_headers"""
        result = parse_ytdlp_extra_args(
            '--user-agent "Mozilla/5.0" --referer https://www.youtube.com/', {}
        )
        self.assertEqual(result['http_headers']['User-Agent'], 'Mozilla/5.0')
        self.assertEqual(result['http_headers']['Referer'], 'https://www.youtube.com/')

    def test_impersonate(self):
        """Test that --impersonate becomes an ImpersonateTarget, not a raw string"""
        from yt_dlp.networking.impersonate import ImpersonateTarget

        result = parse_ytdlp_extra_args('--impersonate chrome', {})
        self.assertIsInstance(result['impersonate'], ImpersonateTarget)
        self.assertEqual(result['impersonate'].client, 'chrome')

    def test_impersonate_empty_means_any_target(self):
        """Test that an empty --impersonate value means 'any available target'"""
        from yt_dlp.networking.impersonate import ImpersonateTarget

        self.assertEqual(parse_impersonate_target(''), ImpersonateTarget())

    def test_retry_counts(self):
        """Test retry-related arguments"""
        result = parse_ytdlp_extra_args('--retries 5 --fragment-retries infinite -N 4', {})
        self.assertEqual(result['retries'], 5)
        self.assertEqual(result['fragment_retries'], float('inf'))
        self.assertEqual(result['concurrent_fragment_downloads'], 4)

    def test_force_ipv4(self):
        """Test that -4 sets the source address"""
        result = parse_ytdlp_extra_args('-4', {})
        self.assertEqual(result['source_address'], '0.0.0.0')

    def test_js_runtimes_name_only(self):
        """Test parsing a runtime name without an explicit path"""
        self.assertEqual(parse_js_runtimes('deno'), {'deno': None})

    def test_js_runtimes_with_path(self):
        """Test parsing a runtime name with an explicit path"""
        self.assertEqual(
            parse_js_runtimes('node:/usr/local/bin/node'), {'node': '/usr/local/bin/node'}
        )

    def test_js_runtimes_multiple(self):
        """Test parsing several runtimes at once"""
        self.assertEqual(parse_js_runtimes('deno,node'), {'deno': None, 'node': None})

    def test_js_runtimes_via_extra_args(self):
        """Test that --js-runtimes reaches the yt-dlp options dict"""
        result = parse_ytdlp_extra_args('--js-runtimes deno', {})
        self.assertEqual(result['js_runtimes'], {'deno': None})
