from django.urls import path
from . import views

app_name = "test_templates"
urlpatterns = [
    path("", views.template_list, name="list"),
    path("new/", views.template_edit, name="create"),
    path("<uuid:pk>/", views.template_detail, name="detail"),
    path("<uuid:pk>/edit/", views.template_edit, name="edit"),
]
