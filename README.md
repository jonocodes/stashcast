# STASHCAST

A single-user Django application for downloading online media (audio/video) for offline consumption and exposing it via podcast feeds.

## Features

- Download media from any URL supported by yt-dlp, direct media URLs, or HTML with referenced media
- Async background processing via Huey task queue
- Automatic media type detection (audio/video)
- Podcast feed generation (RSS/Atom) for audio and video
- Optional transcoding via ffmpeg
- Extractive summarization from subtitles
- Bookmarklet for one-click media ingestion
- Admin interface for managing downloads
- API endpoint protected by API key

## Web view screenshot

![screenshot](./docs/screenshot-web.png)

## Requirements

- Python 3.13+
- SQLite
- yt-dlp
- ffmpeg (for transcoding and subtitle conversion)

## Installation

### 1. Set up environment

First install yt-dlp and ffmpeg to your system.

```bash

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
# Copy example environment file
cp .env.example .env

# Edit .env and set your values
# At minimum, set:
# - STASHCAST_AUDIO_DIR
# - STASHCAST_VIDEO_DIR
# - STASHCAST_API_KEY
```

### 3. Download NLTK data (required for summarization)

```bash
python -c "import nltk; nltk.download('punkt_tab'); nltk.download('stopwords')"
```

### 4. Initialize database

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 5. Run the application

**Option A: Quick Start (all services in one terminal)**

```bash
./run_dev.sh
```

This starts Django server (8000), Huey worker, and test server (8001) all at once.

**Option B: Manual (separate terminals)**

You need to run three processes:

```bash
# Terminal 1: Django development server
python manage.py runserver

# Terminal 2: Huey worker (for background tasks)
python manage.py run_huey

# Terminal 3: Test media server (optional, for testing)
python test_server.py
```

## Usage

### Admin Interface

Access the admin at `http://localhost:8000/admin/`

- View and manage media items
- Monitor download status
- Re-fetch failed downloads
- Regenerate summaries
- View logs

### Bookmarklet

1. Go to `http://localhost:8000/admin/tools/bookmarklet/`
2. Drag the bookmarklet to your bookmarks bar
3. Click it on any page with media to stash

### API Endpoint

```bash
# Stash a URL
curl "http://localhost:8000/stash/?apikey=YOUR_API_KEY&url=https://example.com/video&type=auto"
```

Parameters:

- `apikey` (required): Your API key
- `url` (required): URL to download
- `type` (required): `auto`, `audio`, or `video`

### Podcast Feeds

- Audio feed: `http://localhost:8000/feeds/audio.xml`
- Video feed: `http://localhost:8000/feeds/video.xml`

Add these URLs to your podcast app (AntennaPod, Overcast, etc.)

### Test Server

The test server serves files from `demo_data/` directory on `http://localhost:8001/`

To add test media files:

```bash
# Add your test files to demo_data/
cp /path/to/test.mp3 demo_data/
cp /path/to/test.mp4 demo_data/
```

Then test stashing them:

```bash
# Stash the audio file
curl "http://localhost:8000/stash/?apikey=dev-api-key-change-in-production&url=http://localhost:8001/test.mp3&type=auto"

# Stash the video file
curl "http://localhost:8000/stash/?apikey=dev-api-key-change-in-production&url=http://localhost:8001/test.mp4&type=auto"
```

Your current test files:

- Audio: `http://localhost:8001/01_Eragon_001_of_115.mp3` (4.0 MB)
- Video: `http://localhost:8001/dji_fly_20250723_094842_13_1753459195176_quickshot.mp4` (53.7 MB)

### Transcode Command

Download and transcode media from URLs or local files:

```bash
# Transcode from a URL
python manage.py transcode https://example.com/video.mp4 --outdir ./output

# Transcode from a local file
python manage.py transcode /path/to/video.mp4 --outdir ./output

# The output file will be named using a slug generated from the title
# For example, "My Video.mp4" becomes "my-video.mp4"

# Download only, skip transcoding
python manage.py transcode https://example.com/audio.mp3 --download-only

# Specify media type (default: auto)
python manage.py transcode https://example.com/media --type audio

# Verbose output
python manage.py transcode https://example.com/video.mp4 --verbose

# JSON output
python manage.py transcode https://example.com/video.mp4 --json
```

### Summarize Command

Generate summaries from VTT subtitle files:

```bash
# Summarize a local VTT file
python manage.py summarize demo_data/carpool/subtitles.vtt

# Summarize from a URL
python manage.py summarize http://example.com/subtitles.vtt

# Custom number of sentences (default: 3)
python manage.py summarize demo_data/carpool/subtitles.vtt --sentences 5

# Different algorithms: lexrank (default), textrank, luhn
python manage.py summarize demo_data/carpool/subtitles.vtt --algorithm luhn
```

See `EXAMPLES.md` for more usage examples.

## Architecture

STASHCAST is organized into two layers:

- **Service Layer** (`service/`) - Framework-agnostic media processing shared by CLI and web app
- **Web App Layer** (`media/`) - Django-specific models, views, and background tasks

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed information about the service layer, data flow, and design principles.

### Media Processing Pipeline

1. **PREFETCHING**: Extract metadata and validate URL
2. **DOWNLOADING**: Download media files
3. **PROCESSING**: Transcode if needed, convert subtitles to VTT
4. **READY**: Media is available

### Directory Structure

For the web app (stash endpoint):

```
/audio/<slug>/
  content.m4a OR content.mp3
  thumbnail.webp (if available)
  subtitles.vtt (if available)

/video/<slug>/
  content.mp4
  thumbnail.webp (if available)
  subtitles.vtt (if available)
```

For the transcode command (CLI):

The transcode command outputs files with slug-based names directly in the specified output directory:

```
/output-dir/
  <slug>.mp3 OR <slug>.mp4 (depending on media type)
```

### Key Components

**Service Layer** (shared by CLI and web app):
- **Strategy** (`service/strategy.py`): Download strategy detection
- **Resolve** (`service/resolve.py`): Metadata extraction and type resolution
- **Download** (`service/download.py`): HTTP and yt-dlp download implementations
- **Process** (`service/process.py`): Transcoding and metadata embedding
- **Config** (`service/config.py`): Configuration adapter

**Web App Layer** (Django-specific):
- **Models** (`media/models.py`): MediaItem with all metadata
- **Tasks** (`media/tasks.py`): Huey background tasks for downloading
- **Views** (`media/views.py`): Stash endpoint, item detail pages
- **Feeds** (`media/feeds.py`): Podcast feed generation
- **Admin** (`media/admin.py`): Rich admin interface

## Configuration

See `.env.example` for all available configuration options.

### Environment Variables

#### Required

- `STASHCAST_AUDIO_DIR`: Directory for audio files
- `STASHCAST_VIDEO_DIR`: Directory for video files
- `STASHCAST_API_KEY`: API key for stash endpoint

#### Optional

- `STASHCAST_MEDIA_BASE_URL`: External CDN URL for media files
- `STASHCAST_DEFAULT_YTDLP_ARGS_AUDIO`: Default yt-dlp arguments for audio
- `STASHCAST_DEFAULT_YTDLP_ARGS_VIDEO`: Default yt-dlp arguments for video
- `STASHCAST_DEFAULT_FFMPEG_ARGS_AUDIO`: Default ffmpeg arguments for audio
- `STASHCAST_DEFAULT_FFMPEG_ARGS_VIDEO`: Default ffmpeg arguments for video
- `STASHCAST_SLUG_MAX_WORDS`: Max words in slug (default: 6)
- `STASHCAST_SLUG_MAX_CHARS`: Max characters in slug (default: 40)

## Development

### Running tests

```bash
# Run all tests (163 total)
python manage.py test

# Run only service layer tests (121 tests)
python manage.py test service.tests

# Run only web app tests (42 tests)
python manage.py test media.tests

# Run tests in parallel for faster execution
python manage.py test --parallel
```

### Database migrations

```bash
# Create migrations
python manage.py makemigrations

# Apply migrations
python manage.py migrate
```

## Overwrite Behavior

Fetching the same URL again:

- Reuses the same database row
- Reuses the same slug and GUID
- Overwrites files on disk
- Appends a log entry noting the overwrite

## Summary Generation

Summaries are generated from downloaded subtitles using extractive summarization (LexRank).

- Automatically generated during download if subtitles are available
- Can be regenerated from admin interface
- Future-ready for audio transcription-based summaries
