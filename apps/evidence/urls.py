from django.urls import path
from . import views
app_name = 'evidence'
urlpatterns = [path('quota/', views.quota_policy, name='quota'), path('', views.evidence_list, name='list'), path('upload/', views.evidence_upload, name='upload'),
               path('<uuid:pk>/', views.evidence_detail, name='detail'), path('<uuid:pk>/edit/', views.evidence_edit, name='edit'),
               path('<uuid:pk>/remove/', views.evidence_remove, name='remove'), path('<uuid:pk>/download/', views.evidence_download, name='download'),
               path('<uuid:pk>/thumbnail/', views.evidence_download, {'thumbnail': True}, name='thumbnail')]
