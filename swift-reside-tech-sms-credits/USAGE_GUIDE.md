# Swift SMS Credits - Complete Usage Guide

## How SMS Functionality Works Now

### Overview

The SMS credits system is now **tenant-aware** with per-organization shortcodes. Here's how it works:

### 1. **Organization Setup**

Each organization has:
- `sms_balance`: Current SMS credits (integer)
- `sms_account_number`: Unique account for KCB payments (e.g., "SMS001")
- `sms_price_per_unit`: Price per SMS credit (default: 1.00 KSH)
- `imarabiz_shortcode`: ImaraBiz shortcode for this org (e.g., "KALIMONI_FP", "SWIFT_TECH")

### 2. **SMS Sending Flow**

```
User sends SMS
    ↓
System checks organization.sms_balance
    ↓
Deducts credits atomically
    ↓
Gets organization.imarabiz_shortcode
    ↓
Sends SMS via ImaraBiz API with org's shortcode
    ↓
If success: Log usage
If failure: Refund credits + log error
```

### 3. **SMS Purchase Flow**

```
Admin goes to SMS Settings
    ↓
Sees: Paybill 522533, Account SWIFTTECH#SMS001
    ↓
Pays via M-Pesa
    ↓
KCB sends notification to /sms-credits/api/sms-credits/kcb-notification/
    ↓
System extracts "SMS001" from account
    ↓
Finds organization by sms_account_number
    ↓
Calculates credits: amount / sms_price_per_unit
    ↓
Credits organization.sms_balance
    ↓
Creates SMSPurchaseTransaction record
```

### 4. **Per-Tenant Shortcodes**

- **Company default**: `SWIFT_TECH` (used if org doesn't have shortcode)
- **Per org**: Set `imarabiz_shortcode` field on Organization
- **Example**: Kalimoni School uses `KALIMONI_FP`
- **SMS service** automatically uses org's shortcode when sending

## How to Reuse in Other Web Apps

### Option 1: Install as Package (Recommended)

#### Step 1: Install Package

```bash
cd /path/to/swift-reside-tech-sms-credits
pip install -e .
```

Or if published to PyPI:
```bash
pip install swift-reside-tech-sms-credits
```

#### Step 2: Add to Your App

```python
# settings.py
INSTALLED_APPS = [
    # ... your apps
    'swift_sms_credits',
]

# Point to your Organization model
SMS_CREDITS_ORGANIZATION_MODEL = 'your_app.Organization'

# Configure ImaraBiz (company-level)
IMARABIZ_API_KEY = '069e58a8b3aaae79ac05dc94bc810c18'
IMARABIZ_PARTNER_ID = '205'
IMARABIZ_API_URL = 'https://sms.imarabiz.com/api/services/'

# Configure Swift KCB integration
SWIFT_RESIDE_PAYBILL = '522533'
SWIFT_RESIDE_TILL = 'SWIFTTECH'
SWIFT_SMS_PRICE = 1.0
SWIFT_KCB_PUBLIC_KEY_BASE64 = 'your_base64_key'
SWIFT_KCB_SKIP_SIGNATURE_VERIFICATION = False
```

#### Step 3: Add SMS Fields to Organization

Create migration:

```python
# your_app/migrations/XXXX_add_sms_fields.py
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('your_app', 'previous'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='sms_account_number',
            field=models.CharField(max_length=50, unique=True, null=True),
        ),
        migrations.AddField(
            model_name='organization',
            name='sms_balance',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='organization',
            name='sms_price_per_unit',
            field=models.DecimalField(max_digits=10, decimal_places=2, default=1.00),
        ),
        migrations.AddField(
            model_name='organization',
            name='imarabiz_shortcode',
            field=models.CharField(max_length=50, default='SWIFT_TECH'),
        ),
    ]
```

#### Step 4: Update Your SMS Service

```python
# your_app/sms_service.py
from swift_sms_credits.utils import get_organization_model

class YourSMSService:
    def send_sms(self, phone, message, organization=None, ...):
        # Get shortcode from organization
        if organization:
            shortcode = getattr(organization, 'imarabiz_shortcode', None) or 'SWIFT_TECH'
        else:
            shortcode = 'SWIFT_TECH'
        
        # Check and deduct credits
        if organization:
            from swift_sms_credits.models import SMSUsageLog
            from django.db import transaction
            
            with transaction.atomic():
                org = get_organization_model().objects.select_for_update().get(id=organization.id)
                if org.sms_balance < 1:
                    return {'error': 'Insufficient credits'}
                org.sms_balance -= 1
                org.save()
        
        # Send SMS with org's shortcode
        payload = {
            'shortcode': shortcode,
            # ... other fields
        }
        # ... send via ImaraBiz API
```

#### Step 5: Add URLs

```python
# urls.py
urlpatterns = [
    path('sms-credits/', include('swift_sms_credits.urls')),
]
```

#### Step 6: Run Migrations

```bash
python manage.py migrate swift_sms_credits
```

### Option 2: Copy Tenants App (Quick Start)

If you want to quickly reuse without package:

1. Copy `tenants/` folder to your new app
2. Rename to match your app structure
3. Update imports
4. Run migrations

## Package Structure Breakdown

```
swift-reside-tech-sms-credits/
├── swift_sms_credits/
│   ├── __init__.py
│   ├── apps.py
│   ├── models.py              # SMSPurchaseTransaction, SMSUsageLog
│   ├── utils.py               # get_organization_model()
│   ├── kcb_callbacks.py       # KCB payment endpoints
│   ├── views.py               # SMS settings UI (to be added)
│   ├── admin.py               # Django admin (to be added)
│   ├── urls.py                # URL patterns (to be added)
│   └── migrations/            # Package migrations
├── setup.py
├── README.md
└── USAGE_GUIDE.md
```

## Key Design Decisions

### 1. **Organization Model is External**

- Package doesn't define Organization
- Uses `SMS_CREDITS_ORGANIZATION_MODEL` setting to find it
- Your app provides Organization with SMS fields

### 2. **Per-Tenant Shortcodes**

- Each org has `imarabiz_shortcode` field
- SMS service reads from org when sending
- Default: `SWIFT_TECH` (company default)

### 3. **Separate KCB Keys**

- Swift integration uses `SWIFT_KCB_*` settings
- Separate from school payment integration
- Allows different keys per integration

### 4. **Backward Compatible**

- Existing SMS sending code still works
- Just needs to pass `organization` parameter
- Falls back to default shortcode if no org

## Testing Checklist

- [ ] Package installs correctly
- [ ] Migrations run successfully
- [ ] Organization model has SMS fields
- [ ] SMS Settings page loads
- [ ] KCB payment notification works
- [ ] SMS credits are deducted on send
- [ ] Per-org shortcodes work correctly
- [ ] Purchase history displays
- [ ] Usage logs are created

## Next Steps

1. Complete package files (views.py, admin.py, urls.py)
2. Test package installation
3. Create example integration
4. Publish to PyPI (optional)

