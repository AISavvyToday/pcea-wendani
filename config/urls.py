# config/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("portal.urls", namespace="portal")),
    path('api/payments/', include('payments.urls', namespace='payments-api')),
    path('students/', include('students.urls')),
    path('finance/', include('finance.urls', namespace='finance')),
    path('academics/', include('academics.urls', namespace='academics')),
    path('transport/', include('transport.urls', namespace='transport')),
    path('other-income/', include('other_income.urls', namespace='other_income')),
    path('reports/', include('reports.urls', namespace='reports')),
    path('communications/', include('communications.urls', namespace='communications')),
]

# KCB SMS Credits callbacks - import inside try-except to handle import errors gracefully
try:
    from swift_sms_credits.kcb_callbacks import (
        sms_credits_kcb_notification,
        sms_credits_kcb_till_notification
    )
    urlpatterns += [
        path('api/sms-credits/kcb-notification/', sms_credits_kcb_notification, name='kcb_sms_notification'),
        path('api/sms-credits/kcb-till-notification/', sms_credits_kcb_till_notification, name='kcb_sms_till_notification'),
    ]
except (ImportError, Exception) as e:
    # If import fails (e.g., during URL check), log but don't fail
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"Could not import SMS credits KCB callbacks: {e}. URLs will not be available.")

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)