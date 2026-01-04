# Transcode Management Command

The `transcode` management command provides a CLI interface for downloading and transcoding media files without touching the database. This is useful for testing downloads, verifying transcoding settings, and manual media processing.

## Usage

```bash
./manage.py transcode <input> [options]
```

## Arguments

### Required

- `input` - URL or file path to media (can be direct media URL, hosted site URL, or HTML page with embedded media)

### Optional

- `--type {auto,audio,video}` - Media type to download (default: auto)
- `--outdir PATH` - Output directory (default: current directory)
- `--download-only` - Download only, skip transcoding
- `--keep-original` - Keep original file as original.<ext>
- `--dry-run` - Show what would be done without actually downloading
- `--verbose` - Enable verbose output
- `--json` - Output result as JSON

## Examples

### Dry run to preview what will happen

```bash
./manage.py transcode "https://example.com/video.mp4" --dry-run
```

Output:
```
DRY RUN MODE - No files will be downloaded
Input: https://example.com/video.mp4
Requested type: auto
Output directory: .
Strategy: direct
Title: video
Resolved type: video
Dry run complete
```

### Download MP3 file (no transcoding needed)

```bash
./manage.py transcode \
  "https://archive.org/download/testmp3testfile/mpthreetest.mp3" \
  --outdir /tmp/test \
  --verbose
```

Output:
```
Processing URL: https://archive.org/download/testmp3testfile/mpthreetest.mp3
Strategy: direct
Title: mpthreetest
Requested type: auto, Resolved type: audio
Downloading...
No transcoding needed, file format is already compatible
✓ Transcode complete
  Output: /tmp/test/content.mp3
  Size: 198,658 bytes
  Transcoded: No
```

### Download and keep original file

```bash
./manage.py transcode \
  "https://example.com/audio.ogg" \
  --outdir /tmp/test \
  --keep-original \
  --type audio
```

This will create:
- `/tmp/test/content.m4a` (transcoded to M4A)
- `/tmp/test/original.ogg` (original file)

### Get JSON output

```bash
./manage.py transcode \
  "https://example.com/video.mp4" \
  --outdir /tmp/test \
  --json
```

Output:
```json
{
  "success": true,
  "url": "https://example.com/video.mp4",
  "strategy": "direct",
  "requested_type": "auto",
  "resolved_type": "video",
  "title": "video",
  "output_path": "/tmp/test/content.mp4",
  "file_size": 1234567,
  "transcoded": false,
  "kept_original": false
}
```

### Download only (skip processing)

```bash
./manage.py transcode \
  "https://example.com/video.mp4" \
  --download-only \
  --outdir /tmp/test
```

This downloads the file as-is without any transcoding.

## Output Files

The command writes files to the specified output directory:

### Always created:
- `content.<ext>` - The final media file (transcoded if necessary)

### Optional (with flags):
- `original.<ext>` - Original downloaded file (with `--keep-original`)
- `thumbnail.webp` - Thumbnail image (if available from source)
- `subtitles.vtt` - Subtitle file (if available from source)

## Architecture

The transcode command is built on a reusable service layer that can be used by both the CLI and the web app:

### Service Modules

1. **service/config.py** - Settings adapter
   - Centralizes access to Django settings
   - Provides configuration for yt-dlp and ffmpeg

2. **service/strategy.py** - Download strategy detection
   - Determines whether to use direct HTTP or yt-dlp
   - Single source of truth for strategy logic

3. **service/resolve.py** - Metadata extraction and type resolution
   - Prefetches metadata without downloading
   - Resolves 'auto' type to 'audio' or 'video'
   - Handles HTML extraction fallback

4. **service/download.py** - Download implementation
   - Direct HTTP downloads
   - yt-dlp downloads with thumbnail/subtitle extraction

5. **service/process.py** - Transcoding logic
   - Determines if transcoding is needed
   - Runs ffmpeg with appropriate settings
   - Processes thumbnails and subtitles

6. **service/transcode_service.py** - Main entrypoint
   - `transcode_url_to_dir()` function orchestrates the full workflow
   - Used by both CLI and (potentially) the web app

### CLI Wrapper

- **media/management/commands/transcode.py** - Thin wrapper
  - Parses command-line arguments
  - Calls `transcode_url_to_dir()`
  - Formats output (human-readable or JSON)

## Transcoding Rules

The command follows these rules when deciding whether to transcode:

### Audio
- **Keep as-is**: MP3, M4A
- **Transcode to M4A**: OGG, Opus, WebM, FLAC, WAV, AAC
- Target format: M4A with AAC codec @ 128K

### Video
- **Keep as-is**: MP4
- **Transcode to MP4**: WebM, MKV, AVI, MOV
- Target format: MP4 with H.264 video + AAC audio @ 720p

These rules maximize compatibility with podcast players and mobile devices.

## Error Handling

The command will fail with a clear error message if:
- URL is a playlist (not supported)
- Download fails (network error, invalid URL)
- Transcoding fails (ffmpeg error)
- Output directory is not writable

Use `--verbose` to see detailed error messages and logs.
