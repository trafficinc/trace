from django.urls import path
from . import views
app_name='system_audit'
urlpatterns=[path('',views.index,name='list'),path('export/',views.export,name='export'),path('events/<int:event_id>/',views.detail,name='detail')]
