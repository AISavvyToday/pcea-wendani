# File: payments/authentication.py
# ============================================================
# RATIONALE: Implement custom authentication for bank APIs
# - Equity uses Basic Authentication
# - Co-op uses Basic Authentication
# Both need to return proper JSON responses on failure
# ============================================================

import base64
import logging
from django.conf import settings
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger(__name__)


class EquityBasicAuthentication(authentication.BaseAuthentication):
    """
    Custom Basic Authentication for Equity Bank API.
    Expects header: Authorization: Basic <base64(username:password)>
    """
    
    def authenticate(self, request):
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        
        if not auth_header:
            logger.warning(f"Equity API: Missing Authorization header from {request.META.get('REMOTE_ADDR')}")
            raise AuthenticationFailed({
                'responseCode': '401',
                'responseMessage': 'Missing Authorization header'
            })
        
        # Parse "Basic <base64>" format
        parts = auth_header.split(' ')
        if len(parts) != 2 or parts[0].lower() != 'basic':
            logger.warning(f"Equity API: Invalid Authorization format from {request.META.get('REMOTE_ADDR')}")
            raise AuthenticationFailed({
                'responseCode': '401',
                'responseMessage': 'Invalid Authorization header format. Expected: Basic <base64(username:password)>'
            })
        
        try:
            # Decode base64 credentials
            decoded = base64.b64decode(parts[1]).decode('utf-8')
            username, password = decoded.split(':', 1)
        except (ValueError, UnicodeDecodeError) as e:
            logger.warning(f"Equity API: Failed to decode credentials from {request.META.get('REMOTE_ADDR')}: {e}")
            raise AuthenticationFailed({
                'responseCode': '401',
                'responseMessage': 'Invalid credentials format'
            })
        
        expected_username = settings.EQUITY_IPN_USERNAME
        expected_password = settings.EQUITY_IPN_PASSWORD
        
        if not expected_username or not expected_password:
            logger.error("Equity API: EQUITY_IPN_USERNAME or EQUITY_IPN_PASSWORD not configured in settings")
            raise AuthenticationFailed({
                'responseCode': '500',
                'responseMessage': 'Server configuration error'
            })
        
        if username != expected_username or password != expected_password:
            logger.warning(f"Equity API: Invalid credentials from {request.META.get('REMOTE_ADDR')}")
            raise AuthenticationFailed({
                'responseCode': '401',
                'responseMessage': 'Invalid credentials'
            })
        
        logger.info(f"Equity API: Authentication successful from {request.META.get('REMOTE_ADDR')}")
        # Return None for user since this is service-to-service auth
        return (None, 'equity_basic_auth')
    
    def authenticate_header(self, request):
        return 'Basic realm="Equity Bank API"'


class CoopBasicAuthentication(authentication.BaseAuthentication):
    """
    Custom Basic Authentication for Co-operative Bank IPN.
    Expects header: Authorization: Basic <base64(username:password)>
    """
    
    def authenticate(self, request):
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        
        if not auth_header:
            logger.warning(f"Coop IPN: Missing Authorization header from {request.META.get('REMOTE_ADDR')}")
            raise AuthenticationFailed({
                'MessageCode': '401',
                'Message': 'Missing Authorization header'
            })
        
        # Parse "Basic <base64>" format
        parts = auth_header.split(' ')
        if len(parts) != 2 or parts[0].lower() != 'basic':
            logger.warning(f"Coop IPN: Invalid Authorization format from {request.META.get('REMOTE_ADDR')}")
            raise AuthenticationFailed({
                'MessageCode': '401',
                'Message': 'Invalid Authorization header format'
            })
        
        try:
            # Decode base64 credentials
            decoded = base64.b64decode(parts[1]).decode('utf-8')
            username, password = decoded.split(':', 1)
        except (ValueError, UnicodeDecodeError) as e:
            logger.warning(f"Coop IPN: Failed to decode credentials from {request.META.get('REMOTE_ADDR')}: {e}")
            raise AuthenticationFailed({
                'MessageCode': '401',
                'Message': 'Invalid credentials format'
            })
        
        expected_username = settings.COOP_IPN_USERNAME
        expected_password = settings.COOP_IPN_PASSWORD
        
        if not expected_username or not expected_password:
            logger.error("Coop IPN: COOP_IPN_USERNAME or COOP_IPN_PASSWORD not configured")
            raise AuthenticationFailed({
                'MessageCode': '500',
                'Message': 'Server configuration error'
            })
        
        if username != expected_username or password != expected_password:
            logger.warning(f"Coop IPN: Invalid credentials from {request.META.get('REMOTE_ADDR')}")
            raise AuthenticationFailed({
                'MessageCode': '401',
                'Message': 'Invalid credentials'
            })
        
        logger.info(f"Coop IPN: Authentication successful from {request.META.get('REMOTE_ADDR')}")
        return (None, 'coop_basic_auth')
    
    def authenticate_header(self, request):
        return 'Basic realm="Co-op Bank IPN"'