import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
from apps.core.maintenance import hold_serving_lock
hold_serving_lock()
application = get_asgi_application()
