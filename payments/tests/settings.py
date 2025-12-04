# File: payments/tests/settings.py
# ============================================================
# RATIONALE: Test-specific Django settings
# ============================================================

from config.settings import *  # noqa

# Use in-memory SQLite for faster tests
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Disable migrations for faster tests
class DisableMigrations:
    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


MIGRATION_MODULES = DisableMigrations()

# Test credentials
EQUITY_API_KEY = 'test-equity-api-key-12345'
COOP_IPN_USERNAME = 'testuser'
COOP_IPN_PASSWORD = 'testpass'
SCHOOL_COOP_ACCOUNT_NO = '01234567890100'

# Disable actual SMS/Email sending
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Faster password hashing for tests
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Disable logging during tests
LOGGING = {
    'version': 1,
    'disable_existing_loggers': True,
    'handlers': {
        'null': {
            'class': 'logging.NullHandler',
        },
    },
    'root': {
        'handlers': ['null'],
        'level': 'DEBUG',
    },
}