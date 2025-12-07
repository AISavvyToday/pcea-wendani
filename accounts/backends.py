# accounts/backends.py
"""
Custom authentication backend for email-based login.
Django's default ModelBackend uses username; we use email as USERNAME_FIELD.
"""

import logging
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

logger = logging.getLogger(__name__)
User = get_user_model()


class EmailBackend(ModelBackend):
    """
    Authenticate users by email address instead of username.
    Works with custom User model where USERNAME_FIELD = 'email'.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Authenticate user by email (passed as 'username' by Django's auth forms).

        Args:
            request: The HTTP request object
            username: Email address (Django passes email as 'username')
            password: User's password

        Returns:
            User instance if authentication succeeds, None otherwise
        """
        # Allow email to be passed as either 'username' or 'email' kwarg
        email = username or kwargs.get('email')

        if email is None or password is None:
            logger.debug("Authentication failed: missing email or password")
            return None

        try:
            # Case-insensitive email lookup
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            logger.info(f"Authentication failed: no user with email '{email}'")
            # Run the default password hasher to prevent timing attacks
            User().set_password(password)
            return None
        except User.MultipleObjectsReturned:
            logger.error(f"Multiple users found with email '{email}'")
            return None

        # Check password and user status
        if user.check_password(password) and self.user_can_authenticate(user):
            logger.info(f"User '{email}' authenticated successfully")
            return user

        # Record failed login attempt
        if hasattr(user, 'record_failed_login'):
            user.record_failed_login()
            logger.warning(f"Failed login attempt for '{email}' - attempt #{user.failed_login_attempts}")

        return None

    def get_user(self, user_id):
        """
        Retrieve user by primary key.
        """
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None