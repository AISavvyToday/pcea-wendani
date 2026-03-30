"""URL configuration for communications module."""

from django.urls import path

from . import views

app_name = 'communications'

urlpatterns = [
    path('announcements/', views.AnnouncementListView.as_view(), name='announcement_list'),
    path('announcements/create/', views.AnnouncementCreateView.as_view(), name='announcement_create'),
    path('announcements/<uuid:pk>/', views.AnnouncementDetailView.as_view(), name='announcement_detail'),
    path('announcements/<uuid:pk>/send/', views.SendAnnouncementView.as_view(), name='announcement_send'),

    path('sms/', views.SMSNotificationListView.as_view(), name='sms_notification_list'),
    path('emails/', views.EmailNotificationListView.as_view(), name='email_notification_list'),

    path('templates/', views.NotificationTemplateListView.as_view(), name='notification_template_list'),
    path('templates/create/', views.NotificationTemplateCreateView.as_view(), name='notification_template_create'),
    path('templates/<uuid:pk>/edit/', views.NotificationTemplateUpdateView.as_view(), name='notification_template_update'),

    path('sms-settings/', views.SMSSettingsView.as_view(), name='sms_settings'),
    path('send-sms/', views.SendSingleSMSView.as_view(), name='send_single_sms'),
    path('balance-reminders/', views.BalanceReminderSMSView.as_view(), name='balance_reminder_sms'),
    path('invoice-sms/', views.InvoiceSMSView.as_view(), name='invoice_sms'),
    path('payment-receipt-sms/', views.PaymentReceiptSMSView.as_view(), name='payment_receipt_sms'),
    
]
