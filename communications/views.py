"""Communications module views for announcements, SMS, and email management."""

import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView, View

from academics.models import Staff, Term
from core.mixins import OrganizationFilterMixin, RoleRequiredMixin
from core.models import UserRole
from students.models import Parent, Student

from .forms import SMSWorkflowForm
from .models import Announcement, EmailNotification, NotificationTemplate, SMSNotification
from .services.sms_service import SMSService
from .services.sms_template_service import SMSTemplateService
from .services.sms_workflow_service import SMSWorkflowService
from .utils import normalize_phone_number, parse_phone_numbers

logger = logging.getLogger(__name__)


BALANCE_REMINDER_TEMPLATE_NAME = 'Balance Reminder SMS'
INVOICE_SMS_TEMPLATE_NAME = 'Invoice SMS'
PAYMENT_RECEIPT_TEMPLATE_NAME = 'Payment Receipt SMS'
SMS_TEMPLATE_VARIABLES = [item['key'] for item in SMSTemplateService.get_available_placeholders()]


LEGACY_BALANCE_REMINDER_TEMPLATE = (
    "Christian greetings,\n"
    "You are advised to clear {student.name} arrears of {student.outstanding_balance_display} by "
    "{invoice.payment_deadline_display}. Kindly note that your child will not be allowed back in class "
    "as of the stated date without clearance.\n\n"
    "Pay through:\n"
    "Paybill 247247\n"
    "Account: 280029#{student.admission_number}\n"
    "OR\n"
    "Paybill 400222\n"
    "Account: 393939#{student.admission_number}\n\n"
    "NB: The bus will ONLY pick up the students who have cleared fees.\n"
    "Kindly comply to avoid any inconvenience."
)

DEFAULT_BALANCE_REMINDER_TEMPLATE = (
    "Christian greetings,\n"
    "You are advised to clear {student.full_name} arrears of Ksh. {invoice.total_due_plain} by "
    "{invoice.payment_deadline_long}. Kindly note that your child will not be allowed back in class as of the stated "
    "date without clearance.\n"
    "Pay through:\n"
    "Paybill 247247\n"
    "Account: 280029#{student.admission_number}\n"
    "OR\n"
    "Paybill 400222\n"
    "Account: 393939#{student.admission_number}\n\n"
    "NB: The bus will ONLY pick up the students who have cleared fees.\n"
    "Kindly comply to avoid any inconvenience."
)

LEGACY_INVOICE_SMS_TEMPLATE = (
    "Dear Parent/Guardian,\n"
    "Christian Greetings,\n"
    "Please find below the fee invoice for {invoice.term_label}.\n"
    "Student: {student.name}\n"
    "Admission No.: {student.admission_number}\n"
    "Grade: {student.grade}\n\n"
    "This Term's Fees: {invoice.current_term_fee_amount_display}\n"
    "{invoice.balance_or_prepayment_lines}\n"
    "TOTAL DUE: {invoice.total_due_display}\n"
    "Detailed invoice {invoice.short_link}\n\n"
    "Payment via M-Pesa:\n"
    "Paybill 247247, Account 280029#{student.admission_number}\n"
    "OR\n"
    "Paybill 400222, Account 393939#{student.admission_number}\n\n"
    "For queries, contact the office."
)

DEFAULT_INVOICE_SMS_TEMPLATE = (
    "Dear Parent/Guardian,\n"
    "Christian Greetings,\n"
    "Please find below the fee invoice for {invoice.term_label}.\n"
    "Student: {student.full_name}\n"
    "Admission No.: {student.admission_number}\n"
    "Grade: {student.grade_compact}\n\n"
    "This Term's Fees: KES {invoice.current_term_fee_amount_plain}\n"
    "{invoice.balance_or_prepayment_line}"
    "TOTAL DUE: KES {invoice.total_due_plain}\n"
    "Detailed invoice {invoice.link}\n\n"
    "Payment via M-Pesa:\n"
    "Paybill 247247, Account 280029#{student.admission_number}\n"
    " OR\n"
    "Paybill 400222, Account 393939#{student.admission_number}\n\n"
    "For queries, contact the office."
)

DEFAULT_PAYMENT_RECEIPT_TEMPLATE = (
    "Dear Parent/Guardian,\n"
    "PCEA Wendani Academy acknowledges receipt of payment for the following:\n"
    "Student: {student.full_name}\n"
    "Admission No.: {student.admission_number}\n"
    "Grade: {student.grade_compact}\n\n"
    "Amount Paid: KES {payment.amount_plain}\n"
    "Transaction Ref No.: {payment.transaction_reference}\n"
    "Date of Payment: {payment.payment_date_long}\n\n"
    "Balance Remaining: KES {payment.remaining_balance_plain}\n"
    "Receipt link {receipt.link}\n"
    "For queries, contact the office,"
)


class AnnouncementListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
    model = Announcement
    template_name = 'communications/announcement_list.html'
    context_object_name = 'announcements'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]
    paginate_by = 20


class AnnouncementCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    model = Announcement
    template_name = 'communications/announcement_form.html'
    fields = ['title', 'message', 'target_audience', 'send_sms']
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('communications:announcement_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.organization = self.request.organization
        form.instance.send_email = False
        return super().form_valid(form)


class AnnouncementDetailView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, DetailView):
    model = Announcement
    template_name = 'communications/announcement_detail.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]


class SendAnnouncementView(LoginRequiredMixin, RoleRequiredMixin, View):
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

                    bulk_recipients.append(
                        {
                            'phone': phone,
                            'message': personalized_message,
                            'parent': recipient.get('parent'),
                            'student': recipient.get('student'),
                        }
                    )

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
        recipients = []

        if announcement.target_audience in ['all', 'parents']:
            parents = Parent.objects.filter(organization=organization, is_active=True)
            for parent in parents:
                recipients.append(
                    {
                        'phone': getattr(parent, 'phone_primary', ''),
                        'email': getattr(parent, 'email', ''),
                        'parent': parent,
                        'student': _get_first_child(parent),
                    }
                )

        elif announcement.target_audience == 'teachers':
            staff_members = Staff.objects.filter(
                organization=organization,
                status='active',
                staff_type='teaching',
            ).select_related('user')
            for staff_member in staff_members:
                recipients.append(
                    {
                        'phone': getattr(staff_member, 'phone_number', '') or getattr(staff_member.user, 'phone_number', ''),
                        'email': getattr(staff_member.user, 'email', ''),
                    }
                )

        elif announcement.target_audience == 'staff':
            staff_members = Staff.objects.filter(
                organization=organization,
                status='active',
            ).select_related('user')
            for staff_member in staff_members:
                recipients.append(
                    {
                        'phone': getattr(staff_member, 'phone_number', '') or getattr(staff_member.user, 'phone_number', ''),
                        'email': getattr(staff_member.user, 'email', ''),
                    }
                )

        elif announcement.target_audience == 'students':
            students = Student.objects.filter(organization=organization, status='active').select_related('current_class')
            for student in students:
                parent = getattr(student, 'primary_parent', None)
                if parent:
                    recipients.append(
                        {
                            'phone': getattr(parent, 'phone_primary', ''),
                            'email': getattr(parent, 'email', ''),
                            'student': student,
                            'parent': parent,
                        }
                    )

        return recipients


class SMSNotificationListView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, ListView):
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
    model = NotificationTemplate
    template_name = 'communications/notification_template_list.html'
    context_object_name = 'templates'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    paginate_by = 20


class NotificationTemplateCreateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, CreateView):
    model = NotificationTemplate
    template_name = 'communications/notification_template_form.html'
    fields = ['name', 'template_type', 'subject', 'template_text', 'variables', 'description']
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('communications:notification_template_list')

    def form_valid(self, form):
        form.instance.organization = self.request.organization
        return super().form_valid(form)


class NotificationTemplateUpdateView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, UpdateView):
    model = NotificationTemplate
    template_name = 'communications/notification_template_form.html'
    fields = ['name', 'template_type', 'subject', 'template_text', 'variables', 'description']
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]
    success_url = reverse_lazy('communications:notification_template_list')


class SMSSettingsView(LoginRequiredMixin, RoleRequiredMixin, TemplateView):
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
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN]

    def get(self, request):
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

                bulk_recipients.append(
                    {
                        'phone': phone,
                        'message': personalized_message,
                        'parent': parent_obj,
                        'student': student,
                    }
                )

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


class BaseWorkflowSMSView(LoginRequiredMixin, OrganizationFilterMixin, RoleRequiredMixin, TemplateView):
    template_name = 'communications/sms_workflow.html'
    allowed_roles = [UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN, UserRole.ACCOUNTANT]
    page_title = ''
    page_description = ''
    template_record_name = ''
    default_template_text = ''
    template_description = ''
    preview_method_name = ''
    send_method_name = ''
    success_url_name = ''
    success_message_label = 'SMS'

    def get(self, request, *args, **kwargs):
        form = self._build_form()
        return self.render_to_response(self.get_context_data(form=form, previews=[]))

    def post(self, request, *args, **kwargs):
        form = self._build_form(data=request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form, previews=[]))

        template_record = self.get_template_record()
        template_text = form.cleaned_data['template_text'].strip()
        if template_text != template_record.template_text:
            template_record.template_text = template_text
            template_record.variables = SMS_TEMPLATE_VARIABLES
            template_record.description = self.template_description
            template_record.save(update_fields=['template_text', 'variables', 'description', 'updated_at'])

        workflow_kwargs = {
            'organization': request.organization,
            'template': template_text,
            'grade_levels': form.cleaned_data.get('grade_levels') or None,
            'student_ids': [student.pk for student in form.cleaned_data.get('student_ids', [])] or None,
            'term': form.cleaned_data.get('term'),
            'deadline_date': form.cleaned_data.get('deadline_date'),
        }

        action = request.POST.get('action', 'preview')
        if action == 'send':
            result = getattr(SMSWorkflowService, self.send_method_name)(
                **workflow_kwargs,
                triggered_by=request.user,
            )

            sent_count = result.get('sent_count', 0)
            failed_count = result.get('failed_count', 0)
            warnings = result.get('warnings', [])
            errors = result.get('error_messages', [])

            if sent_count:
                messages.success(request, f'{self.success_message_label} sent to {sent_count} recipient(s).')
            if failed_count:
                messages.warning(request, f'{failed_count} recipient(s) failed.')
            if not sent_count and not failed_count:
                messages.warning(request, 'No matching recipients were found for the selected filters.')
            if warnings:
                messages.warning(request, ' ; '.join(warnings[:3]))
            if errors:
                messages.warning(request, ' ; '.join(errors[:3]))
            return redirect(self.success_url_name)

        previews = getattr(SMSWorkflowService, self.preview_method_name)(**workflow_kwargs)
        if not previews:
            messages.warning(request, 'No matching recipients were found for the selected filters.')
        return self.render_to_response(self.get_context_data(form=form, previews=previews, template_record=template_record))

    def _build_form(self, data=None):
        return SMSWorkflowForm(
            data=data,
            organization=self.request.organization,
            default_template_text=self.get_template_record().template_text,
            deadline_initial=self._default_deadline_date(),
        )

    def _default_deadline_date(self):
        current_term = Term.objects.filter(organization=self.request.organization, is_current=True).first()
        return getattr(current_term, 'fee_deadline', None)

    def get_template_record(self):
        return _get_or_create_sms_template(
            organization=self.request.organization,
            name=self.template_record_name,
            default_text=self.default_template_text,
            description=self.template_description,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault('form', self._build_form())
        context.setdefault('previews', [])
        context['page_title'] = self.page_title
        context['page_description'] = self.page_description
        context['placeholder_docs'] = SMSTemplateService.get_available_placeholders()
        context['template_record'] = kwargs.get('template_record') or self.get_template_record()
        context['success_url_name'] = self.success_url_name
        return context


class BalanceReminderSMSView(BaseWorkflowSMSView):
    page_title = 'Balance Reminder SMS'
    page_description = 'Preview and send personalized outstanding balance reminders to parents.'
    template_record_name = BALANCE_REMINDER_TEMPLATE_NAME
    default_template_text = DEFAULT_BALANCE_REMINDER_TEMPLATE
    template_description = 'Default SMS template used for balance reminder broadcasts.'
    preview_method_name = 'preview_balance_reminders'
    send_method_name = 'send_balance_reminders'
    success_url_name = 'communications:balance_reminder_sms'
    success_message_label = 'Balance reminder SMS'


class InvoiceSMSView(BaseWorkflowSMSView):
    page_title = 'Invoice SMS'
    page_description = 'Preview and send invoice notifications for students with active invoices.'
    template_record_name = INVOICE_SMS_TEMPLATE_NAME
    default_template_text = DEFAULT_INVOICE_SMS_TEMPLATE
    template_description = 'Default SMS template used for invoice notification broadcasts.'
    preview_method_name = 'preview_invoice_notifications'
    send_method_name = 'send_invoice_notifications'
    success_url_name = 'communications:invoice_sms'
    success_message_label = 'Invoice SMS'


def _get_sms_service():
    if isinstance(SMSService, type):
        return SMSService()
    return SMSService


def _legacy_default_texts(name):
    mapping = {
        BALANCE_REMINDER_TEMPLATE_NAME: [LEGACY_BALANCE_REMINDER_TEMPLATE],
        INVOICE_SMS_TEMPLATE_NAME: [LEGACY_INVOICE_SMS_TEMPLATE],
        PAYMENT_RECEIPT_TEMPLATE_NAME: [],
    }
    return mapping.get(name, [])


def _get_or_create_sms_template(*, organization, name, default_text, description=''):
    template_obj, created = NotificationTemplate.objects.get_or_create(
        organization=organization,
        name=name,
        template_type='sms',
        defaults={
            'template_text': default_text,
            'variables': SMS_TEMPLATE_VARIABLES,
            'description': description,
        },
    )

    fields_to_update = []
    if not template_obj.template_text or template_obj.template_text in _legacy_default_texts(name):
        template_obj.template_text = default_text
        fields_to_update.append('template_text')
    if not template_obj.variables:
        template_obj.variables = SMS_TEMPLATE_VARIABLES
        fields_to_update.append('variables')
    if description and template_obj.description != description:
        template_obj.description = description
        fields_to_update.append('description')
    if fields_to_update:
        fields_to_update.append('updated_at')
        template_obj.save(update_fields=fields_to_update)
    return template_obj


def _get_first_child(parent):
    if not parent or not hasattr(parent, 'children'):
        return None

    try:
        return parent.children.all().first()
    except Exception:
        return None


def _candidate_parent_phone_values(phone):
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
