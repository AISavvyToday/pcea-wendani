# config/settings.py
"""
Django settings for config project.

Production-ready baseline for PWASMS (Purple theme integration).
"""

from pathlib import Path
import os
import sys
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# Add local swift_sms_credits package to Python path
SMS_CREDITS_PACKAGE_PATH = BASE_DIR / 'swift-reside-tech-sms-credits'
if str(SMS_CREDITS_PACKAGE_PATH) not in sys.path:
    sys.path.insert(0, str(SMS_CREDITS_PACKAGE_PATH))

# ------------------------------------------------------------------------------
# Core security settings
# ------------------------------------------------------------------------------
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-2e(5&exug+4@0s=m(kr4#k_7@mlc3(@jt-zoa_x#2)jy8i0ru0",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "").lower() == "true"

# ALLOWED_HOSTS = os.environ.get(
#     "DJANGO_ALLOWED_HOSTS",
#     "localhost,127.0.0.1",
# ).split(",")


ALLOWED_HOSTS = ['*']

CSRF_TRUSTED_ORIGINS = [
    host for host in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if host
]

# ------------------------------------------------------------------------------
# Application definition
# ------------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Project apps
    "core",
    "accounts",
    "students",
    "academics",
    "transport",
    "finance",
    "payments",
    "communications",
    "reports",
    "portal",
    "other_income",
    "payroll",
    
    # SMS Credits package (local package)
    "swift_sms_credits",

    "rest_framework",

    'django.contrib.humanize',
]
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
}
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.OrganizationMiddleware",  # Multi-tenancy: Set request.organization
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

# If app is deployed under a subpath (e.g. /c/), set FORCE_SCRIPT_NAME in env
# e.g. FORCE_SCRIPT_NAME=/c so URLs become /c/other-income/, /c/finance/, etc.
_force_script = os.environ.get("FORCE_SCRIPT_NAME", "").strip().rstrip("/")
if _force_script:
    FORCE_SCRIPT_NAME = _force_script

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                    # Custom context processors
                'core.context_processors.user_role_context',
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ------------------------------------------------------------------------------
# Database
# ------------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Override with DATABASE_URL if present (Heroku)
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    DATABASES['default'] = dj_database_url.config(
        default=DATABASE_URL,
        conn_max_age=600,
        conn_health_checks=True,
        ssl_require=True,
    )

# ------------------------------------------------------------------------------
# Password validation
# ------------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ------------------------------------------------------------------------------
# Internationalization
# ------------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

# ------------------------------------------------------------------------------
# Static & media
# ------------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ------------------------------------------------------------------------------
# Auth
# ------------------------------------------------------------------------------
# Custom User Model
AUTH_USER_MODEL = 'accounts.User'

# Authentication backends
AUTHENTICATION_BACKENDS = [
    'accounts.backends.EmailBackend',  # Custom email-based auth
    'django.contrib.auth.backends.ModelBackend',  # Fallback
]

# Login/Logout redirects
LOGIN_URL = 'portal:login'
LOGIN_REDIRECT_URL = 'portal:role_redirect'
LOGOUT_REDIRECT_URL = 'portal:login'

# Session settings
SESSION_COOKIE_AGE = 86400  # 24 hours
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
# ------------------------------------------------------------------------------
# Default auto field
# ------------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ------------------------------------------------------------------------------
# Optional logging for production visibility
# ------------------------------------------------------------------------------
if not DEBUG:
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
            },
        },
        "root": {
            "handlers": ["console"],
            "level": "INFO",
        },
    }



# Bank Integration Settings
# Equity Bank
EQUITY_IPN_USERNAME = os.environ.get('EQUITY_IPN_USERNAME', 'wendani_academy')
EQUITY_IPN_PASSWORD = os.environ.get('EQUITY_IPN_PASSWORD', 'pwasms@!#2026')

# Co-operative Bank
COOP_IPN_USERNAME = os.environ.get('COOP_IPN_USERNAME', 'wendani_academy')
COOP_IPN_PASSWORD = os.environ.get('COOP_IPN_PASSWORD', 'pwasms@!#2026')
SCHOOL_COOP_ACCOUNT_NO = os.environ.get('SCHOOL_COOP_ACCOUNT_NO', '01129158350600')

# Payment callback base URL (for logging purposes)
PAYMENT_CALLBACK_BASE_URL = os.environ.get('PAYMENT_CALLBACK_BASE_URL', '')

#=============================================================================
# EMAIL SETTINGS (Console backend for development)
# =============================================================================

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# For production, switch to real SMTP:
# EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
# EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
# EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
# EMAIL_USE_TLS = True
# EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
# EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')

DEFAULT_FROM_EMAIL = 'PWASMS <noreply@wendaniacademy.ac.ke>'

# Password reset token validity (in seconds) - 24 hours
PASSWORD_RESET_TIMEOUT = 86400


SCHOOL_LOGO_URL = '/static/assets/images/logo.jpeg'
SPONSOR_LOGO_URL = '/static/assets/images/logo2.jpeg'
SCHOOL_BANK_DETAILS = {
    'equity': {'name': 'EQUITY BANK', 'account_name': 'P.C.E.A Wendani Academy', 'account_no': '1130280029105'},
    'coop': {'name': 'CO-OPERATIVE BANK', 'account_name': 'P.C.E.A Wendani Academy', 'account_no': '01129158350600'},
    'paybill_1': {'label': 'M-PESA PAYBILL 247247', 'number': '247247', 'acc_format': '80029#<admission_number>'},
    'paybill_2': {'label': 'M-PESA PAYBILL 400222', 'number': '400222', 'acc_format': '393939#<admission_number>'},
}
SCHOOL_STATEMENT_FOOTNOTE = "This statement is computer-generated and is valid without signature. For any queries, contact the school bursar."
SCHOOL_NAME = "PCEA Wendani Academy"

# =============================================================================
# SMS CREDITS CONFIGURATION (Swift Reside Tech SMS Credits Package)
# =============================================================================

# Point to Organization model for SMS credits (required for KCB callbacks)
SMS_CREDITS_ORGANIZATION_MODEL = 'core.Organization'

# Central SMS Service API Configuration (REQUIRED)
# These settings connect to the central SMS service at sms.swiftresidetech.co.ke
SMS_SERVICE_API_URL = os.environ.get('SMS_SERVICE_API_URL', 'https://sms.swiftresidetech.co.ke/api/v1')
SMS_SERVICE_API_TOKEN = os.environ.get('SMS_SERVICE_API_TOKEN', '')

# Swift Reside Tech KCB Integration (for SMS credit purchases)
# These are used by KCB callback endpoints if KCB calls this webapp directly
# If KCB only calls the central service, these can have defaults for display purposes
SWIFT_RESIDE_PAYBILL = os.environ.get('SWIFT_RESIDE_PAYBILL', '522533')
SWIFT_RESIDE_TILL = os.environ.get('SWIFT_RESIDE_TILL', 'SWIFTTECH')
SWIFT_SMS_PRICE = float(os.environ.get('SWIFT_SMS_PRICE', '1.0'))  # KSH per SMS credit
SWIFT_DEFAULT_SHORTCODE = os.environ.get('SWIFT_DEFAULT_SHORTCODE', 'SWIFT_RE_TECH')
SWIFT_KCB_PUBLIC_KEY_BASE64 = os.environ.get('SWIFT_KCB_PUBLIC_KEY_BASE64', '')
SWIFT_KCB_SIGNATURE_KEY = os.environ.get('SWIFT_KCB_SIGNATURE_KEY', '')
SWIFT_KCB_SKIP_SIGNATURE_VERIFICATION = os.environ.get('SWIFT_KCB_SKIP_SIGNATURE_VERIFICATION', 'True') == 'True'