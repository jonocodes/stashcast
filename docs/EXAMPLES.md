# STASHCAST Examples

## Transcode Command

The `transcode` management command downloads and transcodes media from URLs or local file paths. Output files are named using a slug generated from the media title.

### Basic Usage

Transcode from a URL:
```bash
./manage.py transcode https://example.com/video.mp4 --outdir ./output
```

Transcode from a local file path:
```bash
# Video file
./manage.py transcode demo_data/carpool/vid.mp4 --outdir ./output

# Audio file
./manage.py transcode /path/to/audio.mp3 --outdir ./output
```

### Output Files

The transcode command creates files with slug-based names:

```bash
# Input: "My Amazing Video.mp4"
# Output: ./output/my-amazing-video.mp4

# Input: demo_data/carpool/vid.mp4 (title: "vid")
# Output: ./output/vid.mp4
```

### Options

#### Download only (skip transcoding)
```bash
./manage.py transcode https://example.com/audio.mp3 --download-only
```

#### Specify media type
```bash
# Force audio extraction from a video
./manage.py transcode https://example.com/video.mp4 --type audio

# Force video (default is auto-detect)
./manage.py transcode https://example.com/media --type video
```

#### Custom output directory
```bash
./manage.py transcode https://example.com/video.mp4 --outdir /tmp/videos
```

#### Verbose output
```bash
./manage.py transcode https://example.com/video.mp4 --verbose
```

#### JSON output
```bash
./manage.py transcode https://example.com/video.mp4 --json
```

### Example Output

```
✓ Transcode complete
  URL: https://example.com/my-video.mp4
  Title: My Video
  Slug: my-video
  Type: video
  Strategy: direct
  Output: ./output/my-video.mp4
  Size: 10,485,760 bytes
  Transcoded: No
```

## Summarize Command

The `summarize` management command generates summaries from VTT subtitle files.

### Basic Usage

Summarize a local VTT file:
```bash
./manage.py summarize demo_data/carpool/subtitles.vtt
```

Summarize a VTT file from a URL:
```bash
./manage.py summarize http://example.com/subtitles.vtt
```

### Options

#### Custom number of sentences
```bash
# 5-sentence summary
./manage.py summarize demo_data/carpool/subtitles.vtt --sentences 5

# Single sentence summary
./manage.py summarize demo_data/carpool/subtitles.vtt --sentences 1
```

#### Different algorithms
```bash
# LexRank (default) - graph-based ranking
./manage.py summarize demo_data/carpool/subtitles.vtt --algorithm lexrank

# TextRank - similar to PageRank
./manage.py summarize demo_data/carpool/subtitles.vtt --algorithm textrank

# Luhn - frequency-based
./manage.py summarize demo_data/carpool/subtitles.vtt --algorithm luhn
```

#### Combined options
```bash
./manage.py summarize demo_data/carpool/subtitles.vtt --sentences 5 --algorithm luhn
```

### Example Output

```
Reading VTT from file: demo_data/carpool/subtitles.vtt
Extracting text from VTT...
Extracted 1337 characters
Generating 3-sentence summary using lexrank...

============================================================
SUMMARY
============================================================

Django is a high-level Python web framework that encourages rapid development.
The framework has excellent documentation and a large community of developers.
This makes it easy to find help and resources when you need them.

============================================================
```

## Stashing Media

### From Test Server

```bash
# Stash audio file
curl "http://localhost:8000/stash/?apikey=dev-api-key-change-in-production&url=http://localhost:8001/pecha-kucha-aud/aud.mp3&type=auto"

# Stash video file
curl "http://localhost:8000/stash/?apikey=dev-api-key-change-in-production&url=http://localhost:8001/pecha-kucha-vid/vid.mp4&type=auto"
```

### From YouTube (requires yt-dlp)

```bash
# Auto-detect media type
curl "http://localhost:8000/stash/?apikey=dev-api-key-change-in-production&url=https://www.youtube.com/watch?v=VIDEO_ID&type=auto"

# Force audio only
curl "http://localhost:8000/stash/?apikey=dev-api-key-change-in-production&url=https://www.youtube.com/watch?v=VIDEO_ID&type=audio"

# Force video
curl "http://localhost:8000/stash/?apikey=dev-api-key-change-in-production&url=https://www.youtube.com/watch?v=VIDEO_ID&type=video"
```

## Managing Items in Django Admin

### Re-fetch an Item

1. Go to http://localhost:8000/admin/media/mediaitem/
2. Select the items you want to re-fetch
3. Choose "Re-fetch selected items" from the actions dropdown
4. Click "Go"

### Regenerate Summaries

1. Go to http://localhost:8000/admin/media/mediaitem/
2. Select items with subtitles
3. Choose "Regenerate summaries" from the actions dropdown
4. Click "Go"

## Viewing Feeds

### In a Browser
- Audio: http://localhost:8000/feeds/audio.xml
- Video: http://localhost:8000/feeds/video.xml

### In a Podcast App
Add the feed URL to your podcast app:
- AntennaPod
- Overcast
- Pocket Casts
- Apple Podcasts
- etc.

## Bookmarklet

1. Go to http://localhost:8000/admin/tools/bookmarklet/
2. Configure your preferences
3. Drag the bookmarklet to your bookmarks bar
4. Click it on any page with media to stash

## Testing the Full Pipeline

Run the automated test:
```bash
./test_download.sh
```

This will:
1. Check that servers are running
2. Download audio and video files from test server
3. Wait for processing to complete
4. Show you where to check results
