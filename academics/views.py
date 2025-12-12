# academics/views.py

from django.views.generic import (
    ListView, CreateView, UpdateView, DetailView, TemplateView, FormView, View
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.db.models import Q, Avg
from django.contrib.auth.mixins import LoginRequiredMixin
from core.mixins import RoleRequiredMixin
from .models import (
    AcademicYear, Term, Department, Staff, Class, Subject,
    ClassSubject, Exam, Grade, Attendance, Timetable
)
from .forms import (
    AcademicYearForm, TermForm, SubjectForm, ClassForm,
    ClassSubjectForm, ExamForm, AttendanceForm, GradeForm
)
from students.models import Student


# --- Academic Year Views ---

class AcademicYearListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = AcademicYear
    template_name = 'academics/academic_year_list.html'
    context_object_name = 'academic_years'
    allowed_roles = ['super_admin', 'school_admin']


class AcademicYearCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = AcademicYear
    form_class = AcademicYearForm
    template_name = 'academics/academic_year_form.html'
    success_url = reverse_lazy('academics:academic_year_list')
    allowed_roles = ['super_admin', 'school_admin']


class AcademicYearUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    model = AcademicYear
    form_class = AcademicYearForm
    template_name = 'academics/academic_year_form.html'
    success_url = reverse_lazy('academics:academic_year_list')
    allowed_roles = ['super_admin', 'school_admin']


# --- Term Views ---

class TermListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = Term
    template_name = 'academics/term_list.html'
    context_object_name = 'terms'
    allowed_roles = ['super_admin', 'school_admin']


class TermCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = Term
    form_class = TermForm
    template_name = 'academics/term_form.html'
    success_url = reverse_lazy('academics:term_list')
    allowed_roles = ['super_admin', 'school_admin']


class TermUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    model = Term
    form_class = TermForm
    template_name = 'academics/term_form.html'
    success_url = reverse_lazy('academics:term_list')
    allowed_roles = ['super_admin', 'school_admin']


# --- Subject Views ---

class SubjectListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = Subject
    template_name = 'academics/subject_list.html'
    context_object_name = 'subjects'
    allowed_roles = ['super_admin', 'school_admin']


class SubjectCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = Subject
    form_class = SubjectForm
    template_name = 'academics/subject_form.html'
    success_url = reverse_lazy('academics:subject_list')
    allowed_roles = ['super_admin', 'school_admin']


class SubjectUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    model = Subject
    form_class = SubjectForm
    template_name = 'academics/subject_form.html'
    success_url = reverse_lazy('academics:subject_list')
    allowed_roles = ['super_admin', 'school_admin']


# --- Class Views ---

class ClassListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = Class
    template_name = 'academics/class_list.html'
    context_object_name = 'classes'
    allowed_roles = ['super_admin', 'school_admin']


class ClassCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = Class
    form_class = ClassForm
    template_name = 'academics/class_form.html'
    success_url = reverse_lazy('academics:class_list')
    allowed_roles = ['super_admin', 'school_admin']


class ClassUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    model = Class
    form_class = ClassForm
    template_name = 'academics/class_form.html'
    success_url = reverse_lazy('academics:class_list')
    allowed_roles = ['super_admin', 'school_admin']


# --- ClassSubject Views ---

class ClassSubjectListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = ClassSubject
    template_name = 'academics/class_subject_list.html'
    context_object_name = 'class_subjects'
    allowed_roles = ['super_admin', 'school_admin']


class ClassSubjectCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = ClassSubject
    form_class = ClassSubjectForm
    template_name = 'academics/class_subject_form.html'
    success_url = reverse_lazy('academics:class_subject_list')
    allowed_roles = ['super_admin', 'school_admin']


class ClassSubjectUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    model = ClassSubject
    form_class = ClassSubjectForm
    template_name = 'academics/class_subject_form.html'
    success_url = reverse_lazy('academics:class_subject_list')
    allowed_roles = ['super_admin', 'school_admin']


# --- Exam Views ---

class ExamListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = Exam
    template_name = 'academics/exam_list.html'
    context_object_name = 'exams'
    allowed_roles = ['super_admin', 'school_admin']


class ExamCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = Exam
    form_class = ExamForm
    template_name = 'academics/exam_form.html'
    success_url = reverse_lazy('academics:exam_list')
    allowed_roles = ['super_admin', 'school_admin']


class ExamUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    model = Exam
    form_class = ExamForm
    template_name = 'academics/exam_form.html'
    success_url = reverse_lazy('academics:exam_list')
    allowed_roles = ['super_admin', 'school_admin']


# --- Attendance Views ---

class AttendanceListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = Attendance
    template_name = 'academics/attendance_list.html'
    context_object_name = 'attendance_records'
    allowed_roles = ['teacher', 'super_admin', 'school_admin']

    def get_queryset(self):
        # Teachers see attendance for their classes only
        staff = get_object_or_404(Staff, user=self.request.user)
        classes = Class.objects.filter(class_teacher=staff)
        return Attendance.objects.filter(class_obj__in=classes).order_by('-date')


class AttendanceCreateView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ['teacher']

    def get(self, request, class_pk, date=None):
        staff = get_object_or_404(Staff, user=request.user)
        class_obj = get_object_or_404(Class, pk=class_pk, class_teacher=staff)
        date = date or None

        students = class_obj.students.filter(status='active').order_by('last_name', 'first_name')
        attendance_records = Attendance.objects.filter(class_obj=class_obj, date=date) if date else []

        # Map student id to attendance record
        attendance_map = {a.student_id: a for a in attendance_records}

        context = {
            'class_obj': class_obj,
            'date': date,
            'students': students,
            'attendance_map': attendance_map,
        }
        return render(request, 'academics/attendance_form.html', context)

    def post(self, request, class_pk, date):
        staff = get_object_or_404(Staff, user=request.user)
        class_obj = get_object_or_404(Class, pk=class_pk, class_teacher=staff)

        students = class_obj.students.filter(status='active')
        for student in students:
            status = request.POST.get(f'status_{student.pk}', AttendanceStatus.ABSENT)
            arrival_time = request.POST.get(f'arrival_time_{student.pk}', None)
            departure_time = request.POST.get(f'departure_time_{student.pk}', None)
            remarks = request.POST.get(f'remarks_{student.pk}', '')

            attendance, created = Attendance.objects.get_or_create(
                student=student,
                class_obj=class_obj,
                date=date,
                defaults={'status': status, 'arrival_time': arrival_time, 'departure_time': departure_time, 'remarks': remarks, 'recorded_by': request.user}
            )
            if not created:
                attendance.status = status
                attendance.arrival_time = arrival_time
                attendance.departure_time = departure_time
                attendance.remarks = remarks
                attendance.recorded_by = request.user
                attendance.save()

        messages.success(request, f"Attendance for {class_obj.name} on {date} saved successfully.")
        return redirect('academics:attendance', class_pk=class_obj.pk, date=date)


# --- Grade Entry Views ---

class GradeEntryView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ['teacher']

    def get(self, request, exam_pk, class_pk, subject_pk):
        staff = get_object_or_404(Staff, user=request.user)
        exam = get_object_or_404(Exam, pk=exam_pk)
        class_obj = get_object_or_404(Class, pk=class_pk)
        subject = get_object_or_404(Subject, pk=subject_pk)

        # Verify teacher assignment
        if not ClassSubject.objects.filter(class_obj=class_obj, subject=subject, teacher=staff).exists():
            messages.error(request, "You are not assigned to this subject/class.")
            return redirect('portal:dashboard')

        students = class_obj.students.filter(status='active').order_by('last_name', 'first_name')
        grades = Grade.objects.filter(exam=exam, subject=subject, student__in=students)
        grade_map = {g.student_id: g for g in grades}

        context = {
            'exam': exam,
            'class_obj': class_obj,
            'subject': subject,
            'students': students,
            'grade_map': grade_map,
        }
        return render(request, 'academics/grade_entry_form.html', context)

    def post(self, request, exam_pk, class_pk, subject_pk):
        staff = get_object_or_404(Staff, user=request.user)
        exam = get_object_or_404(Exam, pk=exam_pk)
        class_obj = get_object_or_404(Class, pk=class_pk)
        subject = get_object_or_404(Subject, pk=subject_pk)

        if not ClassSubject.objects.filter(class_obj=class_obj, subject=subject, teacher=staff).exists():
            messages.error(request, "You are not assigned to this subject/class.")
            return redirect('portal:dashboard')

        students = class_obj.students.filter(status='active')
        for student in students:
            marks_str = request.POST.get(f'marks_{student.pk}', '').strip()
            remarks = request.POST.get(f'remarks_{student.pk}', '').strip()
            if marks_str == '':
                continue
            try:
                marks = float(marks_str)
            except ValueError:
                messages.error(request, f"Invalid marks for {student.full_name}.")
                continue

            grade, created = Grade.objects.get_or_create(
                student=student,
                exam=exam,
                subject=subject,
                defaults={'marks': marks, 'remarks': remarks, 'entered_by': request.user}
            )
            if not created:
                grade.marks = marks
                grade.remarks = remarks
                grade.modified_by = request.user
                grade.save()

        messages.success(request, f"Grades for {subject.name} in {exam.name} saved successfully.")
        return redirect('academics:grade_entry', exam_pk=exam.pk, class_pk=class_obj.pk, subject_pk=subject.pk)


# --- Simple Reports ---

class AcademicReportView(LoginRequiredMixin, RoleRequiredMixin, TemplateView):
    template_name = 'academics/academic_report.html'
    allowed_roles = ['super_admin', 'school_admin']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Example: aggregate average marks per class and subject for current term
        current_term = Term.objects.filter(is_current=True).first()
        if not current_term:
            context['error'] = "No current term set."
            return context

        classes = Class.objects.filter(academic_year=current_term.academic_year)
        report_data = []
        for cls in classes:
            subjects = Subject.objects.filter(class_subjects__class_obj=cls).distinct()
            class_data = {'class': cls, 'subjects': []}
            for subject in subjects:
                avg_mark = Grade.objects.filter(
                    exam__term=current_term,
                    subject=subject,
                    student__current_class=cls
                ).aggregate(avg=Avg('marks'))['avg']
                class_data['subjects'].append({'subject': subject, 'avg_mark': avg_mark})
            report_data.append(class_data)
        context['report_data'] = report_data
        context['current_term'] = current_term
        return context