"""
API URL configuration for SMS Credits Service
"""
from django.urls import path
from . import api_views

app_name = 'sms_api'

urlpatterns = [
    path('balance/', api_views.BalanceAPIView.as_view(), name='balance'),
    path('credits/deduct/', api_views.DeductCreditsAPIView.as_view(), name='deduct_credits'),
    path('sms/send/', api_views.SendSMSAPIView.as_view(), name='send_sms'),
    path('sms/bulk/', api_views.SendBulkSMSAPIView.as_view(), name='send_bulk_sms'),
    path('usage/', api_views.UsageHistoryAPIView.as_view(), name='usage_history'),
    path('purchases/', api_views.PurchaseHistoryAPIView.as_view(), name='purchase_history'),
]

