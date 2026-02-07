"""
Token-based authentication for SMS Service API
"""
import logging
from django.conf import settings
from django.http import JsonResponse

logger = logging.getLogger(__name__)


def verify_api_token(request):
    """
    Verify API token from request header or query parameter
    
    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    api_token = settings.SMS_SERVICE_API_TOKEN
    
    if not api_token:
        logger.warning("SMS_SERVICE_API_TOKEN not configured - API authentication disabled")
        return True, None  # Allow if no token configured (for development)
    
    # Check Authorization header first
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if auth_header.startswith('Bearer '):
        token = auth_header.replace('Bearer ', '').strip()
    elif auth_header.startswith('Token '):
        token = auth_header.replace('Token ', '').strip()
    else:
        # Check query parameter
        token = request.GET.get('token', '')
    
    if not token:
        return False, 'Missing authentication token'
    
    if token != api_token:
        logger.warning(f"Invalid API token attempted: {token[:10]}...")
        return False, 'Invalid authentication token'
    
    return True, None


def api_token_required(view_func):
    """
    Decorator to require API token authentication for API views
    """
    def wrapped_view(request, *args, **kwargs):
        is_valid, error = verify_api_token(request)
        if not is_valid:
            return JsonResponse({
                'success': False,
                'error': error or 'Authentication required'
            }, status=401)
        return view_func(request, *args, **kwargs)
    return wrapped_view

