import json
import subprocess
from pathlib import Path

from django.apps import AppConfig
from django.utils import timezone


DEPLOY_TIME = timezone.now()


def _get_git_info():
    """Capture git info at startup for display on the About page.

    Tries two sources in order:
    1. git_info.json written during Docker build (for container deploys)
    2. Live git commands (for local development)
    """
    info = {'commit_sha': '', 'commit_sha_short': '', 'commit_message': '', 'branch': ''}

    # Try reading from the build-time JSON file (Docker deployments)
    # Check /etc first (survives volume mounts), then app dir (local builds)
    for json_path in [Path('/etc/git_info.json'), Path(__file__).resolve().parent.parent / 'git_info.json']:
        try:
            data = json.loads(json_path.read_text())
            if data.get('commit_sha'):
                info['commit_sha'] = data['commit_sha']
                info['commit_sha_short'] = data['commit_sha'][:7]
                info['commit_message'] = data.get('commit_message', '')
                info['branch'] = data.get('branch', '')
                return info
        except Exception:
            pass

    # Fall back to live git commands (local development)
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
