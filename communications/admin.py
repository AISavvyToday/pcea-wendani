# communications/admin.py

from django.contrib import admin
from .models import Announcement, EmailNotification, NotificationTemplate, SMSNotification


admin.register(Announcement)
admin.register(EmailNotification)
admin.register(NotificationTemplate)
admin.register(SMSNotification)