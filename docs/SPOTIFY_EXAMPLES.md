# Spotify URL Examples

This feature allows downloading content from Spotify by finding equivalent sources on other platforms.

## How It Works

When you paste a Spotify URL, StashCast:
1. Extracts metadata from Spotify (title, thumbnail)
2. Searches multiple platforms for matching content
3. Shows you results from: YouTube, SoundCloud, Dailymotion, and Podcast Index (RSS)
4. You select the best match and it downloads from that platform

## Supported Spotify URL Types

### Podcast Episodes
```
https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk
https://open.spotify.com/episode/1234567890abcdef?si=xyz
```

### Podcast Shows
```
https://open.spotify.com/show/2mTUnDkuKUkhiueKcVWoP0
```

### Music Tracks
```
https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT
```

### Albums
```
https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy
```

## Example Workflows

### Downloading a Podcast Episode

1. Someone sends you: `https://open.spotify.com/episode/...`
2. Paste it into StashCast's "Add URL" form
3. StashCast detects it's Spotify and searches for matches
4. You'll see results grouped by platform:
   - **YouTube** - Video versions (often with visuals)
   - **SoundCloud** - Audio-only versions
   - **Dailymotion** - Alternative video platform
   - **Podcast RSS** - Original RSS feed (if Podcast Index API is configured)
5. Select the best match (check duration to verify it's the right episode)
6. Click "Download Selected"

### Downloading a Music Track

1. Paste: `https://open.spotify.com/track/...`
2. StashCast searches YouTube and SoundCloud
3. Select the official music video or audio upload
4. Download

## Platform-Specific Notes

### YouTube
- Most comprehensive results
- Often has official uploads
- Video and audio available

### SoundCloud
- Good for DJ mixes and remixes
- Some podcasts publish here
- Audio-only

### Dailymotion
- Alternative to YouTube
- Some regional content
- Video platform

### Podcast Index (RSS)
- Requires API key (free from podcastindex.org)
- Returns original podcast RSS feed URLs
- Best for podcasts - downloads from the original source
- Set `PODCAST_INDEX_API_KEY` and `PODCAST_INDEX_API_SECRET` in `.env`

## Tips for Finding the Right Match

1. **Check duration** - Make sure the duration matches the original
2. **Check channel/uploader** - Official channels are more reliable
3. **For podcasts** - Podcast Index results give you the original RSS feed
4. **For music** - Look for "Official Audio" or "Official Music Video" in titles

## Configuration

### Enable Podcast Index Search

Get free API keys from [podcastindex.org](https://podcastindex.org/) and add to your `.env`:

```bash
PODCAST_INDEX_API_KEY=your_api_key
PODCAST_INDEX_API_SECRET=your_api_secret
```

This enables searching for original podcast RSS feeds, which often provides higher quality audio than YouTube re-uploads.

## Limitations

- **DRM Content**: Spotify content is DRM-protected - we find alternatives, not bypass DRM
- **Spotify Exclusives**: Some content is only on Spotify and won't be found elsewhere
- **Match Quality**: Automated search may not always find the exact match - verify before downloading
- **Music Availability**: Music labels may not have uploaded to all platforms
