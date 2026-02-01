"""
SMS notification service using imarabiz API

Enhanced with:
- Batching for large sends (avoid Heroku timeouts)
- Async processing using threading
- Balance checking
- Delivery report checking
- SMS credits integration
- Enhanced logging
- Dynamic per-organization shortcode selection
"""
import requests
import json
import logging
import threading
import time
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from .utils import get_organization_model

logger = logging.getLogger(__name__)


def normalize_phone_number(phone_number):
    """
    Normalize phone number to 254xxxxxxxxx format (without +)
    
    Handles:
    - 0xxxxxxxxx -> 254xxxxxxxxx
    - 254xxxxxxxxx -> 254xxxxxxxxx (already correct)
    - +254xxxxxxxxx -> 254xxxxxxxxx (remove +)
    - 7xxxxxxxxx -> 2547xxxxxxxxx (add country code)
    """
    if not phone_number:
        return None
    
    # Remove whitespace
    phone_number = str(phone_number).strip()
    
    # Remove + sign if present
    if phone_number.startswith('+'):
        phone_number = phone_number[1:]
    
    # Remove spaces and dashes
    phone_number = phone_number.replace(' ', '').replace('-', '')
    
    # Handle different formats
    if phone_number.startswith('0'):
        # 0xxxxxxxxx -> 254xxxxxxxxx
        phone_number = '254' + phone_number[1:]
    elif phone_number.startswith('254'):
        # Already correct format
        pass
    elif phone_number.startswith('7') and len(phone_number) == 9:
        # 7xxxxxxxxx -> 2547xxxxxxxxx
        phone_number = '254' + phone_number
    elif not phone_number.startswith('254'):
        # Try to add country code if missing
        if len(phone_number) == 9:
            phone_number = '254' + phone_number
    
    return phone_number


def get_shortcode_for_organization(organization):
    """
    Get shortcode for organization with fallback chain:
    1. organization.imarabiz_shortcode (if set)
    2. SWIFT_RE_TECH (company default)
    3. IMARABIZ_SHORTCODE setting (legacy fallback)
    """
    default_shortcode = getattr(settings, 'SWIFT_DEFAULT_SHORTCODE', 'SWIFT_RE_TECH')
    setting_shortcode = getattr(settings, 'IMARABIZ_SHORTCODE', '')
    
    if organization:
        org_shortcode = getattr(organization, 'imarabiz_shortcode', None)
        if org_shortcode and org_shortcode.strip():
            return org_shortcode.strip()
    
    # Fallback to company default
    if default_shortcode:
        return default_shortcode
    
    # Final fallback to setting
    return setting_shortcode or 'SWIFT_RE_TECH'


class SMSService:
    """
    imarabiz SMS service wrapper with batching, async processing, and credits integration
    """
    
    def __init__(self):
        self.api_key = getattr(settings, 'IMARABIZ_API_KEY', '')
        self.partner_id = getattr(settings, 'IMARABIZ_PARTNER_ID', '')
        self.default_shortcode = getattr(settings, 'SWIFT_DEFAULT_SHORTCODE', 'SWIFT_RE_TECH')
        self.api_url = getattr(settings, 'IMARABIZ_API_URL', 'https://sms.imarabiz.com/api/services/')
        
        # Paybill and account info for templates
        self.paybill_number = getattr(settings, 'PAYBILL_NUMBER', '522533')
        self.account_number = getattr(settings, 'ACCOUNT_NUMBER', '8049876')
        
        # Batching config
        self.batch_size = getattr(settings, 'SMS_BATCH_SIZE', 50)
        self.batch_delay = getattr(settings, 'SMS_BATCH_DELAY', 1.0)
        self.async_enabled = getattr(settings, 'SMS_ASYNC_ENABLED', True)
        
        if not self.api_key or not self.partner_id:
            logger.warning("imarabiz SMS API credentials not configured")
    
    def get_account_balance(self):
        """
        Get imarabiz account balance
        
        Returns:
            dict with 'success', 'balance', 'error' keys
        """
        if not self.api_key or not self.partner_id:
            return {'success': False, 'error': 'SMS service not configured'}
        
        try:
            url = f"{self.api_url}getbalance/"
            payload = {
                'apikey': self.api_key,
                'partnerID': self.partner_id,
            }
            
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"SMS Balance check result: {result}")
            
            if isinstance(result, dict) and 'balance' in result:
                return {'success': True, 'balance': result.get('balance')}
            elif isinstance(result, dict) and 'credit' in result:
                return {'success': True, 'balance': result.get('credit')}
            
            return {'success': True, 'balance': str(result)}
            
        except Exception as e:
            logger.error(f"Failed to get SMS balance: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def get_delivery_report(self, message_id):
        """
        Get delivery report for a specific message
        
        Args:
            message_id: Message ID from send response
        
        Returns:
            dict with 'success', 'status', 'error' keys
        """
        if not self.api_key or not self.partner_id:
            return {'success': False, 'error': 'SMS service not configured'}
        
        if not message_id:
            return {'success': False, 'error': 'Message ID required'}
        
        try:
            url = f"{self.api_url}getdlr/"
            payload = {
                'apikey': self.api_key,
                'partnerID': self.partner_id,
                'messageID': message_id,
            }
            
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"SMS DLR result for {message_id}: {result}")
            
            return {'success': True, 'status': result}
            
        except Exception as e:
            logger.error(f"Failed to get DLR for {message_id}: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def _send_single_sms(self, phone_number, message, client_sms_id=None, shortcode=None):
        """
        Send single SMS using imarabiz API (POST method)
        
        Args:
            phone_number: Recipient phone number
            message: SMS message
            client_sms_id: Optional client SMS ID
            shortcode: Optional shortcode (defaults to SWIFT_RE_TECH)
        
        Returns:
            dict with 'success', 'message_id', 'error' keys
        """
        if not self.api_key or not self.partner_id:
            return {'success': False, 'error': 'SMS service not configured'}
        
        # Use provided shortcode or fallback to default
        use_shortcode = shortcode or self.default_shortcode
        
        try:
            normalized_phone = normalize_phone_number(phone_number)
            if not normalized_phone:
                logger.warning(f"SMS send failed: Invalid phone number '{phone_number}'")
                return {'success': False, 'error': 'Invalid phone number'}
            
            # Prepare request payload
            payload = {
                'apikey': self.api_key,
                'partnerID': self.partner_id,
                'mobile': normalized_phone,
                'message': message,
                'shortcode': use_shortcode,
                'pass_type': 'plain'
            }
            
            # Add client_sms_id if provided
            if client_sms_id:
                payload['clientsmsid'] = client_sms_id
            
            # Send request
            url = f"{self.api_url}sendsms/"
            start_time = time.time()
            response = requests.post(url, json=payload, timeout=10)
            elapsed = time.time() - start_time
            response.raise_for_status()
            
            result = response.json()
            
            # Log the response
            logger.info(
                f"SMS SENT: phone={normalized_phone}, "
                f"shortcode={use_shortcode}, "
                f"chars={len(message)}, "
                f"elapsed={elapsed:.2f}s, "
                f"response={result}"
            )
            
            # Check response format (may vary)
            if isinstance(result, dict):
                # Look for success indicators
                if 'messageID' in result or 'status' in result:
                    message_id = result.get('messageID') or result.get('status')
                    return {'success': True, 'message_id': str(message_id)}
                elif 'error' in result:
                    logger.error(f"SMS API error: {result.get('error')}")
                    return {'success': False, 'error': result.get('error')}
            
            # Default: assume success if no error in response
            return {'success': True, 'message_id': str(result) if result else 'unknown'}
            
        except requests.exceptions.Timeout:
            logger.error(f"SMS send timeout for {phone_number}")
            return {'success': False, 'error': 'API timeout'}
        except requests.exceptions.RequestException as e:
            logger.error(f"SMS API request error for {phone_number}: {str(e)}")
            return {'success': False, 'error': f'API request failed: {str(e)}'}
        except Exception as e:
            logger.error(f"SMS sending error for {phone_number}: {str(e)}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    def _send_bulk_sms(self, sms_list, shortcode=None):
        """
        Send bulk SMS using imarabiz API
        
        Args:
            sms_list: List of dicts with 'mobile', 'message', 'clientsmsid' keys
            shortcode: Optional shortcode (defaults to SWIFT_RE_TECH)
        
        Returns:
            dict with 'success', 'results', 'error' keys
        """
        if not self.api_key or not self.partner_id:
            return {'success': False, 'error': 'SMS service not configured'}
        
        # Use provided shortcode or fallback to default
        use_shortcode = shortcode or self.default_shortcode
        
        try:
            # Normalize phone numbers
            normalized_sms_list = []
            for sms_item in sms_list:
                normalized_phone = normalize_phone_number(sms_item.get('mobile'))
                if normalized_phone:
                    normalized_sms_list.append({
                        'partnerID': self.partner_id,
                        'apikey': self.api_key,
                        'pass_type': 'plain',
                        'clientsmsid': sms_item.get('clientsmsid', ''),
                        'mobile': normalized_phone,
                        'message': sms_item.get('message', ''),
                        'shortcode': use_shortcode
                    })
            
            if not normalized_sms_list:
                return {'success': False, 'error': 'No valid phone numbers'}
            
            # Prepare bulk payload
            payload = {
                'count': len(normalized_sms_list),
                'smslist': normalized_sms_list
            }
            
            # Send request
            url = f"{self.api_url}sendbulk/"
            start_time = time.time()
            response = requests.post(url, json=payload, timeout=30)
            elapsed = time.time() - start_time
            response.raise_for_status()
            
            result = response.json()
            
            logger.info(
                f"BULK SMS SENT: count={len(normalized_sms_list)}, "
                f"shortcode={use_shortcode}, "
                f"elapsed={elapsed:.2f}s, "
                f"response_type={type(result).__name__}"
            )
            
            # Parse bulk response
            if isinstance(result, dict):
                if 'error' in result:
                    return {'success': False, 'error': result.get('error')}
                # Return success with results
                return {'success': True, 'results': result}
            
            return {'success': True, 'results': result}
            
        except requests.exceptions.Timeout:
            logger.error(f"Bulk SMS send timeout")
            return {'success': False, 'error': 'API timeout'}
        except requests.exceptions.RequestException as e:
            logger.error(f"Bulk SMS API request error: {str(e)}")
            return {'success': False, 'error': f'API request failed: {str(e)}'}
        except Exception as e:
            logger.error(f"Bulk SMS sending error: {str(e)}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    def _check_and_deduct_credits(self, organization, sms_count, user=None):
        """
        Check if organization has enough SMS credits and deduct them.
        
        Args:
            organization: Organization instance
            sms_count: Number of SMS to send
            user: User who triggered the send (for logging)
        
        Returns:
            tuple (success: bool, error_message: str or None)
        """
        if not organization:
            logger.warning("SMS credit check: No organization provided")
            return False, "No organization specified"
        
        try:
            # Try to import from package first, fallback to tenants app
            try:
                from .models import SMSUsageLog
            except ImportError:
                # Fallback to tenants app (for current app compatibility)
                from tenants.models import SMSUsageLog
            
            Organization = get_organization_model()
            
            with transaction.atomic():
                # Lock organization for update
                org = Organization.objects.select_for_update().get(id=organization.id)
                
                if org.sms_balance < sms_count:
                    logger.warning(
                        f"SMS credit check FAILED: org={org.name}, "
                        f"required={sms_count}, available={org.sms_balance}"
                    )
                    return False, f"Insufficient SMS credits. Need {sms_count}, have {org.sms_balance}"
                
                # Deduct credits
                balance_before = org.sms_balance
                org.sms_balance -= sms_count
                org.save(update_fields=['sms_balance', 'updated_at'])
                
                # Log usage
                SMSUsageLog.objects.create(
                    organization=org,
                    sms_count=sms_count,
                    purpose='sms_send',
                    balance_before=balance_before,
                    balance_after=org.sms_balance,
                    triggered_by=user,
                )
                
                logger.info(
                    f"SMS credits DEDUCTED: org={org.name}, "
                    f"count={sms_count}, balance: {balance_before} -> {org.sms_balance}"
                )
                
                return True, None
                
        except Exception as e:
            logger.error(f"SMS credit deduction error: {str(e)}", exc_info=True)
            return False, str(e)
    
    def _refund_credits(self, organization, sms_count, reason="Send failed"):
        """Refund SMS credits if send fails after deduction"""
        if not organization:
            return
        
        try:
            # Try to import from package first, fallback to tenants app
            try:
                from .models import SMSUsageLog
            except ImportError:
                # Fallback to tenants app (for current app compatibility)
                from tenants.models import SMSUsageLog
            
            Organization = get_organization_model()
            
            with transaction.atomic():
                org = Organization.objects.select_for_update().get(id=organization.id)
                balance_before = org.sms_balance
                org.sms_balance += sms_count
                org.save(update_fields=['sms_balance', 'updated_at'])
                
                SMSUsageLog.objects.create(
                    organization=org,
                    sms_count=-sms_count,  # Negative for refund
                    purpose=f'refund: {reason}',
                    balance_before=balance_before,
                    balance_after=org.sms_balance,
                )
                
                logger.info(
                    f"SMS credits REFUNDED: org={org.name}, "
                    f"count={sms_count}, reason='{reason}', "
                    f"balance: {balance_before} -> {org.sms_balance}"
                )
                
        except Exception as e:
            logger.error(f"SMS credit refund error: {str(e)}", exc_info=True)
    
    def send_sms(self, phone_number, message, parent=None, client_sms_id=None, 
                 organization=None, user=None, purpose='manual', check_credits=True,
                 sms_notification_model=None):
        """
        Send SMS to a phone number (fails silently)
        
        Args:
            phone_number: Recipient phone number
            message: SMS message content
            parent: Optional Parent instance for logging
            client_sms_id: Optional client SMS ID for tracking
            organization: Organization to charge credits from
            user: User who triggered the send
            purpose: Purpose of the SMS (for logging)
            check_credits: Whether to check/deduct credits (default True)
            sms_notification_model: Optional SMSNotification model class (for logging)
        
        Returns:
            SMSNotification instance (if model provided) or None
        """
        # Determine organization
        if not organization and parent:
            organization = getattr(parent, 'organization', None)
        
        # Get shortcode from organization dynamically
        shortcode = get_shortcode_for_organization(organization)
        
        # Calculate SMS cost (long messages use multiple credits)
        sms_cost = self._calculate_sms_cost(message)
        
        # Create notification record if model provided
        notification = None
        if sms_notification_model:
            try:
                notification = sms_notification_model.objects.create(
                    organization=organization,
                    parent=parent,
                    phone_number=phone_number,
                    message=message,
                    status='pending',
                    client_sms_id=client_sms_id or '',
                    sms_cost=sms_cost,
                    purpose=purpose,
                )
            except Exception as e:
                logger.warning(f"Failed to create SMS notification record: {str(e)}")
        
        # Check and deduct credits if required
        if check_credits and organization:
            success, error = self._check_and_deduct_credits(organization, sms_cost, user)
            if not success:
                if notification:
                    notification.status = 'failed'
                    notification.error_message = error
                    notification.save()
                logger.warning(f"SMS not sent (no credits): {phone_number} - {error}")
                return notification
        
        try:
            # Send SMS with organization's shortcode
            result = self._send_single_sms(phone_number, message, client_sms_id, shortcode=shortcode)
            
            if result.get('success'):
                if notification:
                    notification.status = 'sent'
                    notification.sent_at = timezone.now()
                    notification.message_id = result.get('message_id', '')
                    notification.save()
                logger.info(f"SMS sent successfully to {phone_number} with shortcode {shortcode}")
            else:
                if notification:
                    notification.status = 'failed'
                    notification.error_message = result.get('error', 'Unknown error')
                    notification.save()
                logger.error(f"SMS send failed to {phone_number}: {result.get('error', 'Unknown error')}")
                
                # Refund credits if send failed
                if check_credits and organization:
                    self._refund_credits(organization, sms_cost, result.get('error', 'Unknown error'))
            
        except Exception as e:
            # Fail silently - log error but don't raise
            logger.error(f"Failed to send SMS to {phone_number}: {str(e)}", exc_info=True)
            if notification:
                notification.status = 'failed'
                notification.error_message = str(e)
                notification.save()
            
            # Refund credits if exception
            if check_credits and organization:
                self._refund_credits(organization, sms_cost, str(e))
        
        return notification
    
    def _calculate_sms_cost(self, message):
        """Calculate SMS cost based on message length"""
        if not message:
            return 1
        
        # Standard SMS is 160 chars, concatenated SMS use 153 chars per part
        msg_len = len(message)
        if msg_len <= 160:
            return 1
        else:
            # Each additional part after first uses 153 chars (7 chars for header)
            return 1 + ((msg_len - 160) // 153) + (1 if (msg_len - 160) % 153 > 0 else 0)
    
    def send_bulk_sms(self, recipients, organization=None, user=None, 
                      purpose='bulk', fail_silently=True, check_credits=True,
                      sms_notification_model=None):
        """
        Send SMS to multiple recipients with batching
        
        Args:
            recipients: List of dicts with 'phone_number', 'message', 'parent' (optional), 'client_sms_id' (optional)
            organization: Organization to charge credits from
            user: User who triggered the send
            purpose: Purpose of the SMS batch
            fail_silently: If True, continue even if some SMS fail
            check_credits: Whether to check/deduct credits
            sms_notification_model: Optional SMSNotification model class (for logging)
        
        Returns:
            List of SMSNotification instances (if model provided) or empty list
        """
        if not recipients:
            return []
        
        # Determine organization from first recipient if not provided
        if not organization and recipients:
            parent = recipients[0].get('parent')
            if parent:
                organization = getattr(parent, 'organization', None)
        
        # Get shortcode from organization dynamically
        shortcode = get_shortcode_for_organization(organization)
        
        # Calculate total SMS cost
        total_cost = sum(
            self._calculate_sms_cost(r.get('message', '')) 
            for r in recipients
        )
        
        logger.info(
            f"BULK SMS: Starting send to {len(recipients)} recipients, "
            f"total_cost={total_cost}, org={organization.name if organization else 'None'}, "
            f"shortcode={shortcode}"
        )
        
        # Check credits for entire batch
        if check_credits and organization:
            success, error = self._check_and_deduct_credits(organization, total_cost, user)
            if not success:
                logger.error(f"Bulk SMS aborted - insufficient credits: {error}")
                # Create failed notifications for all recipients
                notifications = []
                if sms_notification_model:
                    for r in recipients:
                        try:
                            notification = sms_notification_model.objects.create(
                                organization=organization,
                                parent=r.get('parent'),
                                phone_number=r.get('phone_number', ''),
                                message=r.get('message', ''),
                                status='failed',
                                error_message=error,
                                sms_cost=self._calculate_sms_cost(r.get('message', '')),
                                purpose=purpose,
                            )
                            notifications.append(notification)
                        except Exception:
                            pass
                return notifications
        
        notifications = []
        failed_count = 0
        
        # Check if all messages are the same for bulk API
        unique_messages = set(r.get('message', '') for r in recipients)
        use_bulk_api = len(unique_messages) == 1 and len(recipients) > 1
        
        # Process in batches
        for batch_start in range(0, len(recipients), self.batch_size):
            batch = recipients[batch_start:batch_start + self.batch_size]
            batch_num = batch_start // self.batch_size + 1
            total_batches = (len(recipients) + self.batch_size - 1) // self.batch_size
            
            logger.info(f"BULK SMS: Processing batch {batch_num}/{total_batches} ({len(batch)} SMS)")
            
            if use_bulk_api:
                # Use bulk API for same-message sends
                batch_notifications = self._send_batch_bulk(
                    batch, organization, purpose, shortcode, sms_notification_model
                )
            else:
                # Send individually for different messages
                batch_notifications = self._send_batch_individual(
                    batch, organization, purpose, shortcode, sms_notification_model
                )
            
            notifications.extend(batch_notifications)
            failed_count += sum(1 for n in batch_notifications if n and hasattr(n, 'status') and n.status == 'failed')
            
            # Delay between batches (avoid rate limiting)
            if batch_start + self.batch_size < len(recipients):
                logger.debug(f"BULK SMS: Waiting {self.batch_delay}s before next batch")
                time.sleep(self.batch_delay)
        
        # Refund credits for failed sends
        if check_credits and organization and failed_count > 0:
            failed_cost = sum(
                (n.sms_cost if hasattr(n, 'sms_cost') else 1) 
                for n in notifications 
                if n and hasattr(n, 'status') and n.status == 'failed'
            )
            if failed_cost > 0:
                self._refund_credits(organization, failed_cost, f"{failed_count} SMS failed")
        
        logger.info(
            f"BULK SMS: Completed - sent={len(notifications) - failed_count}, "
            f"failed={failed_count}, total={len(notifications)}"
        )
        
        return notifications
    
    def _send_batch_bulk(self, batch, organization, purpose, shortcode=None, sms_notification_model=None):
        """Send a batch using bulk API (same message for all)"""
        notifications = []
        
        try:
            sms_list = []
            for idx, recipient in enumerate(batch):
                phone_number = recipient.get('phone_number')
                message = recipient.get('message', '')
                client_sms_id = recipient.get('client_sms_id', f"bulk_{idx}")
                
                if phone_number and message:
                    sms_list.append({
                        'mobile': phone_number,
                        'message': message,
                        'clientsmsid': client_sms_id
                    })
            
            if sms_list:
                result = self._send_bulk_sms(sms_list, shortcode=shortcode)
                
                # Create notification records
                if sms_notification_model:
                    for idx, recipient in enumerate(batch):
                        phone_number = recipient.get('phone_number')
                        message = recipient.get('message', '')
                        parent = recipient.get('parent')
                        client_sms_id = recipient.get('client_sms_id', f"bulk_{idx}")
                        
                        try:
                            notification = sms_notification_model.objects.create(
                                organization=organization,
                                parent=parent,
                                phone_number=phone_number,
                                message=message,
                                status='sent' if result.get('success') else 'failed',
                                sent_at=timezone.now() if result.get('success') else None,
                                error_message='' if result.get('success') else result.get('error', 'Bulk send failed'),
                                client_sms_id=client_sms_id or '',
                                sms_cost=self._calculate_sms_cost(message),
                                purpose=purpose,
                            )
                            notifications.append(notification)
                        except Exception as e:
                            logger.warning(f"Failed to create notification: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Batch bulk send failed: {str(e)}", exc_info=True)
            # Create failed notifications
            if sms_notification_model:
                for recipient in batch:
                    try:
                        notification = sms_notification_model.objects.create(
                            organization=organization,
                            parent=recipient.get('parent'),
                            phone_number=recipient.get('phone_number', ''),
                            message=recipient.get('message', ''),
                            status='failed',
                            error_message=str(e),
                            sms_cost=self._calculate_sms_cost(recipient.get('message', '')),
                            purpose=purpose,
                        )
                        notifications.append(notification)
                    except Exception:
                        pass
        
        return notifications
    
    def _send_batch_individual(self, batch, organization, purpose, shortcode=None, sms_notification_model=None):
        """Send a batch individually (different messages)"""
        notifications = []
        
        for recipient in batch:
            try:
                notification = None
                if sms_notification_model:
                    try:
                        notification = sms_notification_model.objects.create(
                            organization=organization,
                            parent=recipient.get('parent'),
                            phone_number=recipient.get('phone_number', ''),
                            message=recipient.get('message', ''),
                            status='pending',
                            client_sms_id=recipient.get('client_sms_id', ''),
                            sms_cost=self._calculate_sms_cost(recipient.get('message', '')),
                            purpose=purpose,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to create notification: {str(e)}")
                
                result = self._send_single_sms(
                    recipient.get('phone_number'),
                    recipient.get('message', ''),
                    recipient.get('client_sms_id'),
                    shortcode=shortcode
                )
                
                if notification:
                    if result.get('success'):
                        notification.status = 'sent'
                        notification.sent_at = timezone.now()
                        notification.message_id = result.get('message_id', '')
                    else:
                        notification.status = 'failed'
                        notification.error_message = result.get('error', 'Unknown error')
                    notification.save()
                    notifications.append(notification)
                
            except Exception as e:
                logger.error(f"Individual send failed: {str(e)}")
                if sms_notification_model:
                    try:
                        notification = sms_notification_model.objects.create(
                            organization=organization,
                            parent=recipient.get('parent'),
                            phone_number=recipient.get('phone_number', ''),
                            message=recipient.get('message', ''),
                            status='failed',
                            error_message=str(e),
                            sms_cost=self._calculate_sms_cost(recipient.get('message', '')),
                            purpose=purpose,
                        )
                        notifications.append(notification)
                    except Exception:
                        pass
        
        return notifications
    
    def send_bulk_sms_async(self, recipients, organization=None, user=None, 
                            purpose='bulk', check_credits=True, sms_notification_model=None):
        """
        Send bulk SMS asynchronously using threading (for Heroku)
        Returns immediately, SMS sent in background.
        
        Args:
            Same as send_bulk_sms
        
        Returns:
            dict with 'success', 'message', 'count'
        """
        if not self.async_enabled:
            # Fall back to synchronous
            notifications = self.send_bulk_sms(
                recipients, organization, user, purpose, 
                fail_silently=True, check_credits=check_credits,
                sms_notification_model=sms_notification_model
            )
            return {
                'success': True,
                'message': f'Sent {len(notifications)} SMS',
                'count': len(notifications)
            }
        
        def async_send():
            try:
                self.send_bulk_sms(
                    recipients, organization, user, purpose,
                    fail_silently=True, check_credits=check_credits,
                    sms_notification_model=sms_notification_model
                )
            except Exception as e:
                logger.error(f"Async bulk SMS error: {str(e)}", exc_info=True)
        
        # Start background thread
        thread = threading.Thread(target=async_send)
        thread.daemon = True  # Thread will be killed when main process exits
        thread.start()
        
        logger.info(f"ASYNC SMS: Started background send for {len(recipients)} recipients")
        
        return {
            'success': True,
            'message': f'Queued {len(recipients)} SMS for sending',
            'count': len(recipients)
        }


# Create singleton instance
sms_service = SMSService()

