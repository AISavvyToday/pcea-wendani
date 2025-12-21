# reports/forms.py

from academics.models import AcademicYear, TermChoices, TransportRoute

from django import forms
from django.utils import timezone
from academics.models import AcademicYear, TermChoices

class InvoiceReportFilterForm(forms.Form):
    academic_year = forms.ModelChoiceField(queryset=AcademicYear.objects.all(), required=True, widget=forms.Select(attrs={'class': 'form-select'}))
    term = forms.ChoiceField(choices=TermChoices.choices, required=True, widget=forms.Select(attrs={'class': 'form-select'}))
    show_zero_rows = forms.BooleanField(required=False, initial=False, label="Show categories with zero billed")


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
    student_class = forms.ChoiceField(
        required=False,
        choices=[('', 'All Classes')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    bank = forms.ChoiceField(
        required=False,
        choices=[('', 'All Banks')],
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
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    term = forms.ChoiceField(
        choices=TermChoices.choices,
        required=True,
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