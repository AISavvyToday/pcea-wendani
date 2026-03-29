# payments/models.py

from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal
from datetime import time
from core.models import BaseModel, PaymentMethod, PaymentStatus, PaymentSource
from accounts.models import User
from django.utils import timezone


class Payment(BaseModel):
    """
    Payment record - tracks money received from parents.
    """
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='payments',
        null=True,
        blank=True,
        help_text="Organization this payment belongs to"
    )
    
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
    payment_source = models.CharField(max_length=20, choices=PaymentSource.choices)
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
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payments_deleted'
    )

    unallocated_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments_deleted",
    )

    @property
    def unapplied_amount(self):
        """
        Alias for unallocated_amount.
        Used for template and reporting compatibility.
        """
        return self.unallocated_amount
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
        if self.unallocated_amount < 0:
            self.unallocated_amount = Decimal("0.00")

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

    def delete(self, *args, **kwargs):
        raise RuntimeError(
            "Payments must be deleted via InvoiceService.delete_payment()"
        )


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
    matched_by = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='bank_transactions_matched'
    )
    matched_at = models.DateTimeField(null=True, blank=True)
    
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

    @property
    def allocated_amount(self):
        if hasattr(self, "_allocated_amount_cache"):
            return self._allocated_amount_cache

        total = (
            self.reconciliations.filter(is_active=True)
            .aggregate(total=models.Sum("amount"))
            .get("total")
        )
        if total is not None:
            return total

        if self.payment_id:
            return self.payment.amount

        return Decimal("0.00")

    @property
    def remaining_amount(self):
        return max(Decimal("0.00"), (self.amount or Decimal("0.00")) - self.allocated_amount)

    @property
    def is_fully_matched(self):
        return self.remaining_amount <= Decimal("0.00")

    @property
    def effective_matched_at(self):
        return self.matched_at

    @property
    def effective_received_at(self):
        bank_timestamp = self.bank_timestamp
        if bank_timestamp:
            if bank_timestamp.timetz().replace(tzinfo=None) != time(0, 0):
                return bank_timestamp
            return self.callback_received_at or bank_timestamp
        return self.callback_received_at or self.created_at

    @property
    def matched_students(self):
        reconciliations = list(
            self.reconciliations.filter(is_active=True).select_related("student")
        )
        if reconciliations:
            return [reconciliation.student for reconciliation in reconciliations]
        if self.payment_id:
            return [self.payment.student]
        return []

    def get_matching_hints(self):
        """
        Extract useful information from raw_request to help with manual matching.
        Returns a dict with gateway-specific fields that can help identify the student.
        """
        import re
        hints = {
            'bill_reference': '',
            'payer_phone': '',
            'payer_name': '',
            'payment_channel': '',
            'student_hint': '',  # Best guess at student identifier
            'all_references': [],  # All reference-like values found
        }
        
        if not self.raw_request:
            return hints
        
        raw = self.raw_request
        
        if self.gateway == 'equity':
            # Equity Bank payload fields
            bill_number = raw.get('billNumber', '') or raw.get('CustomerRefNumber', '')
            hints['bill_reference'] = bill_number
            hints['payer_phone'] = raw.get('phonenumber', '') or ''
            hints['payment_channel'] = raw.get('paymentMode', '') or ''
            # debitcustname is the SCHOOL's name, not useful for matching
            # tranParticular is typically "BILL PAYMENT"
            
            # Student hint is whatever they typed as bill number
            hints['student_hint'] = bill_number
            
            # Collect all reference-like values
            refs = []
            if bill_number:
                refs.append(f"Bill #: {bill_number}")
            if raw.get('CustomerRefNumber') and raw.get('CustomerRefNumber') != bill_number:
                refs.append(f"Cust Ref: {raw.get('CustomerRefNumber')}")
            if raw.get('phonenumber'):
                refs.append(f"Phone: {raw.get('phonenumber')}")
            hints['all_references'] = refs
            
        elif self.gateway == 'coop':
            # Co-op Bank payload - info is in narration fields
            narration = raw.get('Narration', '') or raw.get('CustMemo', '')
            memo_lines = [
                raw.get('CustMemoLine1', '') or raw.get('Narration1', ''),
                raw.get('CustMemoLine2', '') or raw.get('Narration2', ''),
                raw.get('CustMemoLine3', '') or raw.get('Narration3', ''),
            ]
            
            # Combine all text for parsing
            all_text = ' '.join([narration] + memo_lines)
            
            # Try to extract phone number (254... or 07...)
            phone_match = re.search(r'(254\d{9}|07\d{8}|01\d{8})', all_text)
            if phone_match:
                hints['payer_phone'] = phone_match.group(1)
            
            # Try to extract admission number patterns
            # Common patterns: 393939#StudentName, or just numbers
            admission_match = re.search(r'(\d{4,8})#([A-Za-z,\s]+)', all_text)
            if admission_match:
                hints['student_hint'] = admission_match.group(1)
                hints['payer_name'] = admission_match.group(2).replace(',', ' ').strip()
            
            # Look for payer name after phone number pattern
            # Format: "phone~MPESAC2B_400222~PAYER NAME"
            payer_match = re.search(r'MPESAC2B[_\d]*~([A-Z\s]+)$', all_text)
            if payer_match:
                hints['payer_name'] = payer_match.group(1).strip()
            
            # Payment channel from narration
            if 'MPESAC2B' in all_text:
                hints['payment_channel'] = 'M-PESA C2B'
            elif 'RTGS' in all_text:
                hints['payment_channel'] = 'RTGS'
            elif 'EFT' in all_text:
                hints['payment_channel'] = 'EFT'
            
            # Collect all references
            refs = []
            if hints['student_hint']:
                refs.append(f"Admission #: {hints['student_hint']}")
            if hints['payer_name']:
                refs.append(f"Payer: {hints['payer_name']}")
            if hints['payer_phone']:
                refs.append(f"Phone: {hints['payer_phone']}")
            if raw.get('PaymentRef') or raw.get('MessageReference'):
                refs.append(f"Ref: {raw.get('PaymentRef') or raw.get('MessageReference')}")
            hints['all_references'] = refs
            
            # Use narration as fallback description
            hints['bill_reference'] = raw.get('PaymentRef', '') or raw.get('MessageReference', '')
        
        return hints
    
    @property
    def matching_summary(self):
        """
        Returns a human-readable summary of matching hints for display in templates.
        """
        hints = self.get_matching_hints()
        parts = []
        
        if hints['student_hint']:
            parts.append(f"Student Ref: {hints['student_hint']}")
        if hints['payer_name']:
            parts.append(f"Payer: {hints['payer_name']}")
        if hints['payer_phone']:
            parts.append(f"Phone: {hints['payer_phone']}")
        if hints['payment_channel']:
            parts.append(f"Channel: {hints['payment_channel']}")
            
        return ' | '.join(parts) if parts else 'No matching info available'


class BankTransactionReconciliation(BaseModel):
    """
    Audit record for allocating a bank transaction to one or more student payments.
    """

    bank_transaction = models.ForeignKey(
        BankTransaction,
        on_delete=models.CASCADE,
        related_name="reconciliations",
    )
    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name="bank_transaction_reconciliations",
    )
    student = models.ForeignKey(
        "students.Student",
        on_delete=models.PROTECT,
        related_name="bank_transaction_reconciliations",
    )
    invoice = models.ForeignKey(
        "finance.Invoice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_transaction_reconciliations",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    matched_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_transaction_reconciliations",
    )
    matched_at = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "bank_transaction_reconciliations"
        ordering = ["matched_at", "created_at"]

    def __str__(self):
        return (
            f"{self.bank_transaction.transaction_id} → "
            f"{self.student.admission_number}: {self.amount}"
        )


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
