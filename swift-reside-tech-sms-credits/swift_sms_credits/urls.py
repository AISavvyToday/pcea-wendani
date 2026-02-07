"""
URL configuration for Swift SMS Credits package
"""
from django.urls import path
from . import kcb_callbacks

app_name = 'swift_sms_credits'

urlpatterns = [
    path('kcb-validate/', kcb_callbacks.sms_credits_kcb_validation, name='sms_credits_kcb_validation'),
    path('kcb-notification/', kcb_callbacks.sms_credits_kcb_notification, name='sms_credits_kcb_notification'),
    path('kcb-till-notification/', kcb_callbacks.sms_credits_kcb_till_notification, name='sms_credits_kcb_till_notification'),
]

