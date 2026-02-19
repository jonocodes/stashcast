from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header

from media.tui.widgets.filter_bar import FilterBar


class ItemListScreen(Screen):
    """Main screen showing list of all media items."""

    BINDINGS = [
        Binding('s', 'stash', 'Stash URL'),
        Binding('enter', 'view_detail', 'Detail'),
        Binding('d', 'delete_item', 'Delete'),
        Binding('a', 'toggle_archive', 'Archive'),
        Binding('r', 'retry_item', 'Retry'),
        Binding('f', 'toggle_filter', 'Filter'),
        Binding('R', 'refresh_list', 'Refresh'),
        Binding('q', 'quit', 'Quit'),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._status_filter = 'all'
        self._text_filter = ''
        self._filter_visible = False
        self._items = []  # cache of MediaItem objects keyed by row index

    def compose(self) -> ComposeResult:
        yield Header()
        yield FilterBar(id='filter-widget')
        yield DataTable(id='item-table')
        yield Footer()

    def on_mount(self) -> None:
        self.query_one('#filter-widget').display = False
        table = self.query_one(DataTable)
        table.cursor_type = 'row'
        table.add_columns('Title', 'Status', 'Type', 'Duration', 'Date')
        self._load_items()

    def _load_items(self) -> None:
        from media.models import MediaItem

        table = self.query_one(DataTable)
        table.clear()
        self._items = []

        qs = MediaItem.objects.all().order_by('-created_at')

        if self._status_filter != 'all':
            qs = qs.filter(status=self._status_filter)

        if self._text_filter:
            qs = qs.filter(title__icontains=self._text_filter)

        for item in qs:
            duration = _format_duration(item.duration_seconds)
            date = item.created_at.strftime('%Y-%m-%d') if item.created_at else ''
            status_display = item.status
            table.add_row(
                item.title or item.source_url[:60],
                status_display,
                item.media_type or '?',
                duration,
                date,
                key=item.guid,
            )
            self._items.append(item)

    def _get_selected_item(self):
        """Return the MediaItem for the currently selected row, or None."""
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:
            return None
        guid = str(row_key)
        for item in self._items:
            if item.guid == guid:
                return item
        return None

    def action_stash(self) -> None:
        from media.tui.screens.stash import StashScreen

        self.app.push_screen(StashScreen(), callback=self._on_stash_dismiss)

    def _on_stash_dismiss(self, result) -> None:
        self._load_items()

    def action_view_detail(self) -> None:
        item = self._get_selected_item()
        if not item:
            return
        from media.tui.screens.item_detail import ItemDetailScreen

        self.app.push_screen(
            ItemDetailScreen(item.guid), callback=lambda _: self._load_items()
        )

    def action_delete_item(self) -> None:
        item = self._get_selected_item()
        if not item:
            return
        from media.tui.screens.confirm import ConfirmDialog

        title = item.title or item.source_url[:40]
        self.app.push_screen(
            ConfirmDialog(f'Delete "{title}"?\nThis will remove the item and its files.'),
            callback=lambda confirmed: self._do_delete(item.guid) if confirmed else None,
        )

    @work(thread=True)
    def _do_delete(self, guid: str) -> None:
        import shutil
        from media.models import MediaItem

        try:
            item = MediaItem.objects.get(guid=guid)
            base_dir = item.get_base_dir()
            if base_dir and base_dir.exists():
                shutil.rmtree(base_dir)
            item.delete()
        except MediaItem.DoesNotExist:
            pass
        self.app.call_from_thread(self._load_items)

    def action_toggle_archive(self) -> None:
        item = self._get_selected_item()
        if not item:
            return
        self._do_toggle_archive(item.guid, item.status)

    @work(thread=True)
    def _do_toggle_archive(self, guid: str, current_status: str) -> None:
        from django.utils import timezone
        from media.models import MediaItem

        try:
            item = MediaItem.objects.get(guid=guid)
            if item.status == MediaItem.STATUS_ARCHIVED:
                item.status = MediaItem.STATUS_READY
                item.archived_at = None
            elif item.status == MediaItem.STATUS_READY:
                item.status = MediaItem.STATUS_ARCHIVED
                item.archived_at = timezone.now()
            else:
                return
            item.save()
        except MediaItem.DoesNotExist:
            pass
        self.app.call_from_thread(self._load_items)

    def action_retry_item(self) -> None:
        item = self._get_selected_item()
        if not item:
            return
        if item.status != 'ERROR':
            self.notify('Only ERROR items can be retried.', severity='warning')
            return
        from media.tui.screens.stash import StashScreen

        self.app.push_screen(
            StashScreen(retry_url=item.source_url, retry_type=item.requested_type),
            callback=self._on_stash_dismiss,
        )

    def action_toggle_filter(self) -> None:
        self._filter_visible = not self._filter_visible
        filter_widget = self.query_one('#filter-widget')
        filter_widget.display = self._filter_visible
        if self._filter_visible:
            self.query_one('#filter-text').focus()

    def action_refresh_list(self) -> None:
        self._load_items()
        self.notify('Refreshed.')

    @on(FilterBar.Changed)
    def on_filter_changed(self, event: FilterBar.Changed) -> None:
        self._status_filter = event.status_filter
        self._text_filter = event.text_filter
        self._load_items()


def _format_duration(seconds):
    if not seconds:
        return ''
    mins = seconds // 60
    secs = seconds % 60
    if mins >= 60:
        hours = mins // 60
        mins = mins % 60
        return f'{hours}:{mins:02d}:{secs:02d}'
    return f'{mins}:{secs:02d}'
