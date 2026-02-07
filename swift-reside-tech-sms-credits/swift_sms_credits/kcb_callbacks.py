"""
KCB Bank callback handlers for SMS Credit Purchases

This is a NEW endpoint specifically for Swift Reside Tech to receive
SMS credit purchase notifications. It is SEPARATE from the existing
school payment callbacks in payments/kcb_callbacks.py.

Account format: SWIFT_TILL#ORG_SMS_ACCOUNT
Example: SWIFTTECH#SMS001
"""
import json
import logging
from decimal import Decimal
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.conf import settings
from django.utils import timezone
from django.db import transaction

from .models import SMSPurchaseTransaction
from .utils import get_organization_model

logger = logging.getLogger(__name__)


def get_swift_kcb_config():
    """Get Swift Reside Tech KCB configuration"""
    return {
        'paybill': getattr(settings, 'SWIFT_RESIDE_PAYBILL', '522533'),
        'till': getattr(settings, 'SWIFT_RESIDE_TILL', 'SWIFTTECH'),
        'sms_price': Decimal(str(getattr(settings, 'SWIFT_SMS_PRICE', '1.0'))),
        'skip_signature': getattr(settings, 'SWIFT_KCB_SKIP_SIGNATURE_VERIFICATION', True),
    }


def verify_swift_signature(request_body, signature_header):
    """
    Verify KCB signature for Swift Reside Tech SMS endpoint.
    Standalone implementation - no dependency on payments.kcb
    """
    import base64
    import hmac
    import hashlib
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.backends import default_backend
    
    config = get_swift_kcb_config()
    
    # Skip verification if configured (for initial testing)
    if config['skip_signature']:
        logger.warning("SWIFT SMS: Skipping signature verification (SWIFT_KCB_SKIP_SIGNATURE_VERIFICATION=True)")
        return True
    
    if not signature_header:
        logger.warning("SWIFT SMS: Missing signature header")
        return False
    
    # Convert request body to bytes if string
    if isinstance(request_body, str):
        request_body = request_body.encode('utf-8')
    
    signature_method = getattr(settings, 'SWIFT_KCB_SIGNATURE_METHOD', 'auto')
    public_key_base64 = getattr(settings, 'SWIFT_KCB_PUBLIC_KEY_BASE64', '')
    signature_key = getattr(settings, 'SWIFT_KCB_SIGNATURE_KEY', '')
    
    # Try RSA first if public key available
    if public_key_base64 and signature_method in ('rsa', 'auto'):
        try:
            # Decode base64 to get PEM string
            pem_content = base64.b64decode(public_key_base64).decode('utf-8')
            public_key = serialization.load_pem_public_key(
                pem_content.encode('utf-8'),
                backend=default_backend()
            )
            
            # Decode base64 signature
            signature_bytes = base64.b64decode(signature_header)
            
            # Verify signature
            public_key.verify(
                signature_bytes,
                request_body,
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            logger.info("SWIFT SMS: RSA signature verification successful")
            return True
        except Exception as e:
            if signature_method == 'rsa':
                logger.warning(f"SWIFT SMS: RSA signature verification failed: {str(e)}")
                return False
            # If auto mode and RSA failed, try HMAC
    
    # Try HMAC if signature key available
    if signature_key and signature_method in ('hmac', 'auto'):
        try:
            # Generate expected signature
            expected_signature = hmac.new(
                signature_key.encode('utf-8'),
                request_body,
                hashlib.sha256
            ).digest()
            expected_signature_b64 = base64.b64encode(expected_signature).decode('utf-8')
            
            # Compare signatures (constant-time comparison)
            is_valid = hmac.compare_digest(expected_signature_b64, signature_header)
            if is_valid:
                logger.info("SWIFT SMS: HMAC signature verification successful")
            else:
                logger.warning("SWIFT SMS: HMAC signature verification failed")
            return is_valid
        except Exception as e:
            logger.error(f"SWIFT SMS: HMAC signature verification error: {str(e)}")
            return False
    
    logger.error("SWIFT SMS: No signature verification method available (missing keys)")
    return False


def extract_org_sms_account(customer_reference, swift_till):
    """
    Extract organization SMS account from customer reference.
    
    Account format: SWIFT_TILL#ORG_SMS_ACCOUNT
    Example: SWIFTTECH#SMS001 -> returns 'SMS001'
    
    Also handles: ORG_SMS_ACCOUNT only (no prefix)
    """
    if not customer_reference:
        return None
    
    customer_reference = customer_reference.strip().upper()
    
    # Check if it contains the swift till prefix
    if '#' in customer_reference:
        parts = customer_reference.split('#')
        if len(parts) >= 2:
            # Format: SWIFT_TILL#ORG_SMS_ACCOUNT or PAYBILL#SWIFT_TILL#ORG_SMS_ACCOUNT
            # Return the last part as the org SMS account
            return parts[-1].strip()
    
    # If no #, assume it's just the org SMS account
    return customer_reference


@csrf_exempt
@require_http_methods(["POST"])
def sms_credits_kcb_validation(request):
    """
    Handle KCB Bill Validation request for SMS Credit Purchases
    
    This endpoint validates that an organization exists with the given sms_account_number
    before processing payment.
    
    Request body from KCB:
    {
        "requestId": "uuid",
        "customerReference": "SWIFTTECH#SMS001"  // Organization's sms_account_number (with or without prefix)
    }
    
    Response to KCB:
    {
        "transactionID": "internal_id",
        "statusCode": "0",
        "statusMessage": "Success",
        "CustomerName": "Organization Name",
        "billAmount": "0.00",
        "currency": "KES",
        "billType": "PARTIAL",
        "creditAccountIdentifier": "SMS001"
    }
    
    Note: billType is "PARTIAL" which allows customers to pay any amount (custom amounts).
    billAmount is "0.00" for PARTIAL bills as per KCB API specification.
    """
    config = get_swift_kcb_config()
    
    try:
        # Get raw body for signature verification
        request_body = request.body
        
        # Verify signature
        signature_header = request.META.get('HTTP_SIGNATURE', '')
        
        logger.info("SMS Credits KCB validation request received - verifying signature")
        if not verify_swift_signature(request_body, signature_header):
            logger.warning("SMS Credits validation request failed signature verification")
            return JsonResponse({
                'transactionID': '',
                'statusCode': '1',
                'statusMessage': 'Invalid signature',
                'CustomerName': '',
                'billAmount': '0.00',
                'currency': 'KES',
                'billType': 'PARTIAL',
                'creditAccountIdentifier': '',
            }, status=401)
        
        logger.info("SMS Credits KCB validation signature verified successfully")
        
        # Parse request data
        try:
            data = json.loads(request_body)
        except json.JSONDecodeError as e:
            logger.error(f"SMS Credits validation request: Invalid JSON - {str(e)}")
            return JsonResponse({
                'transactionID': '',
                'statusCode': '1',
                'statusMessage': 'Invalid JSON',
                'CustomerName': '',
                'billAmount': '0.00',
                'currency': 'KES',
                'billType': 'PARTIAL',
                'creditAccountIdentifier': '',
            }, status=400)
        
        customer_reference = data.get('customerReference', '').strip()
        request_id = data.get('requestId', '')
        
        # Validate required fields
        if not customer_reference:
            logger.error("SMS Credits validation request: Missing customerReference")
            return JsonResponse({
                'transactionID': '',
                'statusCode': '1',
                'statusMessage': 'customerReference is required',
                'CustomerName': '',
                'billAmount': '0.00',
                'currency': 'KES',
                'billType': 'PARTIAL',
                'creditAccountIdentifier': '',
            }, status=400)
        
        # Extract SMS account number (handle formats with #)
        sms_account_number = extract_org_sms_account(customer_reference, config['till'])
        if not sms_account_number:
            logger.error(f"SMS Credits validation request: Could not extract SMS account from: {customer_reference}")
            return JsonResponse({
                'transactionID': '',
                'statusCode': '1',
                'statusMessage': 'Invalid account format',
                'CustomerName': '',
                'billAmount': '0.00',
                'currency': 'KES',
                'billType': 'PARTIAL',
                'creditAccountIdentifier': customer_reference,
            }, status=400)
        
        # Find organization by SMS account number
        Organization = get_organization_model()
        logger.info(f"SMS Credits validation: Validating SMS account: {sms_account_number}")
        try:
            organization = Organization.objects.get(sms_account_number=sms_account_number, is_active=True)
            
            logger.info(f"SMS Credits validation successful for organization: {organization.name} (SMS Account: {sms_account_number})")
            
            return JsonResponse({
                'transactionID': str(organization.id),
                'statusCode': '0',
                'statusMessage': 'Success',
                'CustomerName': organization.name,
                'billAmount': '0.00',
                'currency': 'KES',
                'billType': 'PARTIAL',  # PARTIAL allows any payment amount
                'creditAccountIdentifier': sms_account_number,
            })
        except Organization.DoesNotExist:
            logger.warning(f"SMS Credits validation failed: Organization not found for SMS account: {sms_account_number}")
            return JsonResponse({
                'transactionID': '',
                'statusCode': '1',
                'statusMessage': 'Organization not found',
                'CustomerName': '',
                'billAmount': '0.00',
                'currency': 'KES',
                'billType': 'PARTIAL',
                'creditAccountIdentifier': sms_account_number,
            }, status=400)
        except Exception as e:
            logger.error(f"SMS Credits validation error for {sms_account_number}: {str(e)}")
            return JsonResponse({
                'transactionID': '',
                'statusCode': '1',
                'statusMessage': f'Validation error: {str(e)}',
                'CustomerName': '',
                'billAmount': '0.00',
                'currency': 'KES',
                'billType': 'PARTIAL',
                'creditAccountIdentifier': sms_account_number,
            }, status=500)
        
    except json.JSONDecodeError as e:
        logger.error(f"SMS Credits validation request: Invalid JSON - {str(e)}")
        return JsonResponse({
            'transactionID': '',
            'statusCode': '1',
            'statusMessage': 'Invalid JSON',
            'CustomerName': '',
            'billAmount': '0.00',
            'currency': 'KES',
            'billType': 'PARTIAL',
            'creditAccountIdentifier': '',
        }, status=400)
    except Exception as e:
        logger.error(f"SMS Credits validation error: {str(e)}", exc_info=True)
        return JsonResponse({
            'transactionID': '',
            'statusCode': '1',
            'statusMessage': f'Validation error: {str(e)}',
            'CustomerName': '',
            'billAmount': '0.00',
            'currency': 'KES',
            'billType': 'PARTIAL',
            'creditAccountIdentifier': '',
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def sms_credits_kcb_notification(request):
    """
    Handle KCB Payment Notification for SMS Credit Purchases
    
    This endpoint receives notifications when organizations pay to purchase SMS credits.
    Account format: SWIFT_TILL#ORG_SMS_ACCOUNT (e.g., SWIFTTECH#SMS001)
    
    Request body from KCB:
    {
        "transactionReference": "FT00026252",
        "requestId": "uuid",
        "channelCode": "202",
        "timestamp": "2021111103005",
        "transactionAmount": "1000.00",
        "currency": "KES",
        "customerReference": "SWIFTTECH#SMS001",  // Our account format
        "customerName": "John Doe",
        "customerMobileNumber": "25471111111",
        "balance": "100000.00",
        "narration": "SMS Credits Purchase",
        "creditAccountIdentifier": "SWIFTTECH#SMS001",
        "organizationShortCode": "522533",
        "tillNumber": "SWIFTTECH"
    }
    """
    config = get_swift_kcb_config()
    
    try:
        # Get raw body for signature verification
        request_body = request.body
        signature_header = request.META.get('HTTP_SIGNATURE', '')
        
        logger.info("=== SWIFT SMS Credits KCB Notification Received ===")
        
        # Verify signature
        if not verify_swift_signature(request_body, signature_header):
            logger.warning("SWIFT SMS: Failed signature verification")
            return JsonResponse({
                'transactionID': '',
                'statusCode': '1',
                'statusMessage': 'Invalid signature',
            }, status=401)
        
        # Parse request data
        try:
            data = json.loads(request_body)
            logger.info(f"SWIFT SMS: Received payload: {json.dumps(data, indent=2)}")
        except json.JSONDecodeError as e:
            logger.error(f"SWIFT SMS: Invalid JSON - {str(e)}")
            return JsonResponse({
                'transactionID': '',
                'statusCode': '1',
                'statusMessage': 'Invalid JSON',
            }, status=400)
        
        # Extract fields
        transaction_reference = data.get('transactionReference', '').strip()
        customer_reference = data.get('customerReference', '').strip()
        transaction_amount = data.get('transactionAmount', '0')
        channel_code = data.get('channelCode', '').strip()
        timestamp = data.get('timestamp', '').strip()
        customer_mobile = data.get('customerMobileNumber', '').strip()
        customer_name = data.get('customerName', '').strip()
        balance = data.get('balance', '').strip()
        narration = data.get('narration', '').strip()
        request_id = data.get('requestId', '').strip()
        
        # Validate required fields
        if not transaction_reference:
            logger.error("SWIFT SMS: Missing transactionReference")
            return JsonResponse({
                'transactionID': '',
                'statusCode': '1',
                'statusMessage': 'transactionReference is required',
            }, status=400)
        
        if not customer_reference:
            logger.error("SWIFT SMS: Missing customerReference")
            return JsonResponse({
                'transactionID': '',
                'statusCode': '1',
                'statusMessage': 'customerReference is required',
            }, status=400)
        
        # Check for duplicate transaction
        if SMSPurchaseTransaction.objects.filter(bank_reference=transaction_reference).exists():
            existing = SMSPurchaseTransaction.objects.get(bank_reference=transaction_reference)
            logger.info(f"SWIFT SMS: Duplicate transaction ignored - {transaction_reference}")
            return JsonResponse({
                'transactionID': str(existing.id),
                'statusCode': '0',
                'statusMessage': 'Already processed',
            })
        
        # Extract organization SMS account number
        org_sms_account = extract_org_sms_account(customer_reference, config['till'])
        if not org_sms_account:
            logger.error(f"SWIFT SMS: Could not extract org SMS account from: {customer_reference}")
            return JsonResponse({
                'transactionID': '',
                'statusCode': '1',
                'statusMessage': 'Invalid account format',
            }, status=400)
        
        logger.info(f"SWIFT SMS: Extracted org SMS account: {org_sms_account}")
        
        # Find organization by SMS account number
        Organization = get_organization_model()
        try:
            organization = Organization.objects.get(sms_account_number=org_sms_account, is_active=True)
            logger.info(f"SWIFT SMS: Found organization - {organization.name}")
        except Organization.DoesNotExist:
            logger.error(f"SWIFT SMS: Organization not found for SMS account: {org_sms_account}")
            return JsonResponse({
                'transactionID': '',
                'statusCode': '1',
                'statusMessage': f'Organization not found for account: {org_sms_account}',
            }, status=400)
        
        # Parse amount
        try:
            amount = Decimal(str(transaction_amount))
            if amount <= 0:
                raise ValueError("Amount must be positive")
        except (ValueError, TypeError) as e:
            logger.error(f"SWIFT SMS: Invalid amount: {transaction_amount} - {str(e)}")
            return JsonResponse({
                'transactionID': '',
                'statusCode': '1',
                'statusMessage': 'Invalid transaction amount',
            }, status=400)
        
        # Calculate SMS credits
        sms_price = organization.sms_price_per_unit or config['sms_price']
        sms_credits = int(amount / sms_price)
        
        if sms_credits <= 0:
            logger.error(f"SWIFT SMS: Amount too low - KES {amount} yields 0 credits at KES {sms_price}/SMS")
            return JsonResponse({
                'transactionID': '',
                'statusCode': '1',
                'statusMessage': f'Amount too low. Minimum is KES {sms_price} for 1 SMS credit.',
            }, status=400)
        
        # Create transaction and credit organization atomically
        with transaction.atomic():
            # Lock organization for update
            organization = Organization.objects.select_for_update().get(id=organization.id)
            
            # Create purchase transaction
            purchase = SMSPurchaseTransaction.objects.create(
                organization=organization,
                amount=amount,
                sms_credits=sms_credits,
                price_per_sms=sms_price,
                status='completed',
                bank_reference=transaction_reference,
                kcb_channel_code=channel_code,
                kcb_timestamp=timestamp,
                kcb_till_number=config['till'],
                kcb_customer_mobile=customer_mobile,
                kcb_customer_name=customer_name,
                kcb_narration=narration,
                kcb_balance=balance,
                raw_request_data=data,
                completed_at=timezone.now(),
            )
            
            # Credit organization's SMS balance
            old_balance = organization.sms_balance
            organization.sms_balance += sms_credits
            organization.save(update_fields=['sms_balance', 'updated_at'])
            
            logger.info(
                f"SWIFT SMS: Payment processed successfully - "
                f"Org={organization.name}, Amount=KES {amount}, Credits={sms_credits}, "
                f"Balance: {old_balance} -> {organization.sms_balance}, "
                f"Ref={transaction_reference}"
            )
        
        return JsonResponse({
            'transactionID': str(purchase.id),
            'statusCode': '0',
            'statusMessage': 'Notification received',
        })
        
    except Exception as e:
        logger.error(f"SWIFT SMS: Error processing notification - {str(e)}", exc_info=True)
        return JsonResponse({
            'transactionID': '',
            'statusCode': '1',
            'statusMessage': f'Error: {str(e)}',
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def sms_credits_kcb_till_notification(request):
    """
    Handle KCB Till Payment Notification for SMS Credit Purchases
    
    This is similar to the till notification in payments/kcb_callbacks.py
    but specifically for Swift Reside Tech SMS credit purchases.
    
    Per KCB IPN API Specification Document v1.0.4:
    - Nested JSON structure with header and requestPayload
    - businessKey in notificationData = org SMS account number
    """
    config = get_swift_kcb_config()
    message_id = ''
    originator_conversation_id = ''
    
    try:
        request_body = request.body
        signature_header = request.META.get('HTTP_SIGNATURE', '')
        
        logger.info("=== SWIFT SMS Credits KCB Till Notification Received ===")
        
        # Verify signature
        if not verify_swift_signature(request_body, signature_header):
            logger.warning("SWIFT SMS Till: Failed signature verification")
            return JsonResponse({
                'header': {
                    'messageID': message_id,
                    'originatorConversationID': originator_conversation_id,
                    'statusCode': '1',
                    'statusMessage': 'Invalid signature',
                },
                'responsePayload': {
                    'transactionInfo': {
                        'transactionId': ''
                    }
                }
            }, status=401)
        
        # Parse nested payload per KCB IPN spec
        data = json.loads(request_body)
        logger.info(f"SWIFT SMS Till: Received payload: {json.dumps(data, indent=2)}")
        
        # Extract header fields
        header = data.get('header', {})
        message_id = header.get('messageID', '')
        originator_conversation_id = header.get('originatorConversationID', '')
        channel_code = header.get('channelCode', '')
        timestamp = header.get('timeStamp', '')
        
        # Extract notification data from nested structure
        request_payload = data.get('requestPayload', {})
        primary_data = request_payload.get('primaryData', {})
        additional_data = request_payload.get('additionalData', {})
        notification_data = additional_data.get('notificationData', {})
        
        logger.info(f"SWIFT SMS Till: notificationData: {json.dumps(notification_data, indent=2)}")
        
        # Map KCB fields
        # businessKey (with businessKeyType=BillReferenceNumber) = org SMS account
        # Handle format like "SWIFTTECH#SMS001" - extract SMS account
        business_key_raw = notification_data.get('businessKey', '').strip()
        org_sms_account = extract_org_sms_account(business_key_raw, config['till'])
        
        transaction_reference = notification_data.get('transactionID', '').strip()
        transaction_amount = notification_data.get('transactionAmt', '0')
        customer_mobile = notification_data.get('debitMSISDN', '').strip()
        first_name = notification_data.get('firstName', '').strip()
        middle_name = notification_data.get('middleName', '').strip()
        last_name = notification_data.get('lastName', '').strip()
        customer_name = f"{first_name} {middle_name} {last_name}".strip()
        narration = notification_data.get('narration', '').strip()
        balance = notification_data.get('balance', '').strip()
        transaction_date = notification_data.get('transactionDate', '').strip()
        
        # Till number from primaryData.businessKey
        till_number = primary_data.get('businessKey', '').strip()
        
        # Validate required fields
        if not transaction_reference:
            logger.error("SWIFT SMS Till: Missing transactionID")
            return JsonResponse({
                'header': {
                    'messageID': message_id,
                    'originatorConversationID': originator_conversation_id,
                    'statusCode': '1',
                    'statusMessage': 'transactionID is required',
                },
                'responsePayload': {
                    'transactionInfo': {
                        'transactionId': ''
                    }
                }
            }, status=400)
        
        # Check for duplicate
        if SMSPurchaseTransaction.objects.filter(bank_reference=transaction_reference).exists():
            existing = SMSPurchaseTransaction.objects.get(bank_reference=transaction_reference)
            logger.info(f"SWIFT SMS Till: Duplicate ignored - {transaction_reference}")
            return JsonResponse({
                'header': {
                    'messageID': message_id,
                    'originatorConversationID': originator_conversation_id,
                    'statusCode': '0',
                    'statusMessage': 'Already processed',
                },
                'responsePayload': {
                    'transactionInfo': {
                        'transactionId': str(existing.id)
                    }
                }
            })
        
        if not org_sms_account:
            logger.error(f"SWIFT SMS Till: Could not extract org SMS account from: {business_key_raw}")
            return JsonResponse({
                'header': {
                    'messageID': message_id,
                    'originatorConversationID': originator_conversation_id,
                    'statusCode': '1',
                    'statusMessage': 'Invalid account format',
                },
                'responsePayload': {
                    'transactionInfo': {
                        'transactionId': ''
                    }
                }
            }, status=400)
        
        logger.info(f"SWIFT SMS Till: Extracted org SMS account: {org_sms_account}")
        
        # Find organization
        Organization = get_organization_model()
        try:
            organization = Organization.objects.get(sms_account_number=org_sms_account, is_active=True)
            logger.info(f"SWIFT SMS Till: Found organization - {organization.name}")
        except Organization.DoesNotExist:
            logger.error(f"SWIFT SMS Till: Organization not found for SMS account: {org_sms_account}")
            return JsonResponse({
                'header': {
                    'messageID': message_id,
                    'originatorConversationID': originator_conversation_id,
                    'statusCode': '1',
                    'statusMessage': f'Organization not found',
                },
                'responsePayload': {
                    'transactionInfo': {
                        'transactionId': ''
                    }
                }
            }, status=400)
        
        # Parse amount
        try:
            amount = Decimal(str(transaction_amount))
            if amount <= 0:
                raise ValueError()
        except Exception:
            return JsonResponse({
                'header': {
                    'messageID': message_id,
                    'originatorConversationID': originator_conversation_id,
                    'statusCode': '1',
                    'statusMessage': 'Invalid transaction amount',
                },
                'responsePayload': {
                    'transactionInfo': {
                        'transactionId': ''
                    }
                }
            }, status=400)
        
        # Calculate SMS credits
        sms_price = organization.sms_price_per_unit or config['sms_price']
        sms_credits = int(amount / sms_price)
        
        if sms_credits <= 0:
            logger.error(f"SWIFT SMS Till: Amount too low - KES {amount}")
            return JsonResponse({
                'header': {
                    'messageID': message_id,
                    'originatorConversationID': originator_conversation_id,
                    'statusCode': '1',
                    'statusMessage': f'Amount too low',
                },
                'responsePayload': {
                    'transactionInfo': {
                        'transactionId': ''
                    }
                }
            }, status=400)
        
        # Create transaction and credit organization
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(id=organization.id)
            
            purchase = SMSPurchaseTransaction.objects.create(
                organization=organization,
                amount=amount,
                sms_credits=sms_credits,
                price_per_sms=sms_price,
                status='completed',
                bank_reference=transaction_reference,
                kcb_channel_code=channel_code,
                kcb_timestamp=timestamp or transaction_date,
                kcb_till_number=till_number,
                kcb_customer_mobile=customer_mobile,
                kcb_customer_name=customer_name,
                kcb_narration=narration,
                kcb_balance=balance,
                raw_request_data=data,
                completed_at=timezone.now(),
            )
            
            old_balance = organization.sms_balance
            organization.sms_balance += sms_credits
            organization.save(update_fields=['sms_balance', 'updated_at'])
            
            logger.info(
                f"SWIFT SMS Till: Payment processed - "
                f"Org={organization.name}, Amount=KES {amount}, Credits={sms_credits}, "
                f"Balance: {old_balance} -> {organization.sms_balance}, "
                f"Ref={transaction_reference}"
            )
        
        return JsonResponse({
            'header': {
                'messageID': message_id,
                'originatorConversationID': originator_conversation_id,
                'statusCode': '0',
                'statusMessage': 'Notification received',
            },
            'responsePayload': {
                'transactionInfo': {
                    'transactionId': str(purchase.id)
                }
            }
        })
        
    except Exception as e:
        logger.error(f"SWIFT SMS Till: Error - {str(e)}", exc_info=True)
        return JsonResponse({
            'header': {
                'messageID': message_id,
                'originatorConversationID': originator_conversation_id,
                'statusCode': '1',
                'statusMessage': str(e),
            },
            'responsePayload': {
                'transactionInfo': {
                    'transactionId': ''
                }
            }
        }, status=500)

