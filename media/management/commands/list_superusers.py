from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Lists all active superusers'

    def handle(self, *args, **kwargs):
        User = get_user_model()
        superusers = User.objects.filter(is_superuser=True)
        if superusers:
            self.stdout.write('Superusers:')
            for user in superusers:
                self.stdout.write(f'- {user.username} ({user.email})')
        else:
            self.stdout.write(
                'No superusers/admins found, but required. '
                "You can create one using the './manage.py createsuperuser' command."
            )
