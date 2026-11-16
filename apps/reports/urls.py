from django.urls import path
from . import views
app_name='reports'
urlpatterns=[path('',views.report_list,name='list'),path('new/',views.report_edit,name='create'),
             path('<uuid:pk>/',views.report_detail,name='detail'),path('<uuid:pk>/edit/',views.report_edit,name='edit'),
             path('revisions/<uuid:revision_id>/preview/',views.download,{'format':'html','preview':True},name='preview'),
             path('revisions/<uuid:revision_id>/<str:format>/',views.download,name='download')]
