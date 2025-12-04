# File: payments/views/health.py
# ============================================================
# RATIONALE: Health check endpoint for monitoring
# ============================================================

from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny


class HealthCheckView(APIView):
    """
    Health check endpoint for monitoring payment API status.
    No authentication required.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({
            'status': 'healthy',
            'service': 'payment-integration',
            'timestamp': timezone.now().isoformat(),
            'version': '1.0.0'
        }, status=status.HTTP_200_OK)