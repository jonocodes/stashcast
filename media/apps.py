from django.apps import AppConfig


class MediaConfig(AppConfig):
    name = 'media'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        """Import signals when the app is ready"""
