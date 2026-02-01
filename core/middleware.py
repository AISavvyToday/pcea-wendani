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
        # Set organization for authenticated users
        if request.user.is_authenticated:
            if hasattr(request.user, 'organization') and request.user.organization:
                request.organization = request.user.organization
                logger.debug(f"Organization set for user {request.user.email}: {request.organization.name}")
            else:
                # User doesn't have organization - only allow superusers to proceed
                if not request.user.is_superuser:
                    logger.warning(f"User {request.user.email} does not have an organization assigned")
                    # Allow access to login/logout pages
                    if request.path not in ['/login/', '/logout/', '/register/']:
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

