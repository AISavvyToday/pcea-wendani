# finance/models.py

from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal
from core.models import BaseModel, FeeCategory, InvoiceStatus, GradeLevel, TermChoices
from accounts.models import User


class FeeStructure(BaseModel):
    """
    Fee structure definition per grade level and term.
    Defines what fees apply to which students.
    """
    name = models.CharField(max_length=100)  # e.g., "Grade 1-3 Term 1 Fees 2025"
    academic_year = models.ForeignKey(
        'academics.AcademicYear', on_delete=models.CASCADE, related_name='fee_structures'
    )
    term = models.CharField(max_length=10, choices=TermChoices.choices)
    
    # Which grade levels this applies to
    grade_levels = models.JSONField(default=list)  # e.g., ['grade_1', 'grade_2', 'grade_3']
    

    description = models.TextField(blank=True)

    class Meta:
        db_table = 'fee_structures'
        ordering = ['-academic_year__year', 'term']

    def __str__(self):
        return f"{self.name} ({self.academic_year.year})"

    @property
    def total_amount(self):
        return sum(item.amount for item in self.items.all())


class FeeItem(BaseModel):
    """
    Individual fee items within a fee structure.
    e.g., Tuition: 15000, Lunch: 5000, etc.
    """
    fee_structure = models.ForeignKey(
        FeeStructure, on_delete=models.CASCADE, related_name='items'
    )
    category = models.CharField(max_length=20, choices=FeeCategory.choices)
    description = models.CharField(max_length=100)
    amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    is_optional = models.BooleanField(default=False)  # e.g., Transport is optional
    
    # For optional items, can be applied per student
    applies_to_all = models.BooleanField(default=True)

    class Meta:
        db_table = 'fee_items'
        ordering = ['category']

    def __str__(self):
        return f"{self.fee_structure.name} - {self.description}: {self.amount}"


class Discount(BaseModel):
    """
    Discount/Scholarship definitions.
    Can be percentage or fixed amount.
    """
    name = models.CharField(max_length=100)  # e.g., "Sibling Discount", "Staff Child"
    
    DISCOUNT_TYPES = [
        ('percentage', 'Percentage'),
        ('fixed', 'Fixed Amount'),
    ]
    discount_type = models.CharField(max_length=20, choices=DISCOUNT_TYPES)
    value = models.DecimalField(max_digits=10, decimal_places=2)  # % or KES amount
    
    # Which fee categories this applies to (empty = all)
    applicable_categories = models.JSONField(default=list)
    
    # Validity
    academic_year = models.ForeignKey(
        'academics.AcademicYear', on_delete=models.CASCADE, 
        related_name='discounts', null=True, blank=True
    )
    
    description = models.TextField(blank=True)
    requires_approval = models.BooleanField(default=True)

    class Meta:
        db_table = 'discounts'
        ordering = ['name']

    def __str__(self):
        if self.discount_type == 'percentage':
            return f"{self.name} ({self.value}%)"
        return f"{self.name} (KES {self.value})"

    def calculate_discount(self, amount):
        """Calculate discount amount for a given fee amount."""
        if self.discount_type == 'percentage':
            return amount * (self.value / 100)
        return min(self.value, amount)  # Fixed amount, but not more than the fee


class StudentDiscount(BaseModel):
    """
    Discounts assigned to specific students.
    """
    student = models.ForeignKey(
        'students.Student', on_delete=models.CASCADE, related_name='discounts'
    )
    discount = models.ForeignKey(Discount, on_delete=models.CASCADE, related_name='student_discounts')
    
    # Override the discount value for this student if needed
    custom_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Validity period
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    
    # Approval
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_discounts'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    
    reason = models.TextField(blank=True)

    class Meta:
        db_table = 'student_discounts'
        unique_together = ['student', 'discount']

    def __str__(self):
        return f"{self.student.admission_number} - {self.discount.name}"


class Invoice(BaseModel):
    """
    Fee invoice for a student for a specific term.
    """
    # Invoice number (auto-generated)
    invoice_number = models.CharField(max_length=20, unique=True)
    
    student = models.ForeignKey(
        'students.Student', on_delete=models.CASCADE, related_name='invoices'
    )
    term = models.ForeignKey(
        'academics.Term', on_delete=models.CASCADE, related_name='invoices'
    )
    
    # Amounts
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Balance brought forward from previous term
    balance_bf = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Prepayment/credit from previous term
    prepayment = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    status = models.CharField(max_length=20, choices=InvoiceStatus.choices, default=InvoiceStatus.OVERDUE)
    
    # Dates
    issue_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)

    # Notes
    notes = models.TextField(blank=True)
    
    # Tracking
    generated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='invoices_generated'
    )
    fee_structure = models.ForeignKey(
        FeeStructure,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoices'
    )

    class Meta:
        db_table = 'invoices'
        unique_together = ['student', 'term']
        ordering = ['-issue_date']
        indexes = [
            models.Index(fields=['invoice_number']),
            models.Index(fields=['student', 'term']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.invoice_number} - {self.student.admission_number}"

    def generate_invoice_number(self):
        """Generate unique invoice number: INV-YYYY-XXXXX"""
        from django.utils import timezone
        year = timezone.now().year
        last_invoice = Invoice.objects.filter(
            invoice_number__startswith=f'INV-{year}'
        ).order_by('-invoice_number').first()
        
        if last_invoice:
            last_num = int(last_invoice.invoice_number.split('-')[-1])
            new_num = last_num + 1
        else:
            new_num = 1
        
        return f'INV-{year}-{new_num:05d}'

    def update_payment_status(self):
        """Update invoice status based on balance and payment."""
        if self.balance <= 0:
            self.status = InvoiceStatus.PAID
        elif self.amount_paid > 0:
            self.status = InvoiceStatus.PARTIALLY_PAID
        elif self.due_date and self.due_date < __import__("datetime").date.today():
            self.status = InvoiceStatus.OVERDUE

        # Save normally so balance/status stay consistent
        self.save()

    def save(self, *args, **kwargs):
        # Auto-generate invoice number if not set
        if not self.invoice_number:
            self.invoice_number = self.generate_invoice_number()

        # FIXED FORMULA: Add balance_bf to the calculation
        self.balance = (self.total_amount + self.balance_bf - self.amount_paid) + self.prepayment
        super().save(*args, **kwargs)


class InvoiceItem(BaseModel):
    """
    Line items on an invoice.

    Extended to optionally store transport meta (route, trip_type) for transport items.
    """
    TRIP_CHOICES = [
        ('full', 'Full Trip'),
        ('half', 'Half Trip'),
    ]

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    fee_item = models.ForeignKey(
        FeeItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoice_items'
    )
    description = models.CharField(max_length=200)
    category = models.CharField(max_length=50, choices=FeeCategory.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    discount_applied = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    net_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    # Transport-specific metadata (nullable)
    transport_route = models.ForeignKey(
        'transport.TransportRoute',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='invoice_items'
    )
    transport_trip_type = models.CharField(
        max_length=10, choices=TRIP_CHOICES, null=True, blank=True,
        help_text="If set and category=='transport', indicates half/full trip"
    )

    class Meta:
        db_table = 'invoice_items'

    def __str__(self):
        if self.category == 'transport' and self.transport_route:
            trip_display = self.get_transport_trip_type_display() if self.transport_trip_type else 'Trip'
            return f"{self.description} ({self.transport_route.name} - {trip_display})"
        return self.description

    def save(self, *args, **kwargs):
        # Normalize None values
        if self.discount_applied in (None, ''):
            self.discount_applied = Decimal('0.00')
        if self.amount in (None, ''):
            self.amount = Decimal('0.00')

        # Recompute net_amount defensively
        try:
            self.net_amount = (self.amount or Decimal('0.00')) - (self.discount_applied or Decimal('0.00'))
        except Exception:
            # Fallback to zeros for safety
            self.net_amount = Decimal('0.00')

        super().save(*args, **kwargs)