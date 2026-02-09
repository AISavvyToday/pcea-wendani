# reports/forms.py

from django import forms
from django.utils import timezone
from academics.models import AcademicYear, TermChoices
from transport.models import TransportRoute
from core.models import PaymentSource

class InvoiceReportFilterForm(forms.Form):
    academic_year = forms.ModelChoiceField(
        queryset=AcademicYear.objects.all(), 
        required=False, 
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label="Select Academic Year"
    )
    term = forms.ChoiceField(
        choices=[('', 'Select Term')] + list(TermChoices.choices), 
        required=False, 
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    student_class = forms.ChoiceField(
        required=False,
        choices=[('', 'All Classes')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Student name'}),
        label='Student Name'
    )
    admission = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Admission number'}),
        label='Admission Number'
    )
    category = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Category (from description)'}),
        label='Category'
    )
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    show_all = forms.BooleanField(
        required=False,
        initial=False,
        label="Show all (no filters)"
    )


# reports/forms.py
from django import forms
from django.utils import timezone

class FeesCollectionFilterForm(forms.Form):
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        initial=lambda: timezone.now().replace(day=1).date()
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        initial=lambda: timezone.now().date()
    )
    payment_source = forms.ChoiceField(
        required=False,
        choices=[('', 'All Payment Sources')] + list(PaymentSource.choices),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Payment Source'
    )
    student_class = forms.ChoiceField(
        required=False,
        choices=[('', 'All Classes')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    GROUP_BY_CHOICES = [
        ('none', 'List (no grouping)'),
        ('class', 'Group by Class'),
        ('date', 'Group by Date'),
    ]
    group_by = forms.ChoiceField(
        required=False,
        choices=GROUP_BY_CHOICES,
        initial='none',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    show_all = forms.BooleanField(required=False, initial=True, label="Include all payments (no class filter)")



BALANCE_OPERATOR_CHOICES = [
    ('any', 'Any'),
    ('=', '='),
    ('>', '>'),
    ('<', '<'),
    ('>=', '>='),
    ('<=', '<='),
]

class OutstandingBalancesFilterForm(forms.Form):
    # Allow date range OR academic_year+term selection
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='From'
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='To'
    )

    academic_year = forms.ModelChoiceField(
        queryset=AcademicYear.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Academic Year'
    )
    term = forms.ChoiceField(
        choices=TermChoices.choices,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Term'
    )

    student_class = forms.ChoiceField(
        required=False,
        choices=[('', 'All Classes')],
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Class'
    )

    balance_operator = forms.ChoiceField(
        required=False,
        choices=BALANCE_OPERATOR_CHOICES,
        initial='any',
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Balance Filter'
    )
    balance_amount = forms.DecimalField(
        required=False,
        decimal_places=2,
        max_digits=12,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        label='Amount'
    )

    show_zero_balances = forms.BooleanField(
        required=False,
        initial=False,
        label='Include zero balances'
    )



class TransportReportFilterForm(forms.Form):
    academic_year = forms.ModelChoiceField(
        queryset=AcademicYear.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label="Select Academic Year"
    )
    term = forms.ChoiceField(
        choices=[('', 'Select Term')] + list(TermChoices.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    route = forms.ModelChoiceField(
        queryset=TransportRoute.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label='All Routes'
    )
    student_class = forms.ChoiceField(
        required=False,
        choices=[('', 'All Classes')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    show_zero_rows = forms.BooleanField(required=False, initial=False, label='Include zero rows')


class OtherItemsReportFilterForm(forms.Form):
    academic_year = forms.ModelChoiceField(
        queryset=AcademicYear.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label="Select Academic Year"
    )
    term = forms.ChoiceField(
        choices=[('', 'Select Term')] + list(TermChoices.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    student_class = forms.ChoiceField(
        required=False,
        choices=[('', 'All Classes')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Student name'}),
        label='Student Name'
    )
    admission = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Admission number'}),
        label='Admission Number'
    )
    category = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Category (from description)'}),
        label='Category'
    )
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    show_all = forms.BooleanField(
        required=False,
        initial=False,
        label="Show all (no filters)"
    )


class TransferredStudentsFilterForm(forms.Form):
    academic_year = forms.ModelChoiceField(
        queryset=AcademicYear.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label="Select Academic Year",
        label='Academic Year'
    )
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='Transfer Date From'
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='Transfer Date To'
    )
    student_class = forms.ChoiceField(
        required=False,
        choices=[('', 'All Classes')],
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Class/Grade'
    )


class GraduatedStudentsFilterForm(forms.Form):
    academic_year = forms.ModelChoiceField(
        queryset=AcademicYear.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label="Select Academic Year",
        label='Academic Year'
    )
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='Graduation Date From'
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='Graduation Date To'
    )
    student_class = forms.ChoiceField(
        required=False,
        choices=[('', 'All Classes')],
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Class/Grade'
    )


class AdmittedStudentsFilterForm(forms.Form):
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='Admission Date From',
        initial=lambda: timezone.now().replace(month=1, day=1).date()
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='Admission Date To',
        initial=lambda: timezone.now().date()
    )
    student_class = forms.ChoiceField(
        required=False,
        choices=[('', 'All Classes')],
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Class/Grade'
    )