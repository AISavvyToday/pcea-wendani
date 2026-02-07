# communications/services/sms_service.py
"""
SMS Service wrapper that uses the central SMS service API.

This module provides a backward-compatible interface that calls the central
SMS service at sms.swiftresidetech.co.ke via HTTP API.
"""

from .sms_api_client import sms_api_client

# Re-export for backward compatibility
SMSService = type('SMSService', (), {
    'send_sms': lambda self, phone_number, message, organization, purpose='', related_student=None, triggered_by=None: 
        sms_api_client.send_sms(phone_number, message, organization, purpose, related_student, triggered_by),
    
    'send_bulk_sms': lambda self, recipients, message, organization, purpose='', triggered_by=None:
        sms_api_client.send_bulk_sms(recipients, message, organization, purpose, triggered_by),
})()

# For direct usage
__all__ = ['SMSService', 'sms_api_client']

