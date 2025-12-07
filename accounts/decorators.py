# accounts/decorators.py
"""
Custom decorators for role-based access control.
"""

import logging
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from core.models import UserRole

logger = logging.getLogger(__name__)


def role_required(allowed_roles, redirect_url='portal:home'):
    """
    Decorator that restricts view access to users with specific roles.

    Usage:
        @role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN])
        def admin_only_view(request):
            ...

        @role_required([UserRole.ACCOUNTANT], redirect_url='portal:dashboard_bursar')
        def bursar_view(request):
            ...

    Args:
        allowed_roles: List of UserRole values that can access the view
        redirect_url: URL name to redirect unauthorized users (default: home)

    Returns:
        Decorated view function
    """

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            user = request.user

            # Check if user has an allowed role
            if user.role in allowed_roles:
                logger.debug(
                    f"Access granted to '{view_func.__name__}' for user '{user.email}' with role '{user.role}'")
                return view_func(request, *args, **kwargs)

            # Log unauthorized access attempt
            logger.warning(
                f"Unauthorized access attempt to '{view_func.__name__}' by user '{user.email}' "
                f"with role '{user.role}'. Allowed roles: {allowed_roles}"
            )

            # Show error message and redirect
            messages.error(request, "You don't have permission to access that page.")
            return redirect(redirect_url)

        return wrapper

    return decorator


def admin_required(view_func):
    """
    Shortcut decorator for views that require admin access.
    Allows: SUPER_ADMIN, SCHOOL_ADMIN
    """
    return role_required([UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN])(view_func)


def staff_required(view_func):
    """
    Shortcut decorator for views that require staff access.
    Allows: SUPER_ADMIN, SCHOOL_ADMIN, ACCOUNTANT, TEACHER
    """
    return role_required([
        UserRole.SUPER_ADMIN,
        UserRole.SCHOOL_ADMIN,
        UserRole.ACCOUNTANT,
        UserRole.TEACHER
    ])(view_func)


def finance_required(view_func):
    """
    Shortcut decorator for finance-related views.
    Allows: SUPER_ADMIN, SCHOOL_ADMIN, ACCOUNTANT
    """
    return role_required([
        UserRole.SUPER_ADMIN,
        UserRole.SCHOOL_ADMIN,
        UserRole.ACCOUNTANT
    ])(view_func)


def teacher_required(view_func):
    """
    Shortcut decorator for teacher-specific views.
    Allows: SUPER_ADMIN, SCHOOL_ADMIN, TEACHER
    """
    return role_required([
        UserRole.SUPER_ADMIN,
        UserRole.SCHOOL_ADMIN,
        UserRole.TEACHER
    ])(view_func)