# students/forms.py
import logging
from django import forms
from django.core.exceptions import ValidationError

from core.models import StreamChoices
from .models import Student, Parent, StudentParent
from academics.models import Class

logger = logging.getLogger(__name__)


class StudentForm(forms.ModelForm):
    """Form for creating/editing student records."""

    class Meta:
        model = Student
        fields = [
            'admission_number',  # Include it - will be hidden for new students, visible for editing
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
        # Check if this is a new student BEFORE calling super().__init__()
        # If instance is provided but has no pk, or no instance provided, it's a new student
        instance = kwargs.get('instance', None)
        is_new_student = instance is None or not (hasattr(instance, 'pk') and instance.pk)
        
        logger.error(f"StudentForm.__init__ - BEFORE super().__init__(), instance provided: {instance is not None}, is_new_student: {is_new_student}")
        if instance:
            logger.error(f"StudentForm.__init__ - instance.pk: {getattr(instance, 'pk', 'NO PK ATTRIBUTE')}")
        
        super().__init__(*args, **kwargs)
        
        logger.error(f"StudentForm.__init__ - AFTER super().__init__(), instance.pk: {self.instance.pk}, is_bound: {self.is_bound}, is_new_student: {is_new_student}")
        logger.error(f"StudentForm.__init__ - admission_number field exists: {'admission_number' in self.fields}")
        if 'admission_number' in self.fields:
            logger.error(f"StudentForm.__init__ - admission_number.required BEFORE our changes: {self.fields['admission_number'].required}")
            logger.error(f"StudentForm.__init__ - admission_number.initial BEFORE our changes: {self.fields['admission_number'].initial}")
        
        # For editing existing students, make admission_number visible and required
        # Check if instance is actually saved to DB (not just has a pk - UUID instances have pk even when unsaved)
        # _state.adding is False if instance is saved, True if it's new
        is_saved = self.instance.pk and (hasattr(self.instance, '_state') and not self.instance._state.adding)
        
        logger.error(f"StudentForm.__init__ - is_saved check: pk={self.instance.pk}, has _state={hasattr(self.instance, '_state')}, _state.adding={getattr(self.instance._state, 'adding', 'NO _state') if hasattr(self.instance, '_state') else 'N/A'}, is_saved={is_saved}")
        
        if is_saved:
            logger.error(f"StudentForm.__init__ - EDITING existing student, admission_number: {self.instance.admission_number}")
            self.fields['admission_number'].required = True
            self.fields['admission_number'].widget = forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., 2025001'
            })
            self.fields['admission_number'].initial = self.instance.admission_number
        else:
            # For new students, make admission_number a hidden field with auto-generated value
            logger.error(f"StudentForm.__init__ - CREATING new student, instance.admission_number before: {self.instance.admission_number}")
            from .services import StudentService
            if not self.instance.admission_number:
                self.instance.admission_number = StudentService.generate_admission_number(organization=self.instance.organization)
                logger.error(f"StudentForm.__init__ - Generated new admission_number: {self.instance.admission_number}")
            
            generated_value = self.instance.admission_number
            logger.error(f"StudentForm.__init__ - Setting field properties, generated_value: {generated_value}")
            logger.error(f"StudentForm.__init__ - Setting required=False on admission_number field")
            self.fields['admission_number'].required = False
            logger.error(f"StudentForm.__init__ - admission_number.required AFTER setting to False: {self.fields['admission_number'].required}")
            self.fields['admission_number'].widget = forms.HiddenInput()
            self.fields['admission_number'].initial = generated_value
            logger.error(f"StudentForm.__init__ - admission_number.initial AFTER setting: {self.fields['admission_number'].initial}")
            
            # CRITICAL: If form is bound (POST request), inject admission_number into POST data
            # This ensures Django sees the value during validation and doesn't treat it as missing
            if self.is_bound:
                logger.debug(f"StudentForm.__init__ - Form is BOUND (POST), checking POST data")
                logger.debug(f"StudentForm.__init__ - 'admission_number' in self.data: {'admission_number' in self.data}")
                if 'admission_number' in self.data:
                    logger.debug(f"StudentForm.__init__ - POST data has admission_number: {self.data.get('admission_number')}")
                else:
                    logger.debug(f"StudentForm.__init__ - POST data MISSING admission_number, injecting: {generated_value}")
                    from django.http import QueryDict
                    # Make QueryDict mutable and add the value
                    if isinstance(self.data, QueryDict):
                        self.data = self.data.copy()
                    self.data['admission_number'] = generated_value
                    logger.debug(f"StudentForm.__init__ - After injection, self.data['admission_number']: {self.data.get('admission_number')}")
            else:
                logger.debug(f"StudentForm.__init__ - Form is NOT bound (GET request)")
            
            # Set default status to 'active' and hide it
            self.fields['status'].initial = 'active'
            self.fields['status'].widget = forms.HiddenInput()
            self.fields['status_reason'].widget = forms.HiddenInput()
        
        # Make optional fields not required
        optional_fields = [
            'middle_name', 'birth_certificate_number', 'photo',
            'blood_group', 'medical_conditions', 'emergency_contact_name',
            'emergency_contact_phone', 'previous_school', 'previous_class',
            'status_reason', 'special_needs_details', 'transport_route',
            'transport_pickup_person', 'upi_number', 'assessment_number', 'residence'
        ]
        for field in optional_fields:
            if field in self.fields:
                self.fields[field].required = False
    
    def clean_admission_number(self):
        """Handle admission_number validation for new and existing students."""
        logger.debug(f"StudentForm.clean_admission_number - Called, instance.pk: {self.instance.pk}")
        admission_number = self.cleaned_data.get('admission_number')
        logger.debug(f"StudentForm.clean_admission_number - cleaned_data.get('admission_number'): {admission_number}")
        logger.debug(f"StudentForm.clean_admission_number - self.instance.admission_number: {self.instance.admission_number}")
        
        # For new students, if empty, generate one
        if not self.instance.pk:
            logger.debug(f"StudentForm.clean_admission_number - Processing NEW student")
            if not admission_number:
                logger.warning(f"StudentForm.clean_admission_number - admission_number is EMPTY, generating new one")
                from .services import StudentService
                admission_number = StudentService.generate_admission_number(organization=self.instance.organization)
                self.cleaned_data['admission_number'] = admission_number
                self.instance.admission_number = admission_number
                logger.debug(f"StudentForm.clean_admission_number - Generated and set: {admission_number}")
            else:
                logger.debug(f"StudentForm.clean_admission_number - admission_number already present: {admission_number}")
            return admission_number
        
        # For existing students, validate uniqueness
        if self.instance.pk and admission_number:
            logger.debug(f"StudentForm.clean_admission_number - Processing EXISTING student, validating uniqueness")
            qs = Student.objects.filter(admission_number=admission_number)
            qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                logger.error(f"StudentForm.clean_admission_number - Duplicate admission_number found: {admission_number}")
                raise ValidationError('A student with this admission number already exists.')
        
        logger.debug(f"StudentForm.clean_admission_number - Returning: {admission_number}")
        return admission_number

    def clean_admission_date(self):
        admission_date = self.cleaned_data.get('admission_date')
        if not admission_date:
            raise ValidationError('Admission date is required for new student metrics.')
        return admission_date

    def clean(self):
        logger.debug(f"StudentForm.clean - Called, instance.pk: {self.instance.pk}")
        logger.debug(f"StudentForm.clean - Calling super().clean()...")
        cleaned_data = super().clean()
        logger.debug(f"StudentForm.clean - super().clean() returned, cleaned_data keys: {list(cleaned_data.keys())}")
        logger.debug(f"StudentForm.clean - 'admission_number' in cleaned_data: {'admission_number' in cleaned_data}")
        if 'admission_number' in cleaned_data:
            logger.debug(f"StudentForm.clean - cleaned_data['admission_number']: {cleaned_data.get('admission_number')}")
        logger.debug(f"StudentForm.clean - self.instance.admission_number: {self.instance.admission_number}")

        # For new students, ensure admission_number is in cleaned_data
        # This is a final safeguard to prevent validation errors
        if not self.instance.pk:
            logger.debug(f"StudentForm.clean - Processing NEW student")
            if 'admission_number' not in cleaned_data:
                logger.warning(f"StudentForm.clean - admission_number NOT in cleaned_data, adding it")
                if self.instance.admission_number:
                    logger.debug(f"StudentForm.clean - Using instance.admission_number: {self.instance.admission_number}")
                    cleaned_data['admission_number'] = self.instance.admission_number
                else:
                    logger.warning(f"StudentForm.clean - instance.admission_number also empty, generating new one")
                    from .services import StudentService
                    admission_number = StudentService.generate_admission_number(organization=self.instance.organization)
                    cleaned_data['admission_number'] = admission_number
                    self.instance.admission_number = admission_number
                    logger.debug(f"StudentForm.clean - Generated and set: {admission_number}")
            else:
                logger.debug(f"StudentForm.clean - admission_number already in cleaned_data: {cleaned_data.get('admission_number')}")

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

        logger.debug(f"StudentForm.clean - Returning cleaned_data, final admission_number: {cleaned_data.get('admission_number')}")
        
        # Log any errors that exist
        if self.errors:
            logger.error(f"StudentForm.clean - FORM HAS ERRORS: {self.errors}")
            if 'admission_number' in self.errors:
                logger.error(f"StudentForm.clean - admission_number ERROR: {self.errors['admission_number']}")
        
        return cleaned_data
    
    def full_clean(self):
        """Override to add logging before full validation."""
        logger.error(f"StudentForm.full_clean - Called, instance.pk: {self.instance.pk}, is_bound: {self.is_bound}")
        if 'admission_number' in self.fields:
            logger.error(f"StudentForm.full_clean - admission_number.required: {self.fields['admission_number'].required}")
            logger.error(f"StudentForm.full_clean - admission_number.initial: {self.fields['admission_number'].initial}")
        if self.is_bound:
            logger.error(f"StudentForm.full_clean - POST data keys: {list(self.data.keys())[:20]}")
            logger.error(f"StudentForm.full_clean - POST data admission_number: {self.data.get('admission_number', 'NOT IN POST DATA')}")
        try:
            super().full_clean()
            logger.error(f"StudentForm.full_clean - After super().full_clean(), errors: {self.errors}")
        except Exception as e:
            logger.error(f"StudentForm.full_clean - EXCEPTION during validation: {type(e).__name__}: {str(e)}")
            logger.error(f"StudentForm.full_clean - Form errors: {self.errors}")
            raise
    
    def save(self, commit=True):
        """Override save to handle admission_number for new and existing students."""
        logger.debug(f"StudentForm.save - Called, instance.pk: {self.instance.pk}, commit: {commit}")
        logger.debug(f"StudentForm.save - cleaned_data keys: {list(self.cleaned_data.keys()) if hasattr(self, 'cleaned_data') else 'N/A'}")
        if hasattr(self, 'cleaned_data') and 'admission_number' in self.cleaned_data:
            logger.debug(f"StudentForm.save - cleaned_data['admission_number']: {self.cleaned_data.get('admission_number')}")
        logger.debug(f"StudentForm.save - self.instance.admission_number before: {self.instance.admission_number}")
        
        # For new students, admission_number is already set in __init__ method
        # For existing students, update from form data if provided
        if self.instance.pk and hasattr(self, 'cleaned_data') and 'admission_number' in self.cleaned_data:
            # Editing existing student - admission_number is in form fields
            logger.debug(f"StudentForm.save - Editing existing student, updating admission_number")
            self.instance.admission_number = self.cleaned_data['admission_number']
        
        instance = super().save(commit=False)
        logger.debug(f"StudentForm.save - After super().save(commit=False), instance.admission_number: {instance.admission_number}")
        
        # Ensure admission_number is set for new students (fallback if somehow not set in __init__)
        if not instance.pk and not instance.admission_number:
            logger.error(f"StudentForm.save - CRITICAL: New student with NO admission_number, generating fallback!")
            from .services import StudentService
            instance.admission_number = StudentService.generate_admission_number(organization=instance.organization)
            logger.debug(f"StudentForm.save - Generated fallback admission_number: {instance.admission_number}")
        
        if commit:
            logger.debug(f"StudentForm.save - Committing to database, admission_number: {instance.admission_number}")
            instance.save()
        else:
            logger.debug(f"StudentForm.save - Not committing (commit=False)")
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
