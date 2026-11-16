from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

@admin.register(User)
class TRACEUserAdmin(UserAdmin):
    readonly_fields = [field.name for field in User._meta.fields] + ["groups", "user_permissions"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
