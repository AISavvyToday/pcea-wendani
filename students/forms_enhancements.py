from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Case, IntegerField, Q, Value, When

from academics.models import AcademicYear, Class
from core.models import StreamChoices
from .forms import StudentForm
from .models import Club, ClubMembership, Student


GRADE_LABELS = dict(Class._meta.get_field('grade_level').choices)
STREAM_LABELS = dict(StreamChoices.choices)
GRADE_ORDER = [choice[0] for choice in Class._meta.get_field('grade_level').choices]
GRADE_ORDERING = Case(
    *[When(grade_level=value, then=Value(index)) for index, value in enumerate(GRADE_ORDER)],
    default=Value(len(GRADE_ORDER)),
    output_field=IntegerField(),
)


class LabeledClassChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        grade_label = GRADE_LABELS.get(obj.grade_level, obj.grade_level)
        stream_label = STREAM_LABELS.get(obj.stream, obj.stream)
        year = getattr(getattr(obj, 'academic_year', None), 'year', '')
        return f"{grade_label} • {stream_label} • {obj.name}{f' ({year})' if year else ''}"


def order_students_by_grade(queryset):
    return queryset.annotate(
        grade_order=Case(
            *[When(current_class__grade_level=value, then=Value(index)) for index, value in enumerate(GRADE_ORDER)],
            default=Value(len(GRADE_ORDER)),
            output_field=IntegerField(),
        )
    ).order_by('grade_order', 'current_class__name', 'admission_number', 'first_name', 'last_name')


class StudentEnrollmentForm(StudentForm):
    """Enhanced student form that makes stream selection explicit while keeping current_class as the source of truth."""

    grade_level = forms.ChoiceField(
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='Grade Level',
    )
    stream = forms.ChoiceField(
        required=False,
        choices=[('', 'Select stream')] + list(StreamChoices.choices),
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='Stream',
    )

    class Meta(StudentForm.Meta):
        fields = ['grade_level', 'stream'] + StudentForm.Meta.fields

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        self.fields['current_class'] = LabeledClassChoiceField(
            queryset=self.fields['current_class'].queryset,
            required=self.fields['current_class'].required,
            widget=self.fields['current_class'].widget,
            label=self.fields['current_class'].label,
            help_text='Pick the exact class after selecting grade and stream.',
        )

        queryset = Class.objects.select_related('academic_year').filter(is_active=True)
        organization = self.organization or getattr(self.instance, 'organization', None)
        if organization is not None:
            queryset = queryset.filter(organization=organization)

        current_year = AcademicYear.objects.filter(is_current=True)
        if organization is not None:
            current_year = current_year.filter(Q(organization=organization) | Q(organization__isnull=True))
        current_year = current_year.first()
        if current_year is not None:
            current_year_queryset = queryset.filter(academic_year=current_year)
            if current_year_queryset.exists():
                queryset = current_year_queryset

        queryset = queryset.annotate(grade_order=GRADE_ORDERING).order_by('grade_order', 'stream', 'name')
        self.fields['current_class'].queryset = queryset

        grade_choices = [('', 'Select grade')] + [
            (grade_value, GRADE_LABELS.get(grade_value, grade_value))
            for grade_value in queryset.values_list('grade_level', flat=True).distinct()
        ]
        self.fields['grade_level'].choices = grade_choices

        current_class = getattr(self.instance, 'current_class', None)
        if current_class:
            self.fields['grade_level'].initial = current_class.grade_level
            self.fields['stream'].initial = current_class.stream

        if self.is_bound:
            bound_grade = self.data.get('grade_level')
            bound_stream = self.data.get('stream')
            filtered_queryset = queryset
            if bound_grade:
                filtered_queryset = filtered_queryset.filter(grade_level=bound_grade)
            if bound_stream:
                filtered_queryset = filtered_queryset.filter(stream=bound_stream)
            if bound_grade or bound_stream:
                self.fields['current_class'].queryset = filtered_queryset
        else:
            initial_grade = self.fields['grade_level'].initial
            initial_stream = self.fields['stream'].initial
            if initial_grade:
                queryset = queryset.filter(grade_level=initial_grade)
            if initial_stream:
                queryset = queryset.filter(stream=initial_stream)
            if initial_grade or initial_stream:
                self.fields['current_class'].queryset = queryset

    def clean(self):
        cleaned_data = super().clean()
        grade_level = cleaned_data.get('grade_level')
        stream = cleaned_data.get('stream')
        current_class = cleaned_data.get('current_class')
        organization = self.organization or getattr(self.instance, 'organization', None)

        if current_class:
            if grade_level and current_class.grade_level != grade_level:
                self.add_error('current_class', 'Selected class does not belong to the chosen grade level.')
            if stream and current_class.stream != stream:
                self.add_error('current_class', 'Selected class does not belong to the chosen stream.')
            cleaned_data['grade_level'] = current_class.grade_level
            cleaned_data['stream'] = current_class.stream
            return cleaned_data

        if grade_level and stream:
            class_queryset = Class.objects.filter(
                is_active=True,
                grade_level=grade_level,
                stream=stream,
            ).select_related('academic_year')
            if organization is not None:
                class_queryset = class_queryset.filter(organization=organization)

            current_year = AcademicYear.objects.filter(is_current=True)
            if organization is not None:
                current_year = current_year.filter(Q(organization=organization) | Q(organization__isnull=True))
            current_year = current_year.first()
            if current_year is not None:
                year_filtered = class_queryset.filter(academic_year=current_year)
                if year_filtered.exists():
                    class_queryset = year_filtered

            current_class = class_queryset.annotate(grade_order=GRADE_ORDERING).order_by('grade_order', 'name').first()
            if current_class is None:
                self.add_error('current_class', 'No active class exists for the selected grade and stream.')
            else:
                cleaned_data['current_class'] = current_class
        elif grade_level or stream:
            self.add_error('current_class', 'Select both grade and stream, or pick a class directly.')

        return cleaned_data


class BulkStreamTransferForm(forms.Form):
    source_class = LabeledClassChoiceField(
        queryset=Class.objects.none(),
        required=False,
        empty_label='All classes',
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='Source Class',
    )
    source_stream = forms.ChoiceField(
        choices=[('', 'All streams')] + list(StreamChoices.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='Source Stream',
    )
    student_search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Search by name, admission number, or class'}),
        label='Search Students',
    )
    target_class = LabeledClassChoiceField(
        queryset=Class.objects.none(),
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='Destination Class',
    )
    students = forms.ModelMultipleChoiceField(
        queryset=Student.objects.none(),
        required=True,
        widget=forms.CheckboxSelectMultiple,
        label='Students to move',
    )

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        class_queryset = Class.objects.filter(is_active=True).select_related('academic_year')
        if self.organization is not None:
            class_queryset = class_queryset.filter(organization=self.organization)
        current_year = AcademicYear.objects.filter(is_current=True)
        if self.organization is not None:
            current_year = current_year.filter(Q(organization=self.organization) | Q(organization__isnull=True))
        current_year = current_year.first()
        if current_year is not None:
            current_year_queryset = class_queryset.filter(academic_year=current_year)
            if current_year_queryset.exists():
                class_queryset = current_year_queryset
        class_queryset = class_queryset.annotate(grade_order=GRADE_ORDERING).order_by('grade_order', 'stream', 'name')

        self.fields['source_class'].queryset = class_queryset
        self.fields['target_class'].queryset = class_queryset

        student_queryset = Student.objects.filter(is_active=True, status='active').select_related('current_class')
        if self.organization is not None:
            student_queryset = student_queryset.filter(organization=self.organization)

        if self.is_bound:
            source_class_id = self.data.get('source_class')
            source_stream = self.data.get('source_stream')
            target_class_id = self.data.get('target_class')
            student_search = (self.data.get('student_search') or '').strip()
        else:
            source_class_id = self.initial.get('source_class')
            source_stream = self.initial.get('source_stream')
            target_class_id = self.initial.get('target_class')
            student_search = (self.initial.get('student_search') or '').strip()

        if source_class_id:
            try:
                source_class = class_queryset.get(pk=source_class_id)
                student_queryset = student_queryset.filter(current_class=source_class)
            except Class.DoesNotExist:
                pass
        if source_stream:
            student_queryset = student_queryset.filter(current_class__stream=source_stream)
        if student_search:
            student_queryset = student_queryset.filter(
                Q(first_name__icontains=student_search)
                | Q(middle_name__icontains=student_search)
                | Q(last_name__icontains=student_search)
                | Q(admission_number__icontains=student_search)
                | Q(current_class__name__icontains=student_search)
            )

        self.fields['students'].queryset = order_students_by_grade(student_queryset)
        self.fields['students'].label_from_instance = lambda student: (
            f"{student.admission_number or 'N/A'} - {student.full_name}"
            f" ({getattr(student.current_class, 'name', 'No Class')})"
        )

        if target_class_id:
            try:
                self.initial['target_class'] = class_queryset.get(pk=target_class_id)
            except Class.DoesNotExist:
                pass

    def clean(self):
        cleaned_data = super().clean()
        students = cleaned_data.get('students')
        target_class = cleaned_data.get('target_class')
        if not students:
            self.add_error('students', 'Select at least one student to move.')
            return cleaned_data

        if target_class:
            invalid_students = [student for student in students if student.current_class_id == target_class.id]
            if invalid_students and len(invalid_students) == len(students):
                self.add_error('target_class', 'Selected students are already in the destination class.')
        return cleaned_data


class ClubForm(forms.ModelForm):
    class Meta:
        model = Club
        fields = ['name', 'code', 'description', 'patron_name']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'patron_name': forms.TextInput(attrs={'class': 'form-control'}),
        }


class ClubMembershipForm(forms.Form):
    student_search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Search by name, admission number, or class'}),
        label='Search Students',
    )
    students = forms.ModelMultipleChoiceField(
        queryset=Student.objects.none(),
        required=True,
        widget=forms.CheckboxSelectMultiple,
        label='Students',
    )

    def __init__(self, *args, **kwargs):
        organization = kwargs.pop('organization', None)
        club = kwargs.pop('club', None)
        super().__init__(*args, **kwargs)

        if self.is_bound:
            search_term = (self.data.get('student_search') or '').strip()
        else:
            search_term = (self.initial.get('student_search') or '').strip()

        queryset = Student.objects.filter(is_active=True, status='active').select_related('current_class')
        if organization is not None:
            queryset = queryset.filter(organization=organization)
        if club is not None:
            queryset = queryset.exclude(
                club_memberships__club=club,
                club_memberships__is_active=True,
            )
        if search_term:
            queryset = queryset.filter(
                Q(first_name__icontains=search_term)
                | Q(middle_name__icontains=search_term)
                | Q(last_name__icontains=search_term)
                | Q(admission_number__icontains=search_term)
                | Q(current_class__name__icontains=search_term)
            )
        queryset = order_students_by_grade(queryset)
        self.fields['students'].queryset = queryset
        self.fields['students'].label_from_instance = lambda student: (
            f"{student.admission_number or 'N/A'} - {student.full_name}"
            f" ({getattr(student.current_class, 'name', 'No Class')})"
        )
