# students/forms.py
from django import forms
from django.core.exceptions import ValidationError

from core.models import StreamChoices
from .models import Student, Parent, StudentParent
from academics.models import Class


class StudentForm(forms.ModelForm):
    """Form for creating/editing student records."""

    class Meta:
        model = Student
        fields = [
            'admission_date',
            'first_name',
            'middle_name',
            'last_name',
            'gender',
            'date_of_birth',
            'birth_certificate_number',
            'photo',
            'current_class',
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
            # Transport
            'uses_school_transport',
            'transport_route',
            'transport_pickup_person',
            # Government/School Identifiers
            'upi_number',
            'assessment_number',
            # Residence
            'residence',
        ]
        exclude = ['admission_number']  # Explicitly exclude - auto-generated for new students
        widgets = {
            'admission_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'first_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'First Name'
            }),
            'middle_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Middle Name (Optional)'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Last Name'
            }),
            'gender': forms.Select(attrs={'class': 'form-control'}),
            'date_of_birth': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'birth_certificate_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Birth Certificate Number'
            }),
            'photo': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'current_class': forms.Select(attrs={'class': 'form-control'}),
            'blood_group': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., A+, O-, B+'
            }),
            'medical_conditions': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Any allergies, chronic conditions, etc.'
            }),
            'emergency_contact_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Emergency Contact Name'
            }),
            'emergency_contact_phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+254...'
            }),
            'previous_school': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Previous School Name'
            }),
            'previous_class': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Grade 8'
            }),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'status_reason': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Reason for status change (required if changing from Active)'
            }),
            'has_special_needs': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'special_needs_details': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Describe special needs'
            }),
            'uses_school_transport': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'transport_route': forms.Select(attrs={'class': 'form-control'}),
            'transport_pickup_person': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Person authorized to pick up from bus'
            }),
            'upi_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Unique Pupil Identifier'
            }),
            'assessment_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Assessment/Exam Number'
            }),
            'residence': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Residence area/estate'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # For editing existing students, add admission_number field
        if self.instance.pk:
            # Add admission_number field for editing
            self.fields['admission_number'] = forms.CharField(
                max_length=20,
                required=True,
                widget=forms.TextInput(attrs={
                    'class': 'form-control',
                    'placeholder': 'e.g., 2025001'
                })
            )
            self.fields['admission_number'].initial = self.instance.admission_number
        else:
            # For new students, ensure admission_number is completely removed
            # (it's excluded in Meta, but remove it explicitly to be safe)
            if 'admission_number' in self.fields:
                del self.fields['admission_number']
            # Set default status to 'active' and hide it
            self.fields['status'].initial = 'active'
            self.fields['status'].widget = forms.HiddenInput()
            self.fields['status_reason'].widget = forms.HiddenInput()
            # Admission number will be auto-generated in model's save() method if not provided
        
        # Make optional fields not required
        optional_fields = [
            'middle_name', 'birth_certificate_number', 'photo', 'current_class',
            'blood_group', 'medical_conditions', 'emergency_contact_name',
            'emergency_contact_phone', 'previous_school', 'previous_class',
            'status_reason', 'special_needs_details', 'transport_route',
            'transport_pickup_person', 'upi_number', 'assessment_number', 'residence'
        ]
        for field in optional_fields:
            if field in self.fields:
                self.fields[field].required = False
    
    def clean_admission_number(self):
        """Only validate admission_number if editing (field exists in form)"""
        # This method only runs if admission_number field exists in the form
        # For new students, this field doesn't exist, so this method won't be called
        if 'admission_number' not in self.fields:
            # Field doesn't exist in form (new student), skip validation
            return None
        
        admission_number = self.cleaned_data.get('admission_number')
        if not admission_number:
            return None
            
        # Only validate uniqueness when editing existing students
        if self.instance.pk:
            # Check if admission number already exists (excluding current instance)
            qs = Student.objects.filter(admission_number=admission_number)
            qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError('A student with this admission number already exists.')
        
        return admission_number

    def clean(self):
        cleaned_data = super().clean()

        # Validate transport
        uses_transport = cleaned_data.get('uses_school_transport')
        transport_route = cleaned_data.get('transport_route')
        if uses_transport and not transport_route:
            self.add_error('transport_route', 'Transport route is required when using school transport.')

        # Validate special needs
        has_special_needs = cleaned_data.get('has_special_needs')
        special_needs_details = cleaned_data.get('special_needs_details')
        if has_special_needs and not special_needs_details:
            self.add_error('special_needs_details', 'Please provide details about special needs.')

        return cleaned_data
    
    def save(self, commit=True):
        """Override save to auto-generate admission_number for new students."""
        from .services import StudentService
        
        # Handle admission_number BEFORE calling super().save() to avoid validation errors
        if not self.instance.pk:
            # New student - auto-generate admission_number
            # Replace any temporary placeholder with actual generated number
            if not self.instance.admission_number or self.instance.admission_number.startswith("TEMP_"):
                self.instance.admission_number = StudentService.generate_admission_number()
        
        instance = super().save(commit=False)
        
        # Handle admission_number for editing existing students
        if instance.pk and 'admission_number' in self.cleaned_data:
            # Editing existing student - admission_number is in form fields
            instance.admission_number = self.cleaned_data['admission_number']
        
        if commit:
            instance.save()
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
            'first_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'First Name'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Last Name'
            }),
            'gender': forms.Select(attrs={'class': 'form-control'}),
            'id_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'National ID Number'
            }),
            'phone_primary': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+254712345678'
            }),
            'phone_secondary': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+254712345678 (Optional)'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'email@example.com'
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Physical Address'
            }),
            'town': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Town/City'
            }),
            'occupation': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Occupation'
            }),
            'employer': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Employer Name'
            }),
            'relationship': forms.Select(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make fields optional by default - validation will be conditional
        self.fields['first_name'].required = False
        self.fields['last_name'].required = False
        self.fields['phone_primary'].required = False
        self.fields['relationship'].required = False
    
    def clean(self):
        cleaned_data = super().clean()
        first_name = cleaned_data.get('first_name', '').strip()
        last_name = cleaned_data.get('last_name', '').strip()
        phone_primary = cleaned_data.get('phone_primary', '').strip()
        
        # If any field is filled, then required fields must be filled
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
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by name or admission number...'
        })
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


from django import forms
from academics.models import Class
from .models import Student


class StudentPromotionForm(forms.Form):
    """
    Form for bulk promoting students to next class.
    """
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
        # Extract custom 'students' argument before calling super().__init__
        students = kwargs.pop('students', Student.objects.none())

        super().__init__(*args, **kwargs)

        # Set choices for student_ids field
        self.fields['student_ids'].choices = [
            (str(student.id),
             f"{student.admission_number} - {student.full_name} ({student.current_class or 'No Class'})")
            for student in students
        ]

    def clean_student_ids(self):
        """Convert string IDs back to UUIDs"""
        student_ids = self.cleaned_data.get('student_ids', [])
        return student_ids


class StudentImportForm(forms.Form):
    """Form for importing students from Excel file."""
    
    excel_file = forms.FileField(
        label='Excel File',
        help_text='Upload an Excel file (.xlsx) with student data',
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.xlsx,.xls',
        })
    )
    
    def clean_excel_file(self):
        file = self.cleaned_data.get('excel_file')
        if file:
            # Check file extension
            if not file.name.endswith(('.xlsx', '.xls')):
                raise ValidationError('Please upload a valid Excel file (.xlsx or .xls)')
            # Check file size (max 10MB)
            if file.size > 10 * 1024 * 1024:
                raise ValidationError('File size cannot exceed 10MB')
        return file