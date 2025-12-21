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
    path('other-income/', include('other_income.urls', namespace='other_income')),
    path('reports/', include('reports.urls', namespace='reports')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)