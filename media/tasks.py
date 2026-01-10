import os
import shutil
from pathlib import Path
from typing import List

from django.conf import settings
from django.utils import timezone
from huey.contrib.djhuey import db_task

from media.models import MediaItem
from media.processing import (
    download_direct,
    download_ytdlp,
    prefetch_file,
    prefetch_direct,
    prefetch_ytdlp,
    process_files,
    write_log,
)
from media.progress_tracker import update_progress
from media.service.download import download_ytdlp_batch
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
        seconds = int(time_since_update.total_seconds())
        item.error_message = (
            f'Worker timeout: Item stuck in PREFETCHING for {seconds} seconds. '
            'Huey worker may not be running. Start with: python manage.py run_huey'
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
        tmp_dir = media_base / f'tmp-{guid}'
        tmp_dir.mkdir(exist_ok=True)

        # Create log file immediately in tmp directory
        log_path = tmp_dir / 'download.log'
        write_log(log_path, '=== TASK STARTED ===')
        write_log(log_path, f'GUID: {guid}')
        write_log(log_path, f'URL: {item.source_url}')
        write_log(log_path, f'Requested type: {item.requested_type}')
        write_log(log_path, f'Tmp directory: {tmp_dir}')

        # PREFETCHING
        item.status = MediaItem.STATUS_PREFETCHING
        item.save()
        write_log(log_path, '=== PREFETCHING ===')
        update_progress(item.guid, MediaItem.STATUS_PREFETCHING, 0)

        # Determine download strategy
        strategy = choose_download_strategy(item.source_url)
        is_direct = strategy in ('direct', 'file')

        if is_direct:
            # Direct download - minimal metadata
            if Path(item.source_url).exists():
                prefetch_file(item, tmp_dir, log_path)
            else:
                prefetch_direct(item, tmp_dir, log_path)
        else:
            # Use yt-dlp to extract metadata (may fallback to HTML extractor)
            prefetch_ytdlp(item, tmp_dir, log_path)

        # Re-check if URL is now direct (HTML extractor may have found direct media)
        item.refresh_from_db()
        strategy = choose_download_strategy(item.source_url)
        is_direct = strategy in ('direct', 'file')

        write_log(log_path, f'Direct media URL: {is_direct}')
        update_progress(item.guid, MediaItem.STATUS_PREFETCHING, 10)

        # DOWNLOADING
        item.status = MediaItem.STATUS_DOWNLOADING
        item.save()
        write_log(log_path, '=== DOWNLOADING ===')

        if is_direct:
            download_direct(item, tmp_dir, log_path)
        else:
            download_ytdlp(item, tmp_dir, log_path)

        # PROCESSING
        item.status = MediaItem.STATUS_PROCESSING
        item.save()
        write_log(log_path, '=== PROCESSING ===')
        update_progress(item.guid, MediaItem.STATUS_PROCESSING, 40)

        process_files(item, tmp_dir, log_path)

        # Move from tmp directory to final slug-based directory
        write_log(log_path, '=== MOVING TO FINAL DIRECTORY ===')
        final_dir = item.get_base_dir()
        final_dir.parent.mkdir(parents=True, exist_ok=True)

        # If final directory exists, remove it (overwrite behavior)
        if final_dir.exists():
            write_log(log_path, f'Removing existing directory: {final_dir}')
            shutil.rmtree(final_dir)

        # Move tmp directory to final location
        shutil.move(str(tmp_dir), str(final_dir))

        # IMPORTANT: Update log_path BEFORE writing more logs to prevent creating
        # files in the old tmp directory, which would leave it behind after the move
        log_path = final_dir / 'download.log'
        write_log(log_path, f'Moved to: {final_dir}')

        # READY
        item.status = MediaItem.STATUS_READY
        item.downloaded_at = timezone.now()
        item.save()
        write_log(log_path, '=== READY ===')
        write_log(log_path, f'Completed successfully: {item.title}')
        update_progress(item.guid, MediaItem.STATUS_READY, 100)

        # Clean up progress tracker
        from media.progress_tracker import clear_progress

        clear_progress(item.guid)

        # Generate summary if subtitles are available
        if item.subtitle_path and settings.STASHCAST_SUMMARY_SENTENCES > 0:
            write_log(log_path, 'Enqueuing summary generation task')
            generate_summary(item.guid)

    except Exception as e:
        # ERROR
        item.status = MediaItem.STATUS_ERROR
        item.error_message = str(e)
        item.save()
        if log_path:
            write_log(log_path, '=== ERROR ===')
            write_log(log_path, f'Error: {str(e)}')

        # Clean up tmp directory on error
        if tmp_dir and tmp_dir.exists():
            write_log(log_path, f'Cleaning up tmp directory: {tmp_dir}')
            try:
                shutil.rmtree(tmp_dir)
            except Exception as cleanup_error:
                write_log(log_path, f'Failed to clean up tmp: {cleanup_error}')

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
            write_log(log_path, 'No subtitles available for summary generation')
        return

    try:
        if log_path:
            write_log(log_path, '=== GENERATING SUMMARY ===')
            write_log(log_path, f'Reading subtitles from: {subtitle_path}')
        # Read subtitle file and extract text
        with open(subtitle_path, 'r', encoding='utf-8') as f:
            subtitle_text = f.read()

        # Remove VTT formatting
        import re

        lines = subtitle_text.split('\n')
        text_lines = []
        for line in lines:
            # Skip VTT headers, timestamps, cue IDs, and blank lines
            if (
                not line.startswith('WEBVTT')
                and not line.startswith('Kind:')
                and not line.startswith('Language:')
                and '-->' not in line
                and not re.match(r'^\d+$', line.strip())
                and 'align:' not in line
                and 'position:' not in line
                and line.strip()
            ):
                # Remove timing tags like <00:00:00.400> and <c>
                clean_line = re.sub(r'<[^>]+>', '', line)
                if clean_line.strip():
                    text_lines.append(clean_line.strip())

        full_text = ' '.join(text_lines)

        if not full_text:
            return

        # Use sumy for extractive summarization
        from sumy.nlp.tokenizers import Tokenizer
        from sumy.parsers.plaintext import PlaintextParser
        from sumy.summarizers.lex_rank import LexRankSummarizer

        parser = PlaintextParser.from_string(full_text, Tokenizer('english'))
        summarizer = LexRankSummarizer()

        # Generate summary with configured number of sentences
        num_sentences = settings.STASHCAST_SUMMARY_SENTENCES
        summary_sentences = summarizer(parser.document, num_sentences)
        summary = ' '.join(str(sentence) for sentence in summary_sentences)

        item.summary = summary
        item.save()

        if log_path:
            write_log(log_path, f'Generated {len(list(summary_sentences))} sentence summary')

    except Exception as e:
        # Don't fail the whole item if summary generation fails
        log_path = item.get_absolute_log_path()
        if log_path:
            write_log(log_path, f'Summary generation failed: {str(e)}')


@db_task()
def process_media_batch(guids: List[str]):
    """
    Batch processing task for multiple media downloads.

    Uses a single yt-dlp process to download all URLs, leveraging yt-dlp's
    built-in rate limiting and backoff handling. This is more efficient than
    spawning separate processes for each URL.

    Steps:
    1. PREFETCHING - Extract metadata for all items
    2. DOWNLOADING - Download all items in a single yt-dlp session
    3. PROCESSING - Process each item individually
    4. READY - Finalize each item

    Args:
        guids: List of MediaItem GUIDs to process
    """
    if not guids:
        return

    # Get all items and prepare tracking structures
    items = {guid: MediaItem.objects.filter(guid=guid).first() for guid in guids}
    items = {k: v for k, v in items.items() if v is not None}

    if not items:
        return

    # Create batch tmp directory
    media_base = Path(settings.STASHCAST_MEDIA_DIR)
    media_base.mkdir(parents=True, exist_ok=True)
    batch_id = guids[0][:8]  # Use first 8 chars of first GUID as batch ID
    batch_tmp_dir = media_base / f'batch-{batch_id}'
    batch_tmp_dir.mkdir(exist_ok=True)

    # Batch log file
    batch_log_path = batch_tmp_dir / 'batch.log'
    write_log(batch_log_path, '=== BATCH TASK STARTED ===')
    write_log(batch_log_path, f'Processing {len(items)} items')

    # Track per-item tmp directories and logs
    item_tmp_dirs = {}
    item_log_paths = {}

    # URLs to download (only ytdlp strategy items)
    urls_to_download = []
    guid_by_url = {}

    try:
        # === PREFETCHING PHASE ===
        write_log(batch_log_path, '=== PREFETCHING ALL ITEMS ===')

        for guid, item in items.items():
            # Create per-item tmp directory
            tmp_dir = batch_tmp_dir / f'item-{guid}'
            tmp_dir.mkdir(exist_ok=True)
            item_tmp_dirs[guid] = tmp_dir

            log_path = tmp_dir / 'download.log'
            item_log_paths[guid] = log_path

            write_log(log_path, '=== TASK STARTED (BATCH MODE) ===')
            write_log(log_path, f'GUID: {guid}')
            write_log(log_path, f'URL: {item.source_url}')

            item.status = MediaItem.STATUS_PREFETCHING
            item.save()

            try:
                strategy = choose_download_strategy(item.source_url)

                if strategy in ('direct', 'file'):
                    # Direct downloads handled individually
                    write_log(log_path, f'Direct download - will process individually')
                    if Path(item.source_url).exists():
                        prefetch_file(item, tmp_dir, log_path)
                    else:
                        prefetch_direct(item, tmp_dir, log_path)
                else:
                    # yt-dlp URLs collected for batch download
                    prefetch_ytdlp(item, tmp_dir, log_path)
                    urls_to_download.append(item.source_url)
                    guid_by_url[item.source_url] = guid

                write_log(batch_log_path, f'Prefetched: {item.title or item.source_url}')

            except Exception as e:
                item.status = MediaItem.STATUS_ERROR
                item.error_message = f'Prefetch failed: {str(e)}'
                item.save()
                write_log(log_path, f'Error during prefetch: {e}')
                write_log(batch_log_path, f'FAILED prefetch for {guid}: {e}')

        # === DOWNLOADING PHASE ===
        write_log(batch_log_path, '=== DOWNLOADING ALL ITEMS ===')
        write_log(batch_log_path, f'{len(urls_to_download)} URLs to batch download')

        # Update status for all items being downloaded
        for url in urls_to_download:
            guid = guid_by_url[url]
            item = items[guid]
            item.status = MediaItem.STATUS_DOWNLOADING
            item.save()
            update_progress(guid, MediaItem.STATUS_DOWNLOADING, 20)

        # Handle direct downloads individually first
        for guid, item in items.items():
            if item.source_url not in guid_by_url and item.status != MediaItem.STATUS_ERROR:
                tmp_dir = item_tmp_dirs[guid]
                log_path = item_log_paths[guid]
                try:
                    item.status = MediaItem.STATUS_DOWNLOADING
                    item.save()
                    download_direct(item, tmp_dir, log_path)
                    write_log(batch_log_path, f'Direct downloaded: {item.source_url}')
                except Exception as e:
                    item.status = MediaItem.STATUS_ERROR
                    item.error_message = f'Download failed: {str(e)}'
                    item.save()
                    write_log(log_path, f'Error during download: {e}')

        # Batch download all yt-dlp URLs
        if urls_to_download:
            # Determine resolved type (use first item's type for batch)
            first_guid = guid_by_url[urls_to_download[0]]
            resolved_type = items[first_guid].media_type or 'video'

            batch_result = download_ytdlp_batch(
                urls=urls_to_download,
                resolved_type=resolved_type,
                temp_dir=batch_tmp_dir / 'downloads',
                ytdlp_extra_args=settings.STASHCAST_YTDLP_ARGS,
                logger=lambda m: write_log(batch_log_path, m),
            )

            # Process results
            for url, download_info in batch_result.downloads.items():
                guid = guid_by_url[url]
                item = items[guid]
                tmp_dir = item_tmp_dirs[guid]
                log_path = item_log_paths[guid]

                write_log(log_path, f'Downloaded: {download_info.path.name}')

                # Move downloaded files to item's tmp directory
                for src_file in download_info.path.parent.iterdir():
                    dst_file = tmp_dir / src_file.name
                    shutil.move(str(src_file), str(dst_file))

                write_log(batch_log_path, f'Downloaded: {item.title or url}')

            # Handle errors
            for url, error in batch_result.errors.items():
                guid = guid_by_url[url]
                item = items[guid]
                log_path = item_log_paths[guid]

                item.status = MediaItem.STATUS_ERROR
                item.error_message = f'Download failed: {error}'
                item.save()
                write_log(log_path, f'Download error: {error}')
                write_log(batch_log_path, f'FAILED download for {url}: {error}')

        # === PROCESSING PHASE ===
        write_log(batch_log_path, '=== PROCESSING ALL ITEMS ===')

        for guid, item in items.items():
            if item.status == MediaItem.STATUS_ERROR:
                continue

            tmp_dir = item_tmp_dirs[guid]
            log_path = item_log_paths[guid]

            try:
                item.status = MediaItem.STATUS_PROCESSING
                item.save()
                write_log(log_path, '=== PROCESSING ===')
                update_progress(guid, MediaItem.STATUS_PROCESSING, 60)

                process_files(item, tmp_dir, log_path)

                # Move to final directory
                write_log(log_path, '=== MOVING TO FINAL DIRECTORY ===')
                final_dir = item.get_base_dir()
                final_dir.parent.mkdir(parents=True, exist_ok=True)

                if final_dir.exists():
                    write_log(log_path, f'Removing existing directory: {final_dir}')
                    shutil.rmtree(final_dir)

                shutil.move(str(tmp_dir), str(final_dir))
                log_path = final_dir / 'download.log'
                write_log(log_path, f'Moved to: {final_dir}')

                # Mark ready
                item.status = MediaItem.STATUS_READY
                item.downloaded_at = timezone.now()
                item.save()
                write_log(log_path, '=== READY ===')
                update_progress(guid, MediaItem.STATUS_READY, 100)

                from media.progress_tracker import clear_progress
                clear_progress(guid)

                # Generate summary if subtitles available
                if item.subtitle_path and settings.STASHCAST_SUMMARY_SENTENCES > 0:
                    generate_summary(item.guid)

                write_log(batch_log_path, f'Completed: {item.title}')

            except Exception as e:
                item.status = MediaItem.STATUS_ERROR
                item.error_message = f'Processing failed: {str(e)}'
                item.save()
                write_log(log_path, f'Error during processing: {e}')
                write_log(batch_log_path, f'FAILED processing for {guid}: {e}')

        write_log(batch_log_path, '=== BATCH COMPLETE ===')

    finally:
        # Clean up batch tmp directory
        try:
            if batch_tmp_dir.exists():
                shutil.rmtree(batch_tmp_dir)
        except Exception as e:
            write_log(batch_log_path, f'Failed to clean up batch tmp: {e}')
