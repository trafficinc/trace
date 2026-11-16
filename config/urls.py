from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("audit/", include("apps.audit.global_urls")),
    path("engagements/<uuid:engagement_id>/history/", include("apps.audit.urls")),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("engagements/", include("apps.engagements.urls")),
    path("engagements/<uuid:engagement_id>/assets/", include("apps.assets.urls")),
    path("engagements/<uuid:engagement_id>/test-cases/", include("apps.testcases.urls")),
    path("engagements/<uuid:engagement_id>/findings/", include("apps.findings.urls")),
    path("engagements/<uuid:engagement_id>/evidence/", include("apps.evidence.urls")),
    path("engagements/<uuid:engagement_id>/reports/", include("apps.reports.urls")),
    path("report-templates/", include("apps.reports.template_urls")),
    path("finding-templates/", include("apps.findings.template_urls")),
    path("test-templates/", include("apps.testcases.template_urls")),
    path("", include("apps.core.urls")),
]

handler403 = "apps.core.views.permission_denied"
handler404 = "apps.core.views.page_not_found"
