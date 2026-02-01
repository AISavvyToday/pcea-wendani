# communications/urls.py
"""
URL configuration for communications module.
"""

from django.urls import path, include
from . import views

app_name = 'communications'

urlpatterns = [
    # Announcements
    path('announcements/', views.AnnouncementListView.as_view(), name='announcement_list'),
    path('announcements/create/', views.AnnouncementCreateView.as_view(), name='announcement_create'),
    path('announcements/<uuid:pk>/', views.AnnouncementDetailView.as_view(), name='announcement_detail'),
    path('announcements/<uuid:pk>/send/', views.SendAnnouncementView.as_view(), name='announcement_send'),
    
    # SMS Notifications
    path('sms/', views.SMSNotificationListView.as_view(), name='sms_notification_list'),
    
    # Email Notifications
    path('emails/', views.EmailNotificationListView.as_view(), name='email_notification_list'),
    
    # Notification Templates
    path('templates/', views.NotificationTemplateListView.as_view(), name='notification_template_list'),
    path('templates/create/', views.NotificationTemplateCreateView.as_view(), name='notification_template_create'),
    
    # SMS Settings
    path('sms-settings/', views.SMSSettingsView.as_view(), name='sms_settings'),
    
    # Single SMS Sending
    path('send-sms/', views.SendSingleSMSView.as_view(), name='send_single_sms'),
]

