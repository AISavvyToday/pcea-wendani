# other_income/forms.py
from django import forms
from django.forms import inlineformset_factory
from decimal import Decimal

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