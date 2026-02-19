from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, Select


STATUS_OPTIONS = [
    ('All', 'all'),
    ('Ready', 'READY'),
    ('Error', 'ERROR'),
    ('Archived', 'ARCHIVED'),
    ('Downloading', 'DOWNLOADING'),
    ('Processing', 'PROCESSING'),
    ('Prefetching', 'PREFETCHING'),
]


class FilterBar(Widget):
    """Filter bar with status dropdown and text search."""

    class Changed(Message):
        """Emitted when the filter changes."""

        def __init__(self, status_filter: str, text_filter: str) -> None:
            super().__init__()
            self.status_filter = status_filter
            self.text_filter = text_filter

    def compose(self) -> ComposeResult:
        with Horizontal(id='filter-bar'):
            yield Input(placeholder='Search by title...', id='filter-text')
            yield Select(STATUS_OPTIONS, value='all', id='filter-status', allow_blank=False)

    @on(Input.Changed, '#filter-text')
    def on_text_changed(self, event: Input.Changed) -> None:
        self._emit_changed()

    @on(Select.Changed, '#filter-status')
    def on_status_changed(self, event: Select.Changed) -> None:
        self._emit_changed()

    def _emit_changed(self) -> None:
        text_input = self.query_one('#filter-text', Input)
        status_select = self.query_one('#filter-status', Select)
        self.post_message(
            FilterBar.Changed(
                status_filter=str(status_select.value),
                text_filter=text_input.value,
            )
        )
