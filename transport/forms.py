# transport/forms.py
from django import forms
from decimal import Decimal
from .models import TransportRoute, TransportFee
from academics.models import AcademicYear
from core.models import TermChoices


class TransportRouteForm(forms.ModelForm):
    class Meta:
        model = TransportRoute
        fields = ['name', 'description', 'pickup_points', 'dropoff_points']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'required': True}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'pickup_points': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'One pickup point per line'}),
            'dropoff_points': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'One drop-off point per line'}),
        }


class TransportFeeForm(forms.ModelForm):
    class Meta:
        model = TransportFee
        fields = ['route', 'academic_year', 'term', 'amount', 'half_amount']
        widgets = {
            'route': forms.Select(attrs={'class': 'form-select', 'required': True}),
            'academic_year': forms.Select(attrs={'class': 'form-select', 'required': True}),
            'term': forms.Select(attrs={'class': 'form-select', 'required': True}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'required': True}),
            'half_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['route'].queryset = TransportRoute.objects.filter(is_active=True)
        self.fields['academic_year'].queryset = AcademicYear.objects.filter(is_active=True).order_by('-year')
        self.fields['term'].choices = TermChoices.choices

    def clean(self):
        cleaned_data = super().clean()
        route = cleaned_data.get('route')
        academic_year = cleaned_data.get('academic_year')
        term = cleaned_data.get('term')
        
        if route and academic_year and term:
            # Check for duplicate
            existing = TransportFee.objects.filter(
                route=route,
                academic_year=academic_year,
                term=term,
                is_active=True
            )
            if self.instance and self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            
            if existing.exists():
                raise forms.ValidationError(
                    f"A transport fee already exists for {route.name} - {academic_year.year} {term}. "
                    "Please edit the existing fee instead."
                )
        
        amount = cleaned_data.get('amount')
        half_amount = cleaned_data.get('half_amount')
        
        if amount and half_amount and half_amount > amount:
            raise forms.ValidationError("Half trip amount cannot be greater than full trip amount.")
        
        return cleaned_data

