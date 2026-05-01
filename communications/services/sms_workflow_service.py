"""Production SMS workflows for reminders, invoices, receipts, and broadcasts."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from academics.models import Term
from communications.models import SMSNotification
from communications.services.sms_api_client import sms_api_client
from communications.services.sms_template_service import SMSTemplateService
from finance.models import Invoice
from students.models import Student


@dataclass
class WorkflowRecipient:
    student: Student
    parent: Any
    phone: str
    message: str
    unresolved_placeholders: list[str]
    warning: str = ""


class SMSWorkflowService:
    """Reusable engine for personalized SMS previews and sends."""

    @staticmethod
    def _current_term(term: Term | None = None) -> Term | None:
        return term or Term.objects.filter(is_current=True).select_related('academic_year').first()

    @staticmethod
    def _student_queryset(organization, grade_levels=None, student_ids=None):
        queryset = (
            Student.objects.filter(organization=organization, status='active', is_active=True)
            .select_related('current_class', 'organization')
            .prefetch_related('student_parents__parent')
        )

        if grade_levels:
            queryset = queryset.filter(current_class__grade_level__in=grade_levels)
        if student_ids:
            queryset = queryset.filter(id__in=student_ids)

        return queryset.order_by('admission_number', 'first_name', 'last_name')

    @staticmethod
    def _current_invoice(student: Student, term: Term | None = None) -> Invoice | None:
        current_term = SMSWorkflowService._current_term(term)
        queryset = student.invoices.filter(is_active=True).select_related('term', 'organization')
        if current_term:
            invoice = queryset.filter(term=current_term).first()
            if invoice:
                return invoice
        return queryset.order_by('-issue_date', '-created_at').first()

    @staticmethod
    def _build_url(route_name: str, pk) -> str:
        try:
            path = reverse(route_name, kwargs={'pk': pk})
        except NoReverseMatch:
            return ''

        base_url = (
            getattr(settings, 'SITE_URL', '')
            or getattr(settings, 'PAYMENT_CALLBACK_BASE_URL', '')
            or ''
        ).rstrip('/')
        if not base_url:
            return path
        return f"{base_url}{path}"

    @staticmethod
    def _paybill_accounts(admission_number: str) -> dict[str, str]:
        accounts = {}
        bank_details = getattr(settings, 'SCHOOL_BANK_DETAILS', {}) or {}
        for key in ('paybill_1', 'paybill_2'):
            details = bank_details.get(key, {})
            format_value = details.get('acc_format', '')
            if format_value:
                accounts[key] = format_value.replace('<admission_number>', admission_number or '')
        return accounts

    @classmethod
    def _merge_context(cls, base: dict[str, Any], extra: dict[str, Any] | None) -> dict[str, Any]:
        if not extra:
            return base

        merged = dict(base)
        for key, value in extra.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = cls._merge_context(merged[key], value)
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _workflow_extra_context(term: Term | None = None, deadline_date=None) -> dict[str, Any] | None:
        deadline = deadline_date or getattr(term, 'fee_deadline', None)
        if not deadline:
            return None
        return {
            'invoice': {
                'payment_deadline': deadline,
                'payment_deadline_long': SMSWorkflowService._format_long_date(deadline),
            }
        }

    @staticmethod
    def _format_plain_money(value: Decimal | None) -> str:
        amount = value if isinstance(value, Decimal) else Decimal(str(value or '0.00'))
        return f"{amount:,.0f}"

    @staticmethod
    def _format_long_date(value) -> str:
        if not value:
            return ''
        if hasattr(value, 'date'):
            try:
                value = timezone.localtime(value).date()
            except Exception:
                value = value.date()
        return f"{value.day} {value.strftime('%B %Y')}"

    @staticmethod
    def _format_term_label(term: Term | None) -> str:
        if not term:
            return ''
        raw_term = getattr(term, 'term', '') or ''
        term_number = raw_term.split('_')[-1] if '_' in raw_term else raw_term
        year = getattr(getattr(term, 'academic_year', None), 'year', '')
        return f"Term {term_number}, {year}".strip(', ')

    @classmethod
    def build_context(cls, student: Student, invoice: Invoice | None = None, payment=None, extra_context=None) -> dict[str, Any]:
        parent = student.primary_parent
        invoice = invoice or cls._current_invoice(student)
        paybill_accounts = cls._paybill_accounts(student.admission_number or '')
        current_term_fee_amount = getattr(invoice, 'total_amount', Decimal('0.00')) if invoice else Decimal('0.00')
        balance_bf = getattr(invoice, 'balance_bf', Decimal('0.00')) if invoice else Decimal('0.00')
        prepayment = getattr(invoice, 'prepayment', Decimal('0.00')) if invoice else Decimal('0.00')
        total_due = getattr(invoice, 'balance', student.outstanding_balance or Decimal('0.00')) if invoice else (student.outstanding_balance or Decimal('0.00'))
        payment_deadline = getattr(invoice, 'due_date', None) if invoice else None
        invoice_link = cls._build_url('finance:invoice_detail', invoice.pk) if invoice else ''
        invoice_print_url = cls._build_url('finance:invoice_receipt_print', invoice.pk) if invoice else ''
        receipt_link = cls._build_url('finance:payment_receipt', payment.pk) if payment else ''
        grade_class = str(student.current_class) if student.current_class else ''
        grade_level = getattr(student.current_class, 'grade_level', '') if student.current_class else ''
        grade_compact = grade_level.split('_')[-1] if grade_level else grade_class.replace(' ', '')
        balance_or_prepayment_line = ''
        if balance_bf > 0:
            balance_or_prepayment_line = f"Previous Term Balance: KES {cls._format_plain_money(balance_bf)}\n"
        elif prepayment > 0:
            balance_or_prepayment_line = f"Prepayment: KES {cls._format_plain_money(prepayment)}\n"
        remaining_balance = student.outstanding_balance or Decimal('0.00')
        if payment is None and invoice is not None:
            remaining_balance = total_due
        context = {
            'parent': parent,
            'student': {
                'full_name': student.full_name,
                'admission_number': student.admission_number,
                'grade_class': grade_class,
                'grade_compact': grade_compact,
                'outstanding_balance': student.outstanding_balance or Decimal('0.00'),
                'outstanding_balance_plain': cls._format_plain_money(student.outstanding_balance or Decimal('0.00')),
            },
            'invoice': {
                'invoice_number': getattr(invoice, 'invoice_number', ''),
                'term_label': cls._format_term_label(getattr(invoice, 'term', None)),
                'current_term_fee_amount': current_term_fee_amount,
                'current_term_fee_amount_plain': cls._format_plain_money(current_term_fee_amount),
                'balance_bf': balance_bf,
                'balance_bf_plain': cls._format_plain_money(balance_bf),
                'prepayment': prepayment,
                'prepayment_plain': cls._format_plain_money(prepayment),
                'balance_or_prepayment_line': balance_or_prepayment_line,
                'total_due': total_due,
                'total_due_plain': cls._format_plain_money(total_due),
                'due_date': getattr(invoice, 'due_date', None),
                'payment_deadline': payment_deadline,
                'payment_deadline_long': cls._format_long_date(payment_deadline),
                'link': invoice_link,
                'short_link': invoice_link,
                'print_url': invoice_print_url,
                'paybill_account_1': paybill_accounts.get('paybill_1', ''),
                'paybill_account_2': paybill_accounts.get('paybill_2', ''),
            },
            'receipt': {
                'link': receipt_link,
                'print_url': receipt_link,
            },
            'payment': {
                'transaction_reference': getattr(payment, 'transaction_reference', ''),
                'payment_date': getattr(payment, 'payment_date', None),
                'payment_date_long': cls._format_long_date(getattr(payment, 'payment_date', None)),
                'remaining_balance': remaining_balance,
                'remaining_balance_plain': cls._format_plain_money(remaining_balance),
                'receipt_number': getattr(payment, 'receipt_number', ''),
                'amount': getattr(payment, 'amount', Decimal('0.00')),
                'amount_plain': cls._format_plain_money(getattr(payment, 'amount', Decimal('0.00'))),
            },
            'school': {
                'name': getattr(student.organization, 'name', getattr(settings, 'SCHOOL_NAME', 'School')),
            },
        }
        return cls._merge_context(context, extra_context)

    @classmethod
    def _render_recipient(cls, student: Student, template: str, invoice: Invoice | None = None, payment=None, preview=True, extra_context=None):
        parent = student.primary_parent
        phone = getattr(parent, 'phone_primary', '') if parent else ''
        context = cls.build_context(student, invoice=invoice, payment=payment, extra_context=extra_context)
        rendered = SMSTemplateService.render(template, context=context, preview=preview)
        warning = ''
        if rendered['unresolved_placeholders'] and not preview:
            warning = f"Removed unresolved placeholders: {', '.join(rendered['unresolved_placeholders'])}"
        return WorkflowRecipient(
            student=student,
            parent=parent,
            phone=phone,
            message=rendered['message'],
            unresolved_placeholders=rendered['unresolved_placeholders'],
            warning=warning,
        )

    @classmethod
    def _send_personalized_messages(cls, *, organization, recipients: list[WorkflowRecipient], purpose: str, triggered_by=None):
        notifications = []
        valid_recipients = []
        warnings = []

        for recipient in recipients:
            if recipient.warning:
                warnings.append(
                    f"{recipient.student.admission_number or recipient.student.pk}: {recipient.warning}"
                )
            if not recipient.phone:
                notifications.append(
                    SMSNotification.objects.create(
                        organization=organization,
                        recipient_phone='',
                        message=recipient.message,
                        status='failed',
                        error_message='Student primary parent has no phone number.',
                        purpose=purpose,
                        related_student=recipient.student,
                        triggered_by=triggered_by,
                    )
                )
                continue

            valid_recipients.append({
                'phone': recipient.phone,
                'message': recipient.message,
                'student': recipient.student,
            })

        if valid_recipients:
            notifications.extend(
                sms_api_client.send_bulk_sms(
                    recipients=valid_recipients,
                    message='',
                    organization=organization,
                    purpose=purpose,
                    triggered_by=triggered_by,
                )
            )

        error_counter = Counter(
            notification.error_message
            for notification in notifications
            if notification.status == 'failed' and notification.error_message
        )
        return {
            'notifications': notifications,
            'sent_count': sum(1 for notification in notifications if notification.status == 'sent'),
            'failed_count': sum(1 for notification in notifications if notification.status == 'failed'),
            'error_messages': [
                f"{message} ({count})" if count > 1 else message
                for message, count in error_counter.items()
            ],
            'warnings': warnings,
            'audit_rows_created': len(notifications),
        }

    @classmethod
    def preview_balance_reminders(cls, *, organization, template: str, grade_levels=None, student_ids=None, term=None, deadline_date=None):
        students = cls._student_queryset(organization, grade_levels=grade_levels, student_ids=student_ids).filter(outstanding_balance__gt=0)
        extra_context = cls._workflow_extra_context(term=term, deadline_date=deadline_date)
        previews = []
        for student in students:
            invoice = cls._current_invoice(student, term=term)
            previews.append(cls._render_recipient(student, template, invoice=invoice, preview=True, extra_context=extra_context))
        return previews

    @classmethod
    def send_balance_reminders(cls, *, organization, template: str, grade_levels=None, student_ids=None, term=None, deadline_date=None, triggered_by=None):
        students = cls._student_queryset(organization, grade_levels=grade_levels, student_ids=student_ids).filter(outstanding_balance__gt=0)
        extra_context = cls._workflow_extra_context(term=term, deadline_date=deadline_date)
        recipients = [
            cls._render_recipient(
                student,
                template,
                invoice=cls._current_invoice(student, term=term),
                preview=False,
                extra_context=extra_context,
            )
            for student in students
        ]
        return cls._send_personalized_messages(
            organization=organization,
            recipients=recipients,
            purpose='balance_reminder',
            triggered_by=triggered_by,
        )

    @classmethod
    def preview_invoice_notifications(cls, *, organization, template: str, grade_levels=None, student_ids=None, term=None, deadline_date=None):
        students = cls._student_queryset(organization, grade_levels=grade_levels, student_ids=student_ids)
        extra_context = cls._workflow_extra_context(term=term, deadline_date=deadline_date)
        previews = []
        for student in students:
            invoice = cls._current_invoice(student, term=term)
            if invoice:
                previews.append(cls._render_recipient(student, template, invoice=invoice, preview=True, extra_context=extra_context))
        return previews

    @classmethod
    def send_invoice_notifications(cls, *, organization, template: str, grade_levels=None, student_ids=None, term=None, deadline_date=None, triggered_by=None):
        students = cls._student_queryset(organization, grade_levels=grade_levels, student_ids=student_ids)
        extra_context = cls._workflow_extra_context(term=term, deadline_date=deadline_date)
        recipients = []
        for student in students:
            invoice = cls._current_invoice(student, term=term)
            if invoice:
                recipients.append(
                    cls._render_recipient(student, template, invoice=invoice, preview=False, extra_context=extra_context)
                )
        return cls._send_personalized_messages(
            organization=organization,
            recipients=recipients,
            purpose='invoice_notification',
            triggered_by=triggered_by,
        )

    @classmethod
    def preview_broadcast(cls, *, organization, template: str, grade_levels=None, student_ids=None, extra_context=None):
        students = cls._student_queryset(organization, grade_levels=grade_levels, student_ids=student_ids)
        return [
            cls._render_recipient(student, template, preview=True, extra_context=extra_context)
            for student in students
        ]

    @classmethod
    def send_broadcast(cls, *, organization, template: str, grade_levels=None, student_ids=None, triggered_by=None, extra_context=None):
        students = cls._student_queryset(organization, grade_levels=grade_levels, student_ids=student_ids)
        recipients = [
            cls._render_recipient(student, template, preview=False, extra_context=extra_context)
            for student in students
        ]
        return cls._send_personalized_messages(
            organization=organization,
            recipients=recipients,
            purpose='broadcast',
            triggered_by=triggered_by,
        )

    @classmethod
    def preview_receipt_message(cls, payment, template: str):
        return cls._render_recipient(payment.student, template, invoice=payment.invoice, payment=payment, preview=True)

    @classmethod
    def build_payment_receipt_message(cls, payment, template: str) -> str:
        return cls._render_recipient(payment.student, template, invoice=payment.invoice, payment=payment, preview=False).message
