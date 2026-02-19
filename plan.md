# TUI Implementation Plan for StashCast

## Overview

Build a Textual-based TUI accessible via `./manage.py tui` that provides an interactive
interface for managing stashed media. No web server or Huey worker needed — direct
database access with synchronous operations and progress display.

## Library Choice

**Textual** (Python TUI framework by Textualize)
- Add `textual` to pyproject.toml dependencies
- Provides DataTable, Input, ProgressBar, Header, Footer, screens, key bindings
- Built-in test harness (`app.run_test()` / `pilot`) integrates with pytest

## Architecture

```
manage.py tui
  └── TuiCommand (Django management command)
        └── StashCastApp (textual.App)
              ├── ItemListScreen (default)  ── reads MediaItem via Django ORM
              ├── ItemDetailScreen          ── reads single MediaItem
              └── StashScreen               ── calls processing.py synchronously
                    └── progress bar driven by worker thread + callbacks
```

The TUI is a thin presentation layer. All business logic stays in the existing
service/processing modules. Django ORM is used directly (DJANGO_SETTINGS_MODULE is
already set by manage.py).

## Features & Screens

### Screen 1: Item List (default screen)

- **DataTable** with columns: Title, Status, Type, Duration, Date Added
- Sorted by most recent first
- **Footer** with key bindings: `s` Stash, `enter` Detail, `d` Delete, `a` Archive, `r` Retry, `f` Filter, `q` Quit
- **Filter bar** (toggled with `f`): filter by status (READY/ERROR/ARCHIVED/all) and text search on title
- Color-code status: READY=green, ERROR=red, DOWNLOADING/PROCESSING=yellow, ARCHIVED=dim

### Screen 2: Item Detail

- Shows all metadata for a selected MediaItem:
  title, source URL, slug, status, media type, duration, file size,
  content path, thumbnail path, subtitle path, created/updated timestamps
- Key bindings: `escape` Back, `d` Delete, `a` Archive/Unarchive, `o` Open source URL

### Screen 3: Stash URL

- **Input** field for URL
- **RadioSet** for type: Auto / Audio / Video
- On submit:
  - Run the stash pipeline synchronously in a Textual **worker thread**
  - Display a **ProgressBar** (0-100%) updated via callbacks
  - Show status label: "Prefetching..." → "Downloading..." → "Processing..." → "Ready!"
  - On completion, return to Item List (refreshed)
  - On error, show error message with option to dismiss

### Mutations

- **Delete**: confirm dialog → `MediaItem.delete()` + optionally `shutil.rmtree()` on the item's directory
- **Archive**: toggle `status` to ARCHIVED / back to READY, set/clear `archived_at`
- **Retry**: for ERROR items, reset status to PREFETCHING and re-run stash pipeline (same as Stash Screen but for existing item)

## Synchronous Stash with Progress

Reuse the existing pipeline from `stash.py` management command and `processing.py`:

```python
# In a Textual worker thread (non-blocking to the UI):
def stash_with_progress(url, requested_type, progress_callback):
    item = MediaItem.objects.create(source_url=url, requested_type=requested_type)
    tmp_dir = create_tmp_dir(item)
    log_path = tmp_dir / 'log.txt'

    progress_callback(0, "Prefetching...")
    strategy = determine_strategy(url)
    prefetch_X(item, tmp_dir, log_path)  # existing processing.py functions

    progress_callback(10, "Downloading...")
    download_X(item, tmp_dir, log_path)  # existing processing.py functions

    progress_callback(40, "Processing...")
    process_files(item, tmp_dir, log_path)  # existing processing.py function

    move_to_final_dir(item, tmp_dir)
    item.status = MediaItem.STATUS_READY
    item.save()
    progress_callback(100, "Ready!")
```

The `progress_callback` posts messages to the Textual app via `app.call_from_thread()`
to update the ProgressBar widget.

## File Structure

```
media/
├── management/commands/
│   └── tui.py              # Django management command entry point
├── tui/
│   ├── __init__.py
│   ├── app.py              # StashCastApp (textual.App subclass)
│   ├── screens/
│   │   ├── __init__.py
│   │   ├── item_list.py    # Item list screen
│   │   ├── item_detail.py  # Item detail screen
│   │   └── stash.py        # Stash URL screen with progress
│   ├── widgets/
│   │   ├── __init__.py
│   │   └── filter_bar.py   # Status/text filter widget
│   └── styles.tcss         # Textual CSS stylesheet
├── tests/
│   └── test_tui.py         # TUI tests
```

## Testing Strategy

### 1. Widget / Screen Tests (Textual Pilot)

Use Textual's built-in `run_test()` harness with pytest:

```python
import pytest
from media.tui.app import StashCastApp

@pytest.mark.django_db
async def test_item_list_shows_items():
    # Create test data
    MediaItem.objects.create(title="Test Episode", status=MediaItem.STATUS_READY, ...)

    async with StashCastApp().run_test() as pilot:
        table = pilot.app.query_one(DataTable)
        assert table.row_count == 1
        assert "Test Episode" in str(table.get_row_at(0))
```

### 2. Interaction Tests

```python
@pytest.mark.django_db
async def test_delete_item():
    item = MediaItem.objects.create(...)
    async with StashCastApp().run_test() as pilot:
        await pilot.press("enter")     # select item
        await pilot.press("d")         # delete
        await pilot.press("y")         # confirm
        assert MediaItem.objects.count() == 0
```

### 3. Snapshot Tests (visual regression)

Textual supports SVG snapshot comparison — render a screen and compare against a
saved reference. Useful for catching unintended layout changes.

### 4. Unit Tests (no TUI)

Test the stash-with-progress function independently by mocking the processing
functions and verifying the callback sequence:

```python
@patch('media.processing.prefetch_ytdlp')
@patch('media.processing.download_ytdlp')
@patch('media.processing.process_files')
def test_stash_progress_callbacks(mock_process, mock_download, mock_prefetch):
    callbacks = []
    stash_with_progress("https://example.com", "auto", lambda pct, msg: callbacks.append((pct, msg)))
    assert callbacks[0] == (0, "Prefetching...")
    assert callbacks[-1] == (100, "Ready!")
```

## Implementation Order

1. **Add `textual` dependency** to pyproject.toml
2. **Create `media/tui/` package** with app.py and basic screen scaffolding
3. **Item List Screen** — read-only list of MediaItems from DB
4. **Item Detail Screen** — view metadata for selected item
5. **Delete & Archive** — mutations with confirmation dialogs
6. **Stash Screen** — URL input + synchronous stash with progress bar
7. **Filter bar** — status and text filtering on item list
8. **Retry** — re-stash errored items
9. **`manage.py tui` command** — wire it all up
10. **Tests** — pilot tests for each screen, unit tests for stash logic
11. **Styles** — polish colors, layout, keybinding footer

## Open Questions / Future

- Should the TUI support batch stashing (multiple URLs at once)? → Defer to v2
- Should we add a log viewer panel? → Defer to v2
- Inline audio playback via terminal? → Probably not practical, defer
