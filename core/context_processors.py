# core/context_processors.py
"""
Context processor to expose user role flags to all templates.
"""

from core.models import UserRole


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
    }

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