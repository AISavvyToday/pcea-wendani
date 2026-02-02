# SMS Package Reuse Guide

**Quick guide for integrating `swift-reside-tech-sms-credits` into your multi-tenant Django apps.**

---

## How It Works

### SMS Logic Flow
```
Your Code → sms_service.send_sms() → Package SMSService → ImaraBiz API
                                                              ↓
                                                      Deduct org.sms_balance
                                                      Log to SMSNotification
```

### KCB Integration Flow
```
KCB Payment → Callback → Extract ORG_SMS_ACCOUNT → Find Organization
→ Calculate credits (amount / price_per_sms) → Credit org.sms_balance
→ Create SMSPurchaseTransaction
```

**Account Format**: `SWIFT_TILL#ORG_SMS_ACCOUNT` (e.g., `SWIFTTECH#SMS001`)

---

## Installation & Setup

### 1. Install Package

```bash
pip install -e /path/to/swift-reside-tech-sms-credits
```

### 2. Add to INSTALLED_APPS

```python
# settings.py
INSTALLED_APPS = [
    # ... your apps
    'swift_sms_credits',
]
```

### 3. Configure Settings

```python
# settings.py

# Point to your Organization model
SMS_CREDITS_ORGANIZATION_MODEL = 'your_app.Organization'  # or 'tenants.Organization', 'schools.School', etc.

# ImaraBiz SMS API (Company-level - shared across all apps)
IMARABIZ_API_KEY = '069e58a8b3aaae79ac05dc94bc810c18'
IMARABIZ_PARTNER_ID = '205'
IMARABIZ_API_URL = 'https://sms.imarabiz.com/api/services/'
SWIFT_DEFAULT_SHORTCODE = 'SWIFT_RE_TECH'  # Company default shortcode

# KCB Integration for SMS Purchases (Company-level - shared across all apps)
SWIFT_RESIDE_PAYBILL = '522533'
SWIFT_RESIDE_TILL = 'SWIFTTECH'
SWIFT_SMS_PRICE = 1.0  # KSH per SMS credit
SWIFT_KCB_PUBLIC_KEY_BASE64 = '<your_key>'
SWIFT_KCB_SIGNATURE_KEY = '<your_key>'
SWIFT_KCB_SKIP_SIGNATURE_VERIFICATION = False

# SMS Batching (prevents Heroku timeouts)
SMS_ASYNC_ENABLED = True
SMS_BATCH_SIZE = 50
SMS_BATCH_DELAY = 1.0
```

### 4. Add SMS Fields to Organization Model

Your Organization model must have these fields:

```python
class Organization(models.Model):
    # ... existing fields
    
    sms_balance = models.IntegerField(default=0, help_text="SMS credits available")
    sms_account_number = models.CharField(
        max_length=50, 
        unique=True, 
        help_text="Unique account for SMS purchases (e.g., 'SMS001')"
    )
    sms_price_per_unit = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=1.00, 
        help_text="Price per SMS credit in KSH"
    )
    imarabiz_shortcode = models.CharField(
        max_length=50,
        blank=True,
        help_text="ImaraBiz shortcode for this organization (e.g., 'KALIMONI_FP'). Leave empty to use company default."
    )
```

**Create migration:**
```bash
python manage.py makemigrations
python manage.py migrate
```

### 5. Create SMS Service Wrapper

```python
# your_app/sms.py
from swift_sms_credits.sms_service import SMSService as PackageSMSService
from your_app.models import YourSMSNotificationModel  # Optional: your custom model

class SMSService:
    """Wrapper around package SMS service"""
    
    def __init__(self):
        self._service = PackageSMSService()
    
    def send_sms(self, phone_number, message, organization=None, user=None, 
                 purpose='manual', check_credits=True):
        """Send single SMS"""
        return self._service.send_sms(
            phone_number=phone_number,
            message=message,
            organization=organization,
            user=user,
            purpose=purpose,
            check_credits=check_credits,
            sms_notification_model=YourSMSNotificationModel  # Optional
        )
    
    def send_bulk_sms(self, recipients, organization=None, user=None, 
                      purpose='bulk', fail_silently=True, check_credits=True):
        """Send bulk SMS with batching"""
        return self._service.send_bulk_sms(
            recipients=recipients,
            organization=organization,
            user=user,
            purpose=purpose,
            fail_silently=fail_silently,
            check_credits=check_credits,
            sms_notification_model=YourSMSNotificationModel  # Optional
        )
    
    def send_bulk_sms_async(self, recipients, organization=None, user=None, 
                            purpose='bulk', check_credits=True):
        """Send bulk SMS asynchronously (for Heroku)"""
        return self._service.send_bulk_sms_async(
            recipients=recipients,
            organization=organization,
            user=user,
            purpose=purpose,
            check_credits=check_credits,
            sms_notification_model=YourSMSNotificationModel  # Optional
        )

# Create singleton
sms_service = SMSService()
```

### 6. Add KCB Callback URLs

```python
# your_app/urls.py or main urls.py
from swift_sms_credits.kcb_callbacks import (
    sms_credits_kcb_notification,
    sms_credits_kcb_till_notification
)

urlpatterns = [
    # ... your URLs
    path('api/sms-credits/kcb-notification/', sms_credits_kcb_notification),
    path('api/sms-credits/kcb-till-notification/', sms_credits_kcb_till_notification),
]
```

### 7. Run Migrations

```bash
python manage.py migrate swift_sms_credits
```

---

## Usage Examples

### Send Single SMS

```python
from your_app.sms import sms_service

# Send SMS with organization (deducts credits automatically)
result = sms_service.send_sms(
    phone_number='254712345678',
    message='Hello from your app!',
    organization=request.user.organization,
    user=request.user,
    purpose='notification'
)
```

### Send Bulk SMS

```python
recipients = [
    {'phone_number': '254712345678', 'message': 'Message 1'},
    {'phone_number': '254798765432', 'message': 'Message 2'},
]

# Synchronous (batched)
results = sms_service.send_bulk_sms(
    recipients=recipients,
    organization=organization,
    user=request.user,
    purpose='bulk_campaign'
)

# Asynchronous (for large batches on Heroku)
results = sms_service.send_bulk_sms_async(
    recipients=recipients,
    organization=organization,
    user=request.user,
    purpose='bulk_campaign'
)
```

---

## Heroku Config Vars

### Shared (Same for All Apps)

```bash
# ImaraBiz (Company account)
IMARABIZ_API_KEY=069e58a8b3aaae79ac05dc94bc810c18
IMARABIZ_PARTNER_ID=205
SWIFT_DEFAULT_SHORTCODE=SWIFT_RE_TECH

# KCB SMS Purchase Integration (Company paybill)
SWIFT_RESIDE_PAYBILL=522533
SWIFT_RESIDE_TILL=SWIFTTECH
SWIFT_SMS_PRICE=1.0
SWIFT_KCB_PUBLIC_KEY_BASE64=<your_key>
SWIFT_KCB_SIGNATURE_KEY=<your_key>
SWIFT_KCB_SKIP_SIGNATURE_VERIFICATION=False

# SMS Settings
SMS_ASYNC_ENABLED=True
SMS_BATCH_SIZE=50
SMS_BATCH_DELAY=1.0
```

### Per-App (Different per Client)

```bash
# App-specific
DATABASE_URL=<unique_per_app>
DJANGO_ENVIRONMENT=production
SITE_URL=<unique_per_app>
SMS_CREDITS_ORGANIZATION_MODEL=your_app.Organization
```

---

## What Changes vs What Stays Same

### ✅ Stays Same (Package Code)
- `swift_sms_credits` package code (no changes)
- ImaraBiz API integration
- SMS sending logic
- Credit deduction logic
- KCB callback handlers

### 🔄 Changes Per App
- Organization model name (`Organization`, `School`, `CarWash`, `Property`, etc.)
- SMS notification model (if you want custom logging)
- KCB callback URLs (different app = different domain)
- Heroku config vars (per client)

---

## Shortcode Selection Logic

The package automatically selects shortcode in this order:

1. **Organization shortcode**: `organization.imarabiz_shortcode` (if set)
2. **Company default**: `SWIFT_DEFAULT_SHORTCODE` setting
3. **Legacy fallback**: `IMARABIZ_SHORTCODE` setting

**Example:**
- Kalimoni School: `imarabiz_shortcode = 'KALIMONI_FP'` → Uses `KALIMONI_FP`
- Other orgs: `imarabiz_shortcode = ''` → Uses `SWIFT_RE_TECH`

---

## Key Points

1. **One Package, Multiple Apps**: Same package code works across all your apps
2. **Shared KCB Integration**: All apps use same paybill (`522533`) but different account numbers
3. **Per-Org Shortcodes**: Each organization can have its own ImaraBiz shortcode
4. **Automatic Credit Management**: Package handles deduction, refunds, and logging
5. **Heroku-Safe**: Async batching prevents timeouts on large sends

---

## Troubleshooting

### Organization Not Found
- Ensure `SMS_CREDITS_ORGANIZATION_MODEL` points to correct model
- Verify organization has `sms_account_number` set

### SMS Not Sending
- Check `organization.sms_balance > 0`
- Verify ImaraBiz API credentials
- Check logs for API errors

### KCB Callback Not Working
- Verify callback URLs are accessible
- Check signature verification settings
- Ensure account format: `SWIFT_TILL#ORG_SMS_ACCOUNT`

---

## Support

For issues or questions, refer to:
- `README.md` - Full package documentation
- `USAGE_GUIDE.md` - Detailed usage examples
- Package source code in `swift_sms_credits/`

