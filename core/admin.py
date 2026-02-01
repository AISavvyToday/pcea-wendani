from django.contrib import admin
from .models import Organization

@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'sms_account_number', 'sms_balance', 'imarabiz_shortcode', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'code', 'sms_account_number']
    readonly_fields = ['id', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'code', 'is_active')
        }),
        ('Contact Information', {
            'fields': ('address', 'phone', 'email', 'logo_url'),
            'classes': ('collapse',)
        }),
        ('SMS Configuration', {
            'fields': ('sms_account_number', 'sms_balance', 'sms_price_per_unit', 'imarabiz_shortcode')
        }),
        ('Timestamps', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
