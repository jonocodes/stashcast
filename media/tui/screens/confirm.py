from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmDialog(ModalScreen[bool]):
    """Modal confirmation dialog that returns True/False."""

    BINDINGS = [
        Binding('y', 'confirm', 'Yes'),
        Binding('n', 'cancel', 'No'),
        Binding('escape', 'cancel', 'Cancel'),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id='confirm-dialog-container'):
            yield Static(self._message, id='confirm-dialog-message')
            with Horizontal(id='confirm-dialog-buttons'):
                yield Button('Yes (y)', variant='error', id='btn-yes')
                yield Button('No (n)', variant='default', id='btn-no')

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'btn-yes':
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
