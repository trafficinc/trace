from django.urls import path
from . import views

app_name = "assets"
urlpatterns = [
    path("", views.asset_list, name="list"),
    path("new/", views.asset_edit, name="create"),
    path("<uuid:pk>/", views.asset_detail, name="detail"),
    path("<uuid:pk>/edit/", views.asset_edit, name="edit"),
]
