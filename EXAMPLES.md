# STASHCAST Examples

## Summarize Command

The `summarize` management command generates summaries from VTT subtitle files.

### Basic Usage

Summarize a local VTT file:
```bash
python manage.py summarize demo_data/sample.vtt
```

Summarize a VTT file from a URL:
```bash
python manage.py summarize http://example.com/subtitles.vtt
```

### Options

#### Custom number of sentences
```bash
# 5-sentence summary
python manage.py summarize demo_data/sample.vtt --sentences 5

# Single sentence summary
python manage.py summarize demo_data/sample.vtt --sentences 1
```

#### Different algorithms
```bash
# LexRank (default) - graph-based ranking
python manage.py summarize demo_data/sample.vtt --algorithm lexrank

# TextRank - similar to PageRank
python manage.py summarize demo_data/sample.vtt --algorithm textrank

# Luhn - frequency-based
python manage.py summarize demo_data/sample.vtt --algorithm luhn
```

#### Combined options
```bash
python manage.py summarize demo_data/sample.vtt --sentences 5 --algorithm luhn
```

### Example Output

```
Reading VTT from file: demo_data/sample.vtt
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
curl "http://localhost:8000/stash/?apikey=dev-api-key-change-in-production&url=http://localhost:8001/01_Eragon_001_of_115.mp3&type=auto"

# Stash video file
curl "http://localhost:8000/stash/?apikey=dev-api-key-change-in-production&url=http://localhost:8001/dji_fly_20250723_094842_13_1753459195176_quickshot.mp4&type=auto"
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
