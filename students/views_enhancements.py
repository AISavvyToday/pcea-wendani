from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView, View

from academics.models import Class
from core.mixins import OrganizationFilterMixin, RoleRequiredMixin
from core.models import UserRole
from .forms_enhancements import BulkStreamTransferForm, ClubForm, ClubMembershipForm
from .models import Club, ClubMembership, Student


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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['memberships'] = self.object.memberships.filter(is_active=True).select_related('student', 'student__current_class')
        context['membership_form'] = ClubMembershipForm(
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
            return redirect('students:club_detail', pk=club.pk)

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


class BulkStreamTransferView(LoginRequiredMixin, RoleRequiredMixin, TemplateView):
    template_name = 'students/bulk_stream_transfer.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def get_form(self):
        return BulkStreamTransferForm(self.request.GET or None, organization=getattr(self.request, 'organization', None))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = kwargs.get('form') or self.get_form()
        return context

    def post(self, request, *args, **kwargs):
        form = BulkStreamTransferForm(request.POST, organization=getattr(request, 'organization', None))
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
                moved_count += 1

        messages.success(request, f'Successfully moved {moved_count} student(s) to {target_class.name}.')
        return redirect('students:bulk_stream_transfer')
