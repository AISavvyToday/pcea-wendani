# core/middleware.py
"""
Middleware for multi-tenancy support.
Sets request.organization from user.organization for all authenticated requests.
"""

import logging
from django.shortcuts import redirect
from django.contrib import messages

logger = logging.getLogger(__name__)


class OrganizationMiddleware:
    """
    Middleware to set request.organization from user.organization.
    Validates that authenticated users have an organization.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Skip middleware for login/logout/register pages to avoid redirect loops
        login_paths = ['/auth/login/', '/auth/logout/', '/auth/register/', '/login/', '/logout/', '/register/']
        if any(request.path.startswith(path) for path in login_paths):
            request.organization = None
            response = self.get_response(request)
            return response
        
        # Set organization for authenticated users
        if request.user.is_authenticated:
            if hasattr(request.user, 'organization') and request.user.organization:
                request.organization = request.user.organization
                logger.debug(f"Organization set for user {request.user.email}: {request.organization.name}")
            else:
                # User doesn't have organization - allow superusers and staff to proceed
                # (They might need to run migration command first)
                if request.user.is_superuser or request.user.is_staff:
                    request.organization = None
                    logger.warning(f"User {request.user.email} does not have an organization assigned (superuser/staff)")
                else:
                    # Regular users without organization - redirect to login
                    logger.warning(f"User {request.user.email} does not have an organization assigned")
                    messages.error(
                        request,
                        'Your account is not assigned to an organization. Please contact the administrator.'
                    )
                    from django.contrib.auth import logout
                    logout(request)
                    return redirect('portal:login')
        else:
            request.organization = None
        
        response = self.get_response(request)
        return response

