# accounts/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from .models import User, AuditLog


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'full_name', 'role', 'organization', 'is_active', 'is_verified', 'is_locked_display', 'date_joined')
    search_fields = ('email', 'first_name', 'last_name', 'phone_number')
    list_select_related = ('organization',)
    ordering = ('-date_joined',)
    readonly_fields = ('date_joined', 'last_login', 'password_changed_at')
    
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'phone_number', 'profile_photo')}),
        ('Organization', {'fields': ('organization',)}),
        ('Role & Permissions', {'fields': ('role', 'is_active', 'is_staff', 'is_superuser', 'is_verified', 'groups', 'user_permissions')}),
        ('Security', {'fields': ('failed_login_attempts', 'locked_until', 'must_change_password', 'password_changed_at')}),
        ('Important Dates', {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'phone_number', 'role', 'organization', 'password1', 'password2'),
        }),
    )
    
    list_filter = ('role', 'organization', 'is_staff', 'is_active', 'is_verified', 'must_change_password', 'date_joined')
    
    def full_name(self, obj):
        return obj.full_name
    full_name.short_description = 'Name'
    
    def is_locked_display(self, obj):
        if obj.is_locked():
            return format_html('<span style="color: red;">🔒 Locked</span>')
        return format_html('<span style="color: green;">✓</span>')
    is_locked_display.short_description = 'Status'


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'action', 'model_name', 'object_id', 'ip_address')
    list_filter = ('action', 'model_name', 'timestamp')
    search_fields = ('user__email', 'action', 'object_id', 'ip_address')
    readonly_fields = ('user', 'action', 'model_name', 'object_id', 'changes', 'ip_address', 'user_agent', 'timestamp')
    ordering = ('-timestamp',)
    date_hierarchy = 'timestamp'
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False