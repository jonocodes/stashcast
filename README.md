![screenshot](./docs/header-transparent.png)

StashCast is an application for downloading online media (audio/video) for offline consumption and exposing it via podcast feeds, so you can watch it later. It runs as a single user Django web app.

## Motivation

I created this since friends and family often send me links to listen to a single episode of a podcast via Apple Podcasts, or a single lecture on youtube. I don't want to subscribe to the show to listen to a single eposide, but I do want to listen to it - later.

## Features

- Download media from any URL supported by yt-dlp, direct media URLs, or HTML with embedded media
- Async background processing via task queue
- Automatic media type detection (audio/video)
- Podcast feed generation (RSS/Atom) for audio and video
- Optional transcoding via ffmpeg
- Extractive summarization from subtitles
- Bookmarklet for one-click media ingestion
- Admin interface for managing downloads
- Django commands for management via CLI instead of web

### Non-features

- Subscribing to playlists. For that use [TubeSync](https://github.com/meeb/tubesync) or [Podsync](https://github.com/mxpv/podsync).

## Web view screenshot

![screenshot](./docs/screenshot-web.png)

## Requirements

- Python 3.13+
- yt-dlp
- ffmpeg

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
- Combined feed: `http://localhost:8000/feeds/combined.xml`

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

### Stash Command

Download media and add it to your podcast feed (same as web interface but runs in foreground):

```bash
# Stash a URL
python manage.py stash https://example.com/video.mp4

# Specify media type (default: auto)
python manage.py stash https://example.com/audio.mp3 --type audio

# Verbose output (shows all processing steps)
python manage.py stash https://example.com/video.mp4 --verbose

# JSON output (machine-readable)
python manage.py stash https://example.com/video.mp4 --json
```

This command performs the same pipeline as the web app's `/stash/` endpoint but runs synchronously in the foreground. Files are saved to the configured media directories and added to your podcast feeds.

### Transcode Command

Download and transcode media from URLs or local files to a custom output directory:

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

This command is for standalone transcoding without adding to podcast feeds.

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

## How It Works

STASHCAST downloads media from URLs and makes it available through podcast feeds. When you submit a URL:

1. Metadata is extracted (title, duration, etc.)
2. Media is downloaded in the background
3. Files are processed (thumbnails converted to WebP, subtitles to VTT)
4. Optional summaries are generated from subtitles
5. Media becomes available in your podcast feed

For technical details, see [ARCHITECTURE.md](ARCHITECTURE.md)

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

```bash
# Run all tests
python manage.py test

# Create and apply database migrations
python manage.py makemigrations
python manage.py migrate
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for more details on the codebase structure and testing strategy.
