# payroll/admin.py

from django.contrib import admin
from .models import (
    SalaryStructure, Allowance, Deduction, StaffSalary,
    PayrollPeriod, PayrollEntry, PayrollAllowance, PayrollDeduction, Payslip
)


@admin.register(SalaryStructure)
class SalaryStructureAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'basic_salary', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'code']


@admin.register(Allowance)
class AllowanceAdmin(admin.ModelAdmin):
    list_display = ['name', 'allowance_type', 'amount', 'is_percentage', 'percentage', 'is_taxable']
    list_filter = ['allowance_type', 'is_percentage', 'is_taxable']
    search_fields = ['name']


@admin.register(Deduction)
class DeductionAdmin(admin.ModelAdmin):
    list_display = ['name', 'deduction_type', 'amount', 'is_percentage', 'percentage', 'is_calculated']
    list_filter = ['deduction_type', 'is_percentage', 'is_calculated']
    search_fields = ['name']


@admin.register(StaffSalary)
class StaffSalaryAdmin(admin.ModelAdmin):
    list_display = ['staff', 'salary_structure', 'effective_date', 'end_date']
    list_filter = ['effective_date', 'salary_structure']
    search_fields = ['staff__user__email', 'staff__staff_number']
    filter_horizontal = ['allowances', 'deductions']


@admin.register(PayrollPeriod)
class PayrollPeriodAdmin(admin.ModelAdmin):
    list_display = ['period_month', 'period_year', 'start_date', 'end_date', 'is_closed', 'created_at']
    list_filter = ['period_year', 'period_month', 'is_closed']
    search_fields = ['period_year']


@admin.register(PayrollEntry)
class PayrollEntryAdmin(admin.ModelAdmin):
    list_display = ['payroll_period', 'staff', 'gross_salary', 'total_deductions', 'net_salary']
    list_filter = ['payroll_period', 'created_at']
    search_fields = ['staff__user__email', 'staff__staff_number']


@admin.register(Payslip)
class PayslipAdmin(admin.ModelAdmin):
    list_display = ['payroll_entry', 'generated_at', 'generated_by', 'is_downloaded']
    list_filter = ['generated_at', 'is_downloaded']
    search_fields = ['payroll_entry__staff__user__email']
