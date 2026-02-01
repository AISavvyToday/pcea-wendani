# core/mixins.py
from django.contrib.auth.mixins import UserPassesTestMixin
from django.shortcuts import redirect
from django.contrib import messages
from django.db import models
import logging
from core.models import UserRole

logger = logging.getLogger(__name__)


class OrganizationFilterMixin:
    """
    Mixin to automatically filter querysets by organization.
    
    Usage:
        class MyListView(OrganizationFilterMixin, ListView):
            model = MyModel
            
        The queryset will automatically be filtered by request.organization
    """
    
    def get_queryset(self):
        """
        Filter queryset by organization if model has organization field.
        """
        queryset = super().get_queryset()
        
        # Check if model has organization field
        if hasattr(self, 'model') and hasattr(self.model, '_meta'):
            if 'organization' in [f.name for f in self.model._meta.get_fields()]:
                organization = getattr(self.request, 'organization', None)
                if organization:
                    queryset = queryset.filter(organization=organization)
                    logger.debug(f"Filtered {self.model.__name__} queryset by organization: {organization.name}")
                else:
                    logger.warning(f"No organization found for request, returning empty queryset for {self.model.__name__}")
                    queryset = queryset.none()
        
        return queryset
    
    def form_valid(self, form):
        """
        Auto-set organization on form save for CreateView.
        """
        if hasattr(form, 'instance') and hasattr(form.instance, 'organization'):
            organization = getattr(self.request, 'organization', None)
            if organization:
                form.instance.organization = organization
                logger.debug(f"Set organization on {form.instance.__class__.__name__}: {organization.name}")
            else:
                logger.error(f"No organization found when saving {form.instance.__class__.__name__}")
        
        return super().form_valid(form)


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