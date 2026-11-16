from django.urls import path
from . import views
from .models import EngagementStatus

app_name = "engagements"
urlpatterns = [
    path("", views.engagement_list, name="list"),
    path("new/", views.create, name="create"),
    path("<uuid:pk>/", views.detail, name="detail"),
    path("<uuid:pk>/edit/", views.edit, name="edit"),
    path("<uuid:pk>/activate/", views.lifecycle, {"target": EngagementStatus.ACTIVE}, name="activate"),
    path("<uuid:pk>/pause/", views.lifecycle, {"target": EngagementStatus.PAUSED}, name="pause"),
    path("<uuid:pk>/complete/", views.lifecycle, {"target": EngagementStatus.COMPLETED}, name="complete"),
    path("<uuid:pk>/archive/", views.lifecycle, {"target": EngagementStatus.ARCHIVED}, name="archive"),
    path("<uuid:pk>/notes/", views.note_create, name="note_create"),
    path("<uuid:pk>/notes/<uuid:note_id>/edit/", views.note_edit, name="note_edit"),
    path("<uuid:pk>/notes/<uuid:child_id>/delete/", views.child_delete, {"kind": "note"}, name="note_delete"),
    path("<uuid:pk>/milestones/", views.milestone_create, name="milestone_create"),
    path("<uuid:pk>/milestones/<uuid:milestone_id>/edit/", views.milestone_edit, name="milestone_edit"),
    path("<uuid:pk>/milestones/<uuid:milestone_id>/complete/", views.milestone_complete, name="milestone_complete"),
    path("<uuid:pk>/milestones/<uuid:child_id>/delete/", views.child_delete, {"kind": "milestone"}, name="milestone_delete"),
    path("<uuid:pk>/members/", views.members, name="members"),
    path("<uuid:pk>/members/<uuid:membership_id>/change/", views.member_change, name="member_change"),
    path("<uuid:pk>/members/<uuid:membership_id>/revoke/", views.member_revoke, name="member_revoke"),
]
