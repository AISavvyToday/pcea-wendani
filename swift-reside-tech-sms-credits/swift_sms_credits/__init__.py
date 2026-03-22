"""
Swift Reside Tech SMS Credits Package

A Django package for managing SMS credits with multi-tenancy support,
KCB payment integration, and ImaraBiz SMS service.
"""

__version__ = '1.0.0'
__author__ = 'Swift Reside Tech'

__all__ = ['sms_service', 'SMSService', 'get_shortcode_for_organization']


def __getattr__(name):
    """
    Lazily import SMS service helpers so app discovery does not instantiate the
    underlying ImaraBiz client during startup/system checks.
    """
    if name in __all__:
        from .sms_service import sms_service, SMSService, get_shortcode_for_organization
        exports = {
            'sms_service': sms_service,
            'SMSService': SMSService,
            'get_shortcode_for_organization': get_shortcode_for_organization,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
