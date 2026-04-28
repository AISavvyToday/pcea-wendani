# other_income/forms.py
from django import forms
from django.forms import inlineformset_factory
from decimal import Decimal
from django.db.models import Q

from academics.models import AcademicYear, Term
from .models import OtherIncomeInvoice, OtherIncomeItem, OtherIncomePayment


class OtherIncomeInvoiceForm(forms.ModelForm):
    class Meta:
        model = OtherIncomeInvoice
        fields = ['client_name', 'client_contact', 'description', 'issue_date', 'due_date']
        widgets = {
            'client_name': forms.TextInput(attrs={'class': 'form-control'}),
            'client_contact': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'issue_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'due_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }


class OtherIncomeItemForm(forms.ModelForm):
    class Meta:
        model = OtherIncomeItem
        fields = ['description', 'amount']
        widgets = {
            'description': forms.TextInput(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }


OtherIncomeItemFormSet = inlineformset_factory(
    OtherIncomeInvoice,
    OtherIncomeItem,
    form=OtherIncomeItemForm,
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True
)


class OtherIncomePaymentForm(forms.ModelForm):
    class Meta:
        model = OtherIncomePayment
        fields = ['amount', 'payment_method', 'payment_date', 'payer_name', 'payer_contact', 'transaction_reference']
        widgets = {
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'payment_method': forms.TextInput(attrs={'class': 'form-control'}),
            'payment_date': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'payer_name': forms.TextInput(attrs={'class': 'form-control'}),
            'payer_contact': forms.TextInput(attrs={'class': 'form-control'}),
            'transaction_reference': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def clean_amount(self):
        amt = self.cleaned_data.get('amount')
        if amt is None or amt <= Decimal('0.00'):
            raise forms.ValidationError("Amount must be greater than zero.")
        return amt


class OtherIncomeReportStagingFilterForm(forms.Form):
    """
    Staging filter set for the upcoming other-income reports.

    These filters deliberately stick to dimensions that already exist in the
    current domain model so the same rules can later be reused for HTML, Excel,
    and PDF outputs once the business template is confirmed.
    """

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Invoice #, client, or reference'}),
        label='Search'
    )
    academic_year = forms.ModelChoiceField(
        required=False,
        queryset=AcademicYear.objects.none(),
        empty_label='All academic years',
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Academic Year'
    )
    term = forms.ModelChoiceField(
        required=False,
        queryset=Term.objects.none(),
        empty_label='All terms',
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Term'
    )
    status = forms.ChoiceField(
        required=False,
        choices=[('', 'All statuses')] + list(OtherIncomeInvoice.STATUS_CHOICES),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Invoice Status'
    )
    issue_date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='Issue Date From'
    )
    issue_date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='Issue Date To'
    )
    due_date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='Due Date From'
    )
    due_date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='Due Date To'
    )
    payment_date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='Payment Date From'
    )
    payment_date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label='Payment Date To'
    )
    payment_method = forms.ChoiceField(
        required=False,
        choices=[('', 'All payment methods')],
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Payment Method'
    )

    def __init__(self, *args, **kwargs):
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        academic_years = AcademicYear.objects.all()
        terms = Term.objects.select_related('academic_year')
        payments = OtherIncomePayment.objects.filter(is_active=True)

        if organization:
            academic_years = academic_years.filter(Q(organization=organization) | Q(organization__isnull=True))
            terms = terms.filter(Q(organization=organization) | Q(organization__isnull=True))
            payments = payments.filter(
                Q(invoice__organization=organization) | Q(invoice__organization__isnull=True)
            )

        self.fields['academic_year'].queryset = academic_years.order_by('-year')

        selected_year = (
            self.data.get(self.add_prefix('academic_year'))
            or self.initial.get('academic_year')
        )
        if hasattr(selected_year, 'pk'):
            selected_year = selected_year.pk
        if selected_year:
            terms = terms.filter(academic_year_id=selected_year)
        self.fields['term'].queryset = terms.order_by('-academic_year__year', '-start_date', 'term')

        payment_methods = [
            method for method in
            payments
            .exclude(payment_method='')
            .values_list('payment_method', flat=True)
            .distinct()
            .order_by('payment_method')
        ]
        self.fields['payment_method'].choices = [('', 'All payment methods')] + [
            (method, method.replace('_', ' ').title()) for method in payment_methods
        ]

    def clean(self):
        cleaned_data = super().clean()
        term = cleaned_data.get('term')
        academic_year = cleaned_data.get('academic_year')
        if term and academic_year is None:
            cleaned_data['academic_year'] = term.academic_year
        return cleaned_data
