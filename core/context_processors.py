# core/context_processors.py
"""
Context processor to expose user role flags to all templates.
"""

from core.models import UserRole
from django.conf import settings


def user_role_context(request):
    """
    Add user role information and flags to template context.

    Available in templates:
        - user_role: The user's role value (e.g., 'super_admin')
        - user_role_display: Human-readable role name
        - is_admin: True if user is SUPER_ADMIN or SCHOOL_ADMIN
        - is_accountant: True if user is ACCOUNTANT
        - is_teacher: True if user is TEACHER
        - is_parent: True if user is PARENT
        - is_student: True if user is STUDENT
        - is_staff_user: True if user is admin, accountant, or teacher
        - organization: The user's organization
        - is_demo_organisation: True if organization is 'Demo Organisation'
        - site_domain: The site domain (defaults to demo domain for Demo Organisation)
        - school_logo_url: Logo URL (placeholder for Demo Organisation)
        - sponsor_logo_url: Sponsor logo URL (placeholder for Demo Organisation)
    """
    context = {
        'user_role': None,
        'user_role_display': None,
        'is_admin': False,
        'is_accountant': False,
        'is_teacher': False,
        'is_parent': False,
        'is_student': False,
        'is_staff_user': False,
        'organization': None,
        'is_demo_organisation': False,
        'site_domain': None,
        'school_logo_url': getattr(settings, 'SCHOOL_LOGO_URL', '/static/assets/images/logo.jpeg'),
        'sponsor_logo_url': getattr(settings, 'SPONSOR_LOGO_URL', '/static/assets/images/logo2.jpeg'),
    }

    # Get organization from request (set by OrganizationMiddleware)
    organization = getattr(request, 'organization', None)
    if organization:
        context['organization'] = organization
        is_demo = organization.name == 'Demo Organisation'
        context['is_demo_organisation'] = is_demo
        
        # Set domain for Demo Organisation
        if is_demo:
            context['site_domain'] = 'https://demo.schoolmanagementsys.swiftresidetech.co.ke/'
            # Use placeholder logos for Demo Organisation
            context['school_logo_url'] = '/static/assets/images/placeholder_logo.png'
            context['sponsor_logo_url'] = '/static/assets/images/placeholder_logo2.png'
        else:
            # Use default domain from request
            context['site_domain'] = request.build_absolute_uri('/')

    if request.user.is_authenticated:
        role = getattr(request.user, 'role', None)

        if role:
            context.update({
                'user_role': role,
                'user_role_display': request.user.get_role_display() if hasattr(request.user,
                                                                                'get_role_display') else str(role),
                'is_admin': role in [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN],
                'is_accountant': role == UserRole.ACCOUNTANT,
                'is_teacher': role == UserRole.TEACHER,
                'is_parent': role == UserRole.PARENT,
                'is_student': role == UserRole.STUDENT,
                'is_staff_user': role in [
                    UserRole.SUPER_ADMIN,
                    UserRole.SCHOOL_ADMIN,
                    UserRole.ACCOUNTANT,
                    UserRole.TEACHER
                ],
            })

    return context