# File: payments/urls.py
# ============================================================
# RATIONALE: Define URL routes for payment API endpoints
# - Equity Bank: /api/payments/equity/validation/ and /notification/
# - Co-op Bank: /api/payments/coop/ipn/
# ============================================================

from django.urls import path
from .views import (
    EquityValidationView,
    EquityNotificationView,
    CoopIPNView,
)
from .views.health import HealthCheckView

app_name = 'payments'

urlpatterns = [

    # Health check
    path('health/', HealthCheckView.as_view(), name='health-check'),

    # Equity Bank endpoints
    path('equity/validation/', EquityValidationView.as_view(), name='equity-validation'),
    path('equity/notification/', EquityNotificationView.as_view(), name='equity-notification'),
    
    # Co-operative Bank endpoint
    path('coop/ipn/', CoopIPNView.as_view(), name='coop-ipn'),
]