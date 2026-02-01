# payroll/forms.py

from django import forms
from .models import (
    SalaryStructure, Allowance, Deduction, StaffSalary,
    PayrollPeriod, PayrollEntry
)


class SalaryStructureForm(forms.ModelForm):
    class Meta:
        model = SalaryStructure
        fields = ['name', 'code', 'basic_salary', 'description', 'is_active']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }


class AllowanceForm(forms.ModelForm):
    class Meta:
        model = Allowance
        fields = ['name', 'allowance_type', 'amount', 'is_percentage', 'percentage', 'is_taxable', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }


class DeductionForm(forms.ModelForm):
    class Meta:
        model = Deduction
        fields = ['name', 'deduction_type', 'amount', 'is_percentage', 'percentage', 'is_calculated', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }


class StaffSalaryForm(forms.ModelForm):
    class Meta:
        model = StaffSalary
        fields = ['staff', 'salary_structure', 'allowances', 'deductions', 'effective_date', 'end_date', 'notes']
        widgets = {
            'effective_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'allowances': forms.CheckboxSelectMultiple(),
            'deductions': forms.CheckboxSelectMultiple(),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }


class PayrollPeriodForm(forms.ModelForm):
    class Meta:
        model = PayrollPeriod
        fields = ['period_month', 'period_year', 'start_date', 'end_date']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }

