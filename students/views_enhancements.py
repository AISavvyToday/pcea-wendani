from io import BytesIO

import openpyxl
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import urlencode
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView, View
from openpyxl.styles import Alignment, Font
from academics.models import Class
from academics.services.term_state import sync_student_term_state
from core.mixins import OrganizationFilterMixin, RoleRequiredMixin
from core.models import UserRole
from .forms_enhancements import BulkStreamTransferForm, ClubForm, ClubMembershipForm, order_students_by_grade
from .models import Club, ClubMembership, Student


def _fallback_pdf_bytes(title):
    body = f"PDF export unavailable: {title}".encode("utf-8")
    padding = b" " * 160
    return (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R >> endobj\n"
        b"4 0 obj << /Length "
        + str(len(body) + len(padding)).encode("ascii")
        + b" >> stream\n"
        + body
        + padding
        + b"\nendstream endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
    )


class ClubOrganizationMixin:
    def get_queryset(self):
        queryset = Club.objects.filter(is_active=True).prefetch_related(
            Prefetch(
                'memberships',
                queryset=ClubMembership.objects.filter(is_active=True).select_related('student', 'student__current_class')
            )
        )
        organization = getattr(self.request, 'organization', None)
        if organization is None:
            return queryset.none()
        return queryset.filter(organization=organization)


class ClubListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = Club
    template_name = 'students/club_list.html'
    context_object_name = 'clubs'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT, UserRole.TEACHER]

    def get_queryset(self):
        queryset = Club.objects.filter(is_active=True)
        organization = getattr(self.request, 'organization', None)
        if organization is None:
            return queryset.none()
        query = self.request.GET.get('query', '').strip()
        queryset = queryset.filter(organization=organization).annotate(
            active_member_count=Count('memberships', filter=Q(memberships__is_active=True))
        )
        if query:
            queryset = queryset.filter(
                Q(name__icontains=query) |
                Q(code__icontains=query) |
                Q(description__icontains=query) |
                Q(patron_name__icontains=query)
            )
        return queryset.order_by('name')


class ClubCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    model = Club
    form_class = ClubForm
    template_name = 'students/club_form.html'
    success_url = reverse_lazy('students:club_list')
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Club'
        context['button_text'] = 'Create Club'
        return context


class ClubUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    model = Club
    form_class = ClubForm
    template_name = 'students/club_form.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def get_queryset(self):
        organization = getattr(self.request, 'organization', None)
        if organization is None:
            return Club.objects.none()
        return Club.objects.filter(organization=organization, is_active=True)

    def get_success_url(self):
        return reverse_lazy('students:club_detail', kwargs={'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Edit Club: {self.object.name}'
        context['button_text'] = 'Save Changes'
        return context


class ClubDetailView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    model = Club
    template_name = 'students/club_detail.html'
    context_object_name = 'club'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT, UserRole.TEACHER]

    def get_queryset(self):
        organization = getattr(self.request, 'organization', None)
        queryset = Club.objects.filter(is_active=True).prefetch_related(
            Prefetch(
                'memberships',
                queryset=ClubMembership.objects.filter(is_active=True).select_related('student', 'student__current_class')
            )
        )
        if organization is None:
            return queryset.none()
        return queryset.filter(organization=organization)

    def get_memberships(self):
        memberships = self.object.memberships.filter(is_active=True).select_related('student', 'student__current_class')
        membership_ids = list(memberships.values_list('pk', flat=True))
        ordered_students = order_students_by_grade(Student.objects.filter(club_memberships__pk__in=membership_ids)).values_list('pk', flat=True)
        student_order = {student_id: index for index, student_id in enumerate(ordered_students)}
        return sorted(memberships, key=lambda membership: student_order.get(membership.student_id, 999999))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['memberships'] = self.get_memberships()
        context['membership_form'] = kwargs.get('membership_form') or ClubMembershipForm(
            self.request.GET or None,
            organization=getattr(self.request, 'organization', None),
            club=self.object,
        )
        return context


class ClubMembershipUpdateView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def post(self, request, pk):
        organization = getattr(request, 'organization', None)
        club = get_object_or_404(Club, pk=pk, organization=organization, is_active=True)
        form = ClubMembershipForm(request.POST, organization=organization, club=club)
        if not form.is_valid():
            messages.error(request, 'Select at least one student to assign to the club.')
            detail_view = ClubDetailView()
            detail_view.request = request
            detail_view.object = club
            return detail_view.render_to_response(detail_view.get_context_data(membership_form=form))

        created_count = 0
        reactivated_count = 0
        with transaction.atomic():
            for student in form.cleaned_data['students']:
                membership, created = ClubMembership.objects.get_or_create(
                    club=club,
                    student=student,
                    defaults={'is_active': True},
                )
                if created:
                    created_count += 1
                elif not membership.is_active:
                    membership.is_active = True
                    membership.save(update_fields=['is_active', 'updated_at'])
                    reactivated_count += 1

        messages.success(
            request,
            f'Club updated. Added {created_count} new member(s)' + (
                f' and reactivated {reactivated_count} member(s).' if reactivated_count else '.'
            )
        )
        return redirect('students:club_detail', pk=club.pk)


class ClubMembershipRemoveView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def post(self, request, pk, membership_pk):
        organization = getattr(request, 'organization', None)
        club = get_object_or_404(Club, pk=pk, organization=organization, is_active=True)
        membership = get_object_or_404(ClubMembership, pk=membership_pk, club=club, is_active=True)
        membership.is_active = False
        membership.save(update_fields=['is_active', 'updated_at'])
        messages.success(request, f'{membership.student.full_name} removed from {club.name}.')
        return redirect('students:club_detail', pk=club.pk)


class ClubMembersExcelExportView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT, UserRole.TEACHER]

    def get(self, request, pk):
        organization = getattr(request, 'organization', None)
        club = get_object_or_404(Club, pk=pk, organization=organization, is_active=True)
        memberships = ClubDetailView()
        memberships.request = request
        memberships.object = club
        membership_rows = memberships.get_memberships()

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Club Members'
        ws.append(['Club', 'Admission Number', 'Student Name', 'Class', 'Joined On'])
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal='center')
        for membership in membership_rows:
            ws.append([
                club.name,
                membership.student.admission_number or '',
                membership.student.full_name,
                str(membership.student.current_class or ''),
                membership.joined_on.strftime('%Y-%m-%d') if membership.joined_on else '',
            ])
        for column_cells in ws.columns:
            width = max(len(str(cell.value or '')) for cell in column_cells) + 2
            ws.column_dimensions[column_cells[0].column_letter].width = min(width, 30)

        output = BytesIO()
        wb.save(output)
        output.seek(0)
        response = HttpResponse(
            output.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="club-members-{club.name}.xlsx"'
        return response


class ClubMembersPDFExportView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT, UserRole.TEACHER]

    def get(self, request, pk):
        organization = getattr(request, 'organization', None)
        club = get_object_or_404(Club, pk=pk, organization=organization, is_active=True)
        memberships_view = ClubDetailView()
        memberships_view.request = request
        memberships_view.object = club
        membership_rows = memberships_view.get_memberships()

        try:
            from weasyprint import HTML
        except Exception as exc:
            pdf_bytes = _fallback_pdf_bytes(str(exc))
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="club-members-{club.name}.pdf"'
            return response

        html_string = render_to_string('students/pdf/club_members_list.html', {
            'club': club,
            'memberships': membership_rows,
            'request': request,
        })
        pdf_bytes = HTML(string=html_string, base_url=request.build_absolute_uri('/')).write_pdf()
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="club-members-{club.name}.pdf"'
        return response


class BulkStreamTransferView(LoginRequiredMixin, RoleRequiredMixin, TemplateView):
    template_name = 'students/bulk_stream_transfer.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    filter_fields = ('source_class', 'source_stream', 'student_search')

    def get_filter_query_string(self, data):
        query_data = {
            key: value
            for key, value in ((field, data.get(field, '')) for field in self.filter_fields)
            if value
        }
        return urlencode(query_data)

    def get_form(self, data=None, require_move_fields=False):
        return BulkStreamTransferForm(
            data=data or None,
            organization=getattr(self.request, 'organization', None),
            require_move_fields=require_move_fields,
        )

    def get(self, request, *args, **kwargs):
        form = self.get_form(data=request.GET, require_move_fields=False)
        return self.render_to_response(self.get_context_data(form=form))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = kwargs.get('form') or self.get_form(data=self.request.GET, require_move_fields=False)
        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get('action') != 'move':
            filter_query_string = self.get_filter_query_string(request.POST)
            redirect_url = reverse_lazy('students:bulk_stream_transfer')
            if filter_query_string:
                redirect_url = f'{redirect_url}?{filter_query_string}'
            return redirect(redirect_url)

        form = self.get_form(data=request.POST, require_move_fields=True)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        target_class = form.cleaned_data['target_class']
        students = form.cleaned_data['students']
        moved_count = 0
        with transaction.atomic():
            for student in students:
                if student.current_class_id == target_class.id:
                    continue
                student.current_class = target_class
                student.save(update_fields=['current_class', 'updated_at'])
                sync_student_term_state(
                    student,
                    organization=getattr(request, 'organization', None),
                )
                moved_count += 1

        messages.success(request, f'Successfully moved {moved_count} student(s) to {target_class.name}.')
        filter_query_string = self.get_filter_query_string(request.POST)
        redirect_url = reverse_lazy('students:bulk_stream_transfer')
        if filter_query_string:
            redirect_url = f'{redirect_url}?{filter_query_string}'
        return redirect(redirect_url)
