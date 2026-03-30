# core/models.py

import uuid
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    """Abstract base model with created/updated timestamps."""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ActiveManager(models.Manager):
    """Manager that returns only active records."""
    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


class BaseModel(TimeStampedModel):
    """Abstract base model with soft delete capability."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    is_active = models.BooleanField(default=True)
    
    objects = models.Manager()
    active_objects = ActiveManager()

    class Meta:
        abstract = True

    def soft_delete(self):
        self.is_active = False
        self.save(update_fields=['is_active', 'updated_at'])


# ============== ORGANIZATION MODEL ==============

class Organization(BaseModel):
    """
    Multi-tenant organization model.
    Each school/organization is isolated by organization FK on all models.
    """
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True, help_text="Unique organization code")
    
    # Contact information
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    logo_url = models.URLField(blank=True, help_text="URL to organization logo")
    
    # SMS Credits fields (for SMS integration)
    sms_account_number = models.CharField(
        max_length=50, 
        unique=True, 
        blank=True, 
        null=True,
        help_text="Unique SMS account number for KCB payments (e.g., SMS001)"
    )
    sms_balance = models.IntegerField(
        default=0,
        help_text="Current SMS credits balance"
    )
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
        help_text="ImaraBiz SMS shortcode for this organization"
    )
    
    class Meta:
        db_table = 'organizations'
        ordering = ['name']
        verbose_name = 'Organization'
        verbose_name_plural = 'Organizations'
    
    def __str__(self):
        return self.name
    
    def add_sms_credits(self, count):
        """Add SMS credits to organization balance."""
        self.sms_balance += count
        self.save(update_fields=['sms_balance', 'updated_at'])
        return True
    
    def deduct_sms_credits(self, count):
        """Deduct SMS credits from organization balance."""
        if self.sms_balance < count:
            return False
        self.sms_balance -= count
        self.save(update_fields=['sms_balance', 'updated_at'])
        return True
    
    @classmethod
    def get_current_organization(cls, user):
        """Get organization for current user."""
        if hasattr(user, 'organization') and user.organization:
            return user.organization
        return None


# ============== CONSTANTS ==============

class UserRole(models.TextChoices):
    SUPER_ADMIN = 'super_admin', 'Super Administrator'
    SCHOOL_ADMIN = 'school_admin', 'School Administrator'
    ACCOUNTANT = 'accountant', 'Accountant'
    TEACHER = 'teacher', 'Teacher'
    PARENT = 'parent', 'Parent'
    STUDENT = 'student', 'Student'


class Gender(models.TextChoices):
    MALE = 'M', 'Male'
    FEMALE = 'F', 'Female'


class TermChoices(models.TextChoices):
    TERM_1 = 'term_1', 'Term 1'
    TERM_2 = 'term_2', 'Term 2'
    TERM_3 = 'term_3', 'Term 3'

class PaymentMethod(models.TextChoices):
    MOBILE_MONEY = 'mobile_money', 'Mobile Money'
    BANK_DEPOSIT = 'bank_deposit', 'Bank Deposit'
    CHEQUE = 'cheque', 'Cheque'


class PaymentSource(models.TextChoices):
    EQUITY_BANK = 'equity_bank', 'Equity Bank'
    COOP_BANK = 'coop_bank', 'Co-operative Bank'
    MPESA = 'mpesa', 'Mpesa'
    # Internal/system sources (no external cash movement)
    CREDIT = 'credit', 'Student Credit'



class PaymentStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'
    CANCELLED = 'cancelled', 'Cancelled'


class InvoiceStatus(models.TextChoices):
    PARTIALLY_PAID = 'partially_paid', 'Partially Paid'
    PAID = 'paid', 'Paid'
    OVERDUE = 'overdue', 'Overdue'
    CANCELLED = 'cancelled', 'Cancelled'


class AttendanceStatus(models.TextChoices):
    PRESENT = 'present', 'Present'
    ABSENT = 'absent', 'Absent'
    LATE = 'late', 'Late'
    EXCUSED = 'excused', 'Excused'


class GradeLevel(models.TextChoices):
    # Pre-Primary
    PP1 = 'pp1', 'PP1'
    PP2 = 'pp2', 'PP2'
    PlayGroup = 'play_group', 'Play Group'
    # Primary (CBC)
    GRADE_1 = 'grade_1', 'Grade 1'
    GRADE_2 = 'grade_2', 'Grade 2'
    GRADE_3 = 'grade_3', 'Grade 3'
    GRADE_4 = 'grade_4', 'Grade 4'
    GRADE_5 = 'grade_5', 'Grade 5'
    GRADE_6 = 'grade_6', 'Grade 6'
    # Junior Secondary (JSS)
    GRADE_7 = 'grade_7', 'Grade 7'
    GRADE_8 = 'grade_8', 'Grade 8'
    GRADE_9 = 'grade_9', 'Grade 9'


class FeeCategory(models.TextChoices):
    TUITION = 'tuition', 'Tuition'
    BOARDING = 'boarding', 'Boarding'
    TRANSPORT = 'transport', 'Transport'
    MEALS = 'meals', 'Meals/Lunch'
    UNIFORM = 'uniform', 'Uniform'
    BOOKS = 'books', 'Books & Stationery'
    EXAMINATION = 'examination', 'Examination'
    ACTIVITY = 'activity', 'Activity/Extra-curricular'
    DEVELOPMENT = 'development', 'Development Levy'
    ADMISSION = 'admission', 'Admission Fee'
    OTHER = 'other', 'Educational Activities'
    # Special synthetic categories for accounting
    BALANCE_BF = 'balance_bf', 'Balance Brought Forward'
    PREPAYMENT_CREDIT = 'prepayment', 'Prepayment / Credit'

class StreamChoices(models.TextChoices):
    EAST = 'EAST', 'East'
    WEST = 'WEST', 'West'
    SOUTH = 'SOUTH', 'South'