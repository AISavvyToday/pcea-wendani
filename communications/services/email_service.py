# communications/services/email_service.py
"""
Email Service for sending emails with template support.
"""

import logging
from django.core.mail import send_mail
from django.conf import settings
from django.template import Template, Context
from django.utils import timezone
from communications.models import EmailNotification
from core.models import Organization

logger = logging.getLogger(__name__)


class EmailService:
    """
    Service for sending emails.
    Handles template rendering and error handling.
    """
    
    def __init__(self):
        self.from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com')
    
    def send_email(self, recipient_email, subject, message, organization, purpose='', related_student=None, triggered_by=None, template_variables=None):
        """
        Send a single email.
        
        Args:
            recipient_email: Recipient email address
            subject: Email subject
            message: Email message (can contain template variables)
            organization: Organization instance
            purpose: Purpose of email
            related_student: Optional Student instance
            triggered_by: Optional User who triggered
            template_variables: Dict of variables for template rendering
        
        Returns:
            EmailNotification instance (with status 'sent' or 'failed')
        """
        logger.info(f"Sending email to {recipient_email} for organization {organization.name}")
        
        # Render template if variables provided
        if template_variables:
            try:
                template = Template(message)
                context = Context(template_variables)
                message = template.render(context)
            except Exception as e:
                logger.error(f"Error rendering email template: {str(e)}")
                return self._create_failed_notification(
                    recipient_email, subject, message, organization, purpose,
                    f"Template rendering error: {str(e)}", related_student, triggered_by
                )
        
        # Create notification record
        notification = EmailNotification.objects.create(
            organization=organization,
            recipient_email=recipient_email,
            subject=subject,
            message=message,
            status='pending',
            purpose=purpose,
            related_student=related_student,
            triggered_by=triggered_by
        )
        
        try:
            # Send email
            send_mail(
                subject=subject,
                message=message,
                from_email=self.from_email,
                recipient_list=[recipient_email],
                fail_silently=False,
            )
            
            notification.status = 'sent'
            notification.sent_at = timezone.now()
            notification.save(update_fields=['status', 'sent_at'])
            logger.info(f"Email sent successfully to {recipient_email}")
        
        except Exception as e:
            logger.error(f"Error sending email to {recipient_email}: {str(e)}", exc_info=True)
            notification.status = 'failed'
            notification.error_message = str(e)
            notification.save(update_fields=['status', 'error_message'])
        
        return notification
    
    def send_bulk_email(self, recipients, subject, message, organization, purpose='', triggered_by=None, template_variables_list=None):
        """
        Send email to multiple recipients.
        
        Args:
            recipients: List of email addresses or dicts with 'email' and optionally 'student'
            subject: Email subject
            message: Email message (can contain template variables)
            organization: Organization instance
            purpose: Purpose of email
            triggered_by: Optional User who triggered
            template_variables_list: List of variable dicts (one per recipient)
        
        Returns:
            List of EmailNotification instances
        """
        logger.info(f"Sending bulk email to {len(recipients)} recipients for organization {organization.name}")
        
        notifications = []
        
        for i, recipient in enumerate(recipients):
            if isinstance(recipient, dict):
                email = recipient.get('email')
                student = recipient.get('student')
                template_vars = template_variables_list[i] if template_variables_list and i < len(template_variables_list) else None
            else:
                email = recipient
                student = None
                template_vars = None
            
            notification = self.send_email(
                recipient_email=email,
                subject=subject,
                message=message,
                organization=organization,
                purpose=purpose,
                related_student=student,
                triggered_by=triggered_by,
                template_variables=template_vars
            )
            notifications.append(notification)
        
        logger.info(f"Bulk email complete. Sent: {sum(1 for n in notifications if n.status == 'sent')}, Failed: {sum(1 for n in notifications if n.status == 'failed')}")
        return notifications
    
    def _create_failed_notification(self, recipient_email, subject, message, organization, purpose, error_message, related_student=None, triggered_by=None):
        """Create a failed notification record."""
        return EmailNotification.objects.create(
            organization=organization,
            recipient_email=recipient_email or '',
            subject=subject,
            message=message,
            status='failed',
            error_message=error_message,
            purpose=purpose,
            related_student=related_student,
            triggered_by=triggered_by
        )

