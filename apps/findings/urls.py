from django.urls import path
from . import views
app_name = 'findings'
urlpatterns = [path('', views.finding_list, name='list'), path('new/', views.finding_edit, name='create'), path('from-template/<uuid:pk>/', views.template_copy, name='copy'), path('<uuid:pk>/', views.finding_detail, name='detail'), path('<uuid:pk>/edit/', views.finding_edit, name='edit')]
