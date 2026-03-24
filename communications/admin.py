from django.contrib import admin

from .models import Announcement, EmailNotification, NotificationTemplate, SMSNotification


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'target_audience', 'send_sms', 'is_sent', 'sent_at', 'organization')
    list_filter = ('organization', 'target_audience', 'send_sms', 'is_sent')
    search_fields = ('title', 'message')


@admin.register(EmailNotification)
class EmailNotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient_email', 'status', 'purpose', 'organization', 'sent_at')
    list_filter = ('organization', 'status', 'purpose')
    search_fields = ('recipient_email', 'subject', 'message')


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'template_type', 'organization', 'updated_at')
    list_filter = ('organization', 'template_type')
    search_fields = ('name', 'template_text', 'description')


@admin.register(SMSNotification)
class SMSNotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient_phone', 'status', 'purpose', 'organization', 'sent_at')
    list_filter = ('organization', 'status', 'purpose')
    search_fields = ('recipient_phone', 'message', 'error_message')
