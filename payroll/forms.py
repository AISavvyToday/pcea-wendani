from django import forms

from academics.models import Staff

from .models import (
    SalaryStructure,
    Allowance,
    Deduction,
    StaffSalary,
    PayrollPeriod,
)


def supported_staff_queryset(organization):
    queryset = Staff.objects.select_related('user').filter(
        organization=organization,
        user__organization=organization,
    )
    return queryset.order_by('staff_number')


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
    def __init__(self, *args, organization=None, **kwargs):
        self.organization = organization
        super().__init__(*args, **kwargs)

        if organization is not None:
            self.fields['staff'].queryset = supported_staff_queryset(organization)
            self.fields['salary_structure'].queryset = SalaryStructure.objects.filter(organization=organization)
            self.fields['allowances'].queryset = Allowance.objects.filter(organization=organization)
            self.fields['deductions'].queryset = Deduction.objects.filter(organization=organization)

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

    def clean_staff(self):
        staff = self.cleaned_data['staff']
        if self.organization and (
            staff.organization_id != self.organization.id or
            staff.user.organization_id != self.organization.id
        ):
            raise forms.ValidationError('Selected staff member is not available for this organization payroll workflow.')
        return staff


class PayrollPeriodForm(forms.ModelForm):
    class Meta:
        model = PayrollPeriod
        fields = ['period_month', 'period_year', 'start_date', 'end_date']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }
