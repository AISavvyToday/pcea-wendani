"""
Base settings for Swift SMS Credits Service
"""
import os
from pathlib import Path
import dj_database_url

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-dev-key-change-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DEBUG', 'False') == 'True'

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1,sms.swiftresidetech.co.ke').split(',')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # SMS Credits app
    'swift_sms_credits',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # For Heroku static files
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database
# Use DATABASE_URL from Heroku if available, otherwise SQLite for local dev
DATABASES = {
    'default': dj_database_url.config(
        default=f'sqlite:///{BASE_DIR / "db.sqlite3"}',
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# Default User Model (Django's built-in)
AUTH_USER_MODEL = 'auth.User'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Nairobi'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = []

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Security settings for production
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'

# SMS Configuration (ImaraBiz API)
IMARABIZ_API_KEY = os.environ.get('IMARABIZ_API_KEY', '')
IMARABIZ_PARTNER_ID = os.environ.get('IMARABIZ_PARTNER_ID', '')
IMARABIZ_API_URL = os.environ.get('IMARABIZ_API_URL', 'https://sms.imarabiz.com/api/services/')
SWIFT_DEFAULT_SHORTCODE = os.environ.get('SWIFT_DEFAULT_SHORTCODE', 'SWIFT_RE_TECH')

# Swift Reside Tech KCB Configuration (for SMS credit purchases)
SWIFT_RESIDE_PAYBILL = os.environ.get('SWIFT_RESIDE_PAYBILL', '522533')
SWIFT_RESIDE_TILL = os.environ.get('SWIFT_RESIDE_TILL', 'SWIFTTECH')
SWIFT_SMS_PRICE = float(os.environ.get('SWIFT_SMS_PRICE', '1.0'))  # KSH per SMS credit
SWIFT_KCB_PUBLIC_KEY_BASE64 = os.environ.get('SWIFT_KCB_PUBLIC_KEY_BASE64', '')
SWIFT_KCB_SIGNATURE_KEY = os.environ.get('SWIFT_KCB_SIGNATURE_KEY', '')
SWIFT_KCB_SIGNATURE_METHOD = os.environ.get('SWIFT_KCB_SIGNATURE_METHOD', 'auto')  # 'rsa', 'hmac', or 'auto'
SWIFT_KCB_SKIP_SIGNATURE_VERIFICATION = os.environ.get('SWIFT_KCB_SKIP_SIGNATURE_VERIFICATION', 'False') == 'True'

# SMS Sending Configuration
SMS_BATCH_SIZE = int(os.environ.get('SMS_BATCH_SIZE', '50'))
SMS_BATCH_DELAY = float(os.environ.get('SMS_BATCH_DELAY', '1.0'))
SMS_ASYNC_ENABLED = os.environ.get('SMS_ASYNC_ENABLED', 'True') == 'True'

# SMS Credits Organization Model (defaults to package's own Organization model)
SMS_CREDITS_ORGANIZATION_MODEL = os.environ.get('SMS_CREDITS_ORGANIZATION_MODEL', 'swift_sms_credits.Organization')

# API Authentication Token (for webapp authentication)
SMS_SERVICE_API_TOKEN = os.environ.get('SMS_SERVICE_API_TOKEN', '')

# Site URL
SITE_URL = os.environ.get('SITE_URL', 'https://sms.swiftresidetech.co.ke')

