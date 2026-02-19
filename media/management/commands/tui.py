"""
Management command to launch the StashCast TUI.

Usage:
    ./manage.py tui
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Launch the StashCast TUI (Terminal User Interface)'

    def handle(self, *args, **options):
        from media.tui.app import StashCastApp

        app = StashCastApp()
        app.run()
