import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Create or update a test superuser from env vars (TEST_PASSWORD required).'

    def add_arguments(self, parser):
        parser.add_argument(
            'username',
            nargs='?',
            help='Username for the test user (overrides TEST_USERNAME env var)',
        )
        parser.add_argument(
            'password',
            nargs='?',
            help='Password for the test user (overrides TEST_PASSWORD env var)',
        )

    def handle(self, *args, **options):
        username = options['username'] or os.getenv('TEST_USERNAME', 'admin')
        email = os.getenv('TEST_EMAIL', '')
        password = options['password'] or os.getenv('TEST_PASSWORD')

        if not password:
            raise CommandError(
                'TEST_PASSWORD is required (set env var or pass as argument).'
            )

        User = get_user_model()

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'email': email,
                'is_active': True,
            },
        )

        if email:
            user.email = email
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()

        action = 'Created' if created else 'Updated'
        self.stdout.write(
            self.style.SUCCESS(f"{action} test superuser '{username}'.")
        )
