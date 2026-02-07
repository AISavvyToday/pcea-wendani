"""
Organization registry for routing SMS purchases to correct database/web app
"""
from django.conf import settings
from django.db import connections


class OrganizationRegistry:
    """
    Registry mapping sms_account_number to database connection/web app info
    
    Usage:
        # In settings.py (on swiftresidetech.co.ke)
        SMS_CREDITS_ORG_REGISTRY = {
            'SMS001': 'kalimoni_db',  # Kalimoni Primary School
            'SMS002': 'pceawendani_db',  # PCEA Wendani Academy
        }
    """
    
    @staticmethod
    def get_database_for_sms_account(sms_account_number):
        """
        Get database connection name for given sms_account_number
        
        Args:
            sms_account_number: Organization's SMS account number (e.g., 'SMS001')
            
        Returns:
            database alias (e.g., 'default', 'kalimoni_db', 'pceawendani_db')
            Defaults to 'default' if not found in registry
        """
        registry = getattr(settings, 'SMS_CREDITS_ORG_REGISTRY', {})
        database_alias = registry.get(sms_account_number, 'default')
        return database_alias
    
    @staticmethod
    def get_organization_model_for_db(database_alias):
        """
        Get Organization model for specific database
        
        Args:
            database_alias: Database alias to use
            
        Returns:
            Organization model class
        """
        from .utils import get_organization_model
        return get_organization_model()
    
    @staticmethod
    def is_database_configured(database_alias):
        """
        Check if database alias is configured in DATABASES
        
        Args:
            database_alias: Database alias to check
            
        Returns:
            bool: True if database is configured, False otherwise
        """
        return database_alias in connections.databases

