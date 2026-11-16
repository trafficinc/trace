from django.urls import path
from . import views

app_name = "core"
urlpatterns = [
    path("storage/", views.storage_status, name="storage_status"),
    path("search/", views.search, name="search"),
    path("", views.dashboard, name="dashboard"),
    path("editors/<slug:kind>/<str:object_id>/status/", views.editor_status, name="editor_status"),
    path("editors/<slug:kind>/<str:object_id>/presence/", views.editor_presence, name="editor_presence"),
    path("engagements/<uuid:engagement_id>/editors/<slug:kind>/<str:object_id>/status/", views.editor_status, name="engagement_editor_status"),
    path("engagements/<uuid:engagement_id>/editors/<slug:kind>/<str:object_id>/presence/", views.editor_presence, name="engagement_editor_presence"),
    path("health/", views.health, name="health"),
]
