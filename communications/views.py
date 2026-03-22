"""
Communications module views for announcements, SMS, and email management.
"""

import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, TemplateView, View

from academics.models import Staff
from core.mixins import OrganizationFilterMixin, RoleRequiredMixin
from core.models import UserRole
from students.models import Parent, Student

from .models import Announcement, EmailNotification, NotificationTemplate, SMSNotification
from .services.sms_service import SMSService

logger = logging.getLogger(__name__)


class AnnouncementListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    """List all announcements."""

    model = Announcement
    template_name = 'communications/announcement_list.html'
    context_object_name = 'announcements'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]
    paginate_by = 20


class AnnouncementCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    """Create a new announcement."""

    model = Announcement
    template_name = 'communications/announcement_form.html'
    fields = ['title', 'message', 'target_audience', 'send_sms']
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('communications:announcement_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.organization = self.request.organization
        form.instance.send_email = False  # Email disabled
        return super().form_valid(form)


class AnnouncementDetailView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, DetailView):
    """View announcement details."""

    model = Announcement
    template_name = 'communications/announcement_detail.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]


class SendAnnouncementView(LoginRequiredMixin, RoleRequiredMixin, View):
    """Send an announcement to selected audience."""

    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def post(self, request, pk):
        announcement = get_object_or_404(Announcement, pk=pk, organization=request.organization)

        if announcement.is_sent:
            messages.warning(request, 'This announcement has already been sent.')
            return redirect('communications:announcement_detail', pk=pk)

        try:
            recipients = self._get_recipients(announcement, request.organization)
            sms_count = 0
            failed_count = 0
            email_count = 0

            if announcement.send_sms:
                from .services.sms_template_service import SMSTemplateService

                sms_service = _get_sms_service()
                bulk_recipients = []

                for recipient in recipients:
                    phone = recipient.get('phone')
                    if not phone:
                        continue

                    context = {
                        'parent': recipient.get('parent'),
                        'student': recipient.get('student'),
                        'invoice': recipient.get('invoice'),
                        'attendance': recipient.get('attendance'),
                        'grade': recipient.get('grade'),
                        'school': {'name': getattr(request.organization, 'name', '')},
                    }
                    personalized_message = SMSTemplateService.replace_placeholders(
                        announcement.message,
                        context,
                    )

                    bulk_recipients.append({
                        'phone': phone,
                        'message': personalized_message,
                        'parent': recipient.get('parent'),
                        'student': recipient.get('student'),
                    })

                sms_notifications = sms_service.send_bulk_sms(
                    recipients=bulk_recipients,
                    message='',
                    organization=request.organization,
                    purpose='announcement',
                    triggered_by=request.user,
                )

                for notification in sms_notifications:
                    if notification.related_announcement_id != announcement.id:
                        notification.related_announcement = announcement
                        notification.save(update_fields=['related_announcement'])

                sms_count = sum(1 for notification in sms_notifications if notification.status == 'sent')
                failed_count = sum(1 for notification in sms_notifications if notification.status == 'failed')

            announcement.is_sent = True
            announcement.sent_at = timezone.now()
            announcement.sms_count = sms_count
            announcement.email_count = email_count
            announcement.save(update_fields=['is_sent', 'sent_at', 'sms_count', 'email_count'])

            if announcement.send_sms:
                if sms_count and failed_count:
                    messages.warning(
                        request,
                        f'Announcement processed. SMS sent to {sms_count} recipient(s); {failed_count} failed.',
                    )
                elif sms_count:
                    messages.success(request, f'Announcement sent successfully. SMS: {sms_count}')
                elif failed_count:
                    messages.error(request, 'Announcement was marked as sent, but SMS sending failed for all recipients.')
                else:
                    messages.warning(request, 'Announcement was marked as sent, but no valid SMS recipients were found.')
            else:
                messages.success(request, 'Announcement saved successfully.')

            logger.info('Announcement %s processed by %s', announcement.id, request.user.email)

        except Exception as exc:
            logger.error('Error sending announcement: %s', str(exc), exc_info=True)
            messages.error(request, f'Error sending announcement: {str(exc)}')

        return redirect('communications:announcement_detail', pk=pk)

    def _get_recipients(self, announcement, organization):
        """Get recipients based on target audience."""
        recipients = []

        if announcement.target_audience in ['all', 'parents']:
            parents = Parent.objects.filter(organization=organization, is_active=True)
            for parent in parents:
                recipients.append({
                    'phone': getattr(parent, 'phone_primary', ''),
                    'email': getattr(parent, 'email', ''),
                    'parent': parent,
                    'student': _get_first_child(parent),
                })

        elif announcement.target_audience == 'teachers':
            staff_members = Staff.objects.filter(
                organization=organization,
                status='active',
                staff_type='teaching',
            ).select_related('user')
            for staff_member in staff_members:
                recipients.append({
                    'phone': getattr(staff_member, 'phone_number', '') or getattr(staff_member.user, 'phone_number', ''),
                    'email': getattr(staff_member.user, 'email', ''),
                })

        elif announcement.target_audience == 'staff':
            staff_members = Staff.objects.filter(
                organization=organization,
                status='active',
            ).select_related('user')
            for staff_member in staff_members:
                recipients.append({
                    'phone': getattr(staff_member, 'phone_number', '') or getattr(staff_member.user, 'phone_number', ''),
                    'email': getattr(staff_member.user, 'email', ''),
                })

        elif announcement.target_audience == 'students':
            students = Student.objects.filter(organization=organization, status='active').select_related('primary_parent')
            for student in students:
                parent = getattr(student, 'primary_parent', None)
                if parent:
                    recipients.append({
                        'phone': getattr(parent, 'phone_primary', ''),
                        'email': getattr(parent, 'email', ''),
                        'student': student,
                        'parent': parent,
                    })

        return recipients


class SMSNotificationListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    """List SMS notifications."""

    model = SMSNotification
    template_name = 'communications/sms_notification_list.html'
    context_object_name = 'sms_notifications'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]
    paginate_by = 50

    def get_queryset(self):
        queryset = super().get_queryset()
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        return queryset.order_by('-created_at')


class EmailNotificationListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    """List email notifications."""

    model = EmailNotification
    template_name = 'communications/email_notification_list.html'
    context_object_name = 'email_notifications'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]
    paginate_by = 50

    def get_queryset(self):
        queryset = super().get_queryset()
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        return queryset.order_by('-created_at')


class NotificationTemplateListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    """List notification templates."""

    model = NotificationTemplate
    template_name = 'communications/notification_template_list.html'
    context_object_name = 'templates'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    paginate_by = 20


class NotificationTemplateCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    """Create a new notification template."""

    model = NotificationTemplate
    template_name = 'communications/notification_template_form.html'
    fields = ['name', 'template_type', 'subject', 'template_text', 'variables', 'description']
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('communications:notification_template_list')

    def form_valid(self, form):
        form.instance.organization = self.request.organization
        return super().form_valid(form)


class SMSSettingsView(LoginRequiredMixin, RoleRequiredMixin, TemplateView):
    """SMS Credits Settings and Purchase Instructions."""

    template_name = 'communications/sms_settings.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        organization = getattr(self.request, 'organization', None)
        if organization:
            from django.conf import settings
            from .services.sms_api_client import sms_api_client

            context['organization'] = organization
            context['sms_account_number'] = organization.sms_account_number or 'Not Set'
            context['balance_api_available'] = False
            context['balance_error'] = None

            balance_result = sms_api_client.get_balance(organization)
            if balance_result.get('success'):
                context['sms_balance'] = balance_result.get('balance', 0)
                context['sms_price'] = balance_result.get(
                    'price_per_sms',
                    getattr(organization, 'sms_price_per_unit', getattr(settings, 'SWIFT_SMS_PRICE', 1.0)),
                )
                context['balance_api_available'] = True
            else:
                context['sms_balance'] = getattr(organization, 'sms_balance', 0)
                context['sms_price'] = getattr(
                    organization,
                    'sms_price_per_unit',
                    getattr(settings, 'SWIFT_SMS_PRICE', 1.0),
                )
                context['balance_error'] = (
                    balance_result.get('error')
                    or 'Live SMS balance is temporarily unavailable from the central service.'
                )

            context['paybill'] = getattr(settings, 'SWIFT_RESIDE_PAYBILL', '522533')
            context['till'] = getattr(settings, 'SWIFT_RESIDE_TILL', 'SWIFTTECH')
            context['payment_account'] = (
                f"{context['till']}#{organization.sms_account_number}"
                if organization.sms_account_number else None
            )
        return context


class SendSingleSMSView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, View):
    """Send SMS to single or multiple phone numbers."""

    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def get(self, request):
        """Show form for sending single SMS."""
        from .services.sms_template_service import SMSTemplateService

        parents = Parent.objects.filter(
            organization=request.organization,
            is_active=True,
        ).order_by('last_name', 'first_name')[:100]
        placeholders = SMSTemplateService.get_available_placeholders()

        return render(
            request,
            'communications/send_single_sms.html',
            {
                'parents': parents,
                'placeholders': placeholders,
            },
        )

    def post(self, request):
        """Send SMS to provided phone numbers."""
        from .services.sms_template_service import SMSTemplateService
        from .utils import normalize_phone_number, parse_phone_numbers

        phone_input = request.POST.get('phone_numbers', '').strip()
        parent_ids = request.POST.getlist('parent_ids')
        message = request.POST.get('message', '').strip()

        if not message:
            messages.error(request, 'Message is required.')
            return redirect('communications:send_single_sms')

        phone_numbers = []
        seen_phone_numbers = set()

        if phone_input:
            for parsed_phone in parse_phone_numbers(phone_input):
                if parsed_phone not in seen_phone_numbers:
                    seen_phone_numbers.add(parsed_phone)
                    phone_numbers.append(parsed_phone)

        if parent_ids:
            parents = Parent.objects.filter(pk__in=parent_ids, organization=request.organization)
            for parent in parents:
                normalized_phone = normalize_phone_number(getattr(parent, 'phone_primary', ''))
                if normalized_phone and normalized_phone not in seen_phone_numbers:
                    seen_phone_numbers.add(normalized_phone)
                    phone_numbers.append(normalized_phone)

        if not phone_numbers:
            messages.error(request, 'Please provide at least one valid phone number.')
            return redirect('communications:send_single_sms')

        try:
            sms_service = _get_sms_service()
            bulk_recipients = []

            for phone in phone_numbers:
                parent_obj = _find_matching_parent(request.organization, phone)
                student = _get_first_child(parent_obj) if parent_obj else None
                context = {
                    'parent': parent_obj,
                    'student': student,
                    'school': {'name': getattr(request.organization, 'name', '')},
                }
                personalized_message = SMSTemplateService.replace_placeholders(message, context)

                bulk_recipients.append({
                    'phone': phone,
                    'message': personalized_message,
                    'parent': parent_obj,
                    'student': student,
                })

            sms_notifications = sms_service.send_bulk_sms(
                recipients=bulk_recipients,
                message='',
                organization=request.organization,
                purpose='manual',
                triggered_by=request.user,
            )

            sent_count = sum(1 for notification in sms_notifications if notification.status == 'sent')
            failed_count = sum(1 for notification in sms_notifications if notification.status == 'failed')

            if sent_count and failed_count:
                messages.warning(request, f'SMS sent to {sent_count} recipient(s); {failed_count} failed.')
            elif sent_count:
                messages.success(request, f'SMS sent successfully to {sent_count} recipient(s).')
            else:
                messages.error(request, 'SMS sending failed for all recipients.')

        except Exception as exc:
            logger.error('Error sending manual SMS: %s', str(exc), exc_info=True)
            messages.error(request, f'Error sending SMS: {str(exc)}')

        return redirect('communications:send_single_sms')


def _get_sms_service():
    """Return a usable SMS service whether SMSService is a class or an already-created instance."""
    if isinstance(SMSService, type):
        return SMSService()
    return SMSService


def _get_first_child(parent):
    """Safely get the first child related to a parent, if any."""
    if not parent or not hasattr(parent, 'children'):
        return None

    try:
        return parent.children.all().first()
    except Exception:
        return None


def _candidate_parent_phone_values(phone):
    """Build possible stored representations for a phone number."""
    if not phone:
        return []

    values = {str(phone).strip()}
    digits = ''.join(ch for ch in str(phone) if ch.isdigit())

    if digits:
        values.add(digits)

    if digits.startswith('254') and len(digits) == 12:
        values.add(f'+{digits}')
        values.add(f'0{digits[-9:]}')
        values.add(digits[-9:])

    if digits.startswith('0') and len(digits) == 10:
        values.add(f'+254{digits[1:]}')
        values.add(f'254{digits[1:]}')
        values.add(digits[1:])

    if len(digits) == 9:
        values.add(f'+254{digits}')
        values.add(f'254{digits}')
        values.add(f'0{digits}')

    return [value for value in values if value]


def _find_matching_parent(organization, phone):
    """Find a parent whose stored phone matches the supplied phone."""
    if not organization or not phone:
        return None

    candidate_values = _candidate_parent_phone_values(phone)
    if not candidate_values:
        return None

    try:
        return Parent.objects.filter(
            organization=organization,
        ).filter(
            Q(phone_primary__in=candidate_values) | Q(phone_secondary__in=candidate_values)
        ).first()
    except Exception:
        return Parent.objects.filter(
            organization=organization,
            phone_primary__in=candidate_values,
        ).first()