"""
Media metadata and type helpers.

Centralizes ffprobe parsing and extension-based media detection.
"""

import json
import subprocess

from media.service.constants import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS
from media.service.config import get_target_audio_format, get_target_video_format

GENERIC_TITLES = {'content', 'downloaded-media', 'untitled', None, ''}


def normalize_extension(extension):
    """Normalize a file extension for comparison."""
    if not extension:
        return ''
    ext = extension.lower()
    if not ext.startswith('.'):
        ext = f'.{ext}'
    return ext


def get_media_type_from_extension(extension):
    """
    Determine if a file extension is audio or video.

    Args:
        extension: File extension (e.g., '.mp3', '.mp4')

    Returns:
        str: 'audio' or 'video'
    """
    ext = normalize_extension(extension)
    if ext in AUDIO_EXTENSIONS:
        return 'audio'
    return 'video'


def get_streams_from_extension(extension):
    """
    Infer audio/video stream presence from a file extension.

    Returns:
        tuple[bool, bool]: (has_audio, has_video)
    """
    ext = normalize_extension(extension)
    if ext in AUDIO_EXTENSIONS:
        return True, False
    if ext in VIDEO_EXTENSIONS:
        return True, True
    # Default to video+audio for unknown extensions
    return True, True


def extract_ffprobe_metadata(file_path):
    """
    Extract metadata from a media file using ffprobe.

    Returns:
        dict: {'duration_seconds': int|None, 'tags': dict}
    """
    try:
        result = subprocess.run(
            [
                'ffprobe',
                '-v',
                'quiet',
                '-print_format',
                'json',
                '-show_format',
                '-show_streams',
                str(file_path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except Exception:
        return {}

    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}

    tags = metadata.get('format', {}).get('tags', {}) or {}
    normalized_tags = {str(k).lower(): v for k, v in tags.items()}

    duration_seconds = None
    duration_raw = metadata.get('format', {}).get('duration')
    if duration_raw is not None:
        try:
            duration_seconds = int(float(duration_raw))
        except (TypeError, ValueError):
            duration_seconds = None

    return {
        'duration_seconds': duration_seconds,
        'tags': normalized_tags,
    }


def get_title_from_metadata(file_path):
    """
    Return the embedded title from media metadata, if present.

    Args:
        file_path: Path to media file

    Returns:
        str | None
    """
    metadata = extract_ffprobe_metadata(file_path) or {}
    tags = metadata.get('tags', {}) or {}
    title = tags.get('title')
    return title or None


def resolve_title_from_metadata(title, file_path):
    """
    Resolve a generic title by checking embedded media metadata.

    Args:
        title: Current title
        file_path: Path to media file

    Returns:
        str: Updated title if metadata exists, otherwise original title
    """
    if title not in GENERIC_TITLES:
        return title
    meta_title = get_title_from_metadata(file_path)
    return meta_title or title


def get_output_extension(resolved_type, source_extension=None):
    """
    Determine output extension for a resolved media type.

    Args:
        resolved_type: 'audio' or 'video'
        source_extension: Optional extension from source file

    Returns:
        str: Output extension (e.g., '.mp3', '.m4a', '.mp4')
    """
    if resolved_type == 'audio':
        if normalize_extension(source_extension) == '.mp3':
            return '.mp3'
        return get_target_audio_format()
    return get_target_video_format()
