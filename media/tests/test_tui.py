"""Tests for the StashCast TUI."""

import os

os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'

import pytest
from django.test import TestCase, TransactionTestCase

from media.models import MediaItem


def _create_test_items():
    """Helper to create standard test items."""
    item1 = MediaItem.objects.create(
        source_url='https://example.com/video1',
        requested_type=MediaItem.REQUESTED_TYPE_AUTO,
        title='Test Video One',
        slug='test-video-one',
        status=MediaItem.STATUS_READY,
        media_type='video',
        duration_seconds=120,
    )
    item2 = MediaItem.objects.create(
        source_url='https://example.com/audio1',
        requested_type=MediaItem.REQUESTED_TYPE_AUDIO,
        title='Test Audio Two',
        slug='test-audio-two',
        status=MediaItem.STATUS_ERROR,
        media_type='audio',
        error_message='Download failed',
    )
    return item1, item2


# ---- Async TUI tests (need TransactionTestCase for SQLite cross-thread access) ----


class TuiItemListTest(TransactionTestCase):
    """Test the item list screen loads and displays data correctly."""

    @pytest.mark.asyncio
    async def test_item_list_shows_items(self):
        """Items appear in the DataTable."""
        _create_test_items()
        from media.tui.app import StashCastApp
        from textual.widgets import DataTable

        app = StashCastApp()
        async with app.run_test():
            table = app.screen.query_one(DataTable)
            assert table.row_count == 2

    @pytest.mark.asyncio
    async def test_item_list_filter_by_status(self):
        """Filtering by status narrows the table."""
        _create_test_items()
        from media.tui.app import StashCastApp
        from textual.widgets import DataTable

        app = StashCastApp()
        async with app.run_test():
            screen = app.screen
            screen._status_filter = 'READY'
            screen._load_items()
            table = screen.query_one(DataTable)
            assert table.row_count == 1

    @pytest.mark.asyncio
    async def test_item_list_filter_by_text(self):
        """Text filter narrows results to matching titles."""
        _create_test_items()
        from media.tui.app import StashCastApp
        from textual.widgets import DataTable

        app = StashCastApp()
        async with app.run_test():
            screen = app.screen
            screen._text_filter = 'Audio'
            screen._load_items()
            table = screen.query_one(DataTable)
            assert table.row_count == 1

    @pytest.mark.asyncio
    async def test_item_list_refresh(self):
        """Calling action_refresh_list reloads from DB."""
        _create_test_items()
        from media.tui.app import StashCastApp
        from textual.widgets import DataTable

        app = StashCastApp()
        async with app.run_test():
            MediaItem.objects.create(
                source_url='https://example.com/new',
                requested_type=MediaItem.REQUESTED_TYPE_AUTO,
                title='New Item',
                slug='new-item',
                status=MediaItem.STATUS_READY,
            )
            # Call action directly since keybinding for R is tricky in tests
            app.screen.action_refresh_list()
            table = app.screen.query_one(DataTable)
            assert table.row_count == 3


class TuiItemDetailTest(TransactionTestCase):
    """Test the item detail screen."""

    @pytest.mark.asyncio
    async def test_detail_screen_renders(self):
        """Detail screen displays item metadata."""
        item = MediaItem.objects.create(
            source_url='https://example.com/video',
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            title='Detail Test Video',
            slug='detail-test-video',
            status=MediaItem.STATUS_READY,
            media_type='video',
            duration_seconds=300,
            author='Test Author',
            file_size=1024 * 1024 * 50,
        )
        from media.tui.screens.item_detail import ItemDetailScreen
        from media.tui.app import StashCastApp
        from textual.widgets import Static

        app = StashCastApp()
        async with app.run_test() as pilot:
            app.push_screen(ItemDetailScreen(item.guid))
            await pilot.pause()
            # Verify detail screen is showing by checking the title widget
            title_widget = app.screen.query_one('#detail-title', Static)
            assert title_widget is not None
            # Check the screen has a detail container with content
            container = app.screen.query_one('#detail-container')
            statics = container.query(Static)
            assert len(statics) > 3  # title + multiple metadata lines

    @pytest.mark.asyncio
    async def test_detail_screen_escape_goes_back(self):
        """Pressing escape dismisses the detail screen."""
        item = MediaItem.objects.create(
            source_url='https://example.com/video',
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            title='Escape Test',
            slug='escape-test',
            status=MediaItem.STATUS_READY,
            media_type='video',
        )
        from media.tui.screens.item_detail import ItemDetailScreen
        from media.tui.app import StashCastApp
        from media.tui.screens.item_list import ItemListScreen

        app = StashCastApp()
        async with app.run_test() as pilot:
            app.push_screen(ItemDetailScreen(item.guid))
            await pilot.pause()
            await pilot.press('escape')
            await pilot.pause()
            assert isinstance(app.screen, ItemListScreen)


class TuiArchiveTest(TransactionTestCase):
    """Test archive/unarchive functionality."""

    @pytest.mark.asyncio
    async def test_archive_toggles_status(self):
        """Archive worker toggles READY -> ARCHIVED."""
        item = MediaItem.objects.create(
            source_url='https://example.com/video',
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            title='Archive Test',
            slug='archive-test',
            status=MediaItem.STATUS_READY,
            media_type='audio',
        )
        from media.tui.app import StashCastApp

        app = StashCastApp()
        async with app.run_test() as pilot:
            # Call the archive worker directly with the item's guid
            app.screen._do_toggle_archive(item.guid, item.status)
            await pilot.pause(delay=1.0)
            await app.workers.wait_for_complete()
            item.refresh_from_db()
            assert item.status == MediaItem.STATUS_ARCHIVED


class TuiDeleteTest(TransactionTestCase):
    """Test delete functionality."""

    @pytest.mark.asyncio
    async def test_delete_with_confirm(self):
        """Delete worker removes item from database."""
        item = MediaItem.objects.create(
            source_url='https://example.com/video',
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            title='Delete Test',
            slug='delete-test',
            status=MediaItem.STATUS_READY,
            media_type='audio',
        )
        guid = item.guid
        from media.tui.app import StashCastApp

        app = StashCastApp()
        async with app.run_test() as pilot:
            # Call the delete worker directly
            app.screen._do_delete(guid)
            await pilot.pause(delay=1.0)
            await app.workers.wait_for_complete()
            assert MediaItem.objects.filter(guid=guid).count() == 0

    @pytest.mark.asyncio
    async def test_delete_cancel(self):
        """Pressing 'd' then 'n' cancels deletion."""
        item = MediaItem.objects.create(
            source_url='https://example.com/video',
            requested_type=MediaItem.REQUESTED_TYPE_AUTO,
            title='Delete Cancel Test',
            slug='delete-cancel-test',
            status=MediaItem.STATUS_READY,
            media_type='audio',
        )
        from media.tui.app import StashCastApp

        app = StashCastApp()
        async with app.run_test() as pilot:
            await pilot.press('d')
            await pilot.pause()
            await pilot.press('n')
            await pilot.pause()
            assert MediaItem.objects.filter(guid=item.guid).count() == 1


class TuiStashScreenTest(TransactionTestCase):
    """Test the stash screen UI (without actually downloading)."""

    @pytest.mark.asyncio
    async def test_stash_screen_renders(self):
        """Stash screen renders with input, radio buttons, and buttons."""
        from media.tui.app import StashCastApp
        from media.tui.screens.stash import StashScreen
        from textual.widgets import Input, Button, RadioButton

        app = StashCastApp()
        async with app.run_test() as pilot:
            app.push_screen(StashScreen())
            await pilot.pause()
            assert app.screen.query_one('#stash-url-input', Input)
            assert app.screen.query_one('#btn-stash', Button)
            assert app.screen.query_one('#type-auto', RadioButton)

    @pytest.mark.asyncio
    async def test_stash_screen_cancel(self):
        """Escape dismisses the stash screen."""
        from media.tui.app import StashCastApp
        from media.tui.screens.stash import StashScreen
        from media.tui.screens.item_list import ItemListScreen

        app = StashCastApp()
        async with app.run_test() as pilot:
            app.push_screen(StashScreen())
            await pilot.pause()
            await pilot.press('escape')
            await pilot.pause()
            assert isinstance(app.screen, ItemListScreen)

    @pytest.mark.asyncio
    async def test_stash_screen_empty_url_warns(self):
        """Submitting empty URL shows a warning."""
        from media.tui.app import StashCastApp
        from media.tui.screens.stash import StashScreen

        app = StashCastApp()
        async with app.run_test() as pilot:
            app.push_screen(StashScreen())
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            assert isinstance(app.screen, StashScreen)

    @pytest.mark.asyncio
    async def test_stash_screen_retry_prefills_url(self):
        """StashScreen with retry_url prefills the input."""
        from media.tui.app import StashCastApp
        from media.tui.screens.stash import StashScreen
        from textual.widgets import Input

        app = StashCastApp()
        async with app.run_test() as pilot:
            app.push_screen(StashScreen(retry_url='https://example.com/retry'))
            await pilot.pause()
            url_input = app.screen.query_one('#stash-url-input', Input)
            assert url_input.value == 'https://example.com/retry'


class TuiConfirmDialogTest(TransactionTestCase):
    """Test the confirm dialog."""

    @pytest.mark.asyncio
    async def test_confirm_yes(self):
        """Pressing 'y' returns True."""
        from media.tui.app import StashCastApp
        from media.tui.screens.confirm import ConfirmDialog

        result = None

        def capture(value):
            nonlocal result
            result = value

        app = StashCastApp()
        async with app.run_test() as pilot:
            app.push_screen(ConfirmDialog('Test?'), callback=capture)
            await pilot.pause()
            await pilot.press('y')
            await pilot.pause()
            assert result is True

    @pytest.mark.asyncio
    async def test_confirm_no(self):
        """Pressing 'n' returns False."""
        from media.tui.app import StashCastApp
        from media.tui.screens.confirm import ConfirmDialog

        result = None

        def capture(value):
            nonlocal result
            result = value

        app = StashCastApp()
        async with app.run_test() as pilot:
            app.push_screen(ConfirmDialog('Test?'), callback=capture)
            await pilot.pause()
            await pilot.press('n')
            await pilot.pause()
            assert result is False


# ---- Synchronous unit tests (no TUI, no async) ----


class FormatDurationTest(TestCase):
    """Test the duration formatting helper."""

    def test_none_returns_empty(self):
        from media.tui.screens.item_list import _format_duration

        assert _format_duration(None) == ''

    def test_zero_returns_empty(self):
        from media.tui.screens.item_list import _format_duration

        assert _format_duration(0) == ''

    def test_seconds_only(self):
        from media.tui.screens.item_list import _format_duration

        assert _format_duration(45) == '0:45'

    def test_minutes_and_seconds(self):
        from media.tui.screens.item_list import _format_duration

        assert _format_duration(125) == '2:05'

    def test_hours(self):
        from media.tui.screens.item_list import _format_duration

        assert _format_duration(3661) == '1:01:01'


class FormatSizeTest(TestCase):
    """Test the file size formatting helper."""

    def test_none_returns_empty(self):
        from media.tui.screens.item_detail import _format_size

        assert _format_size(None) == ''

    def test_bytes(self):
        from media.tui.screens.item_detail import _format_size

        assert _format_size(512) == '512 B'

    def test_kilobytes(self):
        from media.tui.screens.item_detail import _format_size

        assert _format_size(2048) == '2.0 KB'

    def test_megabytes(self):
        from media.tui.screens.item_detail import _format_size

        result = _format_size(1024 * 1024 * 50)
        assert result == '50.0 MB'

    def test_gigabytes(self):
        from media.tui.screens.item_detail import _format_size

        result = _format_size(1024 * 1024 * 1024 * 2)
        assert result == '2.0 GB'
