"""
Django admin configuration for Swift SMS Credits
"""
from django.contrib import admin
from .models import Organization, SMSPurchaseTransaction, SMSUsageLog


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'sms_account_number', 'sms_balance', 'sms_price_per_unit', 'imarabiz_shortcode', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'sms_account_number', 'slug']
    readonly_fields = ['id', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'is_active')
        }),
        ('SMS Credits', {
            'fields': ('sms_account_number', 'sms_balance', 'sms_price_per_unit', 'imarabiz_shortcode')
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(SMSPurchaseTransaction)
class SMSPurchaseTransactionAdmin(admin.ModelAdmin):
    list_display = ['organization', 'amount', 'sms_credits', 'status', 'bank_reference', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['organization__name', 'organization__sms_account_number', 'bank_reference']
    readonly_fields = ['id', 'created_at', 'updated_at', 'completed_at']
    
    fieldsets = (
        ('Transaction Details', {
            'fields': ('organization', 'amount', 'sms_credits', 'price_per_sms', 'status', 'bank_reference')
        }),
        ('KCB Metadata', {
            'fields': ('kcb_channel_code', 'kcb_timestamp', 'kcb_till_number', 'kcb_customer_mobile', 'kcb_customer_name', 'kcb_narration', 'kcb_balance'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('id', 'error_message', 'raw_request_data', 'created_at', 'updated_at', 'completed_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(SMSUsageLog)
class SMSUsageLogAdmin(admin.ModelAdmin):
    list_display = ['organization', 'sms_count', 'purpose', 'balance_before', 'balance_after', 'created_at']
    list_filter = ['purpose', 'created_at']
    search_fields = ['organization__name', 'organization__sms_account_number', 'purpose']
    readonly_fields = ['id', 'created_at']
    
    fieldsets = (
        ('Usage Details', {
            'fields': ('organization', 'sms_count', 'purpose', 'balance_before', 'balance_after', 'triggered_by')
        }),
        ('Metadata', {
            'fields': ('id', 'notification_ids', 'created_at'),
            'classes': ('collapse',)
        }),
    )

