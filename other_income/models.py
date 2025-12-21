# other_income/models.py
from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone

from core.models import BaseModel
from accounts.models import User


class OtherIncomeInvoice(BaseModel):
    """
    Invoice for non-student income (bus hire, ground hire, events, etc.)
    """
    invoice_number = models.CharField(max_length=30, unique=True, blank=True)
    client_name = models.CharField(max_length=200)
    client_contact = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('unpaid', 'Unpaid'),
        ('partially_paid', 'Partially Paid'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    issue_date = models.DateField(default=timezone.now)
    due_date = models.DateField(null=True, blank=True)

    generated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='other_income_generated')

    class Meta:
        db_table = 'other_income_invoices'
        ordering = ['-issue_date']

    def __str__(self):
        return f"{self.invoice_number} - {self.client_name}"

    def generate_invoice_number(self):
        """Format: OINV-YYYY-XXXXX"""
        year = timezone.now().year
        last = OtherIncomeInvoice.objects.filter(invoice_number__startswith=f"OINV-{year}").order_by('-invoice_number').first()
        if last and last.invoice_number:
            try:
                last_num = int(last.invoice_number.split('-')[-1])
            except Exception:
                last_num = 0
            new_num = last_num + 1
        else:
            new_num = 1
        return f"OINV-{year}-{new_num:05d}"

    def recalc_totals(self):
        items_total = self.items.filter(is_active=True).aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')
        self.subtotal = items_total
        self.total_amount = self.subtotal  # could add taxes/discounts later
        self.balance = self.total_amount - self.amount_paid
        return self

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = self.generate_invoice_number()
        # Recalculate totals before saving (ensure amounts are consistent)
        super().save(*args, **kwargs)
        # After save, ensure subtotal/total/balance reflect items/payments
        self.recalc_totals()
        super().save(update_fields=['subtotal', 'total_amount', 'balance', 'updated_at'])


class OtherIncomeItem(BaseModel):
    """
    Line item for OtherIncomeInvoice.
    """
    invoice = models.ForeignKey(OtherIncomeInvoice, on_delete=models.CASCADE, related_name='items')
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])

    class Meta:
        db_table = 'other_income_items'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.invoice.invoice_number}: {self.description} - {self.amount}"


class OtherIncomePayment(BaseModel):
    """
    Payment record for OtherIncomeInvoice. Independent from student Payment model.
    """
    payment_reference = models.CharField(max_length=30, unique=True, blank=True)
    invoice = models.ForeignKey(OtherIncomeInvoice, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    payment_method = models.CharField(max_length=50, blank=True)  # e.g., 'bank_transfer', 'cash'
    payment_date = models.DateTimeField(default=timezone.now)
    payer_name = models.CharField(max_length=200, blank=True)
    payer_contact = models.CharField(max_length=100, blank=True)
    transaction_reference = models.CharField(max_length=100, blank=True)
    received_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='other_income_received')

    receipt_number = models.CharField(max_length=30, blank=True)

    class Meta:
        db_table = 'other_income_payments'
        ordering = ['-payment_date']

    def __str__(self):
        return f"{self.payment_reference} - {self.invoice.invoice_number} - KES {self.amount}"

    def generate_payment_reference(self):
        today = timezone.now().strftime('%Y%m%d')
        last = OtherIncomePayment.objects.filter(payment_reference__startswith=f"OAP-{today}").order_by('-payment_reference').first()
        if last and last.payment_reference:
            try:
                last_num = int(last.payment_reference.split('-')[-1])
            except Exception:
                last_num = 0
            new_num = last_num + 1
        else:
            new_num = 1
        return f"OAP-{today}-{new_num:05d}"

    def save(self, *args, **kwargs):
        creating = self._state.adding
        if not self.payment_reference:
            self.payment_reference = self.generate_payment_reference()
        if not self.receipt_number:
            # simple receipt: R-OAP-YYYY-XXXXX
            year = timezone.now().year
            last = OtherIncomePayment.objects.filter(receipt_number__startswith=f"R-OAP-{year}").order_by('-receipt_number').first()
            if last and last.receipt_number:
                try:
                    last_num = int(last.receipt_number.split('-')[-1])
                except Exception:
                    last_num = 0
                new_num = last_num + 1
            else:
                new_num = 1
            self.receipt_number = f"R-OAP-{year}-{new_num:05d}"

        super().save(*args, **kwargs)

        # Update invoice paid amount and balance after payment is saved
        inv = self.invoice
        total_paid = inv.payments.aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')
        inv.amount_paid = total_paid
        inv.balance = (inv.total_amount or Decimal('0.00')) - total_paid
        # Update status
        if inv.balance <= 0:
            inv.status = 'paid'
        elif total_paid > 0:
            inv.status = 'partially_paid'
        else:
            inv.status = 'unpaid'
        inv.save(update_fields=['amount_paid', 'balance', 'status', 'updated_at'])