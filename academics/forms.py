from django import forms
from django.db import transaction

from accounts.models import User
from core.models import UserRole

from .models import (
    Attendance,
    Grade,
    Exam,
    ClassSubject,
    AcademicYear,
    Term,
    Subject,
    Class,
    Department,
    Staff,
)


class AcademicYearForm(forms.ModelForm):
    class Meta:
        model = AcademicYear
        fields = ['year', 'start_date', 'end_date', 'is_current']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }


class TermForm(forms.ModelForm):
    class Meta:
        model = Term
        fields = ['academic_year', 'term', 'start_date', 'end_date', 'is_current', 'fee_deadline', 'late_fee_start_date']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'fee_deadline': forms.DateInput(attrs={'type': 'date'}),
            'late_fee_start_date': forms.DateInput(attrs={'type': 'date'}),
        }


class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ['name', 'code', 'grade_levels', 'department', 'subject_type', 'description', 'max_marks', 'pass_marks']
        widgets = {
            'grade_levels': forms.CheckboxSelectMultiple(),
            'description': forms.Textarea(attrs={'rows': 3}),
        }


class ClassForm(forms.ModelForm):
    class Meta:
        model = Class
        fields = ['name', 'grade_level', 'stream', 'class_teacher', 'room', 'academic_year']


class ClassSubjectForm(forms.ModelForm):
    class Meta:
        model = ClassSubject
        fields = ['class_obj', 'subject', 'teacher', 'periods_per_week']


class ExamForm(forms.ModelForm):
    class Meta:
        model = Exam
        fields = ['name', 'term', 'exam_type', 'start_date', 'end_date', 'weight_percentage', 'classes']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'classes': forms.CheckboxSelectMultiple(),
        }


class AttendanceForm(forms.ModelForm):
    class Meta:
        model = Attendance
        fields = ['student', 'date', 'class_obj', 'status', 'arrival_time', 'departure_time', 'remarks']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'arrival_time': forms.TimeInput(attrs={'type': 'time'}),
            'departure_time': forms.TimeInput(attrs={'type': 'time'}),
            'remarks': forms.Textarea(attrs={'rows': 2}),
        }


class GradeForm(forms.ModelForm):
    class Meta:
        model = Grade
        fields = ['student', 'exam', 'subject', 'marks', 'remarks']


class StaffOnboardingForm(forms.ModelForm):
    STAFF_ROLE_CHOICES = [
        (UserRole.TEACHER, 'Teacher'),
        (UserRole.ACCOUNTANT, 'Accountant'),
        (UserRole.SCHOOL_ADMIN, 'School Administrator'),
    ]

    email = forms.EmailField()
    first_name = forms.CharField(max_length=50)
    last_name = forms.CharField(max_length=50)
    user_phone_number = forms.CharField(max_length=15, required=False)
    role = forms.ChoiceField(choices=STAFF_ROLE_CHOICES)

    class Meta:
        model = Staff
        fields = [
            'staff_number',
            'staff_type',
            'department',
            'id_number',
            'tsc_number',
            'date_of_birth',
            'gender',
            'phone_number',
            'address',
            'date_joined',
            'employment_type',
            'qualifications',
            'specialization',
            'status',
        ]
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}),
            'date_joined': forms.DateInput(attrs={'type': 'date'}),
            'address': forms.Textarea(attrs={'rows': 3}),
            'qualifications': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        self.organization = organization
        super().__init__(*args, **kwargs)
        self.linked_user = None

        if organization is not None:
            self.fields['department'].queryset = Department.objects.filter(organization=organization).order_by('name')
        else:
            self.fields['department'].queryset = Department.objects.none()

        for field in self.fields.values():
            widget = field.widget
            existing_class = widget.attrs.get('class', '')
            if isinstance(widget, (forms.Textarea, forms.DateInput, forms.EmailInput, forms.TextInput, forms.Select)):
                css_class = 'form-control' if not isinstance(widget, forms.Select) else 'form-select'
                widget.attrs['class'] = f"{existing_class} {css_class}".strip()

        if self.instance.pk and getattr(self.instance, 'user_id', None):
            self.fields['email'].initial = self.instance.user.email
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial = self.instance.user.last_name
            self.fields['user_phone_number'].initial = self.instance.user.phone_number
            self.fields['role'].initial = self.instance.user.role

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data['email']).lower()
        user_qs = User.objects.filter(email__iexact=email)

        is_editing = bool(getattr(self.instance, 'pk', None)) and not self.instance._state.adding
        current_user = getattr(self.instance, 'user', None)
        if current_user:
            user_qs = user_qs.exclude(pk=current_user.pk)

        existing_user = user_qs.first()
        if existing_user:
            if existing_user.organization_id and self.organization and existing_user.organization_id != self.organization.id:
                raise forms.ValidationError('A user with this email belongs to a different organization.')
            if is_editing:
                raise forms.ValidationError('Another user with this email already exists.')
            if Staff.objects.filter(user=existing_user).exists():
                raise forms.ValidationError('A staff profile with this email already exists.')
            self.linked_user = existing_user

        return email

    def clean_staff_number(self):
        staff_number = self.cleaned_data['staff_number'].strip()
        qs = Staff.objects.filter(staff_number__iexact=staff_number)
        if bool(getattr(self.instance, 'pk', None)) and not self.instance._state.adding:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('This staff number is already in use.')
        return staff_number

    def clean_id_number(self):
        id_number = self.cleaned_data['id_number'].strip()
        qs = Staff.objects.filter(id_number__iexact=id_number)
        if bool(getattr(self.instance, 'pk', None)) and not self.instance._state.adding:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('This ID number is already in use.')
        return id_number

    def clean_department(self):
        department = self.cleaned_data.get('department')
        if department and self.organization and department.organization_id != self.organization.id:
            raise forms.ValidationError('Selected department does not belong to this organization.')
        return department

    def clean(self):
        cleaned_data = super().clean()
        user = getattr(self.instance, 'user', None) or self.linked_user

        if user and self.organization and user.organization_id and user.organization_id != self.organization.id:
            self.add_error('email', 'User organization must match the staff organization.')

        is_editing = bool(getattr(self.instance, 'pk', None)) and not self.instance._state.adding
        current_user = getattr(self.instance, 'user', None)
        if current_user and self.organization and current_user.organization_id and current_user.organization_id != self.organization.id:
            self.add_error(None, 'The linked user belongs to a different organization than this staff record.')

        if self.instance.pk and self.instance.organization_id and self.organization and self.instance.organization_id != self.organization.id:
            self.add_error(None, 'The staff record belongs to a different organization than the current request.')

        return cleaned_data

    @transaction.atomic
    def save(self, commit=True):
        if not self.organization:
            raise ValueError('Staff onboarding requires an organization.')

        staff = super().save(commit=False)
        user = getattr(self.instance, 'user', None) or self.linked_user
        user_defaults = {
            'first_name': self.cleaned_data['first_name'],
            'last_name': self.cleaned_data['last_name'],
            'phone_number': self.cleaned_data['user_phone_number'],
            'role': self.cleaned_data['role'],
            'organization': self.organization,
            'is_active': True,
            'is_staff': self.cleaned_data['role'] in {UserRole.SCHOOL_ADMIN},
        }

        if user is None:
            user = User.objects.create_user(
                email=self.cleaned_data['email'],
                password=None,
                **user_defaults,
            )
            user.must_change_password = True
            user.save(update_fields=['must_change_password'])
        else:
            for field_name, value in user_defaults.items():
                setattr(user, field_name, value)
            user.email = self.cleaned_data['email']
            user.save()

        staff.user = user
        staff.organization = self.organization

        if commit:
            staff.save()
            self.save_m2m()
        return staff
