# config/urls.py
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("dashboard/", RedirectView.as_view(pattern_name="portal:home", permanent=False), name="dashboard"),
    path("contact/", RedirectView.as_view(pattern_name="portal:home", permanent=False), name="contact"),
    path("", include("portal.urls", namespace="portal")),
    path('api/payments/', include('payments.urls', namespace='payments-api')),
    path('students/', include('students.urls')),
    path('finance/', include('finance.urls', namespace='finance')),
    path('academics/', include('academics.urls', namespace='academics')),
    path('transport/', include('transport.urls', namespace='transport')),
    path('other-income/', include('other_income.urls', namespace='other_income')),
    path('trash/', include('trash.urls', namespace='trash')),
    path('reports/', include('reports.urls', namespace='reports')),
    path('communications/', include('communications.urls', namespace='communications')),
    path('payroll/', include('payroll.urls', namespace='payroll')),
    path('trash/', include('trash.urls', namespace='trash')),
]

# KCB SMS Credits callbacks are disabled by default because the preferred
# topology is central-service-only per the reuse guide. Enable explicitly only
# for deployments that intentionally accept direct KCB callbacks in this app.
if getattr(settings, 'SWIFT_SMS_ENABLE_DIRECT_CALLBACKS', False):
    from swift_sms_credits.kcb_callbacks import (
        sms_credits_kcb_notification,
        sms_credits_kcb_till_notification
    )

    urlpatterns += [
        path('api/sms-credits/kcb-notification/', sms_credits_kcb_notification, name='kcb_sms_notification'),
        path('api/sms-credits/kcb-till-notification/', sms_credits_kcb_till_notification, name='kcb_sms_till_notification'),
    ]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
