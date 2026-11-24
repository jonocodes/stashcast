from django.db import connection
from django.http import HttpResponse

HEALTH_PATH = '/healthz'


class HealthCheckMiddleware:
    """Answer /healthz before any host validation happens.

    Container healthchecks call the app on 127.0.0.1, which is usually not in
    ALLOWED_HOSTS. So this must sit first in MIDDLEWARE, before anything calls
    request.get_host().
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path != HEALTH_PATH:
            return self.get_response(request)
        try:
            connection.ensure_connection()
        except Exception:
            return HttpResponse('database unavailable', status=503, content_type='text/plain')
        return HttpResponse('ok', content_type='text/plain')
