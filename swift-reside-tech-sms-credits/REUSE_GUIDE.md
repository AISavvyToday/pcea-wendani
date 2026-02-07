# SMS Package Reuse Guide - Central Service Integration

**Quick guide for integrating the central SMS service API into your Django webapps.**

---

## Architecture Overview

The SMS service is now **centralized** at `sms.swiftresidetech.co.ke`. Your webapps call the central service API instead of handling SMS directly.

```
Your Webapp → API Call → Central SMS Service (sms.swiftresidetech.co.ke) → ImaraBiz SMS Gateway
```

**Benefits:**
- Single KCB integration (one set of endpoints submitted to bank)
- Centralized SMS credit management
- Easy to add new webapps (just copy API client)
- All organizations managed in one place

---

## Quick Integration Steps

### 1. Copy API Client

Copy `notifications/sms_api_client.py` from the Kalimoni Primary School project into your webapp.

**File**: `notifications/sms_api_client.py` (or create new app)

### 2. Update Your SMS Service

Update your `notifications/sms.py` to use the API client. See example in Kalimoni project:

```python
from .sms_api_client import sms_api_client

class SMSService:
    def send_sms(self, phone_number, message, organization=None, ...):
        if not organization or not organization.sms_account_number:
            return None
        
        result = sms_api_client.send_sms(
            sms_account_number=organization.sms_account_number,
            phone_number=phone_number,
            message=message,
            purpose='manual'
        )
        return result
```

### 3. Set Heroku Config Vars

```bash
# Central SMS Service API
heroku config:set SMS_SERVICE_API_URL=https://sms.swiftresidetech.co.ke/api/v1
heroku config:set SMS_SERVICE_API_TOKEN=<token-from-central-service-admin>
```

**Get API Token**: Contact admin of central SMS service to get your API token.

### 4. Ensure Organization Model Has SMS Account Number

Your `Organization` model must have:
- `sms_account_number` field (CharField, unique)
- This should match the SMS account number created in the central service admin

**Example:**
```python
class Organization(models.Model):
    name = models.CharField(max_length=255)
    sms_account_number = models.CharField(max_length=50, unique=True)  # e.g., "SMS001"
    # ... other fields
```

### 5. Create Organization in Central Service

1. Go to `https://sms.swiftresidetech.co.ke/admin/`
2. Navigate to **Swift SMS Credits > Organizations**
3. Create organization with matching `sms_account_number`
4. Set `imarabiz_shortcode` if organization has custom shortcode

---

## API Usage Examples

### Get Balance

```python
from notifications.sms_api_client import sms_api_client

balance_data = sms_api_client.get_balance('SMS001')
print(f"Balance: {balance_data['balance']}")
```

### Send SMS

```python
result = sms_api_client.send_sms(
    sms_account_number='SMS001',
    phone_number='254712345678',
    message='Hello!',
    purpose='notification'
)
```

### Send Bulk SMS

```python
recipients = [
    {'phone_number': '254712345678', 'message': 'Hello 1'},
    {'phone_number': '254798765432', 'message': 'Hello 2'},
]

results = sms_api_client.send_bulk_sms(
    sms_account_number='SMS001',
    recipients=recipients,
    purpose='bulk_notification'
)
```

### Deduct Credits (if needed)

```python
result = sms_api_client.deduct_credits(
    sms_account_number='SMS001',
    sms_count=5,
    purpose='manual_deduction'
)
```

---

## Heroku Configuration Variables

### Required for Each Webapp

```bash
# Central SMS Service API
SMS_SERVICE_API_URL=https://sms.swiftresidetech.co.ke/api/v1
SMS_SERVICE_API_TOKEN=<your-api-token>
```

### Optional (if your app needs these)

```bash
# ImaraBiz (only needed if you're not using central service)
IMARABIZ_API_KEY=<not-needed-if-using-central-service>
IMARABIZ_PARTNER_ID=<not-needed-if-using-central-service>

# KCB (not needed - handled by central service)
SWIFT_RESIDE_PAYBILL=<not-needed>
SWIFT_RESIDE_TILL=<not-needed>
```

---

## Multi-Tenancy Setup

### For Multi-Tenant Apps

1. **Each organization** needs a unique `sms_account_number`
2. **Create organization** in central service admin with matching `sms_account_number`
3. **Set shortcode** per organization in central service admin (or use default)

### For Single-Tenant Apps

1. Create **one organization** in central service admin
2. Set `sms_account_number` in your app's Organization model to match
3. Use that account number for all SMS operations

---

## SMS Purchase Flow

1. **Admin** goes to SMS Settings page in your webapp
2. **Sees payment instructions**: Paybill `522533`, Account `SWIFTTECH#SMS001`
3. **Pays via M-Pesa** using those details
4. **KCB sends notification** to central service (`sms.swiftresidetech.co.ke`)
5. **Central service** credits the organization's balance
6. **Balance updates** immediately (visible via API)

**Note**: Your webapp doesn't handle KCB callbacks - the central service does.

---

## Troubleshooting

### "Organization not found" Error

- Ensure `sms_account_number` in your app matches the one in central service
- Check organization is active in central service admin

### "Authentication failed" Error

- Verify `SMS_SERVICE_API_TOKEN` is set correctly in Heroku config
- Contact central service admin to verify your token

### "Insufficient credits" Error

- Check balance via API: `sms_api_client.get_balance('SMS001')`
- Purchase more credits via M-Pesa (see SMS Purchase Flow above)

---

## What Changes vs. What Stays the Same

### ✅ Changes (New Architecture)

- **SMS sending**: Now calls central API instead of local package
- **Balance checks**: Query central API instead of local database
- **KCB callbacks**: Handled by central service (not your webapp)
- **SMS purchase**: Payments go to central service endpoints

### ✅ Stays the Same

- **Organization model**: Still has `sms_account_number` field
- **SMS service interface**: Same methods (`send_sms`, `send_bulk_sms`, etc.)
- **User experience**: SMS Settings page still works (calls API)
- **Multi-tenancy**: Still filters by organization

---

## Example: School Management System

```python
# notifications/sms.py
from .sms_api_client import sms_api_client

class SMSService:
    def send_sms(self, phone_number, message, organization=None, ...):
        if not organization or not organization.sms_account_number:
            return None
        
        try:
            result = sms_api_client.send_sms(
                sms_account_number=organization.sms_account_number,
                phone_number=phone_number,
                message=message,
                purpose='school_notification'
            )
            return result
        except Exception as e:
            logger.error(f"SMS send failed: {str(e)}")
            return None
```

**Heroku Config:**
```bash
SMS_SERVICE_API_URL=https://sms.swiftresidetech.co.ke/api/v1
SMS_SERVICE_API_TOKEN=your-token-here
```

**Organization Setup:**
- Create organization in central service admin: `sms_account_number = "SCHOOL001"`
- Set in your app's Organization model: `sms_account_number = "SCHOOL001"`
- Done! SMS will work.

---

## Support

For issues:
1. Check central service status: `https://sms.swiftresidetech.co.ke/admin/`
2. Verify API token is correct
3. Check organization exists in central service
4. Contact Swift Reside Tech support
