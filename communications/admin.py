from django.contrib import admin

from .models import Announcement, EmailNotification, NotificationTemplate, SMSNotification


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'target_audience', 'send_sms', 'send_email', 'is_sent', 'sent_at', 'organization')
    list_filter = ('organization', 'target_audience', 'send_sms', 'send_email', 'is_sent', 'created_at')
    search_fields = ('title', 'message')
    readonly_fields = ('created_at', 'updated_at', 'sent_at')
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'


@admin.register(EmailNotification)
class EmailNotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient_email', 'subject', 'status', 'purpose', 'organization', 'sent_at')
    list_filter = ('organization', 'status', 'purpose', 'created_at', 'sent_at')
    search_fields = ('recipient_email', 'subject', 'message')
    readonly_fields = ('created_at', 'updated_at', 'sent_at', 'error_message')
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'template_type', 'organization', 'updated_at')
    list_filter = ('organization', 'template_type', 'created_at', 'updated_at')
    search_fields = ('name', 'template_text', 'description')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('template_type', 'name')


@admin.register(SMSNotification)
class SMSNotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient_phone', 'status', 'purpose', 'organization', 'related_student', 'sent_at')
    list_filter = ('organization', 'status', 'purpose', 'created_at', 'sent_at')
    search_fields = ('recipient_phone', 'message', 'error_message', 'related_student__admission_number', 'related_student__first_name', 'related_student__last_name')
    readonly_fields = ('created_at', 'updated_at', 'sent_at', 'error_message')
    autocomplete_fields = ('related_student', 'triggered_by')
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'
