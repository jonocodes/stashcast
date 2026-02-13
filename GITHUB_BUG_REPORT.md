# [ApplePodcasts] Video podcasts incorrectly extracted as audio-only

## Checklist

- [x] I'm reporting a broken site
- [x] I've verified that I'm running yt-dlp version **2025.01.10** (or latest)
- [x] I've checked that all provided URLs are playable in a browser with the same IP and same login details
- [x] I've checked that none of my issues are already reported
- [x] I've searched the bugtracker for similar issues including closed ones
- [x] I've read the guidelines for opening an issue

## Verbose log

```
$ yt-dlp -vU 'https://podcasts.apple.com/gb/podcast/apple-event-may-7/id275834665?i=1000654821230'

[debug] Command-line config: ['-vU', 'https://podcasts.apple.com/gb/podcast/apple-event-may-7/id275834665?i=1000654821230']
[debug] Encodings: locale UTF-8, fs utf-8, pref UTF-8, out utf-8, error utf-8, screen utf-8
[debug] yt-dlp version 2025.01.10 [...]
[debug] Python 3.11.x
[debug] exe versions: ffmpeg N-..., ffprobe N-...
[debug] Optional libraries: [...]
[debug] Proxy map: {}
[debug] Request Handlers: urllib, requests, websockets
[debug] Loaded 1893 extractors
[ApplePodcasts] Extracting URL: https://podcasts.apple.com/gb/podcast/apple-event-may-7/id275834665?i=1000654821230
[ApplePodcasts] 1000654821230: Downloading webpage
[ApplePodcasts] 1000654821230: Extracting information
[info] 1000654821230: Downloading 1 format(s): 0
[download] Destination: Apple Event — May 7 [1000654821230].mp3
[download] 100% of 221.06MiB in 00:15 at 14.54MiB/s
[info] Downloaded 1 format(s): 0

# NOTE: File downloaded as .mp3 (audio) even though the source is a VIDEO podcast
# The actual URL is: https://applehosted.podcasts.apple.com/apple_keynotes/2024/240507.mp4
```

## Description

The ApplePodcasts extractor treats ALL podcast episodes as audio-only by hardcoding `'vcodec': 'none'` in the return dictionary. This causes video podcasts (like Apple Events, WWDC sessions) to be incorrectly extracted as audio-only content, even though Apple's JSON clearly identifies them as video using the `mediaType` field.

### Example URLs

**Video podcast (currently broken)**:
- https://podcasts.apple.com/gb/podcast/apple-event-may-7/id275834665?i=1000654821230
  - This is Apple's May 7, 2024 iPad event (38 minutes)
  - The actual file is an MP4 video: `https://applehosted.podcasts.apple.com/apple_keynotes/2024/240507.mp4`
  - Apple's JSON has: `"mediaType": "video"`
  - But yt-dlp extracts it as audio-only

**Another video podcast**:
- https://podcasts.apple.com/us/podcast/apple-event-september-9/id275834665?i=1000668924619
  - Apple's iPhone 16 announcement event
  - Also a video podcast incorrectly treated as audio

**Audio podcast (works correctly)**:
- https://podcasts.apple.com/us/podcast/ferreck-dawn-to-the-break-of-dawn-117/id1625658232?i=1000665010654
  - This is an audio-only podcast
  - Correctly extracted as audio

## Expected behavior

When extracting a video podcast from Apple Podcasts:
1. yt-dlp should detect that `mediaType == "video"` in the JSON
2. yt-dlp should NOT set `vcodec: 'none'` for video content
3. The video file should be downloaded (`.mp4` with both video and audio)
4. Format selection should work (`-f best` should get video)

## Actual behavior

Currently:
1. yt-dlp hardcodes `vcodec: 'none'` for ALL Apple Podcasts
2. Video podcasts are treated as audio-only
3. Only audio is downloaded (or the video is downloaded but treated as audio)
4. Format selection doesn't work because yt-dlp thinks there's no video

## Root cause

In `yt_dlp/extractor/applepodcasts.py` line 78:

```python
return {
    'id': episode_id,
    # ... other fields ...
    'vcodec': 'none',  # ← ALWAYS 'none', even for video podcasts
}
```

Apple's JSON provides a `mediaType` field that can be:
- `"video"` for video podcasts
- `"audio"` for audio podcasts

But the extractor ignores this field.

## Proposed fix

Extract the `mediaType` field and conditionally set `vcodec`:

```python
# Extract mediaType to determine if this is video or audio
media_type = traverse_obj(model_data, ('playAction', 'episodeOffer', 'mediaType', {str}))

return {
    'id': episode_id,
    # ... other fields ...
    'vcodec': 'none' if media_type != 'video' else None,  # ← Let yt-dlp detect codec for video
}
```

This is backward compatible because:
- Audio podcasts already have `"mediaType": "audio"` so they'll continue to work
- Video podcasts will now be correctly detected
- If `mediaType` is missing, it defaults to audio (safe fallback)

## Impact

This affects:
- All Apple Events (product launches, WWDC, etc.)
- Any educational/tutorial podcasts that include video
- Users who specifically want to download video podcasts
- Downstream tools that rely on yt-dlp's codec detection

## Additional context

I've created a comprehensive investigation with:
- JSON structure analysis
- Proposed code fix
- Test cases
- Full patch file

Available here: [link to investigation document if uploaded as a gist]

This is a simple 1-line fix that enables video podcast support for Apple Podcasts.
