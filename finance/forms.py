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
from academics.models import AcademicYear, Term, TransportRoute, TransportFee
from students.models import Student, Parent
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
        ('mobile_money', 'Mobile Money'),
        ('bank_deposit', 'Bank Deposit'),
        ('cheque', 'Cheque'),
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
            # Set initial student value
            try:
                self.fields['student'].initial = student_id
            except Exception:
                pass

            # Filter invoices for this student
            self.fields['invoice'].queryset = Invoice.objects.filter(
                student_id=student_id,
                is_active=True,
                balance__gt=0
            ).order_by('-issue_date')

        if invoice_id:
            try:
                self.fields['invoice'].initial = invoice_id
            except Exception:
                pass


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
        widget=forms.Select(attrs={'class': 'form-select transport-route'})
    )
    transport_trip_type = forms.ChoiceField(
        choices=InvoiceItem.TRIP_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select transport-trip-type'})
    )

    class Meta:
        model = InvoiceItem
        fields = ['description', 'category', 'amount', 'discount_applied', 'transport_route', 'transport_trip_type']
        widgets = {
            'description': forms.TextInput(attrs={'class': 'form-control item-description'}),
            'category': forms.Select(
                attrs={'class': 'form-select item-category', 'onchange': 'toggleTransportFields(this)'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control item-amount', 'step': '0.01'}),
            'discount_applied': forms.NumberInput(attrs={'class': 'form-control item-discount', 'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        # Get invoice from kwargs if available
        self.invoice = kwargs.pop('invoice', None)
        super().__init__(*args, **kwargs)

        # If we have an invoice, filter transport routes with fees for this term
        if self.invoice and self.invoice.term:
            from django.db.models import Case, When, Value, F
            from django.db.models.functions import Concat

            # Get transport fees for this term
            transport_fees = TransportFee.objects.filter(
                academic_year=self.invoice.term.academic_year,
                term=self.invoice.term.term,
                is_active=True
            ).select_related('route')

            # Create a mapping of route IDs to fee info for JavaScript
            self.fee_info = {}
            for tf in transport_fees:
                half_amount = tf.half_amount if tf.half_amount is not None else tf.amount / 2
                self.fee_info[str(tf.route.id)] = {
                    'full': float(tf.amount),
                    'half': float(half_amount),
                    'full_display': f"KES {tf.amount}",
                    'half_display': f"KES {half_amount}"
                }

            # Get routes that have fees configured for this term
            routes_with_fees = TransportRoute.objects.filter(
                id__in=[tf.route.id for tf in transport_fees]
            ).distinct()

            # Create enhanced choices with fee information
            route_choices = [('', '--------')]
            for route in routes_with_fees:
                fee = next((tf for tf in transport_fees if tf.route.id == route.id), None)
                if fee:
                    half_amount = fee.half_amount if fee.half_amount is not None else fee.amount / 2
                    label = f"{route.name} (Full: KES {fee.amount} | Half: KES {half_amount})"
                else:
                    label = f"{route.name} (No fee configured)"
                route_choices.append((route.id, label))

            self.fields['transport_route'].choices = route_choices
            self.fields['transport_route'].queryset = routes_with_fees

            # Set initial transport trip type to full if not set
            if self.instance and self.instance.category == 'transport' and not self.instance.transport_trip_type:
                self.initial['transport_trip_type'] = 'full'

        # Set up widget attributes for JavaScript
        if self.instance and self.instance.category == 'transport':
            self.fields['transport_route'].widget.attrs.update({
                'data-initial-value': str(self.instance.transport_route.id) if self.instance.transport_route else ''
            })
            self.fields['transport_trip_type'].widget.attrs.update({
                'data-initial-value': self.instance.transport_trip_type or 'full'
            })

    def clean(self):
        cleaned = super().clean()
        category = cleaned.get('category')
        amount = cleaned.get('amount')
        transport_route = cleaned.get('transport_route')
        transport_trip_type = cleaned.get('transport_trip_type')

        if category == 'transport':
            # For transport items, amount can be auto-calculated if route is selected
            if transport_route and not amount:
                # Amount will be auto-calculated in the view
                pass
            elif transport_route and transport_trip_type and self.invoice:
                # Try to get the fee for display purposes
                try:
                    tf = TransportFee.objects.get(
                        route=transport_route,
                        academic_year=self.invoice.term.academic_year,
                        term=self.invoice.term.term,
                        is_active=True
                    )
                    # Just validate, don't set amount here - view will handle it
                except TransportFee.DoesNotExist:
                    if not amount or amount == Decimal('0.00'):
                        self.add_error('transport_route',
                                       'No transport fee configured for this route in the current term.')
        else:
            # For non-transport items ensure amount is present and non-negative
            if amount in (None, ''):
                self.add_error('amount', 'Amount is required for non-transport items.')
            elif amount is not None and amount < Decimal('0.00'):
                self.add_error('amount', 'Amount must be a non-negative number.')

        return cleaned


InvoiceItemFormSet = inlineformset_factory(
    Invoice, InvoiceItem, form=InvoiceItemForm,
    extra=0, can_delete=True, min_num=0, validate_min=False
)


class FamilyPaymentForm(forms.Form):
    """Form for recording a single payment for a parent with multiple children."""

    parent = forms.ModelChoiceField(
        queryset=Parent.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-control select2'}),
        help_text="Select parent/guardian making the payment"
    )

    amount = forms.DecimalField(
        min_value=Decimal('0.01'),
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
        help_text="Total payment amount to distribute across children"
    )

    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('mpesa', 'M-Pesa'),
    ]
    payment_method = forms.ChoiceField(
        choices=PAYMENT_METHOD_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    PAYMENT_SOURCE_CHOICES = [
        ('equity_bank', 'Equity Bank'),
        ('coop_bank', 'Co-operative Bank'),
        ('mpesa', 'Mpesa'),
        ('cash_office', 'Cash Office'),
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
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., M-PESA code'}),
        help_text="External reference (M-PESA code, cheque number, etc.)"
    )

    payer_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text="Name of person making payment"
    )

    payer_phone = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '0712345678'})
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2})
    )