# academics/views.py

from django.views.generic import (
    ListView, CreateView, UpdateView, DetailView, TemplateView, FormView, View
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.db.models import Q, Avg
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from core.mixins import RoleRequiredMixin, OrganizationFilterMixin
from accounts.models import UserRole
from .models import (
    AcademicYear, Term, Department, Staff, Class, Subject,
    ClassSubject, Exam, Grade, Attendance, Timetable, ReportCard, LeaveApplication
)
from .forms import (
    AcademicYearForm, TermForm, SubjectForm, ClassForm,
    ClassSubjectForm, ExamForm, AttendanceForm, GradeForm
)
from students.models import Student


# --- Academic Year Views ---

class AcademicYearListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    model = AcademicYear
    template_name = 'academics/academic_year_list.html'
    context_object_name = 'academic_years'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]


class AcademicYearCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    model = AcademicYear
    form_class = AcademicYearForm
    template_name = 'academics/academic_year_form.html'
    success_url = reverse_lazy('academics:academic_year_list')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]


class AcademicYearUpdateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, UpdateView):
    model = AcademicYear
    form_class = AcademicYearForm
    template_name = 'academics/academic_year_form.html'
    success_url = reverse_lazy('academics:academic_year_list')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]


# --- Term Views ---

class TermListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    model = Term
    template_name = 'academics/term_list.html'
    context_object_name = 'terms'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]


class TermCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    model = Term
    form_class = TermForm
    template_name = 'academics/term_form.html'
    success_url = reverse_lazy('academics:term_list')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]


class TermUpdateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, UpdateView):
    model = Term
    form_class = TermForm
    template_name = 'academics/term_form.html'
    success_url = reverse_lazy('academics:term_list')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]


# --- Subject Views ---

class SubjectListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    model = Subject
    template_name = 'academics/subject_list.html'
    context_object_name = 'subjects'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]


class SubjectCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    model = Subject
    form_class = SubjectForm
    template_name = 'academics/subject_form.html'
    success_url = reverse_lazy('academics:subject_list')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]


class SubjectUpdateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, UpdateView):
    model = Subject
    form_class = SubjectForm
    template_name = 'academics/subject_form.html'
    success_url = reverse_lazy('academics:subject_list')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]


# --- Class Views ---

class ClassListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    model = Class
    template_name = 'academics/class_list.html'
    context_object_name = 'classes'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]


class ClassCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    model = Class
    form_class = ClassForm
    template_name = 'academics/class_form.html'
    success_url = reverse_lazy('academics:class_list')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]


class ClassUpdateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, UpdateView):
    model = Class
    form_class = ClassForm
    template_name = 'academics/class_form.html'
    success_url = reverse_lazy('academics:class_list')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]


# --- ClassSubject Views ---

class ClassSubjectListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    model = ClassSubject
    template_name = 'academics/class_subject_list.html'
    context_object_name = 'class_subjects'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]


class ClassSubjectCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    model = ClassSubject
    form_class = ClassSubjectForm
    template_name = 'academics/class_subject_form.html'
    success_url = reverse_lazy('academics:class_subject_list')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]


class ClassSubjectUpdateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, UpdateView):
    model = ClassSubject
    form_class = ClassSubjectForm
    template_name = 'academics/class_subject_form.html'
    success_url = reverse_lazy('academics:class_subject_list')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]


# --- Exam Views ---

class ExamListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    model = Exam
    template_name = 'academics/exam_list.html'
    context_object_name = 'exams'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]


class ExamCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    model = Exam
    form_class = ExamForm
    template_name = 'academics/exam_form.html'
    success_url = reverse_lazy('academics:exam_list')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]


class ExamUpdateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, UpdateView):
    model = Exam
    form_class = ExamForm
    template_name = 'academics/exam_form.html'
    success_url = reverse_lazy('academics:exam_list')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]


# --- Attendance Views ---

class AttendanceListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    model = Attendance
    template_name = 'academics/attendance_list.html'
    context_object_name = 'attendance_records'
    allowed_roles = [UserRole.TEACHER, UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def get_queryset(self):
        queryset = super().get_queryset()
        # Teachers see attendance for their classes only
        if self.request.user.role == UserRole.TEACHER:
            try:
                staff = Staff.objects.get(user=self.request.user, organization=self.request.organization)
                classes = Class.objects.filter(class_teacher=staff, organization=self.request.organization)
                queryset = queryset.filter(class_obj__in=classes)
            except Staff.DoesNotExist:
                queryset = queryset.none()
        return queryset.order_by('-date')


class AttendanceCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
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

class GradeEntryView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
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

class AcademicReportView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, TemplateView):
    template_name = 'academics/academic_report.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

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


# ============== REPORT CARDS ==============

class ReportCardGenerateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    """Generate report cards for a class/term."""
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    
    def post(self, request):
        from .services.report_card_service import ReportCardService
        
        class_id = request.POST.get('class_id')
        term_id = request.POST.get('term_id')
        
        try:
            from academics.models import Class as ClassModel
            class_obj = get_object_or_404(ClassModel, pk=class_id, organization=request.organization)
            term = get_object_or_404(Term, pk=term_id, organization=request.organization)
            
            result = ReportCardService.generate_report_cards_for_class(
                class_obj=class_obj,
                term=term,
                organization=request.organization
            )
            
            messages.success(
                request,
                f"Report cards generated! Created: {result['created']}, Updated: {result['updated']}, Errors: {result['errors']}"
            )
        except Exception as e:
            logger.error(f"Error generating report cards: {str(e)}", exc_info=True)
            messages.error(request, f"Error generating report cards: {str(e)}")
        
        return redirect('academics:academic_report')


class ReportCardDetailView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, DetailView):
    """View individual report card."""
    model = ReportCard
    template_name = 'academics/report_card_detail.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.TEACHER]
    
    def get_queryset(self):
        return super().get_queryset().select_related('student', 'term', 'class_obj')


class ReportCardPublishView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    """Publish report cards (make visible to parents)."""
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    
    def post(self, request, pk):
        report_card = get_object_or_404(ReportCard, pk=pk, organization=request.organization)
        report_card.is_published = True
        report_card.published_at = timezone.now()
        report_card.save()
        messages.success(request, f"Report card for {report_card.student.full_name} published.")
        return redirect('academics:report_card_detail', pk=pk)


# ============== TIMETABLE ==============

class TimetableListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    """List timetable entries by class or teacher."""
    model = Timetable
    template_name = 'academics/timetable_list.html'
    context_object_name = 'timetable_entries'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.TEACHER]
    
    def get_queryset(self):
        queryset = super().get_queryset().select_related('class_obj', 'subject', 'teacher', 'term')
        
        class_id = self.request.GET.get('class_id')
        teacher_id = self.request.GET.get('teacher_id')
        term_id = self.request.GET.get('term_id')
        
        if class_id:
            queryset = queryset.filter(class_obj_id=class_id)
        if teacher_id:
            queryset = queryset.filter(teacher_id=teacher_id)
        if term_id:
            queryset = queryset.filter(term_id=term_id)
        
        return queryset.order_by('day_of_week', 'start_time')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['classes'] = Class.objects.filter(organization=self.request.organization)
        context['terms'] = Term.objects.filter(organization=self.request.organization)
        context['is_admin'] = self.request.user.role in [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
        return context


class TimetableCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    """Create a new timetable entry."""
    model = Timetable
    template_name = 'academics/timetable_form.html'
    fields = ['class_obj', 'subject', 'teacher', 'day_of_week', 'start_time', 'end_time', 'room', 'term']
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('academics:timetable_list')
    
    def form_valid(self, form):
        from .services.timetable_service import TimetableService
        
        # Check for conflicts
        conflict_check = TimetableService.check_conflicts(
            class_obj=form.instance.class_obj,
            day=form.instance.day_of_week,
            start_time=form.instance.start_time,
            end_time=form.instance.end_time,
            teacher=form.instance.teacher,
            room=form.instance.room if form.instance.room else None,
            organization=self.request.organization
        )
        
        if conflict_check['has_conflict']:
            for conflict in conflict_check['conflicts']:
                messages.warning(self.request, conflict)
            return self.form_invalid(form)
        
        return super().form_valid(form)


class TimetableUpdateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, UpdateView):
    """Update a timetable entry."""
    model = Timetable
    template_name = 'academics/timetable_form.html'
    fields = ['class_obj', 'subject', 'teacher', 'day_of_week', 'start_time', 'end_time', 'room', 'term']
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('academics:timetable_list')
    
    def form_valid(self, form):
        from .services.timetable_service import TimetableService
        
        # Check for conflicts (excluding current entry)
        conflict_check = TimetableService.check_conflicts(
            class_obj=form.instance.class_obj,
            day=form.instance.day_of_week,
            start_time=form.instance.start_time,
            end_time=form.instance.end_time,
            teacher=form.instance.teacher,
            room=form.instance.room if form.instance.room else None,
            exclude_timetable_id=self.object.id,
            organization=self.request.organization
        )
        
        if conflict_check['has_conflict']:
            for conflict in conflict_check['conflicts']:
                messages.warning(self.request, conflict)
            return self.form_invalid(form)
        
        return super().form_valid(form)


class TeacherScheduleView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    """View teacher's weekly schedule."""
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.TEACHER]
    
    def get(self, request, staff_id=None):
        # If teacher, use their own staff profile
        if request.user.role == UserRole.TEACHER:
            try:
                staff = Staff.objects.get(user=request.user, organization=request.organization)
            except Staff.DoesNotExist:
                messages.error(request, "You don't have a staff profile.")
                return redirect('portal:dashboard_teacher')
        else:
            staff = get_object_or_404(Staff, pk=staff_id, organization=request.organization)
        
        term_id = request.GET.get('term_id')
        if term_id:
            term = get_object_or_404(Term, pk=term_id, organization=request.organization)
        else:
            term = Term.objects.filter(is_current=True, organization=request.organization).first()
        
        timetable_entries = Timetable.objects.filter(
            teacher=staff,
            term=term,
            organization=request.organization
        ).select_related('class_obj', 'subject').order_by('day_of_week', 'start_time')
        
        # Group by day
        schedule = {}
        for entry in timetable_entries:
            day = entry.get_day_of_week_display()
            if day not in schedule:
                schedule[day] = []
            schedule[day].append(entry)
        
        context = {
            'staff': staff,
            'term': term,
            'schedule': schedule,
        }
        return render(request, 'academics/teacher_schedule.html', context)


# ============== STAFF MANAGEMENT ==============

class StaffListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    """List all staff members."""
    model = Staff
    template_name = 'academics/staff_list.html'
    context_object_name = 'staff_members'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    paginate_by = 20
    
    def get_queryset(self):
        queryset = super().get_queryset().select_related('user', 'department')
        
        department_id = self.request.GET.get('department')
        staff_type = self.request.GET.get('staff_type')
        status = self.request.GET.get('status')
        
        if department_id:
            queryset = queryset.filter(department_id=department_id)
        if staff_type:
            queryset = queryset.filter(staff_type=staff_type)
        if status:
            queryset = queryset.filter(status=status)
        
        return queryset.order_by('staff_number')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from .models import Department
        context['departments'] = Department.objects.filter(organization=self.request.organization)
        return context


class StaffCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    """Create a new staff member."""
    model = Staff
    template_name = 'academics/staff_form.html'
    fields = ['user', 'staff_number', 'staff_type', 'department', 'id_number', 'tsc_number', 
              'date_of_birth', 'gender', 'phone_number', 'address', 'date_joined', 
              'employment_type', 'qualifications', 'specialization', 'status']
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('academics:staff_list')


class StaffUpdateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, UpdateView):
    """Update staff member."""
    model = Staff
    template_name = 'academics/staff_form.html'
    fields = ['user', 'staff_number', 'staff_type', 'department', 'id_number', 'tsc_number', 
              'date_of_birth', 'gender', 'phone_number', 'address', 'date_joined', 
              'employment_type', 'qualifications', 'specialization', 'status']
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('academics:staff_list')


class StaffDetailView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, DetailView):
    """View staff member details."""
    model = Staff
    template_name = 'academics/staff_detail.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    
    def get_queryset(self):
        return super().get_queryset().select_related('user', 'department')


# ============== LEAVE MANAGEMENT ==============

class LeaveApplicationListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    """List leave applications."""
    model = LeaveApplication
    template_name = 'academics/leave_application_list.html'
    context_object_name = 'leave_applications'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.TEACHER]
    paginate_by = 20
    
    def get_queryset(self):
        queryset = super().get_queryset().select_related('staff', 'approved_by')
        
        # Teachers see only their own applications
        if self.request.user.role == UserRole.TEACHER:
            try:
                staff = Staff.objects.get(user=self.request.user, organization=self.request.organization)
                queryset = queryset.filter(staff=staff)
            except Staff.DoesNotExist:
                queryset = queryset.none()
        
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        return queryset.order_by('-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_admin'] = self.request.user.role in [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
        return context


class LeaveApplicationCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    """Create a leave application (for teachers)."""
    model = LeaveApplication
    template_name = 'academics/leave_application_form.html'
    fields = ['leave_type', 'start_date', 'end_date', 'reason']
    allowed_roles = [UserRole.TEACHER]
    success_url = reverse_lazy('academics:leave_application_list')
    
    def form_valid(self, form):
        # Get staff for current user
        try:
            staff = Staff.objects.get(user=self.request.user, organization=self.request.organization)
        except Staff.DoesNotExist:
            messages.error(self.request, "You don't have a staff profile.")
            return self.form_invalid(form)
        
        form.instance.staff = staff
        form.instance.organization = self.request.organization
        return super().form_valid(form)


class LeaveApplicationApproveView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    """Approve or reject leave application (for admins)."""
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    
    def get(self, request, pk):
        leave = get_object_or_404(LeaveApplication, pk=pk, organization=request.organization)
        action = request.GET.get('action')  # 'approve' or 'reject'
        
        if action == 'approve':
            leave.status = 'approved'
            leave.approved_by = request.user
            leave.approved_at = timezone.now()
            leave.save()
            messages.success(request, f"Leave application approved.")
        elif action == 'reject':
            leave.status = 'rejected'
            leave.approved_by = request.user
            leave.approved_at = timezone.now()
            leave.rejection_reason = request.GET.get('rejection_reason', '')
            leave.save()
            messages.success(request, f"Leave application rejected.")
        
        return redirect('academics:leave_application_list')