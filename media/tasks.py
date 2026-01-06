import os
import shutil
from pathlib import Path
from huey.contrib.djhuey import db_task
from django.conf import settings
from django.utils import timezone

from media.models import MediaItem
from media.processing import (
    write_log,
    prefetch_direct,
    prefetch_ytdlp,
    download_direct,
    download_ytdlp,
    process_files
)
from media.service.strategy import choose_download_strategy


@db_task()
def process_media(guid):
    """
    Main processing task for media download and conversion.

    Steps:
    1. PREFETCHING - Extract metadata and validate
    2. DOWNLOADING - Download media files
    3. PROCESSING - Transcode if necessary
    4. READY - Finalize and mark complete

    Downloads occur in tmp-{guid}/ directory in the media folder, then moved to final
    slug-based directory after successful completion. This makes debugging easier and
    keeps download progress visible.
    """
    try:
        item = MediaItem.objects.get(guid=guid)
    except MediaItem.DoesNotExist:
        return

    # Check for worker timeout: if task was enqueued but worker wasn't running
    # Items can get stuck in PREFETCHING if worker is down
    now = timezone.now()
    time_since_update = now - item.updated_at

    if item.status == MediaItem.STATUS_PREFETCHING and time_since_update.total_seconds() > 30:
        item.status = MediaItem.STATUS_ERROR
        item.error_message = (
            f"Worker timeout: Item stuck in PREFETCHING for {int(time_since_update.total_seconds())} seconds. "
            "Huey worker may not be running. Start with: python manage.py run_huey"
        )
        item.save()
        return

    # Create tmp directory in media folder for this download
    # Format: <media_dir>/tmp-{guid}/
    tmp_dir = None
    log_path = None

    try:
        # Determine base media directory (don't know slug yet)
        media_base = Path(settings.STASHCAST_MEDIA_DIR)
        media_base.mkdir(parents=True, exist_ok=True)

        # Create tmp directory with GUID
        tmp_dir = media_base / f"tmp-{guid}"
        tmp_dir.mkdir(exist_ok=True)

        # Create log file immediately in tmp directory
        log_path = tmp_dir / 'download.log'
        write_log(log_path, "=== TASK STARTED ===")
        write_log(log_path, f"GUID: {guid}")
        write_log(log_path, f"URL: {item.source_url}")
        write_log(log_path, f"Requested type: {item.requested_type}")
        write_log(log_path, f"Tmp directory: {tmp_dir}")

        # PREFETCHING
        item.status = MediaItem.STATUS_PREFETCHING
        item.save()
        write_log(log_path, "=== PREFETCHING ===")

        # Determine download strategy
        strategy = choose_download_strategy(item.source_url)
        is_direct = strategy in ('direct', 'file')

        if is_direct:
            # Direct download - minimal metadata
            prefetch_direct(item, tmp_dir, log_path)
        else:
            # Use yt-dlp to extract metadata (may fallback to HTML extractor)
            prefetch_ytdlp(item, tmp_dir, log_path)

            # Re-check if URL is now direct (HTML extractor may have found direct media)
            item.refresh_from_db()
            strategy = choose_download_strategy(item.source_url)
            is_direct = strategy in ('direct', 'file')

        write_log(log_path, f"Direct media URL: {is_direct}")

        # DOWNLOADING
        item.status = MediaItem.STATUS_DOWNLOADING
        item.save()
        write_log(log_path, "=== DOWNLOADING ===")

        if is_direct:
            download_direct(item, tmp_dir, log_path)
        else:
            download_ytdlp(item, tmp_dir, log_path)

        # PROCESSING
        item.status = MediaItem.STATUS_PROCESSING
        item.save()
        write_log(log_path, "=== PROCESSING ===")

        process_files(item, tmp_dir, log_path)

        # Move from tmp directory to final slug-based directory
        write_log(log_path, "=== MOVING TO FINAL DIRECTORY ===")
        final_dir = item.get_base_dir()
        final_dir.parent.mkdir(parents=True, exist_ok=True)

        # If final directory exists, remove it (overwrite behavior)
        if final_dir.exists():
            write_log(log_path, f"Removing existing directory: {final_dir}")
            shutil.rmtree(final_dir)

        # Move tmp directory to final location
        shutil.move(str(tmp_dir), str(final_dir))
        write_log(log_path, f"Moved to: {final_dir}")

        # Update log_path to new location for final messages
        log_path = final_dir / 'download.log'

        # READY
        item.status = MediaItem.STATUS_READY
        item.downloaded_at = timezone.now()
        item.save()
        write_log(log_path, "=== READY ===")
        write_log(log_path, f"Completed successfully: {item.title}")

        # Generate summary if subtitles are available
        if item.subtitle_path and settings.STASHCAST_SUMMARY_SENTENCES > 0:
            write_log(log_path, "Enqueuing summary generation task")
            generate_summary(item.guid)

    except Exception as e:
        # ERROR
        item.status = MediaItem.STATUS_ERROR
        item.error_message = str(e)
        item.save()
        if log_path:
            write_log(log_path, "=== ERROR ===")
            write_log(log_path, f"Error: {str(e)}")

        # Clean up tmp directory on error
        if tmp_dir and tmp_dir.exists():
            write_log(log_path, f"Cleaning up tmp directory: {tmp_dir}")
            try:
                shutil.rmtree(tmp_dir)
            except Exception as cleanup_error:
                write_log(log_path, f"Failed to clean up tmp: {cleanup_error}")

        raise


@db_task()
def generate_summary(guid):
    """
    Generate summary from subtitle file using extractive summarization.
    Future: Could be extended to use transcription from audio.
    """
    # Skip summary generation if STASHCAST_SUMMARY_SENTENCES is set to 0
    num_sentences = settings.STASHCAST_SUMMARY_SENTENCES
    if num_sentences <= 0:
        return

    try:
        item = MediaItem.objects.get(guid=guid)
    except MediaItem.DoesNotExist:
        return

    log_path = item.get_absolute_log_path() if item.log_path else None

    subtitle_path = item.get_absolute_subtitle_path()
    if not subtitle_path or not os.path.exists(subtitle_path):
        if log_path:
            write_log(log_path, "No subtitles available for summary generation")
        return

    try:
        if log_path:
            write_log(log_path, "=== GENERATING SUMMARY ===")
            write_log(log_path, f"Reading subtitles from: {subtitle_path}")
        # Read subtitle file and extract text
        with open(subtitle_path, 'r', encoding='utf-8') as f:
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
        log_path = item.get_absolute_log_path()
        if log_path:
            write_log(log_path, f"Summary generation failed: {str(e)}")
