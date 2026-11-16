from django.urls import path
from . import views

app_name = "testcases"
urlpatterns = [
    path("", views.test_list, name="list"),
    path("new/", views.test_edit, name="create"),
    path("<uuid:pk>/", views.test_detail, name="detail"),
    path("<uuid:pk>/edit/", views.test_edit, name="edit"),
    path("<uuid:pk>/notes/new/", views.note_create, name="note_create"),
    path("<uuid:pk>/notes/<uuid:child_id>/edit/", views.note_edit, name="note_edit"),
    path("<uuid:pk>/notes/<uuid:child_id>/delete/", views.child_delete, {"kind": "note"}, name="note_delete"),
    path("<uuid:pk>/references/new/", views.reference_edit, name="reference_create"),
    path("<uuid:pk>/references/<uuid:child_id>/edit/", views.reference_edit, name="reference_edit"),
    path("<uuid:pk>/references/<uuid:child_id>/delete/", views.child_delete, {"kind": "reference"}, name="reference_delete"),
]
