# academics/forms.py

from django import forms
from .models import Attendance, Grade, Exam, ClassSubject, AcademicYear, Term, Subject, Class


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
        fields = ['name', 'grade_level', 'stream', 'capacity', 'class_teacher', 'room', 'academic_year']


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