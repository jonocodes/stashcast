"""
Passenger WSGI file for StashCast Django application.

I created this when trying to deploy to cpanel, but we are no longer deployed there due to huey.

This file is used by Passenger (mod_passenger/Phusion Passenger) to run the
Django application in production environments.

Passenger will:
1. Set up Python environment
2. Import this module
3. Call the 'application' callable to handle requests

For more information:
- https://www.phusionpassenger.com/library/walkthroughs/deploy/python/
- https://docs.djangoproject.com/en/stable/howto/deployment/wsgi/
"""

import os
import sys

from django.core.wsgi import get_wsgi_application

# Add the project directory to the Python path
# This ensures Django can find the project modules
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

# Set the Django settings module
# This must be done before importing Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stashcast.settings")

# Create the WSGI application
# Passenger will call this to handle HTTP requests
application = get_wsgi_application()
