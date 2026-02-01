"""
Swift Reside Tech SMS Credits Package

A Django package for managing SMS credits with multi-tenancy support,
KCB payment integration, and ImaraBiz SMS service.
"""

__version__ = '1.0.0'
__author__ = 'Swift Reside Tech'

# Export SMS service for easy import
from .sms_service import sms_service, SMSService, get_shortcode_for_organization

__all__ = ['sms_service', 'SMSService', 'get_shortcode_for_organization']

