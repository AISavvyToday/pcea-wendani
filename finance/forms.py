# finance/forms.py
"""
Finance module forms for fee structures, invoices, payments, and discounts.
"""

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from decimal import Decimal

from django.forms import inlineformset_factory

from .models import FeeStructure, FeeItem, Discount, StudentDiscount, Invoice, InvoiceItem
from academics.models import AcademicYear, Term, TransportRoute
from students.models import Student
from core.models import FeeCategory, GradeLevel, TermChoices


class FeeStructureForm(forms.ModelForm):
    """Form for creating/editing fee structures."""

    grade_levels = forms.MultipleChoiceField(
        choices=GradeLevel.choices,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        required=True,
        help_text="Select grade levels this fee structure applies to"
    )

    class Meta:
        model = FeeStructure
        fields = ['name', 'academic_year', 'term', 'grade_levels', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Grade 1-3 Term 1 Fees 2025'}),
            'academic_year': forms.Select(attrs={'class': 'form-control'}),
            'term': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['academic_year'].queryset = AcademicYear.objects.filter(is_active=True).order_by('-year')

        if self.instance.pk and self.instance.grade_levels:
            self.initial['grade_levels'] = self.instance.grade_levels


class FeeItemForm(forms.ModelForm):
    """Form for fee items within a fee structure."""

    class Meta:
        model = FeeItem
        fields = ['category', 'description', 'amount']
        widgets = {
            'category': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Tuition Fee'}),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'step': '0.01',
                'placeholder': 'Enter amount'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set amount field as not required initially
        self.fields['amount'].required = False

    def clean(self):
        """Custom validation for fee items."""
        cleaned_data = super().clean()
        category = cleaned_data.get('category')
        amount = cleaned_data.get('amount')

        # Skip validation for empty forms (formset will handle these)
        is_empty = not any(cleaned_data.values())
        if is_empty:
            return cleaned_data

        # Handle transport items
        if category == 'transport':
            # Set amount to 0 for transport items
            cleaned_data['amount'] = Decimal('0.00')
        else:
            # For non-transport items, amount is required
            if amount is None:
                self.add_error('amount', 'This field is required.')
            elif amount < Decimal('0.00'):
                self.add_error('amount', 'Amount must be a positive number.')

        return cleaned_data

    def clean_amount(self):
        """Clean amount field."""
        amount = self.cleaned_data.get('amount')

        # If amount is empty string or None, return None
        if amount in [None, '']:
            return None

        # If it's already a decimal, return it
        if isinstance(amount, Decimal):
            return amount

        # Try to convert to Decimal
        try:
            return Decimal(str(amount))
        except (ValueError, TypeError):
            return None

FeeItemFormSet = forms.inlineformset_factory(
    FeeStructure,
    FeeItem,
    form=FeeItemForm,
    extra=1,  # Start with just 1 empty form instead of 5
    can_delete=True,
    min_num=1,
    validate_min=True
)


class DiscountForm(forms.ModelForm):
    """Form for creating/editing discounts."""

    applicable_categories = forms.MultipleChoiceField(
        choices=FeeCategory.choices,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        required=False,
        help_text="Leave empty to apply to all categories"
    )

    class Meta:
        model = Discount
        fields = ['name', 'discount_type', 'value', 'applicable_categories',
                  'academic_year', 'description', 'requires_approval']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Sibling Discount'}),
            'discount_type': forms.Select(attrs={'class': 'form-control'}),
            'value': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '0.01'}),
            'academic_year': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'requires_approval': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['academic_year'].queryset = AcademicYear.objects.filter(is_active=True).order_by('-year')
        self.fields['academic_year'].required = False

        if self.instance.pk and self.instance.applicable_categories:
            self.initial['applicable_categories'] = self.instance.applicable_categories

    def clean(self):
        cleaned_data = super().clean()
        discount_type = cleaned_data.get('discount_type')
        value = cleaned_data.get('value')

        if discount_type == 'percentage' and value and value > 100:
            raise ValidationError({'value': 'Percentage discount cannot exceed 100%'})

        return cleaned_data


class StudentDiscountForm(forms.ModelForm):
    """Form for assigning discounts to students."""

    student = forms.ModelChoiceField(
        queryset=Student.objects.filter(is_active=True, status='active'),
        widget=forms.Select(attrs={'class': 'form-control select2'}),
        help_text="Select student to assign discount"
    )

    class Meta:
        model = StudentDiscount
        fields = ['student', 'discount', 'custom_value', 'start_date', 'end_date', 'reason']
        widgets = {
            'discount': forms.Select(attrs={'class': 'form-control'}),
            'custom_value': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '0.01'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['discount'].queryset = Discount.objects.filter(is_active=True)
        self.fields['custom_value'].required = False
        self.fields['end_date'].required = False


class InvoiceGenerateForm(forms.Form):
    """Form for bulk invoice generation (NO OVERWRITE)."""

    term = forms.ModelChoiceField(
        queryset=Term.objects.none(),
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text="Select term to generate invoices for"
    )

    grade_levels = forms.MultipleChoiceField(
        choices=GradeLevel.choices,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        required=False,
        help_text="Leave empty to generate for all grades"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['term'].queryset = Term.objects.filter(
            is_active=True
        ).select_related('academic_year').order_by('-academic_year__year', '-term')


class PaymentRecordForm(forms.Form):
    """Form for manually recording payments."""

    student = forms.ModelChoiceField(
        queryset=Student.objects.filter(is_active=True, status='active'),
        widget=forms.Select(attrs={'class': 'form-control select2'}),
        help_text="Select student"
    )

    invoice = forms.ModelChoiceField(
        queryset=Invoice.objects.none(),
        widget=forms.Select(attrs={'class': 'form-control'}),
        required=False,
        help_text="Select invoice (optional - will use most recent if not selected)"
    )

    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0.01'),
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '0.01', 'step': '0.01'}),
        help_text="Payment amount in KES"
    )

    PAYMENT_METHOD_CHOICES = [

        ('mpesa', 'M-PESA'),
        ('equity_bank', 'Equity Bank'),
        ('coop_bank', 'Co-operative Bank'),
        ('manual_entry', 'Manual Entry'),
        ('cheque', 'Cheque'),
        ('bank_transfer', 'Bank Transfer')

    ]


    payment_method = forms.ChoiceField(
        choices=PAYMENT_METHOD_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    PAYMENT_SOURCE_CHOICES = [
        ('equity_bank', 'Equity Bank'),
        ('coop_bank', 'Co-operative Bank'),
        ('mpesa', 'Mpesa')
    ]
    payment_source = forms.ChoiceField(
        choices=PAYMENT_SOURCE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )


    payment_date = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
        help_text="Date and time of payment"
    )

    transaction_reference = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., M-PESA code, cheque number'}),
        help_text="External reference (M-PESA code, cheque number, etc.)"
    )

    payer_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text="Name of person making payment (if different from parent)"
    )

    payer_phone = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '0712345678'}),
        help_text="Phone number of payer"
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        help_text="Additional notes"
    )

    def __init__(self, *args, **kwargs):
        # Extract custom arguments before calling super()
        student_id = kwargs.pop('student_id', None)
        invoice_id = kwargs.pop('invoice_id', None)
        super().__init__(*args, **kwargs)

        if student_id:
            self.fields['invoice'].queryset = Invoice.objects.filter(
                student_id=student_id,
                is_active=True,
                balance__gt=0
            ).order_by('-issue_date')


class BankTransactionMatchForm(forms.Form):
    """Form for manually matching bank transactions to students."""

    student = forms.ModelChoiceField(
        queryset=Student.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-control select2'}),
        help_text="Select student to match this transaction to"
    )

    invoice = forms.ModelChoiceField(
        queryset=Invoice.objects.none(),
        widget=forms.Select(attrs={'class': 'form-control'}),
        required=False,
        help_text="Select specific invoice (optional)"
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        help_text="Notes about this manual match"
    )


class DateRangeFilterForm(forms.Form):
    """Form for filtering by date range."""

    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )

    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )

    term = forms.ModelChoiceField(
        queryset=Term.objects.filter(is_active=True),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )


class InvoiceEditForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ['notes', 'due_date']
        widgets = {
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'due_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

class InvoiceItemForm(forms.ModelForm):
    # show transport fields
    transport_route = forms.ModelChoiceField(
        queryset=TransportRoute.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    transport_trip_type = forms.ChoiceField(
        choices=InvoiceItem.TRIP_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = InvoiceItem
        fields = ['description', 'category', 'amount', 'discount_applied', 'transport_route', 'transport_trip_type']
        widgets = {
            'description': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'discount_applied': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

    def clean(self):
        cleaned = super().clean()
        category = cleaned.get('category')
        # If category is transport and route/trip_type provided, amount may be left blank — handle later in view
        amount = cleaned.get('amount')
        if category != 'transport':
            # For non-transport items ensure amount is present and non-negative
            if amount in (None, ''):
                self.add_error('amount', 'Amount is required for non-transport items.')
            elif amount is not None and amount < Decimal('0.00'):
                self.add_error('amount', 'Amount must be a non-negative number.')
        else:
            # If transport, allow amount to be empty; view will populate it based on transport fee.
            if (not cleaned.get('transport_route')) or (not cleaned.get('transport_trip_type')):
                # It's valid to have an empty transport item (user might want to enter amount manually)
                pass

        return cleaned


InvoiceItemFormSet = inlineformset_factory(
    Invoice, InvoiceItem, form=InvoiceItemForm,
    extra=1, can_delete=True, min_num=1, validate_min=False
)