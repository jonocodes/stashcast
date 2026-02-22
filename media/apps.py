from django.apps import AppConfig
from django.utils import timezone


DEPLOY_TIME = timezone.now()


class MediaConfig(AppConfig):
    name = 'media'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        """Import signals when the app is ready"""
