"""
REST API views for SMS Credits Service
"""
import json
import logging
from django.views import View
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.db import transaction
from django.utils import timezone
from decimal import Decimal

from .models import SMSPurchaseTransaction, SMSUsageLog
from .utils import get_organization_model
from .sms_service import SMSService
from .auth import api_token_required

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(api_token_required, name='dispatch')
class BalanceAPIView(View):
    """Get SMS balance for an organization"""
    
    def get(self, request):
        sms_account_number = request.GET.get('sms_account_number', '').strip()
        
        if not sms_account_number:
            return JsonResponse({
                'success': False,
                'error': 'sms_account_number parameter is required'
            }, status=400)
        
        Organization = get_organization_model()
        try:
            organization = Organization.objects.get(sms_account_number=sms_account_number, is_active=True)
            return JsonResponse({
                'success': True,
                'sms_account_number': organization.sms_account_number,
                'organization_name': organization.name,
                'balance': organization.sms_balance,
                'price_per_sms': float(organization.sms_price_per_unit),
            })
        except Organization.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': f'Organization not found for SMS account: {sms_account_number}'
            }, status=404)


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(api_token_required, name='dispatch')
class DeductCreditsAPIView(View):
    """Deduct SMS credits from an organization"""
    
    def post(self, request):
        try:
            data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON'
            }, status=400)
        
        sms_account_number = data.get('sms_account_number', '').strip()
        sms_count = data.get('sms_count', 0)
        
        if not sms_account_number:
            return JsonResponse({
                'success': False,
                'error': 'sms_account_number is required'
            }, status=400)
        
        try:
            sms_count = int(sms_count)
            if sms_count <= 0:
                raise ValueError("sms_count must be positive")
        except (ValueError, TypeError):
            return JsonResponse({
                'success': False,
                'error': 'sms_count must be a positive integer'
            }, status=400)
        
        Organization = get_organization_model()
        try:
            organization = Organization.objects.get(sms_account_number=sms_account_number, is_active=True)
        except Organization.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': f'Organization not found for SMS account: {sms_account_number}'
            }, status=404)
        
        with transaction.atomic():
            # Lock organization for update
            org = Organization.objects.select_for_update().get(id=organization.id)
            
            if org.sms_balance < sms_count:
                return JsonResponse({
                    'success': False,
                    'error': f'Insufficient SMS credits. Need {sms_count}, have {org.sms_balance}',
                    'balance': org.sms_balance,
                    'required': sms_count
                }, status=400)
            
            balance_before = org.sms_balance
            org.sms_balance -= sms_count
            org.save(update_fields=['sms_balance', 'updated_at'])
            
            # Log usage
            SMSUsageLog.objects.create(
                organization=org,
                sms_count=sms_count,
                purpose=data.get('purpose', 'api_deduction'),
                balance_before=balance_before,
                balance_after=org.sms_balance,
            )
            
            logger.info(
                f"API: Credits deducted - org={org.name}, "
                f"count={sms_count}, balance: {balance_before} -> {org.sms_balance}"
            )
            
            return JsonResponse({
                'success': True,
                'sms_account_number': org.sms_account_number,
                'balance_before': balance_before,
                'balance_after': org.sms_balance,
                'deducted': sms_count,
            })


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(api_token_required, name='dispatch')
class SendSMSAPIView(View):
    """Send SMS via central service"""
    
    def post(self, request):
        try:
            data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON'
            }, status=400)
        
        sms_account_number = data.get('sms_account_number', '').strip()
        phone_number = data.get('phone_number', '').strip()
        message = data.get('message', '').strip()
        purpose = data.get('purpose', 'api_send')
        
        if not sms_account_number:
            return JsonResponse({
                'success': False,
                'error': 'sms_account_number is required'
            }, status=400)
        
        if not phone_number or not message:
            return JsonResponse({
                'success': False,
                'error': 'phone_number and message are required'
            }, status=400)
        
        Organization = get_organization_model()
        try:
            organization = Organization.objects.get(sms_account_number=sms_account_number, is_active=True)
        except Organization.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': f'Organization not found for SMS account: {sms_account_number}'
            }, status=404)
        
        # Use SMS service to send
        sms_service = SMSService()
        result = sms_service.send_sms(
            phone_number=phone_number,
            message=message,
            organization=organization,
            purpose=purpose,
            check_credits=True,
            sms_notification_model=None  # No notification model for API calls
        )
        
        if result:
            return JsonResponse({
                'success': True,
                'message_id': getattr(result, 'message_id', ''),
                'status': getattr(result, 'status', 'sent'),
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Failed to send SMS'
            }, status=500)


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(api_token_required, name='dispatch')
class SendBulkSMSAPIView(View):
    """Send bulk SMS via central service"""
    
    def post(self, request):
        try:
            data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON'
            }, status=400)
        
        sms_account_number = data.get('sms_account_number', '').strip()
        recipients = data.get('recipients', [])
        purpose = data.get('purpose', 'api_bulk')
        
        if not sms_account_number:
            return JsonResponse({
                'success': False,
                'error': 'sms_account_number is required'
            }, status=400)
        
        if not recipients or not isinstance(recipients, list):
            return JsonResponse({
                'success': False,
                'error': 'recipients must be a non-empty list'
            }, status=400)
        
        Organization = get_organization_model()
        try:
            organization = Organization.objects.get(sms_account_number=sms_account_number, is_active=True)
        except Organization.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': f'Organization not found for SMS account: {sms_account_number}'
            }, status=404)
        
        # Validate recipients format
        validated_recipients = []
        for recipient in recipients:
            if isinstance(recipient, dict):
                phone = recipient.get('phone_number', '').strip()
                msg = recipient.get('message', '').strip()
            elif isinstance(recipient, str):
                # Simple format: just phone number, use same message for all
                phone = recipient.strip()
                msg = data.get('message', '').strip()
            else:
                continue
            
            if phone and msg:
                validated_recipients.append({
                    'phone_number': phone,
                    'message': msg,
                })
        
        if not validated_recipients:
            return JsonResponse({
                'success': False,
                'error': 'No valid recipients found'
            }, status=400)
        
        # Use SMS service to send bulk
        sms_service = SMSService()
        results = sms_service.send_bulk_sms(
            recipients=validated_recipients,
            organization=organization,
            purpose=purpose,
            check_credits=True,
            fail_silently=False,
            sms_notification_model=None  # No notification model for API calls
        )
        
        return JsonResponse({
            'success': True,
            'sent_count': len(results),
            'results': [
                {
                    'phone_number': getattr(r, 'phone_number', ''),
                    'status': getattr(r, 'status', 'unknown'),
                    'message_id': getattr(r, 'message_id', ''),
                }
                for r in results
            ]
        })


@method_decorator(api_token_required, name='dispatch')
class UsageHistoryAPIView(View):
    """Get SMS usage history for an organization"""
    
    def get(self, request):
        sms_account_number = request.GET.get('sms_account_number', '').strip()
        limit = int(request.GET.get('limit', 50))
        
        if not sms_account_number:
            return JsonResponse({
                'success': False,
                'error': 'sms_account_number parameter is required'
            }, status=400)
        
        Organization = get_organization_model()
        try:
            organization = Organization.objects.get(sms_account_number=sms_account_number, is_active=True)
        except Organization.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': f'Organization not found for SMS account: {sms_account_number}'
            }, status=404)
        
        usage_logs = SMSUsageLog.objects.filter(
            organization=organization
        ).order_by('-created_at')[:limit]
        
        return JsonResponse({
            'success': True,
            'sms_account_number': organization.sms_account_number,
            'usage_logs': [
                {
                    'id': str(log.id),
                    'sms_count': log.sms_count,
                    'purpose': log.purpose,
                    'balance_before': log.balance_before,
                    'balance_after': log.balance_after,
                    'created_at': log.created_at.isoformat(),
                }
                for log in usage_logs
            ]
        })


@method_decorator(api_token_required, name='dispatch')
class PurchaseHistoryAPIView(View):
    """Get SMS purchase history for an organization"""
    
    def get(self, request):
        sms_account_number = request.GET.get('sms_account_number', '').strip()
        limit = int(request.GET.get('limit', 50))
        
        if not sms_account_number:
            return JsonResponse({
                'success': False,
                'error': 'sms_account_number parameter is required'
            }, status=400)
        
        Organization = get_organization_model()
        try:
            organization = Organization.objects.get(sms_account_number=sms_account_number, is_active=True)
        except Organization.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': f'Organization not found for SMS account: {sms_account_number}'
            }, status=404)
        
        purchases = SMSPurchaseTransaction.objects.filter(
            organization=organization
        ).order_by('-created_at')[:limit]
        
        return JsonResponse({
            'success': True,
            'sms_account_number': organization.sms_account_number,
            'purchases': [
                {
                    'id': str(purchase.id),
                    'amount': float(purchase.amount),
                    'sms_credits': purchase.sms_credits,
                    'price_per_sms': float(purchase.price_per_sms),
                    'status': purchase.status,
                    'bank_reference': purchase.bank_reference,
                    'created_at': purchase.created_at.isoformat(),
                }
                for purchase in purchases
            ]
        })

