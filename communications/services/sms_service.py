# communications/services/sms_service.py
"""
SMS Service for sending SMS via ImaraBiz API with SMS credits management.
"""

import logging
import requests
import time
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from communications.models import SMSNotification
from core.models import Organization

logger = logging.getLogger(__name__)


class SMSService:
    """
    Service for sending SMS via ImaraBiz API.
    Handles credit deduction, API calls, and error handling.
    """
    
    def __init__(self):
        self.api_key = getattr(settings, 'IMARABIZ_API_KEY', '')
        self.partner_id = getattr(settings, 'IMARABIZ_PARTNER_ID', '')
        self.api_url = getattr(settings, 'IMARABIZ_API_URL', 'https://sms.imarabiz.com/api/services/')
        self.batch_size = getattr(settings, 'SMS_BATCH_SIZE', 50)
        self.batch_delay = getattr(settings, 'SMS_BATCH_DELAY', 1.0)
    
    def send_sms(self, phone_number, message, organization, purpose='', related_student=None, triggered_by=None):
        """
        Send a single SMS.
        
        Args:
            phone_number: Phone number in format 254XXXXXXXXX
            message: SMS message text
            organization: Organization instance
            purpose: Purpose of SMS (e.g., 'fee_reminder', 'announcement')
            related_student: Optional Student instance
            triggered_by: Optional User who triggered the SMS
        
        Returns:
            SMSNotification instance (with status 'sent' or 'failed')
        """
        logger.info(f"Sending SMS to {phone_number} for organization {organization.name}")
        
        # Validate phone number format
        phone_number = self._normalize_phone(phone_number)
        if not phone_number:
            logger.error(f"Invalid phone number format: {phone_number}")
            return self._create_failed_notification(
                phone_number, message, organization, purpose,
                "Invalid phone number format", related_student, triggered_by
            )
        
        # Check organization SMS balance
        if not hasattr(organization, 'sms_balance') or organization.sms_balance < 1:
            logger.warning(f"Organization {organization.name} has insufficient SMS credits: {organization.sms_balance}")
            return self._create_failed_notification(
                phone_number, message, organization, purpose,
                "Insufficient SMS credits", related_student, triggered_by
            )
        
        # Get organization shortcode
        shortcode = getattr(organization, 'imarabiz_shortcode', 'SWIFT_TECH')
        
        # Create notification record
        notification = SMSNotification.objects.create(
            organization=organization,
            recipient_phone=phone_number,
            message=message,
            status='pending',
            purpose=purpose,
            related_student=related_student,
            triggered_by=triggered_by
        )
        
        try:
            # Deduct credit atomically
            with transaction.atomic():
                # Lock organization for update
                org = Organization.objects.select_for_update().get(id=organization.id)
                if org.sms_balance < 1:
                    raise ValueError("Insufficient SMS credits")
                
                org.sms_balance -= 1
                org.save(update_fields=['sms_balance', 'updated_at'])
                
                logger.debug(f"Deducted 1 SMS credit from {org.name}. New balance: {org.sms_balance}")
            
            # Send SMS via ImaraBiz API
            success = self._send_via_api(phone_number, message, shortcode)
            
            if success:
                notification.status = 'sent'
                notification.sent_at = timezone.now()
                notification.save(update_fields=['status', 'sent_at'])
                logger.info(f"SMS sent successfully to {phone_number}")
            else:
                # Refund credit on failure
                with transaction.atomic():
                    org = Organization.objects.select_for_update().get(id=organization.id)
                    org.sms_balance += 1
                    org.save(update_fields=['sms_balance', 'updated_at'])
                    logger.debug(f"Refunded 1 SMS credit to {org.name}. New balance: {org.sms_balance}")
                
                notification.status = 'failed'
                notification.error_message = "Failed to send via API"
                notification.save(update_fields=['status', 'error_message'])
                logger.error(f"Failed to send SMS to {phone_number}")
        
        except Exception as e:
            logger.error(f"Error sending SMS to {phone_number}: {str(e)}", exc_info=True)
            
            # Refund credit on exception
            try:
                with transaction.atomic():
                    org = Organization.objects.select_for_update().get(id=organization.id)
                    org.sms_balance += 1
                    org.save(update_fields=['sms_balance', 'updated_at'])
            except Exception as refund_error:
                logger.error(f"Error refunding credit: {str(refund_error)}")
            
            notification.status = 'failed'
            notification.error_message = str(e)
            notification.save(update_fields=['status', 'error_message'])
        
        return notification
    
    def send_bulk_sms(self, recipients, message, organization, purpose='', triggered_by=None):
        """
        Send SMS to multiple recipients in batches.
        
        Args:
            recipients: List of dicts with 'phone' and optionally 'student'
            message: SMS message text
            organization: Organization instance
            purpose: Purpose of SMS
            triggered_by: Optional User who triggered
        
        Returns:
            List of SMSNotification instances
        """
        logger.info(f"Sending bulk SMS to {len(recipients)} recipients for organization {organization.name}")
        
        notifications = []
        
        # Process in batches
        for i in range(0, len(recipients), self.batch_size):
            batch = recipients[i:i + self.batch_size]
            
            for recipient in batch:
                phone = recipient.get('phone')
                student = recipient.get('student')
                
                notification = self.send_sms(
                    phone_number=phone,
                    message=message,
                    organization=organization,
                    purpose=purpose,
                    related_student=student,
                    triggered_by=triggered_by
                )
                notifications.append(notification)
            
            # Delay between batches
            if i + self.batch_size < len(recipients):
                time.sleep(self.batch_delay)
        
        logger.info(f"Bulk SMS complete. Sent: {sum(1 for n in notifications if n.status == 'sent')}, Failed: {sum(1 for n in notifications if n.status == 'failed')}")
        return notifications
    
    def _send_via_api(self, phone_number, message, shortcode):
        """
        Send SMS via ImaraBiz API.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # ImaraBiz API endpoint
            url = f"{self.api_url}send"
            
            payload = {
                'api_key': self.api_key,
                'partner_id': self.partner_id,
                'shortcode': shortcode,
                'mobile': phone_number,
                'message': message,
            }
            
            headers = {
                'Content-Type': 'application/json',
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                # Check response format (adjust based on actual API response)
                if data.get('status') == 'success' or data.get('success'):
                    logger.debug(f"ImaraBiz API success: {data}")
                    return True
                else:
                    logger.error(f"ImaraBiz API error: {data}")
                    return False
            else:
                logger.error(f"ImaraBiz API HTTP error: {response.status_code} - {response.text}")
                return False
        
        except requests.exceptions.RequestException as e:
            logger.error(f"ImaraBiz API request exception: {str(e)}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"ImaraBiz API unexpected error: {str(e)}", exc_info=True)
            return False
    
    def _normalize_phone(self, phone):
        """
        Normalize phone number to 254XXXXXXXXX format.
        
        Returns:
            str: Normalized phone number or None if invalid
        """
        if not phone:
            return None
        
        # Remove spaces, dashes, etc.
        phone = ''.join(filter(str.isdigit, str(phone)))
        
        # Convert to 254 format
        if phone.startswith('0'):
            phone = '254' + phone[1:]
        elif phone.startswith('+254'):
            phone = phone[1:]
        elif not phone.startswith('254'):
            phone = '254' + phone
        
        # Validate length (254 + 9 digits = 12 total)
        if len(phone) == 12 and phone.startswith('254'):
            return phone
        
        return None
    
    def _create_failed_notification(self, phone_number, message, organization, purpose, error_message, related_student=None, triggered_by=None):
        """Create a failed notification record."""
        return SMSNotification.objects.create(
            organization=organization,
            recipient_phone=phone_number or '',
            message=message,
            status='failed',
            error_message=error_message,
            purpose=purpose,
            related_student=related_student,
            triggered_by=triggered_by
        )

