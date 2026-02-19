import os
from pathlib import Path

from textual.app import App
from textual.binding import Binding

from media.tui.screens.item_list import ItemListScreen

# Textual runs an async event loop, but Django ORM calls are synchronous.
# This is safe because we're single-threaded for DB reads and use worker
# threads for mutations.
os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')


class StashCastApp(App):
    """StashCast TUI application."""

    TITLE = 'StashCast'
    CSS_PATH = Path(__file__).parent / 'styles.tcss'

    BINDINGS = [
        Binding('q', 'quit', 'Quit'),
    ]

    def on_mount(self) -> None:
        self.push_screen(ItemListScreen())
