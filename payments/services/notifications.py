# File: payments/services/notifications.py
# ============================================================
# RATIONALE: Handle sending payment receipts and notifications
# - Sends SMS receipts to parents
# - Sends email receipts (if email available)
# - Updates payment record with receipt sent status
# ============================================================

import logging
from django.utils import timezone
from django.conf import settings

from payments.models import Payment

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending payment notifications and receipts."""
    
    @staticmethod
    def send_payment_receipt(payment: Payment) -> bool:
        """
        Send payment receipt to parent via SMS and/or email.
        
        Args:
            payment: The Payment record
        
        Returns:
            True if at least one notification was sent successfully
        """
        student = payment.student
        sent = False
        
        # Get parent contact info
        parent = getattr(student, 'parent', None)
        parent_phone = getattr(parent, 'phone', None) if parent else None
        parent_email = getattr(parent, 'email', None) if parent else None
        
        # Fallback to payer phone if no parent phone
        phone = parent_phone or payment.payer_phone
        
        # Format receipt message
        message = NotificationService.format_sms_receipt(payment)
        
        # Send SMS
        if phone:
            # Get organization from payment
            organization = getattr(payment, 'organization', None)
            if not organization and hasattr(payment, 'student'):
                organization = getattr(payment.student, 'organization', None)
            
            if organization:
                sms_sent = NotificationService.send_sms(phone, message, organization)
                if sms_sent:
                    sent = True
                    logger.info(f"SMS receipt sent for payment {payment.payment_reference} to {phone}")
            else:
                logger.warning(f"Cannot send SMS receipt - no organization found for payment {payment.payment_reference}")
        
        # Send Email
        if parent_email:
            email_sent = NotificationService.send_email_receipt(parent_email, payment)
            if email_sent:
                sent = True
                logger.info(f"Email receipt sent for payment {payment.payment_reference} to {parent_email}")
        
        # Update payment record
        if sent:
            payment.receipt_sent = True
            payment.receipt_sent_at = timezone.now()
            payment.save(update_fields=['receipt_sent', 'receipt_sent_at', 'updated_at'])
        
        return sent
    
    @staticmethod
    def format_sms_receipt(payment: Payment) -> str:
        """
        Format SMS receipt message.
        
        Format:
        PCEA Wendani Academy
        Receipt: RCP-2025-00001
        Student: John Doe (PWA2254)
        Amount: KES 10,000
        Balance: KES 5,000
        Date: 2025-01-09
        Thank you for your payment.
        """
        student = payment.student
        student_name = f"{student.first_name} {student.last_name}"
        
        # Get current balance
        balance = 0
        if payment.invoice:
            balance = payment.invoice.balance
        
        message = (
            f"PCEA Wendani Academy\n"
            f"Receipt: {payment.receipt_number}\n"
            f"Student: {student_name} ({student.admission_number})\n"
            f"Amount: KES {payment.amount:,.0f}\n"
            f"Balance: KES {balance:,.0f}\n"
            f"Date: {payment.payment_date.strftime('%Y-%m-%d')}\n"
            f"Thank you for your payment."
        )
        
        return message
    
    @staticmethod
    def send_sms(phone: str, message: str, organization=None) -> bool:
        """
        Send SMS via central SMS service API.
        
        Args:
            phone: Phone number
            message: SMS message
            organization: Optional Organization instance (required for credit deduction)
        
        Returns:
            bool: True if sent successfully, False otherwise
        """
        if not organization:
            logger.warning("SMS send called without organization - cannot send")
            return False
        
        try:
            from communications.services.sms_api_client import sms_api_client
            
            notification = sms_api_client.send_sms(
                phone_number=phone,
                message=message,
                organization=organization,
                purpose='payment_receipt'
            )
            
            return notification.status == 'sent'
        
        except Exception as e:
            logger.error(f"SMS sending failed: {e}", exc_info=True)
            return False
    
    @staticmethod
    def send_email_receipt(email: str, payment: Payment) -> bool:
        """
        Send email receipt.
        
        TODO: Implement email sending via Django email backend.
        """
        student = payment.student
        student_name = f"{student.first_name} {student.last_name}"
        
        subject = f"Payment Receipt - {payment.receipt_number}"
        
        # TODO: Use proper email template
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
        
        # TODO: Implement actual email sending
        # try:
        #     from django.core.mail import send_mail
        #     send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [email])
        #     return True
        # except Exception as e:
        #     logger.error(f"Email sending failed: {e}")
        #     return False
        
        return True  # Placeholder