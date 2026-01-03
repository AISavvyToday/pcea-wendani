# core/mixins.py
from django.contrib.auth.mixins import UserPassesTestMixin
from django.shortcuts import redirect
from django.contrib import messages
from core.models import UserRole


class RoleRequiredMixin(UserPassesTestMixin):
    """
    Mixin to restrict view access based on user roles.

    Usage:
        class MyView(RoleRequiredMixin, View):
            allowed_roles = [User.UserRole.SUPER_ADMIN, User.UserRole.SCHOOL_ADMIN]
    """
    allowed_roles = []

    def test_func(self):
        if not self.request.user.is_authenticated:
            return False

        if not self.allowed_roles:
            return True

        return self.request.user.role in self.allowed_roles

    def handle_no_permission(self):
        messages.error(
            self.request,
            'You do not have permission to access this page.'
        )
        # Redirect admin users to admin dashboard instead of home
        if self.request.user.is_authenticated and self.request.user.role in [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]:
            return redirect('portal:dashboard_admin')
        return redirect('portal:home')