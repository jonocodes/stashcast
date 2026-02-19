from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class ItemDetailScreen(Screen):
    """Screen showing detailed metadata for a single media item."""

    BINDINGS = [
        Binding('escape', 'go_back', 'Back'),
        Binding('d', 'delete_item', 'Delete'),
        Binding('a', 'toggle_archive', 'Archive'),
        Binding('q', 'quit', 'Quit'),
    ]

    def __init__(self, guid: str) -> None:
        super().__init__()
        self._guid = guid

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(id='detail-container')
        yield Footer()

    def on_mount(self) -> None:
        self._render_detail()

    def _render_detail(self) -> None:
        from media.models import MediaItem

        container = self.query_one('#detail-container')
        container.remove_children()

        try:
            item = MediaItem.objects.get(guid=self._guid)
        except MediaItem.DoesNotExist:
            container.mount(Static('Item not found.'))
            return

        lines = [
            ('Title', item.title or '(untitled)'),
            ('GUID', item.guid),
            ('Status', item.status),
            ('Source URL', item.source_url),
            ('Webpage URL', item.webpage_url or ''),
            ('Slug', item.slug),
            ('Media Type', item.media_type or ''),
            ('Requested Type', item.requested_type),
            ('Duration', _format_duration(item.duration_seconds)),
            ('File Size', _format_size(item.file_size)),
            ('MIME Type', item.mime_type or ''),
            ('Author', item.author or ''),
            ('Extractor', item.extractor or ''),
            ('Content Path', item.content_path or ''),
            ('Thumbnail', item.thumbnail_path or ''),
            ('Subtitle', item.subtitle_path or ''),
            ('Created', str(item.created_at) if item.created_at else ''),
            ('Downloaded', str(item.downloaded_at) if item.downloaded_at else ''),
            ('Archived', str(item.archived_at) if item.archived_at else ''),
        ]

        title_widget = Static(f'[bold]{item.title or item.source_url}[/bold]', id='detail-title')
        container.mount(title_widget)

        for label, value in lines:
            if value:
                container.mount(Static(f'[dim]{label:>16}[/dim]  {value}'))

        if item.error_message:
            container.mount(Static(f'\n[red]Error: {item.error_message}[/red]', id='detail-error'))

        if item.description:
            container.mount(Static(f'\n[dim]Description:[/dim]\n{item.description[:500]}'))

        if item.summary:
            container.mount(Static(f'\n[dim]Summary:[/dim]\n{item.summary[:500]}'))

    def action_go_back(self) -> None:
        self.dismiss(None)

    def action_delete_item(self) -> None:
        from media.tui.screens.confirm import ConfirmDialog

        self.app.push_screen(
            ConfirmDialog('Delete this item and its files?'),
            callback=self._on_delete_confirm,
        )

    def _on_delete_confirm(self, confirmed: bool) -> None:
        if not confirmed:
            return
        import shutil
        from media.models import MediaItem

        try:
            item = MediaItem.objects.get(guid=self._guid)
            base_dir = item.get_base_dir()
            if base_dir and base_dir.exists():
                shutil.rmtree(base_dir)
            item.delete()
        except MediaItem.DoesNotExist:
            pass
        self.dismiss('deleted')

    def action_toggle_archive(self) -> None:
        from django.utils import timezone
        from media.models import MediaItem

        try:
            item = MediaItem.objects.get(guid=self._guid)
            if item.status == MediaItem.STATUS_ARCHIVED:
                item.status = MediaItem.STATUS_READY
                item.archived_at = None
                item.save()
                self.notify('Unarchived.')
            elif item.status == MediaItem.STATUS_READY:
                item.status = MediaItem.STATUS_ARCHIVED
                item.archived_at = timezone.now()
                item.save()
                self.notify('Archived.')
            else:
                self.notify('Can only archive READY items.', severity='warning')
                return
        except MediaItem.DoesNotExist:
            self.notify('Item not found.', severity='error')
            return
        self._render_detail()


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


def _format_size(size_bytes):
    if not size_bytes:
        return ''
    if size_bytes < 1024:
        return f'{size_bytes} B'
    elif size_bytes < 1024 * 1024:
        return f'{size_bytes / 1024:.1f} KB'
    elif size_bytes < 1024 * 1024 * 1024:
        return f'{size_bytes / (1024 * 1024):.1f} MB'
    return f'{size_bytes / (1024 * 1024 * 1024):.1f} GB'
