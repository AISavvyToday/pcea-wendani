# File: payments/services/notifications.py
# ============================================================
# RATIONALE: Handle sending payment receipts and notifications
# - Sends SMS receipts to parents
# - Sends email receipts (if email available)
# - Updates payment record with receipt sent status
# ============================================================

import logging
from django.utils import timezone

from payments.models import Payment
from communications.services.sms_api_client import sms_api_client
from communications.services.sms_workflow_service import SMSWorkflowService

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending payment notifications and receipts."""

    RECEIPT_TEMPLATE = (
        "Dear {parent.first_name}, we have received {payment.amount} for "
        "{student.name} ({student.admission_number}) on {payment.payment_date}. "
        "Ref: {payment.transaction_reference}. Receipt No: {payment.receipt_number}. "
        "Remaining balance: {payment.remaining_balance}. "
        "Receipt: {receipt.link}. Thank you."
    )

    @staticmethod
    def send_payment_receipt(payment: Payment) -> bool:
        """Send payment receipt to the student's primary parent."""
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
                    logger.info("SMS receipt sent for payment %s to %s", payment.payment_reference, phone)
            else:
                logger.warning("Cannot send SMS receipt - no organization found for payment %s", payment.payment_reference)

        if parent_email:
            email_sent = NotificationService.send_email_receipt(parent_email, payment)
            if email_sent:
                sent = True
                logger.info("Email receipt sent for payment %s to %s", payment.payment_reference, parent_email)

        if sent:
            payment.receipt_sent = True
            payment.receipt_sent_at = timezone.now()
            payment.save(update_fields=['receipt_sent', 'receipt_sent_at', 'updated_at'])

        return sent

    @staticmethod
    def format_sms_receipt(payment: Payment) -> str:
        """Format SMS receipt message with remaining balance and receipt link."""
        return SMSWorkflowService.build_payment_receipt_message(payment, NotificationService.RECEIPT_TEMPLATE)

    @staticmethod
    def send_sms(phone: str, message: str, organization=None, student=None) -> bool:
        """Send SMS via central SMS service API."""
        if not organization:
            logger.warning("SMS send called without organization - cannot send")
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
        except Exception as e:
            logger.error(f"SMS sending failed: {e}", exc_info=True)
            return False

    @staticmethod
    def send_email_receipt(email: str, payment: Payment) -> bool:
        """Send email receipt."""
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

        PCEA Wendani Academy
        """

        logger.info(f"Email to {email}: {subject}")
        return True
