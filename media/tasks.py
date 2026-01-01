import os
import subprocess
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
import requests
from huey.contrib.djhuey import db_task
from django.conf import settings
from django.utils import timezone
import yt_dlp

from media.models import MediaItem
from media.utils import generate_slug, ensure_unique_slug


def is_direct_media_url(url):
    """Check if URL is a direct media file"""
    media_extensions = [
        '.mp3', '.m4a', '.mp4', '.webm', '.ogg', '.wav',
        '.aac', '.flac', '.opus', '.mkv', '.avi', '.mov'
    ]
    parsed = urlparse(url)
    path = parsed.path.lower()
    return any(path.endswith(ext) for ext in media_extensions)


def write_log(log_path, message):
    """Append message to log file"""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, 'a') as f:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        f.write(f"[{timestamp}] {message}\n")


@db_task()
def process_media(guid):
    """
    Main processing task for media download and conversion.

    Steps:
    1. PREFETCHING - Extract metadata and validate
    2. DOWNLOADING - Download media files
    3. PROCESSING - Transcode if necessary
    4. READY - Finalize and mark complete
    """
    try:
        item = MediaItem.objects.get(guid=guid)
    except MediaItem.DoesNotExist:
        return

    # Log file will be set after we know the base_dir
    log_path = None

    try:
        # PREFETCHING
        item.status = MediaItem.STATUS_PREFETCHING
        item.save()

        is_direct = is_direct_media_url(item.source_url)

        if is_direct:
            # Direct download - minimal metadata
            log_path = prefetch_direct(item, log_path)
        else:
            # Use yt-dlp to extract metadata (may fallback to HTML extractor)
            log_path = prefetch_ytdlp(item, log_path)

            # Re-check if URL is now direct (HTML extractor may have found direct media)
            item.refresh_from_db()
            is_direct = is_direct_media_url(item.source_url)

        write_log(log_path, "=== PREFETCHING ===")
        write_log(log_path, f"Direct media URL: {is_direct}")

        # DOWNLOADING
        item.status = MediaItem.STATUS_DOWNLOADING
        item.save()
        write_log(log_path, "=== DOWNLOADING ===")

        if is_direct:
            download_direct(item, log_path)
        else:
            download_ytdlp(item, log_path)

        # PROCESSING
        item.status = MediaItem.STATUS_PROCESSING
        item.save()
        write_log(log_path, "=== PROCESSING ===")

        process_files(item, log_path)

        # READY
        item.status = MediaItem.STATUS_READY
        item.downloaded_at = timezone.now()
        item.save()
        write_log(log_path, "=== READY ===")
        write_log(log_path, f"Completed successfully: {item.title}")

        # Generate summary if subtitles are available
        if item.subtitle_path:
            write_log(log_path, "Enqueuing summary generation task")
            generate_summary(item.guid)

    except Exception as e:
        # ERROR
        item.status = MediaItem.STATUS_ERROR
        item.error_message = str(e)
        item.save()
        if log_path:
            write_log(log_path, f"=== ERROR ===")
            write_log(log_path, f"Error: {str(e)}")
        raise


def prefetch_direct(item, log_path):
    """Prefetch metadata for direct URL"""
    # For direct URLs, use the filename as title
    parsed = urlparse(item.source_url)
    filename = Path(parsed.path).stem
    item.title = filename or "downloaded-media"

    # Resolve media type based on extension
    if item.requested_type == MediaItem.REQUESTED_TYPE_AUTO:
        audio_exts = ['.mp3', '.m4a', '.ogg', '.wav', '.aac', '.flac', '.opus']
        path = parsed.path.lower()
        if any(path.endswith(ext) for ext in audio_exts):
            item.media_type = MediaItem.MEDIA_TYPE_AUDIO
        else:
            item.media_type = MediaItem.MEDIA_TYPE_VIDEO
    else:
        item.media_type = item.requested_type

    # Generate slug
    existing = MediaItem.objects.filter(source_url=item.source_url).exclude(guid=item.guid).first()
    slug = generate_slug(item.title)
    item.slug = ensure_unique_slug(slug, item.source_url, existing)

    # Set base directory
    if item.media_type == MediaItem.MEDIA_TYPE_AUDIO:
        item.base_dir = str(Path(settings.STASHCAST_AUDIO_DIR) / item.slug)
    else:
        item.base_dir = str(Path(settings.STASHCAST_VIDEO_DIR) / item.slug)

    # Create directory and set up log file
    os.makedirs(item.base_dir, exist_ok=True)
    log_path = Path(item.base_dir) / 'download.log'
    item.log_path = str(log_path)

    item.save()
    write_log(log_path, f"Title: {item.title}")
    write_log(log_path, f"Media type: {item.media_type}")
    write_log(log_path, f"Slug: {item.slug}")

    return log_path


def extract_media_from_html(url):
    """
    Extract embedded media URL from an HTML page.

    This is a fallback for pages that yt-dlp doesn't recognize.
    Looks for <audio>, <video>, and <source> tags.

    Returns:
        tuple: (media_url, media_type) or (None, None) if no media found
    """
    try:
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin

        # Fetch the HTML
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        # Look for <audio> tags with src
        audio_tag = soup.find('audio', src=True)
        if audio_tag:
            media_url = urljoin(url, audio_tag['src'])
            return (media_url, MediaItem.MEDIA_TYPE_AUDIO)

        # Look for <video> tags with src
        video_tag = soup.find('video', src=True)
        if video_tag:
            media_url = urljoin(url, video_tag['src'])
            return (media_url, MediaItem.MEDIA_TYPE_VIDEO)

        # Look for <source> tags inside <audio>
        audio_with_source = soup.find('audio')
        if audio_with_source:
            source_tag = audio_with_source.find('source', src=True)
            if source_tag:
                media_url = urljoin(url, source_tag['src'])
                return (media_url, MediaItem.MEDIA_TYPE_AUDIO)

        # Look for <source> tags inside <video>
        video_with_source = soup.find('video')
        if video_with_source:
            source_tag = video_with_source.find('source', src=True)
            if source_tag:
                media_url = urljoin(url, source_tag['src'])
                return (media_url, MediaItem.MEDIA_TYPE_VIDEO)

        # No media found
        return (None, None)

    except Exception as e:
        # Return None if extraction fails
        return (None, None)


def prefetch_ytdlp(item, log_path):
    """Prefetch metadata using yt-dlp"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(item.source_url, download=False)

            # Check for playlist
            if 'entries' in info:
                raise Exception("fetching playlist not supported")

            # Extract metadata
            item.title = info.get('title', 'Untitled')
            item.description = info.get('description', '')
            item.author = info.get('uploader', '') or info.get('channel', '')
            item.duration_seconds = info.get('duration')
            item.extractor = info.get('extractor', '')
            item.external_id = info.get('id', '')
            item.webpage_url = info.get('webpage_url', item.source_url)

            # Parse upload date
            if info.get('upload_date'):
                try:
                    upload_date = datetime.strptime(info['upload_date'], '%Y%m%d')
                    item.publish_date = timezone.make_aware(upload_date)
                except:
                    pass

            # Resolve media type
            if item.requested_type == MediaItem.REQUESTED_TYPE_AUTO:
                # Check if video streams exist
                formats = info.get('formats', [])
                has_video = any(f.get('vcodec') != 'none' for f in formats)
                item.media_type = MediaItem.MEDIA_TYPE_VIDEO if has_video else MediaItem.MEDIA_TYPE_AUDIO
            else:
                item.media_type = item.requested_type

            # Generate slug
            existing = MediaItem.objects.filter(source_url=item.source_url).exclude(guid=item.guid).first()
            slug = generate_slug(item.title)
            item.slug = ensure_unique_slug(slug, item.source_url, existing)

            # Set base directory
            if item.media_type == MediaItem.MEDIA_TYPE_AUDIO:
                item.base_dir = str(Path(settings.STASHCAST_AUDIO_DIR) / item.slug)
            else:
                item.base_dir = str(Path(settings.STASHCAST_VIDEO_DIR) / item.slug)

            # Create directory and set up log file
            os.makedirs(item.base_dir, exist_ok=True)
            log_path = Path(item.base_dir) / 'download.log'
            item.log_path = str(log_path)

            item.save()
            write_log(log_path, f"Extracting metadata from: {item.source_url}")
            write_log(log_path, f"Title: {item.title}")
            write_log(log_path, f"Media type: {item.media_type}")
            write_log(log_path, f"Slug: {item.slug}")
            write_log(log_path, f"Duration: {item.duration_seconds}s")

            return log_path

    except Exception as e:
        # Try HTML extractor as fallback
        write_log_msg = f"yt-dlp extraction failed: {str(e)}"
        if log_path:
            write_log(log_path, write_log_msg)
        else:
            print(write_log_msg)

        write_log_msg = "Attempting to extract media from HTML..."
        if log_path:
            write_log(log_path, write_log_msg)
        else:
            print(write_log_msg)

        media_url, detected_media_type = extract_media_from_html(item.source_url)

        if media_url:
            # Found embedded media - treat as direct download
            write_log_msg = f"Found embedded media: {media_url}"
            if log_path:
                write_log(log_path, write_log_msg)
            else:
                print(write_log_msg)

            # Update the source URL to the extracted media URL
            original_url = item.source_url
            item.source_url = media_url
            item.webpage_url = original_url

            # Determine media type
            if item.requested_type == MediaItem.REQUESTED_TYPE_AUTO:
                item.media_type = detected_media_type
            else:
                item.media_type = item.requested_type

            # Use the original page URL for title/slug generation
            parsed = urlparse(original_url)
            page_title = Path(parsed.path).stem or "embedded-media"
            item.title = page_title

            # Generate slug
            existing = MediaItem.objects.filter(webpage_url=original_url).exclude(guid=item.guid).first()
            slug = generate_slug(item.title)
            item.slug = ensure_unique_slug(slug, original_url, existing)

            # Set base directory
            if item.media_type == MediaItem.MEDIA_TYPE_AUDIO:
                item.base_dir = str(Path(settings.STASHCAST_AUDIO_DIR) / item.slug)
            else:
                item.base_dir = str(Path(settings.STASHCAST_VIDEO_DIR) / item.slug)

            # Create directory and set up log file
            os.makedirs(item.base_dir, exist_ok=True)
            log_path = Path(item.base_dir) / 'download.log'
            item.log_path = str(log_path)

            item.save()
            write_log(log_path, f"HTML extractor found media: {media_url}")
            write_log(log_path, f"Original page: {original_url}")
            write_log(log_path, f"Title: {item.title}")
            write_log(log_path, f"Media type: {item.media_type}")
            write_log(log_path, f"Slug: {item.slug}")

            return log_path
        else:
            # No media found in HTML either
            write_log_msg = "No embedded media found in HTML"
            if log_path:
                write_log(log_path, write_log_msg)
            else:
                print(write_log_msg)
            raise Exception(f"yt-dlp failed and no embedded media found: {str(e)}")


def extract_metadata_with_ffprobe(item, file_path, log_path):
    """
    Extract metadata from media file using ffprobe.

    Extracts: duration, title, artist/author, and other metadata
    """
    import json

    try:
        # Run ffprobe to get JSON metadata
        result = subprocess.run([
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            str(file_path)
        ], capture_output=True, text=True, check=True)

        metadata = json.loads(result.stdout)

        # Extract duration (in seconds)
        if 'format' in metadata and 'duration' in metadata['format']:
            duration = float(metadata['format']['duration'])
            item.duration_seconds = int(duration)
            write_log(log_path, f"Duration: {int(duration)}s")

        # Extract title from format tags
        if 'format' in metadata and 'tags' in metadata['format']:
            tags = metadata['format']['tags']

            # Title (try various tag names)
            for tag_name in ['title', 'Title', 'TITLE']:
                if tag_name in tags:
                    item.title = tags[tag_name]
                    write_log(log_path, f"Title: {item.title}")
                    break

            # Artist/Author (try various tag names)
            for tag_name in ['artist', 'Artist', 'ARTIST', 'author', 'Author']:
                if tag_name in tags:
                    item.author = tags[tag_name]
                    write_log(log_path, f"Author: {item.author}")
                    break

            # Album (could be useful)
            for tag_name in ['album', 'Album', 'ALBUM']:
                if tag_name in tags:
                    # You could add an album field to the model if needed
                    write_log(log_path, f"Album: {tags[tag_name]}")
                    break

        item.save()

    except subprocess.CalledProcessError as e:
        write_log(log_path, f"ffprobe error: {e}")
    except json.JSONDecodeError as e:
        write_log(log_path, f"Could not parse ffprobe output: {e}")
    except Exception as e:
        write_log(log_path, f"Unexpected error extracting metadata: {e}")


def download_direct(item, log_path):
    """Download media directly via HTTP"""
    os.makedirs(item.base_dir, exist_ok=True)

    # Determine file extension
    parsed = urlparse(item.source_url)
    ext = Path(parsed.path).suffix or '.mp4'

    # Determine content filename
    if item.media_type == MediaItem.MEDIA_TYPE_AUDIO:
        if ext == '.mp3':
            content_file = 'content.mp3'
        else:
            content_file = 'content.m4a'
    else:
        content_file = 'content.mp4'

    content_path = Path(item.base_dir) / content_file

    write_log(log_path, f"Downloading to: {content_path}")

    # Download file
    response = requests.get(item.source_url, stream=True)
    response.raise_for_status()

    with open(content_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    item.content_path = str(content_path)
    item.file_size = content_path.stat().st_size
    item.mime_type = response.headers.get('content-type', 'application/octet-stream')
    item.save()

    write_log(log_path, f"Downloaded {item.file_size} bytes")

    # Extract metadata using ffprobe
    try:
        write_log(log_path, "Extracting metadata with ffprobe...")
        extract_metadata_with_ffprobe(item, content_path, log_path)
    except Exception as e:
        write_log(log_path, f"Could not extract metadata: {e}")


def download_ytdlp(item, log_path):
    """Download media using yt-dlp"""
    os.makedirs(item.base_dir, exist_ok=True)

    # Prepare yt-dlp options
    if item.media_type == MediaItem.MEDIA_TYPE_AUDIO:
        format_spec = 'bestaudio/best'
        default_args = settings.STASHCAST_DEFAULT_YTDLP_ARGS_AUDIO
    else:
        format_spec = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        default_args = settings.STASHCAST_DEFAULT_YTDLP_ARGS_VIDEO

    # Use temp directory for download, then move to fixed names
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_output = Path(temp_dir) / 'download.%(ext)s'

        ydl_opts = {
            'format': format_spec,
            'outtmpl': str(temp_output),
            'writethumbnail': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['en'],
            'noplaylist': True,
            'quiet': False,
        }

        write_log(log_path, f"Downloading with yt-dlp: {item.source_url}")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([item.source_url])

        # Move files to final locations with fixed names
        # yt-dlp may create files like: download.mp4, download.f137.mp4, download.webp, etc.
        files = list(Path(temp_dir).iterdir())
        write_log(log_path, f"Downloaded {len(files)} files from yt-dlp")

        # Find main content file (video/audio)
        content_files = [f for f in files if f.suffix in ['.mp4', '.mkv', '.webm', '.mp3', '.m4a', '.ogg']]
        if content_files:
            # Use the largest file as the main content
            temp_file = max(content_files, key=lambda f: f.stat().st_size)

            if item.media_type == MediaItem.MEDIA_TYPE_AUDIO:
                if temp_file.suffix == '.mp3':
                    dest = Path(item.base_dir) / 'content.mp3'
                else:
                    dest = Path(item.base_dir) / 'content.m4a'
            else:
                dest = Path(item.base_dir) / 'content.mp4'

            shutil.copy2(temp_file, dest)
            item.content_path = str(dest)
            item.file_size = dest.stat().st_size
            write_log(log_path, f"Content saved to: {dest} ({item.file_size} bytes)")

        # Find and save thumbnail
        thumb_files = [f for f in files if f.suffix in ['.jpg', '.jpeg', '.png', '.webp'] and 'thumbnail' not in f.stem]
        if not thumb_files:
            # Also check for files with 'download' in name that are images
            thumb_files = [f for f in files if f.suffix in ['.jpg', '.jpeg', '.png', '.webp']]

        if thumb_files:
            temp_file = thumb_files[0]  # Take first thumbnail found
            dest = Path(item.base_dir) / f'thumbnail_temp{temp_file.suffix}'
            shutil.copy2(temp_file, dest)
            write_log(log_path, f"Thumbnail saved (temp): {dest}")

        # Find and save subtitles
        subtitle_files = [f for f in files if f.suffix in ['.vtt', '.srt']]
        if subtitle_files:
            temp_file = subtitle_files[0]  # Take first subtitle found
            dest = Path(item.base_dir) / f'subtitles_temp{temp_file.suffix}'
            shutil.copy2(temp_file, dest)
            write_log(log_path, f"Subtitles saved (temp): {dest}")

    item.save()


def process_files(item, log_path):
    """Process downloaded files (transcode, convert thumbnails/subtitles)"""
    base_dir = Path(item.base_dir)

    # Process thumbnail
    for thumb_file in base_dir.glob('thumbnail_temp*'):
        webp_path = base_dir / 'thumbnail.webp'
        try:
            # Use Pillow to convert to webp
            from PIL import Image
            img = Image.open(thumb_file)
            img.save(webp_path, 'WEBP', quality=85)
            item.thumbnail_path = str(webp_path)
            thumb_file.unlink()
            write_log(log_path, f"Thumbnail converted to webp: {webp_path}")
        except Exception as e:
            write_log(log_path, f"Thumbnail conversion failed: {e}")

    # Process subtitles - convert to VTT
    for sub_file in base_dir.glob('subtitles_temp*'):
        vtt_path = base_dir / 'subtitles.vtt'
        if sub_file.suffix == '.vtt':
            # Already VTT, just rename
            shutil.move(sub_file, vtt_path)
        else:
            # Convert SRT to VTT using ffmpeg
            try:
                subprocess.run([
                    'ffmpeg', '-i', str(sub_file),
                    str(vtt_path)
                ], check=True, capture_output=True)
                sub_file.unlink()
            except subprocess.CalledProcessError as e:
                write_log(log_path, f"Subtitle conversion failed: {e}")
                # Just rename it
                shutil.move(sub_file, vtt_path)

        item.subtitle_path = str(vtt_path)
        write_log(log_path, f"Subtitles saved: {vtt_path}")

    # Determine MIME type
    if item.content_path:
        content_file = Path(item.content_path)
        if content_file.suffix == '.mp3':
            item.mime_type = 'audio/mpeg'
        elif content_file.suffix == '.m4a':
            item.mime_type = 'audio/mp4'
        elif content_file.suffix == '.mp4':
            item.mime_type = 'video/mp4'
        else:
            item.mime_type = 'application/octet-stream'

    item.save()
    write_log(log_path, "Processing complete")


@db_task()
def generate_summary(guid):
    """
    Generate summary from subtitle file using extractive summarization.
    Future: Could be extended to use transcription from audio.
    """
    try:
        item = MediaItem.objects.get(guid=guid)
    except MediaItem.DoesNotExist:
        return

    log_path = item.log_path if item.log_path else None

    if not item.subtitle_path or not os.path.exists(item.subtitle_path):
        if log_path:
            write_log(log_path, "No subtitles available for summary generation")
        return

    try:
        if log_path:
            write_log(log_path, "=== GENERATING SUMMARY ===")
            write_log(log_path, f"Reading subtitles from: {item.subtitle_path}")
        # Read subtitle file and extract text
        with open(item.subtitle_path, 'r', encoding='utf-8') as f:
            subtitle_text = f.read()

        # Remove VTT formatting
        import re
        lines = subtitle_text.split('\n')
        text_lines = []
        for line in lines:
            # Skip VTT headers, timestamps, cue IDs, and blank lines
            if (not line.startswith('WEBVTT') and
                not line.startswith('Kind:') and
                not line.startswith('Language:') and
                not '-->' in line and
                not re.match(r'^\d+$', line.strip()) and
                not 'align:' in line and
                not 'position:' in line and
                line.strip()):
                # Remove timing tags like <00:00:00.400> and <c>
                clean_line = re.sub(r'<[^>]+>', '', line)
                if clean_line.strip():
                    text_lines.append(clean_line.strip())

        full_text = ' '.join(text_lines)

        if not full_text:
            return

        # Use sumy for extractive summarization
        from sumy.parsers.plaintext import PlaintextParser
        from sumy.nlp.tokenizers import Tokenizer
        from sumy.summarizers.lex_rank import LexRankSummarizer

        parser = PlaintextParser.from_string(full_text, Tokenizer("english"))
        summarizer = LexRankSummarizer()

        # Generate summary with configured number of sentences
        num_sentences = settings.STASHCAST_SUMMARY_SENTENCES
        summary_sentences = summarizer(parser.document, num_sentences)
        summary = ' '.join(str(sentence) for sentence in summary_sentences)

        item.summary = summary
        item.save()

        if log_path:
            write_log(log_path, f"Generated {len(list(summary_sentences))} sentence summary")

    except Exception as e:
        # Don't fail the whole item if summary generation fails
        if item.log_path:
            write_log(item.log_path, f"Summary generation failed: {str(e)}")
