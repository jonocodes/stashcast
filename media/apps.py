import subprocess

from django.apps import AppConfig
from django.utils import timezone


DEPLOY_TIME = timezone.now()


def _get_git_info():
    """Capture git info at startup for display on the About page."""
    info = {'commit_sha': '', 'commit_sha_short': '', 'commit_message': '', 'branch': ''}
    try:
        info['commit_sha'] = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], stderr=subprocess.DEVNULL, text=True
        ).strip()
        info['commit_sha_short'] = info['commit_sha'][:7]
        info['commit_message'] = subprocess.check_output(
            ['git', 'log', '-1', '--pretty=%s'], stderr=subprocess.DEVNULL, text=True
        ).strip()
        info['branch'] = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        pass
    return info


GIT_INFO = _get_git_info()


class MediaConfig(AppConfig):
    name = 'media'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        """Import signals when the app is ready"""
