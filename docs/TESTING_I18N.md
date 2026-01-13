# Testing Multi-Language Support

This document describes how to test the internationalization (i18n) features.

## Automated Tests to Run

Before deploying i18n changes, run the full test suite:

```bash
# Run all tests
pytest

# Or use the justfile command
just test
```

Expected: All existing tests should pass without modification.

## Language Validation Tests

### Test 1: Supported Language Codes

Test that supported language codes work correctly:

```bash
# Test English (default)
LANGUAGE_CODE=en python manage.py check
# Expected: No errors

# Test English with region
LANGUAGE_CODE=en-us python manage.py check
# Expected: No errors

# Test Spanish
LANGUAGE_CODE=es python manage.py check
# Expected: No errors

# Test French
LANGUAGE_CODE=fr python manage.py check
# Expected: No errors

# Test German
LANGUAGE_CODE=de python manage.py check
# Expected: No errors

# Test Japanese
LANGUAGE_CODE=ja python manage.py check
# Expected: No errors

# Test Chinese Simplified
LANGUAGE_CODE=zh-hans python manage.py check
# Expected: No errors

# Test Chinese Traditional
LANGUAGE_CODE=zh-hant python manage.py check
# Expected: No errors
```

### Test 2: Unsupported Language Code (Should Fail)

Test that unsupported language codes fail on startup:

```bash
# Test unsupported language
LANGUAGE_CODE=xyz python manage.py check
# Expected: ValueError with message about unsupported language

# Test unsupported variant
LANGUAGE_CODE=klingon python manage.py check
# Expected: ValueError with message about unsupported language
```

Expected error message format:
```
ValueError: Unsupported LANGUAGE_CODE: 'xyz'.
Supported languages: en, es, fr, de, ja, zh-hans, zh-hant, pt, it, ru, ar, ko.
Set LANGUAGE_CODE environment variable to one of the supported languages.
```

### Test 3: Missing LANGUAGE_CODE (Should Use Default)

```bash
# Unset LANGUAGE_CODE
unset LANGUAGE_CODE
python manage.py check
# Expected: No errors, uses default 'en-us'
```

## Template Translation Tests

### Test 4: Translation Tags Present

Verify that translation tags are present in all templates:

```bash
# Check for {% trans %} tags
grep -r "{% trans " media/templates/

# Check for {% load i18n %} tags
grep -r "{% load.*i18n" media/templates/
```

Expected: All user-facing strings should be wrapped in `{% trans %}` tags.

### Test 5: Model Choice Fields

Verify that model choice fields use gettext_lazy:

```bash
# Check models.py for translation
grep -A 5 "CHOICES = " media/models.py | grep "_("
```

Expected: All choice tuples should use `_()` for translation.

## Subtitle Language Tests

### Test 6: Subtitle Language Extraction

Test that STASHCAST_SUBTITLE_LANGUAGE is correctly extracted:

```python
# In Django shell (./manage.py shell):
from django.conf import settings

# Test extraction
test_cases = [
    ('en', 'en'),
    ('en-us', 'en'),
    ('en-gb', 'en'),
    ('zh-hans', 'zh-hans'),
    ('zh-hant', 'zh-hant'),
    ('pt-br', 'pt'),
]

for input_code, expected_subtitle_lang in test_cases:
    # Set LANGUAGE_CODE and reimport settings
    import os
    os.environ['LANGUAGE_CODE'] = input_code
    # ... check STASHCAST_SUBTITLE_LANGUAGE equals expected
```

### Test 7: yt-dlp Subtitle Download

Test that subtitles are downloaded in the correct language:

```bash
# Set language to Spanish
export LANGUAGE_CODE=es

# Start server and worker
./manage.py runserver &
./manage.py run_huey &

# Add a YouTube video with Spanish subtitles
# Check that Spanish subtitles are downloaded
```

Expected: Video should download with Spanish subtitles (if available).

## UI Translation Tests

### Test 8: English UI (Default)

```bash
export LANGUAGE_CODE=en
./manage.py runserver
```

Visit pages and verify:
- Home page: All text in English
- Admin form: Labels and buttons in English
- Grid view: Headers and messages in English
- Feed links: All text in English

### Test 9: Spanish UI (When Translations Exist)

After creating Spanish translations:

```bash
# Generate and compile Spanish translations
python manage.py makemessages -l es
# Edit locale/es/LC_MESSAGES/django.po
python manage.py compilemessages

export LANGUAGE_CODE=es
./manage.py runserver
```

Visit pages and verify:
- Home page: Text translated to Spanish
- Admin form: Labels and buttons in Spanish
- Status messages: In Spanish
- Feed links: In Spanish

### Test 10: Fallback to English

When translations don't exist for a string:

```bash
export LANGUAGE_CODE=fr
./manage.py runserver
```

Expected: Untranslated strings should display in English (source language).

## Integration Tests

### Test 11: End-to-End Download Flow

Test complete flow with non-English language:

```bash
export LANGUAGE_CODE=ja
./manage.py runserver
./manage.py run_huey
```

1. Visit home page (should show Japanese text when translated)
2. Click "Add" button
3. Enter a YouTube URL
4. Select media type
5. Submit form
6. Check status messages
7. Wait for download completion
8. Check that Japanese subtitles were downloaded (if available)
9. View item detail page
10. Check RSS feed

Expected: All user-facing text should be in Japanese (when translated), and Japanese subtitles should be downloaded.

### Test 12: Language Consistency

Verify that UI language and subtitle language stay consistent:

```bash
export LANGUAGE_CODE=de
```

1. Download a video
2. Check subtitle language in media file
3. Check UI language in templates
4. Verify both are German

## Accessibility Tests

### Test 13: Screen Reader Compatibility

With a screen reader enabled:

1. Navigate the home page
2. Tab through navigation elements
3. Verify ARIA labels are present
4. Check that translated text is read correctly

### Test 14: HTML Lang Attribute

Verify the HTML lang attribute matches LANGUAGE_CODE:

```bash
export LANGUAGE_CODE=fr
./manage.py runserver
```

Check home page source:
```html
<html lang="fr">
```

Expected: The lang attribute should match the primary language code.

## Performance Tests

### Test 15: Translation Loading

Measure page load time with translations:

```bash
# Before translations
time curl http://localhost:8000/

# After translations
export LANGUAGE_CODE=es
python manage.py compilemessages
time curl http://localhost:8000/
```

Expected: Minimal performance difference (< 10ms).

## Regression Tests

### Test 16: Existing Functionality

Verify all existing features still work:

- [ ] Media download works
- [ ] Thumbnail extraction works
- [ ] Subtitle extraction works (now language-aware)
- [ ] Transcoding works
- [ ] Summarization works
- [ ] RSS feeds generate correctly
- [ ] Admin interface works
- [ ] Bookmarklet works
- [ ] Task queue processes jobs
- [ ] Database queries work

## Manual Testing Checklist

- [ ] Install fresh and run migrations
- [ ] Create admin user
- [ ] Set LANGUAGE_CODE to 'es'
- [ ] Start server
- [ ] Verify home page displays
- [ ] Add a media URL
- [ ] Check worker processes it
- [ ] View grid/list views
- [ ] Check RSS feeds
- [ ] Try different language codes
- [ ] Try invalid language code (should error)
- [ ] Verify subtitles download in correct language

## Known Issues / Edge Cases

1. **Missing translations**: If a language is supported but translations don't exist, strings display in English
2. **Subtitle availability**: Not all videos have subtitles in all languages
3. **Auto-generated subtitles**: May fallback to auto-generated if native subtitles unavailable
4. **RTL languages**: Arabic may need additional CSS for proper text direction

## Adding Test Cases

When adding new translatable strings:

1. Add to template with `{% trans %}`
2. Add to models with `_()`
3. Run `makemessages`
4. Verify string appears in .po file
5. Add translation test case above

## CI/CD Integration

Recommended CI checks:

```yaml
- name: Check for untranslated strings
  run: |
    python manage.py makemessages -a --no-obsolete
    git diff --exit-code locale/

- name: Compile translations
  run: |
    python manage.py compilemessages

- name: Validate language codes
  run: |
    for lang in en es fr de ja zh-hans; do
      LANGUAGE_CODE=$lang python manage.py check
    done
```
