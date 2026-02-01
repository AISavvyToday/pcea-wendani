# payroll/views.py

from django.views.generic import (
    ListView, CreateView, UpdateView, DetailView, View, TemplateView
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.db.models import Sum, Q
from core.mixins import RoleRequiredMixin, OrganizationFilterMixin
from accounts.models import UserRole
from academics.models import Staff
from .models import (
    SalaryStructure, Allowance, Deduction, StaffSalary,
    PayrollPeriod, PayrollEntry, PayrollAllowance, PayrollDeduction, Payslip
)
from .forms import (
    SalaryStructureForm, AllowanceForm, DeductionForm,
    StaffSalaryForm, PayrollPeriodForm
)
from .services.payroll_calculator import PayrollCalculator
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


# ============== SALARY STRUCTURE ==============

class SalaryStructureListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    model = SalaryStructure
    template_name = 'payroll/salary_structure_list.html'
    context_object_name = 'salary_structures'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    paginate_by = 20


class SalaryStructureCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    model = SalaryStructure
    form_class = SalaryStructureForm
    template_name = 'payroll/salary_structure_form.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('payroll:salary_structure_list')
    
    def form_valid(self, form):
        form.instance.organization = self.request.organization
        return super().form_valid(form)


class SalaryStructureUpdateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, UpdateView):
    model = SalaryStructure
    form_class = SalaryStructureForm
    template_name = 'payroll/salary_structure_form.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('payroll:salary_structure_list')


# ============== ALLOWANCES ==============

class AllowanceListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    model = Allowance
    template_name = 'payroll/allowance_list.html'
    context_object_name = 'allowances'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    paginate_by = 20


class AllowanceCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    model = Allowance
    form_class = AllowanceForm
    template_name = 'payroll/allowance_form.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('payroll:allowance_list')
    
    def form_valid(self, form):
        form.instance.organization = self.request.organization
        return super().form_valid(form)


class AllowanceUpdateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, UpdateView):
    model = Allowance
    form_class = AllowanceForm
    template_name = 'payroll/allowance_form.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('payroll:allowance_list')


# ============== DEDUCTIONS ==============

class DeductionListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    model = Deduction
    template_name = 'payroll/deduction_list.html'
    context_object_name = 'deductions'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    paginate_by = 20


class DeductionCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    model = Deduction
    form_class = DeductionForm
    template_name = 'payroll/deduction_form.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('payroll:deduction_list')
    
    def form_valid(self, form):
        form.instance.organization = self.request.organization
        return super().form_valid(form)


class DeductionUpdateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, UpdateView):
    model = Deduction
    form_class = DeductionForm
    template_name = 'payroll/deduction_form.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('payroll:deduction_list')


# ============== STAFF SALARY ==============

class StaffSalaryListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    model = StaffSalary
    template_name = 'payroll/staff_salary_list.html'
    context_object_name = 'staff_salaries'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    paginate_by = 20
    
    def get_queryset(self):
        return super().get_queryset().select_related('staff', 'staff__user', 'salary_structure')


class StaffSalaryCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    model = StaffSalary
    form_class = StaffSalaryForm
    template_name = 'payroll/staff_salary_form.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('payroll:staff_salary_list')
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields['staff'].queryset = Staff.objects.filter(organization=self.request.organization)
        form.fields['salary_structure'].queryset = SalaryStructure.objects.filter(organization=self.request.organization)
        form.fields['allowances'].queryset = Allowance.objects.filter(organization=self.request.organization)
        form.fields['deductions'].queryset = Deduction.objects.filter(organization=self.request.organization)
        return form
    
    def form_valid(self, form):
        form.instance.organization = self.request.organization
        return super().form_valid(form)


class StaffSalaryUpdateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, UpdateView):
    model = StaffSalary
    form_class = StaffSalaryForm
    template_name = 'payroll/staff_salary_form.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('payroll:staff_salary_list')


# ============== PAYROLL PERIODS ==============

class PayrollPeriodListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    model = PayrollPeriod
    template_name = 'payroll/payroll_period_list.html'
    context_object_name = 'periods'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    paginate_by = 20


class PayrollPeriodCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    model = PayrollPeriod
    form_class = PayrollPeriodForm
    template_name = 'payroll/payroll_period_form.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('payroll:payroll_period_list')
    
    def form_valid(self, form):
        form.instance.organization = self.request.organization
        return super().form_valid(form)


# ============== PAYROLL GENERATION ==============

class PayrollGenerateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    """Generate payroll for a period."""
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    
    def get(self, request):
        """Show form to select period for payroll generation."""
        periods = PayrollPeriod.objects.filter(
            organization=request.organization,
            is_closed=False
        ).order_by('-period_year', '-period_month')
        
        return render(request, 'payroll/payroll_generate.html', {
            'periods': periods,
        })
    
    def post(self, request):
        """Generate payroll entries for selected period."""
        period_id = request.POST.get('period_id')
        
        try:
            period = get_object_or_404(PayrollPeriod, pk=period_id, organization=request.organization)
            
            if period.is_closed:
                messages.error(request, 'This payroll period is already closed.')
                return redirect('payroll:payroll_generate')
            
            # Get all active staff with salary configurations
            staff_with_salary = Staff.objects.filter(
                organization=request.organization,
                status='active',
                salary__isnull=False
            ).select_related('salary', 'salary__salary_structure')
            
            created_count = 0
            updated_count = 0
            errors = []
            
            for staff in staff_with_salary:
                try:
                    staff_salary = staff.salary
                    
                    # Get allowances and deductions
                    allowances = staff_salary.allowances.all()
                    deductions = staff_salary.deductions.all()
                    
                    # Calculate payroll
                    calc_result = PayrollCalculator.calculate_payroll(
                        staff_salary,
                        list(allowances),
                        list(deductions)
                    )
                    
                    # Create or update payroll entry
                    entry, created = PayrollEntry.objects.update_or_create(
                        payroll_period=period,
                        staff=staff,
                        defaults={
                            'organization': request.organization,
                            'staff_salary': staff_salary,
                            'basic_salary': calc_result['basic_salary'],
                            'total_allowances': calc_result['total_allowances'],
                            'gross_salary': calc_result['gross_salary'],
                            'nhif': calc_result['nhif'],
                            'nssf_employee': calc_result['nssf_employee'],
                            'nssf_employer': calc_result['nssf_employer'],
                            'paye': calc_result['paye'],
                            'other_deductions': calc_result['other_deductions'],
                            'total_deductions': calc_result['total_deductions'],
                            'net_salary': calc_result['net_salary'],
                        }
                    )
                    
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1
                    
                    # Create allowance items
                    PayrollAllowance.objects.filter(payroll_entry=entry).delete()
                    for allowance in allowances:
                        amount = calc_result['allowance_breakdown'].get(allowance.id, Decimal('0.00'))
                        PayrollAllowance.objects.create(
                            payroll_entry=entry,
                            allowance=allowance,
                            amount=amount
                        )
                    
                    # Create deduction items
                    PayrollDeduction.objects.filter(payroll_entry=entry).delete()
                    for deduction in deductions:
                        amount = calc_result['deduction_breakdown'].get(deduction.id, Decimal('0.00'))
                        PayrollDeduction.objects.create(
                            payroll_entry=entry,
                            deduction=deduction,
                            amount=amount
                        )
                
                except Exception as e:
                    logger.error(f"Error generating payroll for {staff.user.email}: {str(e)}", exc_info=True)
                    errors.append(f"{staff.user.full_name}: {str(e)}")
            
            if errors:
                messages.warning(request, f'Payroll generated with {len(errors)} errors. Created: {created_count}, Updated: {updated_count}')
            else:
                messages.success(request, f'Payroll generated successfully! Created: {created_count}, Updated: {updated_count}')
            
        except Exception as e:
            logger.error(f"Error generating payroll: {str(e)}", exc_info=True)
            messages.error(request, f'Error generating payroll: {str(e)}')
        
        return redirect('payroll:payroll_list', period_id=period_id)


class PayrollListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    """List payrolls by period."""
    model = PayrollEntry
    template_name = 'payroll/payroll_list.html'
    context_object_name = 'payroll_entries'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    paginate_by = 50
    
    def get_queryset(self):
        queryset = super().get_queryset().select_related('staff', 'staff__user', 'payroll_period', 'staff_salary')
        period_id = self.kwargs.get('period_id') or self.request.GET.get('period_id')
        if period_id:
            queryset = queryset.filter(payroll_period_id=period_id)
        return queryset.order_by('staff__staff_number')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        periods = PayrollPeriod.objects.filter(organization=self.request.organization).order_by('-period_year', '-period_month')
        context['periods'] = periods
        return context


class PayrollDetailView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, DetailView):
    """View payroll entry details."""
    model = PayrollEntry
    template_name = 'payroll/payroll_detail.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    
    def get_queryset(self):
        return super().get_queryset().select_related(
            'staff', 'staff__user', 'payroll_period', 'staff_salary'
        ).prefetch_related('allowance_items__allowance', 'deduction_items__deduction')


# ============== PAYSLIPS ==============

class PayslipListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    """List payslips."""
    model = Payslip
    template_name = 'payroll/payslip_list.html'
    context_object_name = 'payslips'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]
    paginate_by = 50
    
    def get_queryset(self):
        queryset = super().get_queryset().select_related(
            'payroll_entry', 'payroll_entry__staff', 'payroll_entry__staff__user', 'payroll_entry__payroll_period'
        )
        period_id = self.request.GET.get('period_id')
        if period_id:
            queryset = queryset.filter(payroll_entry__payroll_period_id=period_id)
        return queryset.order_by('-generated_at')


class PayslipGenerateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    """Generate payslips for a payroll period."""
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    
    def post(self, request, period_id):
        period = get_object_or_404(PayrollPeriod, pk=period_id, organization=request.organization)
        
        payroll_entries = PayrollEntry.objects.filter(
            payroll_period=period,
            organization=request.organization
        )
        
        generated_count = 0
        for entry in payroll_entries:
            # Create payslip if not exists
            payslip, created = Payslip.objects.get_or_create(
                payroll_entry=entry,
                defaults={
                    'organization': request.organization,
                    'generated_by': request.user,
                }
            )
            if created:
                generated_count += 1
        
        messages.success(request, f'Generated {generated_count} payslips for {period}.')
        return redirect('payroll:payslip_list')


class PayslipDetailView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, DetailView):
    """View payslip details."""
    model = Payslip
    template_name = 'payroll/payslip_detail.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]
    
    def get_queryset(self):
        return super().get_queryset().select_related(
            'payroll_entry', 'payroll_entry__staff', 'payroll_entry__staff__user',
            'payroll_entry__payroll_period', 'payroll_entry__staff_salary'
        ).prefetch_related(
            'payroll_entry__allowance_items__allowance',
            'payroll_entry__deduction_items__deduction'
        )


# ============== PAYROLL REPORTS ==============

class PayrollReportView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, TemplateView):
    """Payroll reports and analytics."""
    template_name = 'payroll/payroll_report.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        period_id = self.request.GET.get('period_id')
        
        if period_id:
            period = get_object_or_404(PayrollPeriod, pk=period_id, organization=self.request.organization)
            entries = PayrollEntry.objects.filter(
                payroll_period=period,
                organization=self.request.organization
            )
            
            context['period'] = period
            context['total_staff'] = entries.count()
            context['total_gross'] = entries.aggregate(Sum('gross_salary'))['gross_salary__sum'] or Decimal('0.00')
            context['total_deductions'] = entries.aggregate(Sum('total_deductions'))['total_deductions__sum'] or Decimal('0.00')
            context['total_net'] = entries.aggregate(Sum('net_salary'))['net_salary__sum'] or Decimal('0.00')
            context['total_nhif'] = entries.aggregate(Sum('nhif'))['nhif__sum'] or Decimal('0.00')
            context['total_nssf_employee'] = entries.aggregate(Sum('nssf_employee'))['nssf_employee__sum'] or Decimal('0.00')
            context['total_nssf_employer'] = entries.aggregate(Sum('nssf_employer'))['nssf_employer__sum'] or Decimal('0.00')
            context['total_paye'] = entries.aggregate(Sum('paye'))['paye__sum'] or Decimal('0.00')
            context['entries'] = entries
        
        periods = PayrollPeriod.objects.filter(organization=self.request.organization).order_by('-period_year', '-period_month')
        context['periods'] = periods
        
        return context
