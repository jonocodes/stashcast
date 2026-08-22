"""
Configuration adapter for media processing settings.

Centralizes access to Django settings and environment variables,
ensuring consistent configuration across CLI and web app.
"""

from django.conf import settings


def get_ytdlp_args_for_type(media_type):
    """
    Get yt-dlp arguments for the specified media type.

    Args:
        media_type: 'audio' or 'video'

    Returns:
        str: yt-dlp command-line arguments
    """
    if media_type == 'audio':
        return settings.STASHCAST_DEFAULT_YTDLP_ARGS_AUDIO
    elif media_type == 'video':
        return settings.STASHCAST_DEFAULT_YTDLP_ARGS_VIDEO
    else:
        return ''


def get_ffmpeg_args_for_type(media_type):
    """
    Get ffmpeg arguments for the specified media type.

    Args:
        media_type: 'audio' or 'video'

    Returns:
        str: ffmpeg command-line arguments
    """
    if media_type == 'audio':
        return settings.STASHCAST_DEFAULT_FFMPEG_ARGS_AUDIO
    elif media_type == 'video':
        return settings.STASHCAST_DEFAULT_FFMPEG_ARGS_VIDEO
    else:
        return ''


def get_media_dir():
    """Get the media directory path"""
    return settings.STASHCAST_MEDIA_DIR


def get_acceptable_audio_formats():
    """
    Get list of audio formats that don't need transcoding.

    Returns:
        list: File extensions that are acceptable without transcoding
    """
    # MP3 and M4A are widely supported in podcast players
    return ['.mp3', '.m4a']


def get_acceptable_video_formats():
    """
    Get list of video formats that don't need transcoding.

    Returns:
        list: File extensions that are acceptable without transcoding
    """
    # MP4 is widely supported across browsers and devices
    return ['.mp4']


def get_target_audio_format():
    """Get the target audio format for transcoding"""
    return '.m4a'


def get_target_video_format():
    """Get the target video format for transcoding"""
    return '.mp4'


def parse_extractor_args(value):
    """
    Parse a single --extractor-args value into the dict form yt-dlp's API expects.

    Args:
        value: String like 'youtube:player_client=tv,web_safari;formats=missing_pot'

    Returns:
        dict: e.g. {'youtube': {'player_client': ['tv', 'web_safari'],
                                'formats': ['missing_pot']}}
    """
    ie_key, _, raw_args = value.partition(':')
    parsed = {}
    for chunk in raw_args.split(';'):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, _, values = chunk.partition('=')
        parsed[key.strip().lower()] = [v.strip() for v in values.split(',') if v.strip()]
    return {ie_key.strip().lower(): parsed}


def merge_extractor_args(base_opts, extractor_args):
    """
    Merge extractor args into base_opts without dropping already-configured keys.

    Args:
        base_opts: yt-dlp options dict (modified in place)
        extractor_args: Dict as returned by parse_extractor_args()

    Returns:
        dict: The updated base_opts
    """
    existing = base_opts.setdefault('extractor_args', {})
    for ie_key, args in extractor_args.items():
        existing.setdefault(ie_key, {}).update(args)
    return base_opts


def parse_ytdlp_extra_args(args_string, base_opts):
    """
    Parse yt-dlp extra arguments string and apply to base options dict.

    Args:
        args_string: String of yt-dlp arguments (e.g., '--format "bv*[height<=720]"')
        base_opts: Base yt-dlp options dict to update

    Returns:
        dict: Updated yt-dlp options dict

    Example:
        >>> opts = {'format': 'best', 'quiet': True}
        >>> parse_ytdlp_extra_args('--format "bestaudio" --merge-output-format mp4', opts)
        {'format': 'bestaudio', 'quiet': True, 'merge_output_format': 'mp4'}
    """
    if not args_string:
        return base_opts

    import shlex

    args_list = shlex.split(args_string)

    # Parse common yt-dlp arguments
    i = 0
    while i < len(args_list):
        arg = args_list[i]

        if arg == '--format' or arg == '-f':
            if i + 1 < len(args_list):
                base_opts['format'] = args_list[i + 1]
                i += 2
            else:
                i += 1
        elif arg == '--merge-output-format':
            if i + 1 < len(args_list):
                base_opts['merge_output_format'] = args_list[i + 1]
                i += 2
            else:
                i += 1
        elif arg == '--audio-format':
            if i + 1 < len(args_list):
                base_opts['postprocessors'] = base_opts.get('postprocessors', []) + [
                    {
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': args_list[i + 1],
                    }
                ]
                i += 2
            else:
                i += 1
        elif arg == '--audio-quality':
            if i + 1 < len(args_list):
                # This needs to be combined with audio-format postprocessor
                i += 2
            else:
                i += 1
        elif arg == '--embed-metadata':
            base_opts['postprocessors'] = base_opts.get('postprocessors', []) + [
                {'key': 'FFmpegMetadata', 'add_metadata': True}
            ]
            i += 1
        elif arg == '--embed-thumbnail':
            base_opts['postprocessors'] = base_opts.get('postprocessors', []) + [
                {'key': 'EmbedThumbnail'}
            ]
            i += 1
        elif arg == '--convert-thumbnails':
            if i + 1 < len(args_list):
                base_opts['postprocessors'] = base_opts.get('postprocessors', []) + [
                    {'key': 'FFmpegThumbnailsConvertor', 'format': args_list[i + 1]}
                ]
                i += 2
            else:
                i += 1
        elif arg == '--convert-subs':
            if i + 1 < len(args_list):
                base_opts['postprocessors'] = base_opts.get('postprocessors', []) + [
                    {'key': 'FFmpegSubtitlesConvertor', 'format': args_list[i + 1]}
                ]
                i += 2
            else:
                i += 1
        elif arg == '--embed-subs':
            base_opts['postprocessors'] = base_opts.get('postprocessors', []) + [
                {'key': 'FFmpegEmbedSubtitle'}
            ]
            i += 1
        elif arg == '--proxy':
            if i + 1 < len(args_list):
                base_opts['proxy'] = args_list[i + 1]
                i += 2
            else:
                i += 1
        elif arg == '--sleep-interval':
            if i + 1 < len(args_list):
                base_opts['sleep_interval'] = int(args_list[i + 1])
                i += 2
            else:
                i += 1
        elif arg == '--max-sleep-interval':
            if i + 1 < len(args_list):
                base_opts['max_sleep_interval'] = int(args_list[i + 1])
                i += 2
            else:
                i += 1
        elif arg == '--extractor-args':
            # Needed for YouTube workarounds, e.g.
            # --extractor-args "youtube:player_client=tv,web_safari"
            if i + 1 < len(args_list):
                merge_extractor_args(base_opts, parse_extractor_args(args_list[i + 1]))
                i += 2
            else:
                i += 1
        elif arg == '--cookies':
            if i + 1 < len(args_list):
                base_opts['cookiefile'] = args_list[i + 1]
                i += 2
            else:
                i += 1
        elif arg == '--cookies-from-browser':
            if i + 1 < len(args_list):
                base_opts['cookiesfrombrowser'] = parse_cookies_from_browser(args_list[i + 1])
                i += 2
            else:
                i += 1
        elif arg == '--user-agent':
            if i + 1 < len(args_list):
                headers = base_opts.setdefault('http_headers', {})
                headers['User-Agent'] = args_list[i + 1]
                i += 2
            else:
                i += 1
        elif arg == '--referer':
            if i + 1 < len(args_list):
                headers = base_opts.setdefault('http_headers', {})
                headers['Referer'] = args_list[i + 1]
                i += 2
            else:
                i += 1
        elif arg == '--impersonate':
            if i + 1 < len(args_list):
                base_opts['impersonate'] = parse_impersonate_target(args_list[i + 1])
                i += 2
            else:
                i += 1
        elif arg == '--retries' or arg == '-R':
            if i + 1 < len(args_list):
                base_opts['retries'] = _parse_retry_count(args_list[i + 1])
                i += 2
            else:
                i += 1
        elif arg == '--fragment-retries':
            if i + 1 < len(args_list):
                base_opts['fragment_retries'] = _parse_retry_count(args_list[i + 1])
                i += 2
            else:
                i += 1
        elif arg == '--concurrent-fragments' or arg == '-N':
            if i + 1 < len(args_list):
                base_opts['concurrent_fragment_downloads'] = int(args_list[i + 1])
                i += 2
            else:
                i += 1
        elif arg == '--source-address':
            if i + 1 < len(args_list):
                base_opts['source_address'] = args_list[i + 1]
                i += 2
            else:
                i += 1
        elif arg == '--force-ipv4' or arg == '-4':
            base_opts['source_address'] = '0.0.0.0'
            i += 1
        elif arg == '--geo-bypass':
            base_opts['geo_bypass'] = True
            i += 1
        elif arg == '--js-runtimes':
            if i + 1 < len(args_list):
                base_opts['js_runtimes'] = parse_js_runtimes(args_list[i + 1])
                i += 2
            else:
                i += 1
        else:
            # Skip unknown args
            i += 1

    return base_opts


def parse_cookies_from_browser(value):
    """
    Parse a --cookies-from-browser value into yt-dlp's tuple form.

    Args:
        value: String like 'firefox', 'chrome:Default' or 'chrome+gnomekeyring:Profile 1'

    Returns:
        tuple: (browser, profile_or_None, keyring_or_None, container_or_None)
    """
    browser_part, _, rest = value.partition(':')
    browser, _, keyring = browser_part.partition('+')
    profile, _, container = rest.partition('::')
    return (
        browser.strip().lower(),
        profile.strip() or None,
        keyring.strip().upper() or None,
        container.strip() or None,
    )


def _parse_retry_count(value):
    """Convert a yt-dlp retry count ('10' or 'infinite') into an int."""
    if value.strip().lower() in ('inf', 'infinite'):
        return float('inf')
    return int(value)


def parse_impersonate_target(value):
    """
    Convert an --impersonate value into the object yt-dlp's Python API requires.

    The CLI accepts a string, but YoutubeDL asserts on an ImpersonateTarget instance,
    so passing the raw string through would raise an AssertionError at startup.

    Args:
        value: String like 'chrome', 'safari', 'chrome-110' or '' for any target

    Returns:
        ImpersonateTarget
    """
    from yt_dlp.networking.impersonate import ImpersonateTarget

    value = (value or '').strip()
    if not value:
        return ImpersonateTarget()
    return ImpersonateTarget.from_str(value)


def parse_js_runtimes(value):
    """
    Parse a --js-runtimes value into the dict form yt-dlp's Python API expects.

    A JavaScript runtime lets yt-dlp solve YouTube's player challenges; without one
    it falls back to clients whose stream URLs often return 403 Forbidden.

    Args:
        value: Comma-separated NAME[:PATH] list, e.g. 'deno,node:/usr/local/bin/node'

    Returns:
        dict: e.g. {'deno': None, 'node': '/usr/local/bin/node'}
    """
    runtimes = {}
    for entry in (value or '').split(','):
        entry = entry.strip()
        if not entry:
            continue
        name, _, path = entry.partition(':')
        runtimes[name.strip().lower()] = path.strip() or None
    return runtimes
