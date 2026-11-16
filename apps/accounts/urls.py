from django.contrib.auth import views
from django.urls import path
from . import views as account_views

app_name = "accounts"
urlpatterns = [
    path("login/", account_views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("password/", account_views.password_change, name="password_change"),
    path("profile/", account_views.profile, name="profile"),
    path("users/", account_views.users, name="users"),
    path("users/new/", account_views.user_create, name="user_create"),
    path("users/<int:pk>/status/", account_views.user_status, name="user_status"),
]
