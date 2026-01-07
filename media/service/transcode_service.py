"""
Main transcode service entrypoint.

Provides a single function to transcode URLs to a directory,
used by both the CLI and the web app.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
import tempfile
import shutil

from media.service.strategy import choose_download_strategy
from media.service.resolve import prefetch, resolve_media_type, PlaylistNotSupported
from media.service.download import download_direct, download_ytdlp, download_file
from media.service.process import (
    needs_transcode,
    transcode_to_playable,
    add_metadata_without_transcode,
    process_thumbnail,
    process_subtitle
)
from media.service.config import (
    get_ytdlp_args_for_type,
    get_ffmpeg_args_for_type,
    get_target_audio_format,
    get_target_video_format
)
from media.utils import generate_slug
import subprocess
import json


def extract_duration(file_path):
    """
    Extract duration from media file using ffprobe.

    Returns:
        int: Duration in seconds, or None if extraction fails
    """
    try:
        result = subprocess.run([
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            str(file_path)
        ], capture_output=True, text=True, check=True)

        metadata = json.loads(result.stdout)

        if 'format' in metadata and 'duration' in metadata['format']:
            return int(float(metadata['format']['duration']))

        return None
    except (subprocess.CalledProcessError, ValueError, KeyError):
        return None


@dataclass
class TranscodeResult:
    """Result from transcoding operation"""
    url: str
    strategy: str
    requested_type: str
    resolved_type: str
    title: str
    slug: str
    downloaded_path: Path
    output_path: Path
    transcoded: bool
    file_size: int
    duration_seconds: Optional[int] = None
    thumbnail_path: Optional[Path] = None
    subtitle_path: Optional[Path] = None


def transcode_url_to_dir(
    url,
    outdir='.',
    requested_type='auto',
    download_only=False,
    verbose=False
):
    """
    Download and transcode media from a URL or file path to a directory.

    This is the main entrypoint for the transcode service. It handles:
    - Strategy detection (direct vs yt-dlp)
    - Metadata prefetching
    - Type resolution
    - Download
    - Transcoding (if needed)

    Args:
        url: Source URL or file path
        outdir: Output directory (default: current directory)
        requested_type: 'auto', 'audio', or 'video' (default: 'auto')
        download_only: If True, skip transcoding (default: False)
        verbose: If True, enable verbose logging (default: False)

    Returns:
        TranscodeResult with details about the operation

    Raises:
        PlaylistNotSupported: If URL is a playlist
        Exception: For other errors during processing
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # Create logger
    def logger(message):
        if verbose:
            print(message)

    logger(f"Processing URL: {url}")

    # Convert local file paths to file:// URLs for yt-dlp compatibility
    original_url = url
    file_path = Path(url)
    if file_path.exists():
        # Convert to absolute file:// URL for yt-dlp
        absolute_path = file_path.absolute()
        url = f"file://{absolute_path}"
        logger(f"Converted to file URL: {url}")

    # Step 1: Determine download strategy (use original path for strategy detection)
    strategy = choose_download_strategy(original_url)
    logger(f"Strategy: {strategy}")

    # Step 2: Prefetch metadata
    logger("Prefetching metadata...")
    # Use original_url for file strategy, url for others
    prefetch_url = original_url if strategy == 'file' else url
    prefetch_result = prefetch(prefetch_url, strategy, logger=logger)

    if not prefetch_result.title:
        prefetch_result.title = "untitled"

    logger(f"Title: {prefetch_result.title}")

    # Generate slug from title
    slug = generate_slug(prefetch_result.title)
    logger(f"Slug: {slug}")

    # Step 3: Resolve media type
    resolved_type = resolve_media_type(requested_type, prefetch_result)
    logger(f"Requested type: {requested_type}, Resolved type: {resolved_type}")

    # Step 4: Download
    logger("Downloading...")

    # If HTML extraction found a media URL, use that instead of the original
    download_url = url
    download_strategy = strategy

    if prefetch_result.extracted_media_url:
        download_url = prefetch_result.extracted_media_url
        logger(f"Using extracted media URL: {download_url}")

        # Determine new strategy for extracted URL
        if download_url.startswith('file://'):
            # Local file - use file copy strategy
            download_strategy = 'file'
            download_url = download_url.replace('file://', '')
        elif download_url.startswith(('http://', 'https://')):
            # Check if it's a direct media file or needs yt-dlp
            parsed = urlparse(download_url)
            ext = Path(parsed.path).suffix.lower()
            media_exts = ['.mp3', '.m4a', '.ogg', '.wav', '.aac', '.flac', '.opus',
                         '.mp4', '.mkv', '.webm', '.mov', '.avi']
            if ext in media_exts:
                download_strategy = 'direct'
            else:
                download_strategy = 'ytdlp'

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = Path(temp_dir)

        if strategy == 'file' or download_strategy == 'file':
            # Local file copy (use original_url which is the file path)
            file_to_copy = download_url if download_strategy == 'file' else original_url
            temp_file = temp_dir / f"download{prefetch_result.file_extension or '.tmp'}"
            download_info = download_file(file_to_copy, temp_file, logger=logger)
        elif strategy == 'direct' or download_strategy == 'direct':
            # Direct download
            temp_file = temp_dir / f"download{prefetch_result.file_extension or '.tmp'}"
            download_info = download_direct(download_url, temp_file, logger=logger)
        else:
            # yt-dlp download
            ytdlp_args = get_ytdlp_args_for_type(resolved_type)
            download_info = download_ytdlp(
                download_url,
                resolved_type,
                temp_dir,
                ytdlp_extra_args=ytdlp_args,
                logger=logger
            )

        logger(f"Downloaded: {download_info.path} ({download_info.file_size} bytes)")

        # Determine output filename using slug
        if download_only:
            # Just copy/move the file
            output_path = outdir / f"{slug}{download_info.extension}"
            shutil.copy2(download_info.path, output_path)
            logger(f"Content saved: {output_path}")
            transcoded = False
        else:
            # Check if transcoding is needed
            if needs_transcode(download_info.path, resolved_type):
                logger("Transcoding required...")

                # Determine target format
                if resolved_type == 'audio':
                    target_ext = get_target_audio_format()
                else:
                    target_ext = get_target_video_format()

                output_path = outdir / f"{slug}{target_ext}"
                ffmpeg_args = get_ffmpeg_args_for_type(resolved_type)

                # Prepare metadata for embedding
                metadata = {
                    'title': prefetch_result.title,
                    'author': prefetch_result.author,
                    'description': prefetch_result.description
                }

                transcode_to_playable(
                    download_info.path,
                    resolved_type,
                    output_path,
                    ffmpeg_extra_args=ffmpeg_args,
                    metadata=metadata,
                    logger=logger
                )
                transcoded = True
            else:
                # No transcoding needed
                logger("No transcoding needed, file format is already compatible")

                # For audio: prefer .mp3 if that's what we have, otherwise .m4a
                # For video: use .mp4
                if resolved_type == 'audio':
                    if download_info.extension == '.mp3':
                        output_ext = '.mp3'
                    else:
                        output_ext = get_target_audio_format()
                else:
                    output_ext = get_target_video_format()

                output_path = outdir / f"{slug}{output_ext}"

                # Prepare metadata for embedding
                metadata = {
                    'title': prefetch_result.title,
                    'author': prefetch_result.author,
                    'description': prefetch_result.description
                }

                # Add metadata without transcoding (uses stream copy)
                add_metadata_without_transcode(
                    download_info.path,
                    output_path,
                    metadata=metadata,
                    logger=logger
                )
                logger(f"Content saved: {output_path}")
                transcoded = False

        # Process thumbnail if available
        thumbnail_path = None
        if download_info.thumbnail_path:
            thumbnail_output = outdir / "thumbnail.png"
            thumbnail_path = process_thumbnail(
                download_info.thumbnail_path,
                thumbnail_output,
                logger=logger
            )

        # Process subtitle if available
        subtitle_path = None
        if download_info.subtitle_path:
            subtitle_output = outdir / "subtitles.vtt"
            subtitle_path = process_subtitle(
                download_info.subtitle_path,
                subtitle_output,
                logger=logger
            )

        # Extract duration from output file
        duration_seconds = extract_duration(output_path)

        # Create result
        result = TranscodeResult(
            url=url,
            strategy=strategy,
            requested_type=requested_type,
            resolved_type=resolved_type,
            title=prefetch_result.title,
            slug=slug,
            downloaded_path=download_info.path,
            output_path=output_path,
            transcoded=transcoded,
            file_size=output_path.stat().st_size,
            duration_seconds=duration_seconds,
            thumbnail_path=thumbnail_path,
            subtitle_path=subtitle_path
        )

        logger("=" * 60)
        logger(f"Complete! Output: {output_path} ({result.file_size} bytes)")
        if thumbnail_path:
            logger(f"Thumbnail: {thumbnail_path}")
        if subtitle_path:
            logger(f"Subtitles: {subtitle_path}")

        return result
