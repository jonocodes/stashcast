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
        else:
            # Skip unknown args
            i += 1

    return base_opts
