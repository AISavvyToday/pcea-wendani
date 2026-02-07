# Central SMS Service - Deployment Guide

This is the **central SMS service** webapp deployed at `sms.swiftresidetech.co.ke`. It handles all KCB callbacks for SMS credit purchases and provides a REST API for other webapps to query balances and send SMS.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Central SMS Service (sms.swiftresidetech.co.ke)            │
│  - KCB Callbacks (3 endpoints)                              │
│  - REST API (balance, credits, SMS sending)                 │
│  - Master Organization Database                             │
└─────────────────────────────────────────────────────────────┘
                    ▲                    ▲
                    │                    │
        ┌───────────┴──────────┐        │
        │                       │        │
┌───────▼────────┐    ┌─────────▼───────┐│
│ kalimoniprimary│    │ pceawendaniacad ││
│ school.co.ke   │    │ emy.co.ke       ││
│ (calls API)    │    │ (calls API)     ││
└────────────────┘    └─────────────────┘
```

## Deployment to Heroku

### 1. Create Heroku App

```bash
heroku create swift-sms-service
heroku domains:add sms.swiftresidetech.co.ke
```

### 2. Set Environment Variables

```bash
# Database
heroku config:set DATABASE_URL=<postgres_url>

# Django
heroku config:set SECRET_KEY=<your-secret-key>
heroku config:set DEBUG=False
heroku config:set ALLOWED_HOSTS=sms.swiftresidetech.co.ke

# KCB Integration (Swift Reside Tech)
heroku config:set SWIFT_RESIDE_PAYBILL=522533
heroku config:set SWIFT_RESIDE_TILL=SWIFTTECH
heroku config:set SWIFT_SMS_PRICE=1.0
heroku config:set SWIFT_KCB_PUBLIC_KEY_BASE64=<base64-encoded-public-key>
heroku config:set SWIFT_KCB_SIGNATURE_KEY=<hmac-signature-key>
heroku config:set SWIFT_KCB_SIGNATURE_METHOD=auto
heroku config:set SWIFT_KCB_SKIP_SIGNATURE_VERIFICATION=False

# ImaraBiz SMS Gateway
heroku config:set IMARABIZ_API_KEY=<your-api-key>
heroku config:set IMARABIZ_PARTNER_ID=<your-partner-id>
heroku config:set SWIFT_DEFAULT_SHORTCODE=SWIFT_RE_TECH

# SMS Sending Configuration
heroku config:set SMS_BATCH_SIZE=50
heroku config:set SMS_BATCH_DELAY=1.0
heroku config:set SMS_ASYNC_ENABLED=True

# API Authentication
heroku config:set SMS_SERVICE_API_TOKEN=<generate-secure-random-token>

# Site URL
heroku config:set SITE_URL=https://sms.swiftresidetech.co.ke
```

### 3. Deploy

```bash
git init
git add .
git commit -m "Initial commit"
heroku git:remote -a swift-sms-service
git push heroku main
```

### 4. Run Migrations

```bash
heroku run python manage.py migrate
heroku run python manage.py createsuperuser
```

## KCB Endpoints

Submit these endpoints to KCB Bank for SMS credit purchase integration:

1. **Validation**: `https://sms.swiftresidetech.co.ke/tenants/api/sms-credits/kcb-validate/`
2. **Notification (Paybill)**: `https://sms.swiftresidetech.co.ke/tenants/api/sms-credits/kcb-notification/`
3. **Notification (Till)**: `https://sms.swiftresidetech.co.ke/tenants/api/sms-credits/kcb-till-notification/`

## Creating Organizations

After deployment, create organizations via Django admin:

1. Go to `https://sms.swiftresidetech.co.ke/admin/`
2. Navigate to **Swift SMS Credits > Organizations**
3. Click **Add Organization**
4. Fill in:
   - **Name**: Organization name (e.g., "Kalimoni Primary School")
   - **SMS Account Number**: Will be auto-generated (e.g., "SMS001")
   - **SMS Balance**: Starting balance (default: 0)
   - **SMS Price Per Unit**: Price per SMS credit (default: 1.0)
   - **ImaraBiz Shortcode**: Organization's shortcode (e.g., "KALIMONI_FP") or leave empty for default
   - **Is Active**: Check to activate

5. Save and note the **SMS Account Number** - this is what organizations use to purchase credits.

## API Endpoints

### Authentication

All API endpoints require token authentication via `Authorization: Bearer <token>` header or `?token=<token>` query parameter.

### Get Balance

```bash
GET /api/v1/balance/?sms_account_number=SMS001
Authorization: Bearer <token>
```

Response:
```json
{
  "success": true,
  "sms_account_number": "SMS001",
  "organization_name": "Kalimoni Primary School",
  "balance": 1000,
  "price_per_sms": 1.0
}
```

### Deduct Credits

```bash
POST /api/v1/credits/deduct/
Authorization: Bearer <token>
Content-Type: application/json

{
  "sms_account_number": "SMS001",
  "sms_count": 5,
  "purpose": "api_deduction"
}
```

### Send SMS

```bash
POST /api/v1/sms/send/
Authorization: Bearer <token>
Content-Type: application/json

{
  "sms_account_number": "SMS001",
  "phone_number": "254712345678",
  "message": "Hello!",
  "purpose": "api_send"
}
```

### Send Bulk SMS

```bash
POST /api/v1/sms/bulk/
Authorization: Bearer <token>
Content-Type: application/json

{
  "sms_account_number": "SMS001",
  "recipients": [
    {"phone_number": "254712345678", "message": "Hello 1"},
    {"phone_number": "254798765432", "message": "Hello 2"}
  ],
  "purpose": "api_bulk"
}
```

### Usage History

```bash
GET /api/v1/usage/?sms_account_number=SMS001&limit=50
Authorization: Bearer <token>
```

### Purchase History

```bash
GET /api/v1/purchases/?sms_account_number=SMS001&limit=50
Authorization: Bearer <token>
```

## Integration with Other Webapps

See `REUSE_GUIDE.md` for instructions on integrating this service into other Django webapps.

