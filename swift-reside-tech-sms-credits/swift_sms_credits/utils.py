"""
Utility functions for swift_sms_credits package
"""
from django.conf import settings
from django.apps import apps


def get_organization_model():
    """
    Get the Organization model class from settings.
    Defaults to 'swift_sms_credits.Organization' if not specified.
    """
    model_path = getattr(settings, 'SMS_CREDITS_ORGANIZATION_MODEL', 'swift_sms_credits.Organization')
    app_label, model_name = model_path.split('.')
    return apps.get_model(app_label, model_name)


def get_user_model():
    """Get the User model class"""
    from django.contrib.auth import get_user_model
    return get_user_model()

