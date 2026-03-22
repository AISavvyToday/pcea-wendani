# communications/services/sms_api_client.py
"""
SMS API Client for calling the central SMS service at sms.swiftresidetech.co.ke

This client handles all SMS operations via HTTP API calls to the central service.
The central service manages ImaraBiz integration, credit deduction, and KCB payments.
"""

import logging
import requests
from django.conf import settings
from django.utils import timezone
from communications.models import SMSNotification

logger = logging.getLogger(__name__)


class SMSAPIClient:
    """
    Client for calling the central SMS service API.
    """
    
    def __init__(self):
        self.api_url = getattr(settings, 'SMS_SERVICE_API_URL', 'https://sms.swiftresidetech.co.ke/api/v1')
        self.api_token = getattr(settings, 'SMS_SERVICE_API_TOKEN', '')

    def _get_headers(self):
        """Get request headers with authentication."""
        return {
            'Authorization': f'Bearer {self.api_token}',
            'Content-Type': 'application/json',
        }

    def _configuration_error(self):
        """Return a user-facing configuration error for missing API credentials."""
        if self.api_token:
            return None
        return "SMS central service API token is not configured"
    
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
            if len(phone) == 9:
                phone = '254' + phone
        
        # Validate length (254 + 9 digits = 12 total)
        if len(phone) == 12 and phone.startswith('254'):
            return phone
        
        return None
    
    def get_balance(self, organization):
        """
        Get SMS balance for an organization.
        
        Args:
            organization: Organization instance with sms_account_number
        
        Returns:
            dict with 'success', 'balance', 'error' keys
        """
        if not organization or not hasattr(organization, 'sms_account_number') or not organization.sms_account_number:
            return {'success': False, 'error': 'Organization missing SMS account number'}

        configuration_error = self._configuration_error()
        if configuration_error:
            return {'success': False, 'error': configuration_error}

        try:
            url = f"{self.api_url}/balance/"
            params = {'sms_account_number': organization.sms_account_number}
            
            response = requests.get(
                url,
                params=params,
                headers=self._get_headers(),
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    return {
                        'success': True,
                        'balance': data.get('balance', 0),
                        'price_per_sms': data.get('price_per_sms', 1.0)
                    }
                else:
                    return {'success': False, 'error': data.get('error', 'Unknown error')}
            else:
                return {'success': False, 'error': f'API returned status {response.status_code}'}
        
        except requests.exceptions.RequestException as e:
            logger.error(f"SMS API balance check failed: {str(e)}")
            return {'success': False, 'error': str(e)}
        except Exception as e:
            logger.error(f"SMS API balance check error: {str(e)}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    def send_sms(self, phone_number, message, organization, purpose='', related_student=None, triggered_by=None):
        """
        Send a single SMS via the central service.
        
        Args:
            phone_number: Phone number (will be normalized)
            message: SMS message text
            organization: Organization instance with sms_account_number
            purpose: Purpose of SMS (e.g., 'fee_reminder', 'announcement')
            related_student: Optional Student instance
            triggered_by: Optional User who triggered the SMS
        
        Returns:
            SMSNotification instance (with status 'sent' or 'failed')
        """
        logger.info(f"Sending SMS to {phone_number} for organization {organization.name}")
        
        # Validate organization
        if not organization or not hasattr(organization, 'sms_account_number') or not organization.sms_account_number:
            error_msg = "Organization missing SMS account number"
            logger.error(error_msg)
            return self._create_failed_notification(
                phone_number, message, organization, purpose,
                error_msg, related_student, triggered_by
            )

        configuration_error = self._configuration_error()
        if configuration_error:
            logger.error(configuration_error)
            return self._create_failed_notification(
                phone_number, message, organization, purpose,
                configuration_error, related_student, triggered_by
            )
        
        # Normalize phone number
        normalized_phone = self._normalize_phone(phone_number)
        if not normalized_phone:
            error_msg = f"Invalid phone number format: {phone_number}"
            logger.error(error_msg)
            return self._create_failed_notification(
                phone_number, message, organization, purpose,
                error_msg, related_student, triggered_by
            )
        
        # Create notification record
        notification = SMSNotification.objects.create(
            organization=organization,
            recipient_phone=normalized_phone,
            message=message,
            status='pending',
            purpose=purpose,
            related_student=related_student,
            triggered_by=triggered_by
        )
        
        try:
            # Call central service API
            url = f"{self.api_url}/sms/send/"
            payload = {
                'sms_account_number': organization.sms_account_number,
                'phone_number': normalized_phone,
                'message': message,
                'purpose': purpose or 'manual',
            }
            
            response = requests.post(
                url,
                json=payload,
                headers=self._get_headers(),
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    notification.status = 'sent'
                    notification.sent_at = timezone.now()
                    notification.save(update_fields=['status', 'sent_at'])
                    logger.info(f"SMS sent successfully to {normalized_phone}")
                else:
                    notification.status = 'failed'
                    notification.error_message = data.get('error', 'Unknown error')
                    notification.save(update_fields=['status', 'error_message'])
                    logger.error(f"Failed to send SMS to {normalized_phone}: {data.get('error')}")
            else:
                error_msg = f"API returned status {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', error_msg)
                except:
                    error_msg = f"{error_msg}: {response.text[:200]}"
                
                notification.status = 'failed'
                notification.error_message = error_msg
                notification.save(update_fields=['status', 'error_message'])
                logger.error(f"Failed to send SMS to {normalized_phone}: {error_msg}")
        
        except requests.exceptions.RequestException as e:
            error_msg = f"API request failed: {str(e)}"
            logger.error(f"SMS API request error: {error_msg}", exc_info=True)
            notification.status = 'failed'
            notification.error_message = error_msg
            notification.save(update_fields=['status', 'error_message'])
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(f"Error sending SMS: {error_msg}", exc_info=True)
            notification.status = 'failed'
            notification.error_message = error_msg
            notification.save(update_fields=['status', 'error_message'])
        
        return notification
    
    def send_bulk_sms(self, recipients, message, organization, purpose='', triggered_by=None):
        """
        Send SMS to multiple recipients via the central service.
        
        Args:
            recipients: List of dicts with 'phone' and optionally 'student', 'parent', 'message'
            message: Default SMS message text (can be overridden per recipient)
            organization: Organization instance
            purpose: Purpose of SMS
            triggered_by: Optional User who triggered
        
        Returns:
            List of SMSNotification instances
        """
        logger.info(f"Sending bulk SMS to {len(recipients)} recipients for organization {organization.name}")
        
        # Validate organization
        if not organization or not hasattr(organization, 'sms_account_number') or not organization.sms_account_number:
            logger.error("Organization missing SMS account number")
            notifications = []
            for recipient in recipients:
                phone = recipient.get('phone', '')
                notifications.append(self._create_failed_notification(
                    phone, message, organization, purpose,
                    "Organization missing SMS account number",
                    recipient.get('student'), triggered_by
                ))
            return notifications

        configuration_error = self._configuration_error()
        if configuration_error:
            logger.error(configuration_error)
            notifications = []
            for recipient in recipients:
                phone = recipient.get('phone', '')
                notifications.append(self._create_failed_notification(
                    phone, message, organization, purpose,
                    configuration_error, recipient.get('student'), triggered_by
                ))
            return notifications
        
        # Prepare recipients for bulk API
        api_recipients = []
        for recipient in recipients:
            phone = recipient.get('phone', '')
            normalized_phone = self._normalize_phone(phone)
            if normalized_phone:
                # Use recipient-specific message if provided, otherwise use default
                recipient_message = recipient.get('message', message)
                api_recipients.append({
                    'phone_number': normalized_phone,
                    'message': recipient_message,
                })
        
        if not api_recipients:
            logger.warning("No valid phone numbers found in recipients")
            return []
        
        # Call bulk SMS API
        try:
            url = f"{self.api_url}/sms/bulk/"
            payload = {
                'sms_account_number': organization.sms_account_number,
                'recipients': api_recipients,
                'purpose': purpose or 'bulk',
            }
            
            response = requests.post(
                url,
                json=payload,
                headers=self._get_headers(),
                timeout=60  # Longer timeout for bulk
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    # Create notification records for all recipients
                    notifications = []
                    results = data.get('results', [])
                    result_map = {r.get('phone_number'): r for r in results}
                    
                    for recipient in recipients:
                        phone = recipient.get('phone', '')
                        normalized_phone = self._normalize_phone(phone)
                        if normalized_phone:
                            result = result_map.get(normalized_phone, {})
                            recipient_message = recipient.get('message', message)
                            
                            notification = SMSNotification.objects.create(
                                organization=organization,
                                recipient_phone=normalized_phone,
                                message=recipient_message,
                                status=result.get('status', 'sent'),
                                sent_at=timezone.now() if result.get('status') == 'sent' else None,
                                error_message=result.get('error', '') if result.get('status') != 'sent' else '',
                                purpose=purpose or 'bulk',
                                related_student=recipient.get('student'),
                                triggered_by=triggered_by
                            )
                            notifications.append(notification)
                    
                    logger.info(f"Bulk SMS complete. Sent: {sum(1 for n in notifications if n.status == 'sent')}, Failed: {sum(1 for n in notifications if n.status == 'failed')}")
                    return notifications
                else:
                    error_msg = data.get('error', 'Unknown error')
                    logger.error(f"Bulk SMS failed: {error_msg}")
                    # Create failed notifications
                    notifications = []
                    for recipient in recipients:
                        phone = recipient.get('phone', '')
                        normalized_phone = self._normalize_phone(phone)
                        if normalized_phone:
                            notifications.append(self._create_failed_notification(
                                normalized_phone, message, organization, purpose,
                                error_msg, recipient.get('student'), triggered_by
                            ))
                    return notifications
            else:
                error_msg = f"API returned status {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', error_msg)
                except:
                    error_msg = f"{error_msg}: {response.text[:200]}"
                
                logger.error(f"Bulk SMS API error: {error_msg}")
                # Create failed notifications
                notifications = []
                for recipient in recipients:
                    phone = recipient.get('phone', '')
                    normalized_phone = self._normalize_phone(phone)
                    if normalized_phone:
                        notifications.append(self._create_failed_notification(
                            normalized_phone, message, organization, purpose,
                            error_msg, recipient.get('student'), triggered_by
                        ))
                return notifications
        
        except requests.exceptions.RequestException as e:
            error_msg = f"API request failed: {str(e)}"
            logger.error(f"Bulk SMS API request error: {error_msg}", exc_info=True)
            # Create failed notifications
            notifications = []
            for recipient in recipients:
                phone = recipient.get('phone', '')
                normalized_phone = self._normalize_phone(phone)
                if normalized_phone:
                    notifications.append(self._create_failed_notification(
                        normalized_phone, message, organization, purpose,
                        error_msg, recipient.get('student'), triggered_by
                    ))
            return notifications
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(f"Bulk SMS error: {error_msg}", exc_info=True)
            # Create failed notifications
            notifications = []
            for recipient in recipients:
                phone = recipient.get('phone', '')
                normalized_phone = self._normalize_phone(phone)
                if normalized_phone:
                    notifications.append(self._create_failed_notification(
                        normalized_phone, message, organization, purpose,
                        error_msg, recipient.get('student'), triggered_by
                    ))
            return notifications
    
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


# Create singleton instance
sms_api_client = SMSAPIClient()
