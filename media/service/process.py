"""
Media processing and transcoding service.

Determines if transcoding is needed and performs it using ffmpeg.
"""
from dataclasses import dataclass
from pathlib import Path
import subprocess
import shutil

from media.service.config import (
    get_acceptable_audio_formats,
    get_acceptable_video_formats,
    get_target_audio_format,
    get_target_video_format,
    get_ffmpeg_args_for_type
)


@dataclass
class ProcessedFileInfo:
    """Information about a processed file"""
    path: Path
    file_size: int
    extension: str
    was_transcoded: bool
    thumbnail_path: Path = None
    subtitle_path: Path = None


def needs_transcode(file_path, resolved_type):
    """
    Determine if a file needs transcoding.

    Args:
        file_path: Path to the downloaded file
        resolved_type: 'audio' or 'video'

    Returns:
        bool: True if transcoding is needed
    """
    file_path = Path(file_path)
    ext = file_path.suffix.lower()

    if resolved_type == 'audio':
        acceptable = get_acceptable_audio_formats()
        # MP3 and M4A are acceptable for audio
        return ext not in acceptable
    elif resolved_type == 'video':
        acceptable = get_acceptable_video_formats()
        # MP4 is acceptable for video
        return ext not in acceptable
    else:
        return False


def get_existing_metadata(file_path):
    """
    Extract existing metadata from a media file using ffprobe.

    Returns:
        dict with keys: title, artist, comment
    """
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_format', '-of', 'json', str(file_path)],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            tags = data.get('format', {}).get('tags', {})
            # ffprobe returns tags in lowercase
            return {
                'title': tags.get('title'),
                'artist': tags.get('artist'),
                'comment': tags.get('comment')
            }
    except Exception:
        pass
    return {}


def transcode_to_playable(input_path, resolved_type, output_path, ffmpeg_extra_args='',
                          metadata=None, logger=None):
    """
    Transcode a media file to a widely-compatible format.

    Args:
        input_path: Path to input file
        resolved_type: 'audio' or 'video'
        output_path: Path for output file
        ffmpeg_extra_args: Additional ffmpeg arguments from settings
        metadata: Dict with optional keys: title, author, description
        logger: Optional callable(str) for logging

    Returns:
        ProcessedFileInfo
    """
    def log(message):
        if logger:
            logger(message)

    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    log(f"Transcoding {input_path} to {output_path}")
    log(f"Type: {resolved_type}")

    # Get ffmpeg args from settings
    ffmpeg_args = get_ffmpeg_args_for_type(resolved_type)
    if ffmpeg_extra_args:
        ffmpeg_args = f"{ffmpeg_args} {ffmpeg_extra_args}"

    # Parse ffmpeg args into a list
    args_list = ffmpeg_args.split()

    # Check existing metadata in source file
    existing_metadata = get_existing_metadata(input_path)

    # Build metadata arguments
    # Prefer existing metadata from source file, only add our metadata if source doesn't have it
    metadata_args = []
    if metadata:
        # Only add title if source doesn't already have one
        if metadata.get('title') and not existing_metadata.get('title'):
            metadata_args.extend(['-metadata', f"title={metadata['title']}"])
        # Only add artist if source doesn't already have one
        if metadata.get('author') and not existing_metadata.get('artist'):
            metadata_args.extend(['-metadata', f"artist={metadata['author']}"])
        # Only add comment if source doesn't already have one
        if metadata.get('description') and not existing_metadata.get('comment'):
            metadata_args.extend(['-metadata', f"comment={metadata['description']}"])

    # Build ffmpeg command
    # Use -map_metadata 0 to copy all existing metadata from input
    cmd = [
        'ffmpeg',
        '-i', str(input_path),
        '-y',  # Overwrite output file
        '-map_metadata', '0',  # Copy existing metadata from input
    ] + args_list + metadata_args + [
        str(output_path)
    ]

    log(f"Running: {' '.join(cmd)}")

    # Run ffmpeg
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        log(f"ffmpeg stderr: {result.stderr}")
        raise Exception(f"ffmpeg failed with code {result.returncode}")

    file_size = output_path.stat().st_size
    log(f"Transcoding complete: {file_size} bytes")

    return ProcessedFileInfo(
        path=output_path,
        file_size=file_size,
        extension=output_path.suffix,
        was_transcoded=True
    )


def add_metadata_without_transcode(input_path, output_path, metadata=None, logger=None):
    """
    Copy a media file and add/update metadata without transcoding.

    Uses ffmpeg stream copy to preserve quality while updating metadata.

    Args:
        input_path: Path to input file
        output_path: Path for output file
        metadata: Dict with optional keys: title, author, description
        logger: Optional callable(str) for logging

    Returns:
        Path to output file
    """
    def log(message):
        if logger:
            logger(message)

    input_path = Path(input_path)
    output_path = Path(output_path)

    if not metadata or not any(metadata.values()):
        # No metadata to add, just copy the file
        shutil.copy2(input_path, output_path)
        return output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)

    log(f"Adding metadata to {input_path}")

    # Build metadata arguments
    metadata_args = []
    if metadata.get('title'):
        metadata_args.extend(['-metadata', f"title={metadata['title']}"])
    if metadata.get('author'):
        metadata_args.extend(['-metadata', f"artist={metadata['author']}"])
    if metadata.get('description'):
        metadata_args.extend(['-metadata', f"comment={metadata['description']}"])

    # Build ffmpeg command with stream copy (no transcoding)
    cmd = [
        'ffmpeg',
        '-i', str(input_path),
        '-y',  # Overwrite output file
        '-c', 'copy',  # Copy all streams without re-encoding
    ] + metadata_args + [
        str(output_path)
    ]

    log(f"Running: {' '.join(cmd)}")

    # Run ffmpeg
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        log(f"ffmpeg metadata add failed, falling back to simple copy")
        log(f"ffmpeg stderr: {result.stderr}")
        # Fallback to simple copy
        shutil.copy2(input_path, output_path)

    return output_path


def process_thumbnail(thumbnail_path, output_path, logger=None):
    """
    Convert thumbnail to PNG format for broad client compatibility.

    Args:
        thumbnail_path: Path to input thumbnail
        output_path: Path for output PNG file
        logger: Optional callable(str) for logging

    Returns:
        Path to processed thumbnail or None
    """
    def log(message):
        if logger:
            logger(message)

    if not thumbnail_path or not Path(thumbnail_path).exists():
        return None

    try:
        from PIL import Image

        thumbnail_path = Path(thumbnail_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        log(f"Converting thumbnail to PNG: {thumbnail_path}")

        img = Image.open(thumbnail_path)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        img.save(output_path, 'PNG', optimize=True)

        log(f"Thumbnail saved: {output_path}")
        return output_path

    except Exception as e:
        log(f"Thumbnail conversion failed: {e}")
        # Fallback: just copy the original
        shutil.copy2(thumbnail_path, output_path)
        return output_path


def process_subtitle(subtitle_path, output_path, logger=None):
    """
    Convert subtitle to VTT format.

    Args:
        subtitle_path: Path to input subtitle
        output_path: Path for output VTT file
        logger: Optional callable(str) for logging

    Returns:
        Path to processed subtitle or None
    """
    def log(message):
        if logger:
            logger(message)

    if not subtitle_path or not Path(subtitle_path).exists():
        return None

    subtitle_path = Path(subtitle_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if subtitle_path.suffix == '.vtt':
        # Already VTT, just copy
        log(f"Copying VTT subtitle: {subtitle_path}")
        shutil.copy2(subtitle_path, output_path)
        return output_path

    # Convert SRT to VTT using ffmpeg
    try:
        log(f"Converting subtitle to VTT: {subtitle_path}")

        cmd = [
            'ffmpeg',
            '-i', str(subtitle_path),
            '-y',
            str(output_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            log(f"Subtitle conversion failed, copying original")
            shutil.copy2(subtitle_path, output_path)

        log(f"Subtitle saved: {output_path}")
        return output_path

    except Exception as e:
        log(f"Subtitle processing failed: {e}")
        # Fallback: just copy the original
        shutil.copy2(subtitle_path, output_path)
        return output_path
