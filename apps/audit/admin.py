from django.contrib import admin
from apps.engagements.permissions import is_system_admin
from .models import AuditEvent, EntityRevision


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ["created_at", "action", "actor", "engagement", "subject_id"]
    readonly_fields = [field.name for field in AuditEvent._meta.fields]

    def has_view_permission(self, request, obj=None):
        return is_system_admin(request.user)

    def has_module_permission(self, request):
        return is_system_admin(request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EntityRevision)
class EntityRevisionAdmin(AuditEventAdmin):
    list_display = ["created_at", "entity_kind", "entity_id", "entity_version"]
    readonly_fields = [field.name for field in EntityRevision._meta.fields]
