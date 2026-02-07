"""
Models for Swift SMS Credits package

This package includes its own Organization model for the central SMS service.
Other webapps can use their own Organization models by setting SMS_CREDITS_ORGANIZATION_MODEL.
"""
import uuid
import secrets
import string
from django.db import models
from django.utils import timezone
from django.conf import settings


def get_organization_model_path():
    """Get Organization model path from settings"""
    return getattr(settings, 'SMS_CREDITS_ORGANIZATION_MODEL', 'swift_sms_credits.Organization')


def generate_sms_account_number():
    """Generate a unique SMS account number for an organization"""
    # Format: SMS + 6 random alphanumeric characters
    chars = string.ascii_uppercase + string.digits
    while True:
        account_number = 'SMS' + ''.join(secrets.choice(chars) for _ in range(6))
        if not Organization.objects.filter(sms_account_number=account_number).exists():
            return account_number


class Organization(models.Model):
    """
    Organization model for central SMS service.
    
    Each organization has a unique SMS account number and manages its own SMS credits.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, help_text="Organization name")
    slug = models.SlugField(max_length=100, unique=True, blank=True, help_text="URL-friendly identifier")
    
    # SMS Credits
    sms_account_number = models.CharField(
        max_length=50, 
        unique=True, 
        help_text="Unique account number for SMS purchases (e.g., 'SMS001')"
    )
    sms_balance = models.IntegerField(default=0, help_text="SMS credits available")
    sms_price_per_unit = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=1.00, 
        help_text="Price per SMS credit in KSH"
    )
    imarabiz_shortcode = models.CharField(
        max_length=50,
        default='SWIFT_RE_TECH',
        blank=True,
        help_text="ImaraBiz shortcode for this organization (e.g., 'KALIMONI_FP'). Leave empty to use company default."
    )
    
    # Status
    is_active = models.BooleanField(default=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
        verbose_name = 'Organization'
        verbose_name_plural = 'Organizations'
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        # Auto-generate SMS account number if not set
        if not self.sms_account_number:
            self.sms_account_number = generate_sms_account_number()
        
        # Auto-generate slug if not set
        if not self.slug:
            from django.utils.text import slugify
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while Organization.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        
        super().save(*args, **kwargs)
    
    def add_sms_credits(self, count):
        """Add SMS credits to balance"""
        self.sms_balance += count
        self.save(update_fields=['sms_balance', 'updated_at'])
        return True
    
    def deduct_sms_credits(self, count):
        """Deduct SMS credits from balance"""
        if self.sms_balance >= count:
            self.sms_balance -= count
            self.save(update_fields=['sms_balance', 'updated_at'])
            return True
        return False


class SMSPurchaseTransaction(models.Model):
    """
    SMS purchase transaction log - tracks payments for SMS credits
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('reversed', 'Reversed'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        get_organization_model_path(),
        on_delete=models.PROTECT,
        related_name='sms_purchases',
        help_text="Organization that purchased SMS credits"
    )
    
    # Payment details
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Amount paid in KSH")
    sms_credits = models.IntegerField(help_text="Number of SMS credits purchased")
    price_per_sms = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Price per SMS at time of purchase"
    )
    
    # Transaction status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Bank reference
    bank_reference = models.CharField(max_length=100, unique=True, db_index=True, help_text="Bank transaction reference")
    
    # KCB metadata
    kcb_channel_code = models.CharField(max_length=20, blank=True)
    kcb_timestamp = models.CharField(max_length=50, blank=True)
    kcb_till_number = models.CharField(max_length=50, blank=True)
    kcb_customer_mobile = models.CharField(max_length=20, blank=True)
    kcb_customer_name = models.CharField(max_length=255, blank=True)
    kcb_narration = models.TextField(blank=True)
    kcb_balance = models.CharField(max_length=50, blank=True, help_text="Account balance after transaction from KCB")
    
    # Raw request data for debugging
    raw_request_data = models.JSONField(null=True, blank=True, help_text="Raw KCB notification data")
    
    # Error tracking
    error_message = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'SMS Purchase Transaction'
        verbose_name_plural = 'SMS Purchase Transactions'
        indexes = [
            models.Index(fields=['organization', 'created_at']),
            models.Index(fields=['status']),
            models.Index(fields=['bank_reference']),
        ]
    
    def __str__(self):
        return f"{self.organization.name} - KES {self.amount} ({self.sms_credits} SMS) - {self.status}"
    
    def complete_transaction(self):
        """Mark transaction as completed and credit organization"""
        if self.status == 'completed':
            return False  # Already completed
        
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at', 'updated_at'])
        
        # Credit organization's SMS balance
        if hasattr(self.organization, 'add_sms_credits'):
            self.organization.add_sms_credits(self.sms_credits)
        else:
            # Fallback: directly update balance
            self.organization.sms_balance += self.sms_credits
            self.organization.save(update_fields=['sms_balance'])
        return True


class SMSUsageLog(models.Model):
    """
    Track SMS usage per organization - for billing and analytics
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        get_organization_model_path(),
        on_delete=models.PROTECT,
        related_name='sms_usage_logs'
    )
    
    # Usage details
    sms_count = models.IntegerField(default=1, help_text="Number of SMS sent")
    purpose = models.CharField(max_length=100, blank=True, help_text="Purpose (e.g., 'low_balance_alert', 'payment_confirmation', 'manual')")
    
    # Balance tracking
    balance_before = models.IntegerField(help_text="SMS balance before this usage")
    balance_after = models.IntegerField(help_text="SMS balance after this usage")
    
    # Reference to notification (optional)
    notification_ids = models.JSONField(null=True, blank=True, help_text="List of SMSNotification IDs")
    
    # User who triggered the SMS (if applicable)
    # Use settings.AUTH_USER_MODEL for User model reference
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='triggered_sms_usage'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'SMS Usage Log'
        verbose_name_plural = 'SMS Usage Logs'
        indexes = [
            models.Index(fields=['organization', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.organization.name} - {self.sms_count} SMS ({self.purpose}) - {self.created_at.date()}"

