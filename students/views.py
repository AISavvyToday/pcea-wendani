# students/views.py
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import ListView, CreateView, UpdateView, DetailView, FormView
from django.core.paginator import Paginator
from django.db import transaction
from django.views.generic import DeleteView
from django.urls import reverse_lazy
from django.contrib import messages
from core.mixins import RoleRequiredMixin
from accounts.models import User
from .models import Student, Parent, StudentParent
from .forms import StudentForm, ParentForm, StudentSearchForm, StudentPromotionForm
from .services import StudentService
from academics.models import Class, AcademicYear, Term
from core.models import UserRole


class StudentListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    """List all students with search and filters"""

    model = Student
    template_name = 'students/student_list.html'
    context_object_name = 'students'
    paginate_by = 20
    allowed_roles = [
        UserRole.SUPER_ADMIN,
        UserRole.SCHOOL_ADMIN,
        UserRole.ACCOUNTANT,
        UserRole.TEACHER
    ]

    def get_queryset(self):
        queryset = Student.objects.select_related('current_class').prefetch_related('parents')

        # Get filter parameters
        query = self.request.GET.get('query', '')
        class_id = self.request.GET.get('current_class', '')  # Use 'current_class' as per form field name
        status = self.request.GET.get('status', '')  # Use 'status' as per form field name
        gender = self.request.GET.get('gender', '')  # Use 'gender' as per form field name
        is_boarder = self.request.GET.get('is_boarder', '')  # Use 'is_boarder' as per form field name
        stream = self.request.GET.get('stream', '')  # ADD THIS LINE: Get stream from form

        # Apply filters via service
        queryset = StudentService.search_students(
            query=query if query else None,
            class_id=class_id if class_id else None,
            status=status if status else None,
            gender=gender if gender else None,  # ADD THIS LINE
            is_boarder=is_boarder if is_boarder else None,  # ADD THIS LINE
            stream=stream if stream else None  # ADD THIS LINE
        )

        return queryset

    def get_paginate_by(self, queryset):
        per_page = self.request.GET.get('per_page')
        try:
            per_page = int(per_page)
            if per_page <= 0:
                raise ValueError()
        except Exception:
            per_page = self.paginate_by
        return per_page

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_form'] = StudentSearchForm(self.request.GET)
        context['total_students'] = Student.objects.count()
        context['active_students'] = Student.objects.filter(status='active').count()
        return context


class StudentCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    """Create a new student"""

    model = Student
    form_class = StudentForm
    template_name = 'students/student_form.html'
    success_url = reverse_lazy('students:list')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Register New Student'
        context['button_text'] = 'Register Student'

        if self.request.POST:
            context['parent_form_1'] = ParentForm(self.request.POST, prefix='parent1')
            context['parent_form_2'] = ParentForm(self.request.POST, prefix='parent2')
        else:
            context['parent_form_1'] = ParentForm(prefix='parent1')
            context['parent_form_2'] = ParentForm(prefix='parent2')

        return context

    def form_valid(self, form):
        context = self.get_context_data()
        parent_form_1 = context['parent_form_1']
        parent_form_2 = context['parent_form_2']

        # Prepare student data
        student_data = form.cleaned_data

        # Prepare parents data
        parents_data = []

        if parent_form_1.is_valid() and parent_form_1.cleaned_data.get('first_name'):
            parent_1_data = parent_form_1.cleaned_data.copy()
            parent_1_data['is_primary'] = parent_1_data.pop('is_primary', True)
            parents_data.append(parent_1_data)

        if parent_form_2.is_valid() and parent_form_2.cleaned_data.get('first_name'):
            parent_2_data = parent_form_2.cleaned_data.copy()
            parent_2_data['is_primary'] = parent_2_data.pop('is_primary', False)
            parents_data.append(parent_2_data)

        try:
            # Use service to create student with parents
            student = StudentService.create_student_with_parents(
                student_data=student_data,
                parents_data=parents_data if parents_data else None
            )

            messages.success(
                self.request,
                f'Student {student.get_full_name()} registered successfully!'
            )
            return redirect(self.success_url)

        except Exception as e:
            messages.error(self.request, f'Error registering student: {str(e)}')
            return self.form_invalid(form)


class StudentUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    """Edit existing student"""

    model = Student
    form_class = StudentForm
    template_name = 'students/student_form.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def get_success_url(self):
        return reverse_lazy('students:detail', kwargs={'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Student: {self.object.get_full_name()}'
        context['button_text'] = 'Update Student'
        context['is_edit'] = True
        return context

    def form_valid(self, form):
        messages.success(self.request, 'Student updated successfully!')
        return super().form_valid(form)


class StudentDetailView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    model = Student
    template_name = 'students/student_detail.html'
    context_object_name = 'student'
    allowed_roles = [
        UserRole.SUPER_ADMIN,
        UserRole.SCHOOL_ADMIN,
        UserRole.ACCOUNTANT,
        UserRole.TEACHER
    ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        student = self.object

        # Core profile data using service
        profile_data = StudentService.get_student_profile_data(student)
        context.update(profile_data)

        # ----------------------------
        # FINANCE DATA
        # ----------------------------
        invoices = student.invoices.select_related('term').order_by('-issue_date')[:25]
        payments = student.payments.order_by('-payment_date')[:25]

        context['invoices'] = invoices
        context['payments'] = payments

        # Total paid (sum of completed payments)
        total_paid = student.payments.filter(
            status='completed'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        context['total_paid'] = total_paid

        # Outstanding balance (from invoices)
        outstanding_balance = student.invoices.filter(
            is_active=True
        ).exclude(
            status=InvoiceStatus.CANCELLED
        ).aggregate(total=Sum('balance'))['total'] or Decimal('0.00')
        context['outstanding_balance'] = outstanding_balance

        # ✅ CREDIT / PREPAYMENT - Get from student.credit_balance field
        credit_balance = student.credit_balance

        # Display logic:
        # If credit_balance is NEGATIVE = student has prepayment/credit
        # If credit_balance is POSITIVE = student owes money (debt)

        # For template display, we want to show prepayment/credit as positive number
        # and debt as positive number (in the outstanding balance section)

        # Calculate display values:
        if credit_balance < 0:
            # Student has credit (prepayment)
            context['credit_balance'] = abs(credit_balance)  # Show as positive for display
            context['has_credit'] = True
            context['has_debt'] = False
        else:
            # Student owes money (or balance is zero)
            context['credit_balance'] = Decimal('0.00')  # No credit to display
            context['has_credit'] = False
            context['has_debt'] = credit_balance > 0
            # Add debt to outstanding balance
            if credit_balance > 0:
                context['outstanding_balance'] += credit_balance

        # Keep original for calculations if needed
        context['raw_credit_balance'] = credit_balance

        # ----------------------------
        # DOCUMENTS & RECORDS
        # ----------------------------
        context['documents'] = student.documents.order_by('-created_at')[:50]
        context['discipline_records'] = student.discipline_records.order_by('-incident_date')[:50]
        context['medical_records'] = student.medical_records.order_by('-record_date')[:50]
        context['grades'] = student.grades.select_related(
            'exam', 'subject'
        ).order_by('-entered_at')[:100]
        context['attendance_recent'] = student.attendance_records.select_related(
            'class_obj'
        ).order_by('-date')[:50]

        # Enrollment history returned by service
        context['enrollments'] = profile_data.get('enrollments', [])

        # Parents (already prepared by service)
        context['student_parents'] = profile_data.get('student_parents', [])

        # Active tab (server-side fallback)
        context['active_tab'] = self.request.GET.get('tab', 'overview')

        return context


class StudentPromotionView(LoginRequiredMixin, RoleRequiredMixin, FormView):
    """Bulk promote students to next class"""

    template_name = 'students/student_promotion.html'
    form_class = StudentPromotionForm
    success_url = reverse_lazy('students:list')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()

        # Get students from selected class
        class_id = self.request.GET.get('class_id')
        if class_id:
            students = Student.objects.filter(
                current_class_id=class_id,
                status='active'
            )
        else:
            students = Student.objects.filter(status='active')

        kwargs['students'] = students
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['classes'] = Class.objects.all()
        context['selected_class'] = self.request.GET.get('class_id')
        context['current_year'] = AcademicYear.objects.filter(is_current=True).first()
        context['current_term'] = Term.objects.filter(is_current=True).first()
        return context

    def form_valid(self, form):
        student_ids = form.cleaned_data['student_ids']
        target_class = form.cleaned_data['target_class']

        # Get current academic year and term
        academic_year = AcademicYear.objects.filter(is_current=True).first()
        term = Term.objects.filter(is_current=True).first()

        if not academic_year or not term:
            messages.error(self.request, 'No current academic year or term set.')
            return redirect('students:promote')

        try:
            promoted_count = StudentService.promote_students(
                student_ids=student_ids,
                target_class=target_class,
                academic_year=academic_year,
                term=term
            )

            messages.success(
                self.request,
                f'Successfully promoted {promoted_count} student(s) to {target_class.name}!'
            )
        except Exception as e:
            messages.error(self.request, f'Error promoting students: {str(e)}')

        return redirect(self.success_url)


class StudentDeleteView(LoginRequiredMixin, RoleRequiredMixin, DeleteView):
    """
    View for soft-deleting a student record.
    Only accessible by Super Admin and School Admin.
    """
    model = Student
    template_name = 'students/student_confirm_delete.html'
    success_url = reverse_lazy('students:list')
    context_object_name = 'student'

    allowed_roles = [
        UserRole.SUPER_ADMIN,
        UserRole.SCHOOL_ADMIN,
    ]

    def delete(self, request, *args, **kwargs):
        """
        Perform soft delete instead of hard delete.
        Changes student status to 'inactive' instead of removing from database.
        """
        self.object = self.get_object()
        success_url = self.get_success_url()

        # Soft delete - change status to inactive
        self.object.status = 'inactive'
        self.object.status_date = timezone.now()
        self.object.status_reason = f"Deleted by {request.user.get_full_name()}"
        self.object.save()

        messages.success(
            request,
            f'Student {self.object.full_name} ({self.object.admission_number}) has been deactivated successfully.'
        )

        return HttpResponseRedirect(success_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Delete Student'

        # Get related data to show what will be affected
        student = self.object
        context['related_data'] = {
            'parents': student.parents.count(),
            'invoices': student.invoices.count(),
            'payments': student.payments.count(),
            'attendance_records': student.attendance_records.count(),
        }

        return context


# students/views.py - Add these views at the end

class ParentListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    """List all parents/guardians with search"""

    model = Parent
    template_name = 'students/parent_list.html'
    context_object_name = 'parents'
    paginate_by = 20
    allowed_roles = [
        UserRole.SUPER_ADMIN,
        UserRole.SCHOOL_ADMIN,
        UserRole.ACCOUNTANT,
        UserRole.TEACHER
    ]

    def get_queryset(self):
        queryset = Parent.objects.prefetch_related('children').all()

        # Search functionality
        query = self.request.GET.get('query', '')
        if query:
            queryset = queryset.filter(
                Q(first_name__icontains=query) |
                Q(last_name__icontains=query) |
                Q(phone_primary__icontains=query) |
                Q(id_number__icontains=query) |
                Q(email__icontains=query)
            )

        # Filter by relationship
        relationship = self.request.GET.get('relationship', '')
        if relationship:
            queryset = queryset.filter(relationship=relationship)

        return queryset.order_by('last_name', 'first_name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['total_parents'] = Parent.objects.count()
        context['query'] = self.request.GET.get('query', '')
        context['relationship_filter'] = self.request.GET.get('relationship', '')
        context['relationship_choices'] = Parent.RELATIONSHIP_CHOICES
        return context


class ParentDetailView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    """Parent profile with their children"""

    model = Parent
    template_name = 'students/parent_detail.html'
    context_object_name = 'parent'
    allowed_roles = [
        UserRole.SUPER_ADMIN,
        UserRole.SCHOOL_ADMIN,
        UserRole.ACCOUNTANT,
        UserRole.TEACHER
    ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get all children with their relationships
        context['children'] = StudentParent.objects.filter(
            parent=self.object
        ).select_related('student', 'student__current_class')

        # Get total outstanding balance for all children
        total_balance = 0
        for sp in context['children']:
            # This will be implemented when finance module is ready
            # total_balance += sp.student.get_outstanding_balance()
            pass

        context['total_balance'] = total_balance
        context['active_tab'] = self.request.GET.get('tab', 'overview')

        return context


class ParentCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    """Create a new parent/guardian"""

    model = Parent
    form_class = ParentForm
    template_name = 'students/parent_form.html'
    success_url = reverse_lazy('students:parent_list')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Register New Parent/Guardian'
        context['button_text'] = 'Register Parent'
        return context

    def form_valid(self, form):
        messages.success(
            self.request,
            f'Parent/Guardian {form.instance.full_name} registered successfully!'
        )
        return super().form_valid(form)


class ParentUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    """Edit existing parent/guardian"""

    model = Parent
    form_class = ParentForm
    template_name = 'students/parent_form.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def get_success_url(self):
        return reverse_lazy('students:parent_detail', kwargs={'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Parent: {self.object.full_name}'
        context['button_text'] = 'Update Parent'
        context['is_edit'] = True
        return context

    def form_valid(self, form):
        messages.success(self.request, 'Parent/Guardian updated successfully!')
        return super().form_valid(form)


class ParentDeleteView(LoginRequiredMixin, RoleRequiredMixin, DeleteView):
    """Soft delete a parent/guardian"""

    model = Parent
    template_name = 'students/parent_confirm_delete.html'
    success_url = reverse_lazy('students:parent_list')
    context_object_name = 'parent'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        success_url = self.get_success_url()

        # Check if parent has children
        children_count = self.object.children.count()
        if children_count > 0:
            messages.error(
                request,
                f'Cannot delete {self.object.full_name}. They have {children_count} child(ren) linked. Please unlink children first.'
            )
            return redirect('students:parent_detail', pk=self.object.pk)

        # Delete parent
        parent_name = self.object.full_name
        self.object.delete()

        messages.success(
            request,
            f'Parent/Guardian {parent_name} has been deleted successfully.'
        )

        return HttpResponseRedirect(success_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Delete Parent/Guardian'
        context['children'] = self.object.children.all()
        return context