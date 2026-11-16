from django.apps import AppConfig
from django.contrib.admin.apps import AdminConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"

    def ready(self):
        from . import checks  # noqa: F401


class TRACEAdminConfig(AdminConfig):
    default_site = "apps.core.admin.ServerAdminSite"
