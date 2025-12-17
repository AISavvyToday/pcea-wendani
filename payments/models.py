# payments/models.py

from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal
from core.models import BaseModel, PaymentMethod, PaymentStatus
from accounts.models import User


class Payment(BaseModel):
    """
    Payment record - tracks money received from parents.
    """
    # Payment reference (auto-generated)
    payment_reference = models.CharField(max_length=30, unique=True)
    
    student = models.ForeignKey(
        'students.Student', on_delete=models.CASCADE, related_name='payments'
    )
    invoice = models.ForeignKey(
        'finance.Invoice', on_delete=models.SET_NULL, 
        null=True, blank=True, related_name='payments'
    )
    
    amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    
    # Payment date/time
    payment_date = models.DateTimeField()
    
    # Payer info (may differ from parent)
    payer_name = models.CharField(max_length=100, blank=True)
    payer_phone = models.CharField(max_length=15, blank=True)
    
    # Bank/M-PESA reference
    transaction_reference = models.CharField(max_length=50, blank=True)  # e.g., M-PESA code
    
    # For manual payments
    received_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments_received'
    )
    
    # Receipt
    receipt_number = models.CharField(max_length=30, blank=True)
    receipt_sent = models.BooleanField(default=False)
    receipt_sent_at = models.DateTimeField(null=True, blank=True)
    
    # Notes
    notes = models.TextField(blank=True)
    
    # Reconciliation
    is_reconciled = models.BooleanField(default=False)
    reconciled_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments_reconciled'
    )
    reconciled_at = models.DateTimeField(null=True, blank=True)

    unallocated_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    class Meta:
        db_table = 'payments'
        ordering = ['-payment_date']
        indexes = [
            models.Index(fields=['payment_reference']),
            models.Index(fields=['student', 'payment_date']),
            models.Index(fields=['status', 'payment_date']),
            models.Index(fields=['transaction_reference']),
        ]

    def __str__(self):
        return f"{self.payment_reference} - {self.student.admission_number} - KES {self.amount}"

    def save(self, *args, **kwargs):
        if not self.payment_reference:
            self.payment_reference = self.generate_payment_reference()
        if not self.receipt_number and self.status == PaymentStatus.COMPLETED:
            self.receipt_number = self.generate_receipt_number()
        super().save(*args, **kwargs)

    def generate_payment_reference(self):
        """Generate unique payment reference: PAY-YYYYMMDD-XXXXX"""
        from django.utils import timezone
        today = timezone.now()
        date_str = today.strftime('%Y%m%d')
        
        last_payment = Payment.objects.filter(
            payment_reference__startswith=f'PAY-{date_str}'
        ).order_by('-payment_reference').first()
        
        if last_payment:
            last_num = int(last_payment.payment_reference.split('-')[-1])
            new_num = last_num + 1
        else:
            new_num = 1
        
        return f'PAY-{date_str}-{new_num:05d}'

    def generate_receipt_number(self):
        """Generate receipt number: RCP-YYYY-XXXXX"""
        from django.utils import timezone
        year = timezone.now().year
        
        last_receipt = Payment.objects.filter(
            receipt_number__startswith=f'RCP-{year}'
        ).exclude(receipt_number='').order_by('-receipt_number').first()
        
        if last_receipt:
            last_num = int(last_receipt.receipt_number.split('-')[-1])
            new_num = last_num + 1
        else:
            new_num = 1
        
        return f'RCP-{year}-{new_num:05d}'


class BankTransaction(BaseModel):
    """
    Raw transaction data from bank APIs/IPNs.
    Stores the original callback data for audit purposes.
    """
    # Link to payment (once matched)
    payment = models.ForeignKey(
        Payment, on_delete=models.SET_NULL, 
        null=True, blank=True, related_name='bank_transactions'
    )
    
    # Bank/Gateway
    GATEWAY_CHOICES = [
        ('equity', 'Equity Bank'),
        ('coop', 'Co-operative Bank'),
        ('mpesa', 'M-PESA'),
    ]
    gateway = models.CharField(max_length=20, choices=GATEWAY_CHOICES)
    
    # Transaction details from bank
    transaction_id = models.CharField(max_length=50, unique=True)  # Bank's transaction ID
    transaction_reference = models.CharField(max_length=50, blank=True)  # Our reference sent to bank
    
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='KES')
    
    # Payer details from bank
    payer_account = models.CharField(max_length=50, blank=True)  # Phone or account number
    payer_name = models.CharField(max_length=100, blank=True)
    
    # Status from bank
    bank_status = models.CharField(max_length=50)
    bank_status_description = models.TextField(blank=True)
    
    # Timestamps from bank
    bank_timestamp = models.DateTimeField(null=True, blank=True)
    
    # Raw callback data (for debugging/audit)
    raw_request = models.JSONField(default=dict)
    raw_response = models.JSONField(default=dict)
    
    # Processing status
    PROCESSING_STATUS = [
        ('received', 'Received'),
        ('processing', 'Processing'),
        ('matched', 'Matched to Payment'),
        ('failed', 'Failed to Process'),
        ('duplicate', 'Duplicate'),
    ]
    processing_status = models.CharField(max_length=20, choices=PROCESSING_STATUS, default='received')
    processing_notes = models.TextField(blank=True)
    
    # Callback info
    callback_url = models.URLField(blank=True)
    callback_received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'bank_transactions'
        ordering = ['-callback_received_at']
        indexes = [
            models.Index(fields=['transaction_id']),
            models.Index(fields=['gateway', 'processing_status']),
            models.Index(fields=['payer_account']),
        ]

    def __str__(self):
        return f"{self.gateway} - {self.transaction_id} - KES {self.amount}"


class PaymentAllocation(BaseModel):
    """
    Tracks how a payment is allocated across invoice items.
    A single payment can be split across multiple fee categories.
    """
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='allocations')
    invoice_item = models.ForeignKey(
        'finance.InvoiceItem', on_delete=models.CASCADE, related_name='allocations'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'payment_allocations'

    def __str__(self):
        return f"{self.payment.payment_reference} → {self.invoice_item.description}: {self.amount}"


class PaymentReminder(BaseModel):
    """
    Track payment reminders sent to parents.
    """
    invoice = models.ForeignKey(
        'finance.Invoice', on_delete=models.CASCADE, related_name='reminders'
    )
    
    REMINDER_TYPES = [
        ('sms', 'SMS'),
        ('email', 'Email'),
        ('both', 'SMS & Email'),
    ]
    reminder_type = models.CharField(max_length=10, choices=REMINDER_TYPES)