# transport/views.py
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, View
from django.db import transaction
from core.mixins import RoleRequiredMixin, OrganizationFilterMixin
from accounts.models import UserRole
from .models import TransportRoute, TransportFee
from .forms import TransportRouteForm, TransportFeeForm


class TransportRouteListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    """List all transport routes and fees with modals for CRUD operations"""
    template_name = 'transport/transport_list.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get(self, request):
        from academics.models import AcademicYear
        routes = TransportRoute.objects.filter(is_active=True).prefetch_related('fees').order_by('name')
        fees = TransportFee.objects.filter(is_active=True).select_related('route', 'academic_year').order_by('route__name', 'academic_year__year', 'term')
        academic_years = AcademicYear.objects.filter(is_active=True).order_by('-year')
        
        # Prepare route-fee combinations for table display
        route_fee_rows = []
        for route in routes:
            active_fees = [f for f in route.fees.all() if f.is_active]
            if active_fees:
                for fee in active_fees:
                    route_fee_rows.append({
                        'route': route,
                        'fee': fee,
                        'is_first_fee': active_fees.index(fee) == 0,
                        'active_fee_count': len(active_fees),
                    })
            else:
                route_fee_rows.append({
                    'route': route,
                    'fee': None,
                    'is_first_fee': True,
                    'active_fee_count': 0,
                })
        
        return render(request, self.template_name, {
            'routes': routes,
            'fees': fees,
            'academic_years': academic_years,
            'route_fee_rows': route_fee_rows,
        })


class TransportRouteCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    """Create a new transport route"""
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def post(self, request):
        form = TransportRouteForm(request.POST)
        if form.is_valid():
            route = form.save()
            return JsonResponse({
                'success': True,
                'message': f'Route "{route.name}" created successfully.',
                'route': {
                    'id': str(route.id),
                    'name': route.name,
                    'description': route.description,
                    'pickup_points': route.pickup_points,
                    'dropoff_points': route.dropoff_points,
                }
            })
        return JsonResponse({
            'success': False,
            'errors': form.errors,
        }, status=400)


class TransportRouteUpdateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    """Update an existing transport route"""
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def post(self, request, pk):
        route = get_object_or_404(TransportRoute, pk=pk, is_active=True)
        form = TransportRouteForm(request.POST, instance=route)
        if form.is_valid():
            route = form.save()
            return JsonResponse({
                'success': True,
                'message': f'Route "{route.name}" updated successfully.',
                'route': {
                    'id': str(route.id),
                    'name': route.name,
                    'description': route.description,
                    'pickup_points': route.pickup_points,
                    'dropoff_points': route.dropoff_points,
                }
            })
        return JsonResponse({
            'success': False,
            'errors': form.errors,
        }, status=400)


class TransportRouteDeleteView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    """Delete (soft delete) a transport route"""
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def post(self, request, pk):
        route = get_object_or_404(TransportRoute, pk=pk, is_active=True)
        
        # Check if route has active students
        student_count = route.students.filter(is_active=True, uses_school_transport=True).count()
        if student_count > 0:
            return JsonResponse({
                'success': False,
                'message': f'Cannot delete route. {student_count} active student(s) are using this route.',
            }, status=400)
        
        # Check if route has fees
        fee_count = route.fees.filter(is_active=True).count()
        if fee_count > 0:
            return JsonResponse({
                'success': False,
                'message': f'Cannot delete route. It has {fee_count} active fee(s). Please delete fees first.',
            }, status=400)
        
        route.soft_delete()
        return JsonResponse({
            'success': True,
            'message': f'Route "{route.name}" deleted successfully.',
        })


class TransportFeeCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    """Create a new transport fee"""
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def post(self, request):
        form = TransportFeeForm(request.POST)
        if form.is_valid():
            fee = form.save()
            return JsonResponse({
                'success': True,
                'message': f'Transport fee created successfully.',
                'fee': {
                    'id': str(fee.id),
                    'route_id': str(fee.route.id),
                    'route_name': fee.route.name,
                    'academic_year_id': str(fee.academic_year.id),
                    'academic_year_year': str(fee.academic_year.year),
                    'term': fee.term,
                    'term_display': fee.get_term_display(),
                    'amount': str(fee.amount),
                    'half_amount': str(fee.half_amount) if fee.half_amount else None,
                }
            })
        return JsonResponse({
            'success': False,
            'errors': form.errors,
        }, status=400)


class TransportFeeUpdateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    """Update an existing transport fee"""
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def post(self, request, pk):
        fee = get_object_or_404(TransportFee, pk=pk, is_active=True)
        form = TransportFeeForm(request.POST, instance=fee)
        if form.is_valid():
            fee = form.save()
            return JsonResponse({
                'success': True,
                'message': f'Transport fee updated successfully.',
                'fee': {
                    'id': str(fee.id),
                    'route_id': str(fee.route.id),
                    'route_name': fee.route.name,
                    'academic_year_id': str(fee.academic_year.id),
                    'academic_year_year': str(fee.academic_year.year),
                    'term': fee.term,
                    'term_display': fee.get_term_display(),
                    'amount': str(fee.amount),
                    'half_amount': str(fee.half_amount) if fee.half_amount else None,
                }
            })
        return JsonResponse({
            'success': False,
            'errors': form.errors,
        }, status=400)


class TransportFeeDeleteView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    """Delete (soft delete) a transport fee"""
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def post(self, request, pk):
        fee = get_object_or_404(TransportFee, pk=pk, is_active=True)
        fee.soft_delete()
        return JsonResponse({
            'success': True,
            'message': f'Transport fee deleted successfully.',
        })


class TransportRouteDetailView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    """Get route details for editing"""
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get(self, request, pk):
        route = get_object_or_404(TransportRoute, pk=pk, is_active=True)
        return JsonResponse({
            'id': str(route.id),
            'name': route.name,
            'description': route.description,
            'pickup_points': route.pickup_points,
            'dropoff_points': route.dropoff_points,
        })


class TransportFeeDetailView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    """Get fee details for editing"""
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]

    def get(self, request, pk):
        fee = get_object_or_404(TransportFee, pk=pk, is_active=True)
        return JsonResponse({
            'id': str(fee.id),
            'route_id': str(fee.route.id),
            'route_name': fee.route.name,
            'academic_year_id': str(fee.academic_year.id),
            'academic_year_year': str(fee.academic_year.year),
            'term': fee.term,
            'amount': str(fee.amount),
            'half_amount': str(fee.half_amount) if fee.half_amount else '',
        })

