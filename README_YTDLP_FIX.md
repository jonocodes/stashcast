# yt-dlp Apple Podcasts Video Fix Package

## What is this?

Complete investigation and fix for yt-dlp's ApplePodcasts extractor to support video podcasts. Currently, ALL Apple Podcasts are downloaded as audio-only, even when they're actually video content.

## Quick Demo

Run the verification script to see the issue:

```bash
python3 verify_issue.py
```

This will:
- ✅ Confirm video podcasts have `mediaType: "video"` in Apple's JSON
- ✅ Confirm audio podcasts have `mediaType: "audio"` in Apple's JSON
- ✅ Show that yt-dlp ignores this field and treats everything as audio

## Files Included

### 📋 Documentation
| File | Purpose |
|------|---------|
| `APPLE_PODCASTS_VIDEO_INVESTIGATION.md` | Complete technical investigation with JSON analysis |
| `YTDLP_CONTRIBUTION_SUMMARY.md` | Step-by-step guide for contributing to yt-dlp |
| `README_YTDLP_FIX.md` | This file |

### 💻 Code & Patches
| File | Purpose |
|------|---------|
| `applepodcasts_video_fix.patch` | Git patch ready to apply |
| `applepodcasts_fixed.py` | Complete fixed extractor with comments |
| `verify_issue.py` | Script to demonstrate the bug and verify the fix |

### 📝 GitHub Templates
| File | Purpose |
|------|---------|
| `GITHUB_BUG_REPORT.md` | Bug report template for GitHub issue |
| `GITHUB_PR_DESCRIPTION.md` | Pull request description template |

## The Fix (TL;DR)

**Current code** (line 78 of `applepodcasts.py`):
```python
'vcodec': 'none',  # ❌ Always treats as audio
```

**Fixed code**:
```python
# Extract mediaType to determine if video or audio
media_type = traverse_obj(model_data, ('playAction', 'episodeOffer', 'mediaType', {str}))

'vcodec': 'none' if media_type != 'video' else None,  # ✅ Checks actual type
```

**Result**:
- Video podcasts: `vcodec: None` → yt-dlp detects video correctly → downloads `.mp4` ✅
- Audio podcasts: `vcodec: 'none'` → yt-dlp treats as audio → downloads `.mp3` ✅

## How to Contribute This Fix

### Option 1: File a Bug Report (Easier)

1. Go to https://github.com/yt-dlp/yt-dlp/issues/new
2. Copy from `GITHUB_BUG_REPORT.md`
3. Submit

### Option 2: Submit a Pull Request (More Impact)

```bash
# Fork yt-dlp on GitHub first!

# Clone and setup
git clone https://github.com/YOUR_USERNAME/yt-dlp.git
cd yt-dlp
git checkout -b applepodcasts-video-support

# Apply the fix
git apply /path/to/applepodcasts_video_fix.patch

# Or manually edit yt_dlp/extractor/applepodcasts.py following the patch

# Test and format
hatch fmt
hatch test test.test_download:TestApplePodcasts  # optional

# Commit and push
git add yt_dlp/extractor/applepodcasts.py
git commit -m "[ie/ApplePodcasts] Add video podcast support"
git push origin applepodcasts-video-support

# Create PR on GitHub using GITHUB_PR_DESCRIPTION.md
```

## Testing Examples

### Video Podcast (Currently Broken)
```bash
yt-dlp 'https://podcasts.apple.com/gb/podcast/apple-event-may-7/id275834665?i=1000654821230'
# ❌ Downloads as .mp3 (audio only)
# ✅ Should download as .mp4 (video with audio)
```

### Audio Podcast (Works Fine)
```bash
yt-dlp 'https://podcasts.apple.com/us/podcast/ferreck-dawn-to-the-break-of-dawn-117/id1625658232?i=1000665010654'
# ✅ Downloads as .mp3 (audio only) - correct!
```

## Why This Matters

### Affected Content
- 🎥 Apple Events (product launches, keynotes)
- 🎥 WWDC Sessions (developer presentations)
- 🎥 Educational video podcasts
- 🎥 Any video podcast on Apple Podcasts

### Impact
- **Users**: Can't download video podcasts from Apple Podcasts
- **Developers**: Tools using yt-dlp (like StashCast) can't detect video
- **Scale**: Hundreds of video podcasts on Apple Podcasts

## Key Points

✅ **Simple**: Only 3 lines of code added
✅ **Safe**: Fully backward compatible (audio podcasts unchanged)
✅ **Data exists**: Apple already provides `mediaType` field
✅ **Well-tested**: Includes test cases for both video and audio
✅ **High impact**: Enables entire category of content

## Questions?

Read the detailed investigation:
- Technical analysis → `APPLE_PODCASTS_VIDEO_INVESTIGATION.md`
- Contribution guide → `YTDLP_CONTRIBUTION_SUMMARY.md`

## Background

This fix was created while investigating why video podcasts from Apple Podcasts were downloading as audio-only in StashCast (which uses yt-dlp). The issue is in yt-dlp's ApplePodcasts extractor, which hardcodes all content as audio.

---

**Created**: 2026-01-10
**Status**: Ready for contribution to yt-dlp
**Verified**: Both video and audio podcasts tested and confirmed
