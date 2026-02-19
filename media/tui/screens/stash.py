import shutil
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal
from textual.message import Message
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    RadioButton,
    RadioSet,
    Static,
)


class StashScreen(Screen):
    """Screen for stashing a new URL with synchronous progress display."""

    BINDINGS = [
        Binding('escape', 'cancel', 'Cancel'),
    ]

    class StashComplete(Message):
        pass

    def __init__(self, retry_url: str = '', retry_type: str = 'auto') -> None:
        super().__init__()
        self._retry_url = retry_url
        self._retry_type = retry_type
        self._is_stashing = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id='stash-container'):
            yield Static('[bold]Stash a URL[/bold]', id='stash-title')
            yield Input(
                placeholder='Enter URL to stash...',
                value=self._retry_url,
                id='stash-url-input',
            )
            with RadioSet(id='stash-type-group'):
                yield RadioButton('Auto', value=self._retry_type == 'auto', id='type-auto')
                yield RadioButton('Audio', value=self._retry_type == 'audio', id='type-audio')
                yield RadioButton('Video', value=self._retry_type == 'video', id='type-video')
            with Horizontal(id='stash-buttons'):
                yield Button('Stash', variant='primary', id='btn-stash')
                yield Button('Cancel', id='btn-cancel')
            yield ProgressBar(total=100, show_eta=False, id='stash-progress')
            yield Label('', id='stash-status-label')
        yield Footer()

    def on_mount(self) -> None:
        self.query_one('#stash-progress').display = False
        self.query_one('#stash-status-label').display = False
        self.query_one('#stash-url-input', Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'btn-stash':
            self._start_stash()
        elif event.button.id == 'btn-cancel':
            self.action_cancel()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == 'stash-url-input':
            self._start_stash()

    def _start_stash(self) -> None:
        if self._is_stashing:
            return

        url = self.query_one('#stash-url-input', Input).value.strip()
        if not url:
            self.notify('Please enter a URL.', severity='warning')
            return

        requested_type = self._get_selected_type()
        self._is_stashing = True

        # Show progress, hide buttons
        self.query_one('#stash-progress').display = True
        self.query_one('#stash-status-label').display = True
        self.query_one('#btn-stash', Button).disabled = True
        self.query_one('#stash-url-input', Input).disabled = True

        self._run_stash(url, requested_type)

    def _get_selected_type(self) -> str:
        if self.query_one('#type-audio', RadioButton).value:
            return 'audio'
        elif self.query_one('#type-video', RadioButton).value:
            return 'video'
        return 'auto'

    def _update_progress(self, percent: int, message: str) -> None:
        """Thread-safe progress update."""
        self.app.call_from_thread(self._set_progress, percent, message)

    def _set_progress(self, percent: int, message: str) -> None:
        self.query_one('#stash-progress', ProgressBar).update(progress=percent)
        self.query_one('#stash-status-label', Label).update(message)

    @work(thread=True, exclusive=True)
    def _run_stash(self, url: str, requested_type: str) -> None:
        """Run the stash pipeline synchronously in a worker thread."""
        from django.conf import settings
        from django.utils import timezone

        from media.models import MediaItem
        from media.processing import (
            write_log,
            prefetch_file,
            prefetch_direct,
            prefetch_ytdlp,
            download_direct,
            download_ytdlp,
            process_files,
        )
        from media.service.strategy import choose_download_strategy
        from media.tasks import check_episode_limit

        # Check episode limit
        limit_error = check_episode_limit()
        if limit_error:
            self.app.call_from_thread(self._stash_error, limit_error)
            return

        # Map type
        type_map = {
            'auto': MediaItem.REQUESTED_TYPE_AUTO,
            'audio': MediaItem.REQUESTED_TYPE_AUDIO,
            'video': MediaItem.REQUESTED_TYPE_VIDEO,
        }
        requested_type_const = type_map.get(requested_type, MediaItem.REQUESTED_TYPE_AUTO)

        # Check for existing item
        existing = MediaItem.objects.filter(
            source_url=url, requested_type=requested_type_const
        ).first()

        if existing:
            item = existing
            item.status = MediaItem.STATUS_PREFETCHING
            item.error_message = ''
            item.save()
        else:
            item = MediaItem.objects.create(
                source_url=url,
                requested_type=requested_type_const,
                status=MediaItem.STATUS_PREFETCHING,
            )

        media_base = Path(settings.STASHCAST_MEDIA_DIR)
        media_base.mkdir(parents=True, exist_ok=True)
        tmp_dir = media_base / f'tmp-{item.guid}'
        tmp_dir.mkdir(exist_ok=True)
        log_path = tmp_dir / 'download.log'

        try:
            write_log(log_path, '=== TASK STARTED (TUI) ===')

            # PREFETCHING
            self._update_progress(5, 'Prefetching metadata...')
            strategy = choose_download_strategy(item.source_url)
            is_direct = strategy in ('direct', 'file')

            if is_direct:
                if Path(item.source_url).exists():
                    prefetch_file(item, tmp_dir, log_path)
                else:
                    prefetch_direct(item, tmp_dir, log_path)
            else:
                prefetch_ytdlp(item, tmp_dir, log_path)

            item.refresh_from_db()
            strategy = choose_download_strategy(item.source_url)
            is_direct = strategy in ('direct', 'file')

            # DOWNLOADING
            self._update_progress(15, f'Downloading: {item.title or url[:40]}...')
            item.status = MediaItem.STATUS_DOWNLOADING
            item.save()

            if is_direct:
                download_direct(item, tmp_dir, log_path)
            else:
                download_ytdlp(item, tmp_dir, log_path)

            # PROCESSING
            self._update_progress(60, 'Processing files...')
            item.status = MediaItem.STATUS_PROCESSING
            item.save()
            process_files(item, tmp_dir, log_path)

            # MOVE TO FINAL DIR
            self._update_progress(85, 'Finalizing...')
            final_dir = item.get_base_dir()
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            if final_dir.exists():
                shutil.rmtree(final_dir)
            shutil.move(str(tmp_dir), str(final_dir))

            # READY
            item.status = MediaItem.STATUS_READY
            item.downloaded_at = timezone.now()
            item.save()

            self._update_progress(100, f'Done: {item.title}')

            self.app.call_from_thread(self._stash_success, item.title or url)

        except Exception as e:
            item.status = MediaItem.STATUS_ERROR
            item.error_message = str(e)
            item.save()

            if tmp_dir and tmp_dir.exists():
                try:
                    shutil.rmtree(tmp_dir)
                except Exception:
                    pass

            self.app.call_from_thread(self._stash_error, str(e))

    def _stash_success(self, title: str) -> None:
        self.notify(f'Stashed: {title}', severity='information')
        self._is_stashing = False
        self.dismiss('success')

    def _stash_error(self, error: str) -> None:
        self._is_stashing = False
        self.query_one('#stash-status-label', Label).update(f'[red]Error: {error}[/red]')
        self.query_one('#btn-stash', Button).disabled = False
        self.query_one('#stash-url-input', Input).disabled = False

    def action_cancel(self) -> None:
        if not self._is_stashing:
            self.dismiss(None)
