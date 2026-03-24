# ============================================================
# PAYMENT NOTIFICATION SERVICE (manual + automated receipts)
# ============================================================

import logging

from django.conf import settings
from django.utils import timezone

from communications.models import NotificationTemplate
from communications.services.sms_api_client import sms_api_client
from communications.services.sms_workflow_service import SMSWorkflowService
from payments.models import Payment

logger = logging.getLogger(__name__)

PAYMENT_RECEIPT_TEMPLATE_NAME = 'Payment Receipt SMS'
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


class NotificationService:
    """Service for sending payment notifications and receipts."""

    RECEIPT_TEMPLATE = DEFAULT_PAYMENT_RECEIPT_TEMPLATE

    @staticmethod
    def _receipt_template_for(payment: Payment) -> str:
        organization = getattr(payment, 'organization', None) or getattr(payment.student, 'organization', None)
        if not organization:
            return NotificationService.RECEIPT_TEMPLATE

        template_obj, _ = NotificationTemplate.objects.get_or_create(
            organization=organization,
            name=PAYMENT_RECEIPT_TEMPLATE_NAME,
            template_type='sms',
            defaults={
                'template_text': NotificationService.RECEIPT_TEMPLATE,
                'variables': [],
                'description': 'Default SMS template used for payment receipt notifications.',
            },
        )
        if not template_obj.template_text:
            template_obj.template_text = NotificationService.RECEIPT_TEMPLATE
            template_obj.save(update_fields=['template_text', 'updated_at'])
        return template_obj.template_text

    @staticmethod
    def send_payment_receipt(payment: Payment) -> bool:
        if payment.receipt_sent:
            logger.info('Receipt already sent for payment %s; skipping duplicate send.', payment.payment_reference)
            return True

        student = payment.student
        sent = False
        parent = student.primary_parent
        parent_phone = getattr(parent, 'phone_primary', None) if parent else None
        parent_email = getattr(parent, 'email', None) if parent else None
        phone = parent_phone or payment.payer_phone
        message = NotificationService.format_sms_receipt(payment)

        if phone:
            organization = getattr(payment, 'organization', None) or getattr(student, 'organization', None)
            if organization:
                sms_sent = NotificationService.send_sms(phone, message, organization, student=student)
                if sms_sent:
                    sent = True
                    logger.info('SMS receipt sent for payment %s to %s', payment.payment_reference, phone)
            else:
                logger.warning('Cannot send SMS receipt - no organization found for payment %s', payment.payment_reference)

        if parent_email:
            email_sent = NotificationService.send_email_receipt(parent_email, payment)
            if email_sent:
                sent = True
                logger.info('Email receipt sent for payment %s to %s', payment.payment_reference, parent_email)

        if sent:
            payment.receipt_sent = True
            payment.receipt_sent_at = timezone.now()
            payment.save(update_fields=['receipt_sent', 'receipt_sent_at', 'updated_at'])

        return sent

    @staticmethod
    def format_sms_receipt(payment: Payment) -> str:
        return SMSWorkflowService.build_payment_receipt_message(payment, NotificationService._receipt_template_for(payment))

    @staticmethod
    def send_sms(phone: str, message: str, organization=None, student=None) -> bool:
        if not organization:
            logger.warning('SMS send called without organization - cannot send')
            return False
        try:
            notification = sms_api_client.send_sms(
                phone_number=phone,
                message=message,
                organization=organization,
                purpose='payment_receipt',
                related_student=student,
            )
            return notification.status == 'sent'
        except Exception as exc:
            logger.error('SMS sending failed: %s', exc, exc_info=True)
            return False

    @staticmethod
    def send_email_receipt(email: str, payment: Payment) -> bool:
        student = payment.student
        student_name = f"{student.first_name} {student.last_name}"
        subject = f"Payment Receipt - {payment.receipt_number}"
        body = f"""
        Dear Parent/Guardian,

        We acknowledge receipt of your payment for {student_name} ({student.admission_number}).

        Receipt Number: {payment.receipt_number}
        Amount Paid: KES {payment.amount:,.0f}
        Payment Date: {payment.payment_date.strftime('%Y-%m-%d %H:%M')}
        Payment Method: {payment.get_payment_method_display()}
        Transaction Reference: {payment.transaction_reference}

        Current Balance: KES {payment.invoice.balance if payment.invoice else 0:,.0f}

        Thank you for your continued support.

        {getattr(settings, 'SCHOOL_NAME', 'PCEA Wendani Academy')}
        """
        logger.info('Email to %s: %s', email, subject)
        return True
