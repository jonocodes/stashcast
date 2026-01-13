import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Create or update a demo admin user from env vars (DEMO_PASSWORD required).'

    def add_arguments(self, parser):
        parser.add_argument(
            'username',
            nargs='?',
            help='Username for the demo user (overrides DEMO_USERNAME env var)',
        )
        parser.add_argument(
            'password',
            nargs='?',
            help='Password for the demo user (overrides DEMO_PASSWORD env var)',
        )

    def handle(self, *args, **options):
        username = options['username'] or os.getenv('DEMO_USERNAME', 'demo')
        email = os.getenv('DEMO_EMAIL', '')
        password = options['password'] or os.getenv('DEMO_PASSWORD')
        group_name = os.getenv('DEMO_GROUP', 'DemoReadOnly')

        if not password:
            raise CommandError(
                'DEMO_PASSWORD is required (refusing to create a demo user without it).'
            )

        User = get_user_model()

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'email': email,
                'is_active': True,
            },
        )

        # Update fields deterministically
        if email:
            user.email = email
        user.is_active = True
        user.is_staff = True  # required for admin
        user.is_superuser = False  # keep it constrained
        user.set_password(password)
        user.save()

        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)

        view_perms = Permission.objects.filter(codename__startswith='view_')
        group.permissions.add(*view_perms)

        action = 'Created' if created else 'Updated'
        self.stdout.write(
            self.style.SUCCESS(f"{action} demo user '{username}' and ensured group '{group_name}'.")
        )
