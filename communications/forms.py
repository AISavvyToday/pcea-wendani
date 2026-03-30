from django import forms

from academics.models import Term
from core.models import GradeLevel
from students.models import Student


class PaymentReceiptTemplateForm(forms.Form):
    template_text = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 10}),
        help_text='Used automatically when payment receipts are sent. Supports placeholders like {student.name}, {payment.amount_plain}, and {receipt.link}.',
        label='Payment receipt SMS template',
    )


class SMSWorkflowForm(forms.Form):
    """Reusable form for balance reminder and invoice SMS workflows."""

    grade_levels = forms.MultipleChoiceField(
        choices=GradeLevel.choices,
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-control', 'size': 8}),
        help_text='Optional. Leave blank to include all grades.',
        label='Filter by grade(s)',
    )
    student_ids = forms.ModelMultipleChoiceField(
        queryset=Student.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-control', 'size': 12}),
        help_text='Optional. Leave blank to target all matching students.',
        label='Specific students',
    )
    term = forms.ModelChoiceField(
        queryset=Term.objects.none(),
        required=False,
        empty_label='Current term',
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='Term',
    )
    deadline_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        help_text='Optional. Overrides the payment deadline placeholder in the SMS preview/send.',
        label='Payment deadline',
    )
    template_text = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 6}),
        help_text='You can use placeholders like {parent.first_name}, {student.name}, {invoice.total_due}.',
        label='SMS template',
    )

    def __init__(self, *args, organization=None, default_template_text='', deadline_initial=None, **kwargs):
        super().__init__(*args, **kwargs)

        term_queryset = Term.objects.none()
        student_queryset = Student.objects.none()

        if organization is not None:
            term_queryset = Term.objects.filter(organization=organization).select_related('academic_year').order_by(
                '-academic_year__year', '-term'
            )
            student_queryset = Student.objects.filter(
                organization=organization,
                is_active=True,
                status='active',
            ).select_related('current_class').order_by('admission_number', 'first_name', 'last_name')

        self.fields['term'].queryset = term_queryset
        self.fields['student_ids'].queryset = student_queryset

        if not self.is_bound and default_template_text and not self.initial.get('template_text'):
            self.initial['template_text'] = default_template_text
        if not self.is_bound and deadline_initial and not self.initial.get('deadline_date'):
            self.initial['deadline_date'] = deadline_initial
