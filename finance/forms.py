# finance/forms.py
"""
Finance module forms for fee structures, invoices, payments, and discounts.
"""

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from decimal import Decimal

from .models import FeeStructure, FeeItem, Discount, StudentDiscount, Invoice
from academics.models import AcademicYear, Term
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
        fields = ['name', 'academic_year', 'term', 'grade_levels', 'is_boarding', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Grade 1-3 Term 1 Fees 2025'}),
            'academic_year': forms.Select(attrs={'class': 'form-control'}),
            'term': forms.Select(attrs={'class': 'form-control'}),
            'is_boarding': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
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
        fields = ['category', 'description', 'amount', 'is_optional', 'applies_to_all']
        widgets = {
            'category': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Tuition Fee'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '0.01'}),
            'is_optional': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'applies_to_all': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


FeeItemFormSet = forms.inlineformset_factory(
    FeeStructure,
    FeeItem,
    form=FeeItemForm,
    extra=5,
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
    """Form for bulk invoice generation."""

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

    include_balance_bf = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        help_text="Include balance brought forward from previous term"
    )

    overwrite_existing = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        help_text="Overwrite existing invoices (use with caution)"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['term'].queryset = Term.objects.filter(
            is_active=True
        ).select_related('academic_year').order_by('-academic_year__year', '-term_number')


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
        ('cash', 'Cash'),
        ('cheque', 'Cheque'),
        ('bank_transfer', 'Bank Transfer'),
        ('mpesa', 'M-PESA'),
    ]

    payment_method = forms.ChoiceField(
        choices=PAYMENT_METHOD_CHOICES,
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
        student_id = kwargs.pop('student_id', None)
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