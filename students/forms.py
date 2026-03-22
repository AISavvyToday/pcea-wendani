import logging

from django import forms
from django.core.exceptions import ValidationError

from academics.models import Class
from core.models import GradeLevel, StreamChoices
from .models import Club, Parent, Student

logger = logging.getLogger(__name__)


class GroupedClassModelChoiceField(forms.ModelChoiceField):
    """Show classes grouped by grade level and stream for easier stream-aware selection."""

    def label_from_instance(self, obj):
        return f"{obj.name} ({obj.academic_year.year})"

    @property
    def choices(self):
        blank_choice = [('', self.empty_label)] if self.empty_label is not None else []
        grouped_choices = []
        grouped = {}

        for class_obj in self.queryset:
            group_label = f"{class_obj.get_grade_level_display()} • {class_obj.get_stream_display()}"
            grouped.setdefault(group_label, []).append(
                (self.prepare_value(class_obj), self.label_from_instance(class_obj))
            )

        for group_label, group_options in grouped.items():
            grouped_choices.append((group_label, group_options))

        return blank_choice + grouped_choices


class StudentForm(forms.ModelForm):
    """Form for creating/editing student records."""

    current_class = GroupedClassModelChoiceField(
        queryset=Class.objects.none(),
        required=True,
        empty_label="Select class by grade and stream",
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='Current Grade / Stream',
    )
    clubs = forms.ModelMultipleChoiceField(
        queryset=Club.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-control', 'size': 6}),
        help_text='Optional: assign the student to one or more clubs.',
    )

    class Meta:
        model = Student
        fields = [
            'admission_number',
            'admission_date',
            'first_name',
            'middle_name',
            'last_name',
            'gender',
            'date_of_birth',
            'birth_certificate_number',
            'photo',
            'current_class',
            'clubs',
            'blood_group',
            'medical_conditions',
            'emergency_contact_name',
            'emergency_contact_phone',
            'previous_school',
            'previous_class',
            'status',
            'status_reason',
            'has_special_needs',
            'special_needs_details',
            'uses_school_transport',
            'transport_route',
            'transport_pickup_person',
            'upi_number',
            'assessment_number',
            'residence',
        ]
        widgets = {
            'admission_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'}),
            'middle_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Middle Name (Optional)'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name'}),
            'gender': forms.Select(attrs={'class': 'form-control'}),
            'date_of_birth': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'birth_certificate_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Birth Certificate Number'}),
            'photo': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'blood_group': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., A+, O-, B+'}),
            'medical_conditions': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Any allergies, chronic conditions, etc.'}),
            'emergency_contact_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Emergency Contact Name'}),
            'emergency_contact_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+254...'}),
            'previous_school': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Previous School Name'}),
            'previous_class': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Grade 8'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'status_reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Reason for status change (required if changing from Active)'}),
            'has_special_needs': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'special_needs_details': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Describe special needs'}),
            'uses_school_transport': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'transport_route': forms.Select(attrs={'class': 'form-control'}),
            'transport_pickup_person': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Person authorized to pick up from bus'}),
            'upi_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Unique Pupil Identifier'}),
            'assessment_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Assessment/Exam Number'}),
            'residence': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Residence area/estate'}),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        instance = kwargs.get('instance')
        is_new_student = instance is None or instance._state.adding

        super().__init__(*args, **kwargs)

        class_queryset = Class.objects.select_related('academic_year').order_by(
            'grade_level', 'stream', 'name', '-academic_year__year'
        )
        club_queryset = Club.objects.order_by('name')
        if self.organization:
            class_queryset = class_queryset.filter(organization=self.organization)
            club_queryset = club_queryset.filter(organization=self.organization)

        self.fields['current_class'].queryset = class_queryset
        self.fields['clubs'].queryset = club_queryset
        self.fields['current_class'].help_text = 'Classes are grouped by grade and stream so the stream is always visible.'

        is_saved = bool(self.instance.pk and not self.instance._state.adding)
        if is_saved:
            self.fields['admission_number'].required = True
            self.fields['admission_number'].widget = forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': 'e.g., 2025001'}
            )
            self.fields['admission_number'].initial = self.instance.admission_number
        else:
            from .services import StudentService

            if not self.instance.admission_number:
                self.instance.admission_number = StudentService.generate_admission_number(
                    organization=self.organization or self.instance.organization
                )

            self.fields['admission_number'].required = False
            self.fields['admission_number'].widget = forms.HiddenInput()
            self.fields['admission_number'].initial = self.instance.admission_number

            if self.is_bound and 'admission_number' not in self.data:
                self.data = self.data.copy()
                self.data['admission_number'] = self.instance.admission_number

            self.fields['status'].initial = 'active'
            self.fields['status'].widget = forms.HiddenInput()
            self.fields['status_reason'].widget = forms.HiddenInput()

        optional_fields = [
            'middle_name', 'birth_certificate_number', 'photo', 'clubs',
            'blood_group', 'medical_conditions', 'emergency_contact_name',
            'emergency_contact_phone', 'previous_school', 'previous_class',
            'status_reason', 'special_needs_details', 'transport_route',
            'transport_pickup_person', 'upi_number', 'assessment_number', 'residence'
        ]
        for field in optional_fields:
            if field in self.fields:
                self.fields[field].required = False

        if is_new_student and not self.initial.get('current_class') and class_queryset.count() == 1:
            self.fields['current_class'].initial = class_queryset.first()

    def clean_admission_number(self):
        admission_number = self.cleaned_data.get('admission_number')

        if not self.instance.pk:
            if not admission_number:
                from .services import StudentService
                admission_number = StudentService.generate_admission_number(
                    organization=self.organization or self.instance.organization
                )
            return admission_number

        if admission_number:
            duplicate = Student.objects.filter(admission_number=admission_number).exclude(pk=self.instance.pk)
            if duplicate.exists():
                raise ValidationError('A student with this admission number already exists.')

        return admission_number

    def clean_current_class(self):
        current_class = self.cleaned_data.get('current_class')
        if current_class and self.organization and current_class.organization_id != self.organization.id:
            raise ValidationError('Please choose a class from your organization.')
        return current_class

    def clean(self):
        cleaned_data = super().clean()

        uses_transport = cleaned_data.get('uses_school_transport')
        transport_route = cleaned_data.get('transport_route')
        if uses_transport and not transport_route:
            self.add_error('transport_route', 'Transport route is required when using school transport.')

        has_special_needs = cleaned_data.get('has_special_needs')
        special_needs_details = cleaned_data.get('special_needs_details')
        if has_special_needs and not special_needs_details:
            self.add_error('special_needs_details', 'Please provide details about special needs.')

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not instance.admission_number:
            from .services import StudentService

            instance.admission_number = StudentService.generate_admission_number(
                organization=self.organization or instance.organization
            )

        if commit:
            instance.save()
            self.save_m2m()
        return instance


class ParentForm(forms.ModelForm):
    """Form for creating/editing parent/guardian records."""

    class Meta:
        model = Parent
        fields = [
            'first_name',
            'last_name',
            'gender',
            'id_number',
            'phone_primary',
            'phone_secondary',
            'email',
            'address',
            'town',
            'occupation',
            'employer',
            'relationship',
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name'}),
            'gender': forms.Select(attrs={'class': 'form-control'}),
            'id_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'National ID Number'}),
            'phone_primary': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+254712345678'}),
            'phone_secondary': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+254712345678 (Optional)'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@example.com'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Physical Address'}),
            'town': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Town/City'}),
            'occupation': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Occupation'}),
            'employer': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Employer Name'}),
            'relationship': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = False
        self.fields['last_name'].required = False
        self.fields['phone_primary'].required = False
        self.fields['relationship'].required = False

    def clean(self):
        cleaned_data = super().clean()
        first_name = cleaned_data.get('first_name', '').strip()
        last_name = cleaned_data.get('last_name', '').strip()
        phone_primary = cleaned_data.get('phone_primary', '').strip()
        has_any_data = bool(first_name or last_name or phone_primary)

        if has_any_data:
            if not first_name:
                self.add_error('first_name', 'First name is required when providing parent information.')
            if not last_name:
                self.add_error('last_name', 'Last name is required when providing parent information.')
            if not phone_primary:
                self.add_error('phone_primary', 'Primary phone is required when providing parent information.')
            if not cleaned_data.get('relationship'):
                self.add_error('relationship', 'Relationship is required when providing parent information.')

        return cleaned_data

    def clean_phone_primary(self):
        phone = self.cleaned_data.get('phone_primary')
        if phone and not phone.startswith('+254'):
            raise ValidationError('Phone number must start with +254')
        return phone


class StudentSearchForm(forms.Form):
    """Form for searching/filtering students."""

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Search by name or admission number...'})
    )
    current_class = forms.ModelChoiceField(
        queryset=Class.objects.all(),
        required=False,
        empty_label="All Classes",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    stream = forms.ChoiceField(
        choices=[('', 'All Streams')] + list(StreamChoices.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    club = forms.ModelChoiceField(
        queryset=Club.objects.all(),
        required=False,
        empty_label='All Clubs',
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    status = forms.ChoiceField(
        choices=[('', 'All Status')] + Student.STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    gender = forms.ChoiceField(
        choices=[('', 'All Genders'), ('M', 'Male'), ('F', 'Female')],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    is_boarder = forms.ChoiceField(
        choices=[('', 'All'), ('yes', 'Boarders Only'), ('no', 'Day Scholars Only')],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    def __init__(self, *args, **kwargs):
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        class_queryset = Class.objects.order_by('grade_level', 'stream', 'name')
        club_queryset = Club.objects.order_by('name')
        if organization:
            class_queryset = class_queryset.filter(organization=organization)
            club_queryset = club_queryset.filter(organization=organization)

        self.fields['current_class'].queryset = class_queryset
        self.fields['club'].queryset = club_queryset


class StudentPromotionForm(forms.Form):
    """Form for bulk promoting students to next class."""

    student_ids = forms.MultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        label="Select Students to Promote",
        required=True
    )
    target_class = forms.ModelChoiceField(
        queryset=Class.objects.all(),
        label="Promote to Class",
        help_text="Select the class to promote students to",
        required=True
    )

    def __init__(self, *args, **kwargs):
        students = kwargs.pop('students', Student.objects.none())
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        self.fields['student_ids'].choices = [
            (str(student.id), f"{student.admission_number} - {student.full_name} ({student.current_class or 'No Class'})")
            for student in students
        ]

        if organization:
            self.fields['target_class'].queryset = self.fields['target_class'].queryset.filter(organization=organization)

    def clean_student_ids(self):
        return self.cleaned_data.get('student_ids', [])


class BulkStreamReassignmentForm(forms.Form):
    student_ids = forms.MultipleChoiceField(required=True, widget=forms.MultipleHiddenInput)
    target_stream = forms.ChoiceField(
        choices=StreamChoices.choices,
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text='Choose the stream to move the selected students into.',
    )
    target_class = forms.ModelChoiceField(
        queryset=Class.objects.none(),
        required=False,
        empty_label='Auto-resolve class from each student grade',
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text='Optional: pick an exact class. Leave blank to keep each student in the matching grade and academic year.',
    )

    def __init__(self, *args, **kwargs):
        students = kwargs.pop('students', Student.objects.none())
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        self.fields['student_ids'].choices = [
            (str(student.pk), f"{student.admission_number} - {student.full_name}")
            for student in students
        ]

        queryset = Class.objects.order_by('grade_level', 'stream', 'name')
        if organization:
            queryset = queryset.filter(organization=organization)
        self.fields['target_class'].queryset = queryset

    def clean(self):
        cleaned_data = super().clean()
        target_stream = cleaned_data.get('target_stream')
        target_class = cleaned_data.get('target_class')

        if target_class and target_stream and target_class.stream != target_stream:
            self.add_error('target_class', 'Target class stream must match the selected target stream.')

        return cleaned_data


class ClubForm(forms.ModelForm):
    class Meta:
        model = Club
        fields = ['name', 'description', 'patron']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Wildlife Club'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Optional club description'}),
            'patron': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)
        if organization:
            self.fields['patron'].queryset = self.fields['patron'].queryset.filter(organization=organization)
        self.fields['patron'].required = False


class StudentImportForm(forms.Form):
    """Form for importing students from Excel file."""

    excel_file = forms.FileField(
        label='Excel File',
        help_text='Upload an Excel file (.xlsx) with student data',
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.xlsx,.xls'})
    )

    def clean_excel_file(self):
        file = self.cleaned_data.get('excel_file')
        if file:
            if not file.name.endswith(('.xlsx', '.xls')):
                raise ValidationError('Please upload a valid Excel file (.xlsx or .xls)')
            if file.size > 10 * 1024 * 1024:
                raise ValidationError('File size cannot exceed 10MB')
        return file
