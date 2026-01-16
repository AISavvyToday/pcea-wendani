# students/models.py
from decimal import Decimal
from core.models import InvoiceStatus
from django.db import models
from django.core.validators import RegexValidator
from core.models import BaseModel, Gender, GradeLevel
from accounts.models import User

from django.db.models import Sum


class Parent(BaseModel):
    """
    Parent/Guardian model.
    A parent can have multiple children (students).
    Links to User account for portal access.
    """
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, 
        related_name='parent_profile',
        null=True, blank=True  # Parent may not have portal access yet
    )
    
    # Personal info
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True)
    id_number = models.CharField(max_length=20, unique=True, blank=True, null=True)
    
    # Contact info
    phone_primary = models.CharField(
        max_length=15,
        validators=[RegexValidator(r'^\+?254\d{9}$', 'Enter a valid Kenyan phone number')]
    )
    phone_secondary = models.CharField(max_length=15, blank=True)
    email = models.EmailField(blank=True)
    
    # Address
    address = models.TextField(blank=True)
    town = models.CharField(max_length=50, blank=True)
    
    # Employment (for records)
    occupation = models.CharField(max_length=100, blank=True)
    employer = models.CharField(max_length=100, blank=True)
    
    # Relationship type
    RELATIONSHIP_CHOICES = [
        ('father', 'Father'),
        ('mother', 'Mother'),
        ('guardian', 'Guardian'),
        ('sponsor', 'Sponsor'),
        ('other', 'Other'),
    ]
    relationship = models.CharField(
        max_length=20,
        choices=RELATIONSHIP_CHOICES,
        default="guardian",
    )

    class Meta:
        db_table = 'parents'
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.phone_primary})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class Student(BaseModel):
    """
    Student model - core entity of the system.
    Tracks all student information from admission to graduation.
    """
    # Link to user account (for student portal access, optional)
    user = models.OneToOneField(
        User, on_delete=models.SET_NULL,
        related_name='student_profile',
        null=True, blank=True
    )
    
    # Admission info
    admission_number = models.CharField(max_length=20, unique=True, blank=True, null=True)
    admission_date = models.DateField()
    
    # Personal info
    first_name = models.CharField(max_length=50)
    middle_name = models.CharField(max_length=50, blank=True)
    last_name = models.CharField(max_length=50)
    gender = models.CharField(max_length=1, choices=Gender.choices)
    date_of_birth = models.DateField()
    birth_certificate_number = models.CharField(max_length=20, blank=True)
    
    # Photo
    photo = models.ImageField(upload_to='student_photos/', blank=True, null=True)
    
    # Current class (updated each term/year)
    current_class = models.ForeignKey(
        'academics.Class', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='students'
    )
    
    # Parent/Guardian relationships
    parents = models.ManyToManyField(Parent, through='StudentParent', related_name='children')
    
    # Medical info
    blood_group = models.CharField(max_length=5, blank=True)
    medical_conditions = models.TextField(blank=True, help_text='Allergies, chronic conditions, etc.')
    emergency_contact_name = models.CharField(max_length=100, blank=True)
    emergency_contact_phone = models.CharField(max_length=15, blank=True)
    
    # Previous school
    previous_school = models.CharField(max_length=100, blank=True)
    previous_class = models.CharField(max_length=20, blank=True)
    
    # Status
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('graduated', 'Graduated'),
        ('transferred', 'Transferred'),
        ('suspended', 'Suspended'),
        ('expelled', 'Expelled'),
        ('withdrawn', 'Withdrawn'),
        ('inactive', 'Inactive'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    status_date = models.DateTimeField(
        null=True, blank=True,
        help_text="Date when the status was last changed"
    )
    status_reason = models.TextField(
        blank=True,
        help_text="Reason for status change"
    )
    
    # Special needs
    has_special_needs = models.BooleanField(default=False)
    special_needs_details = models.TextField(blank=True)
    
    # Transport
    uses_school_transport = models.BooleanField(default=False)
    transport_route = models.ForeignKey(
        'transport.TransportRoute',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='students',
    )
    transport_pickup_person = models.CharField(
        max_length=100, blank=True,
        help_text="Person authorized to pick up the student from the bus"
    )
    
    # Government/School Identifiers
    upi_number = models.CharField(
        max_length=30, blank=True,
        help_text="Unique Pupil Identifier (NEMIS/Ministry of Education)"
    )
    assessment_number = models.CharField(
        max_length=30, blank=True,
        help_text="Assessment/Examination number"
    )
    
    # Residence
    residence = models.CharField(
        max_length=100, blank=True,
        help_text="Student's residence area/estate"
    )
    
    credit_balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Positive = owes money (debt), Negative = has credit (prepayment)"
    )
    
    # Frozen balance fields - set at term start (Excel import), never change during the term
    # Used by dashboard for consistent reporting
    balance_bf_original = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Frozen debt from previous term at term start (positive value). Never changes during the term."
    )
    
    prepayment_original = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Frozen prepayment from previous term at term start (positive value). Never changes during the term."
    )

    outstanding_balance = models.DecimalField(
    max_digits=12,
    decimal_places=2,
    default=Decimal("0.00"),
    help_text="Sum of balances of all unpaid, active invoices"
    )


    class Meta:
        db_table = 'students'
        ordering = ['admission_number']
        indexes = [
            models.Index(fields=['admission_number']),
            models.Index(fields=['current_class', 'status']),
            models.Index(fields=['last_name', 'first_name']),
        ]

    def __str__(self):
        adm_num = self.admission_number or "N/A"
        return f"{adm_num} - {self.full_name}"

    @property
    def full_name(self):
        names = [self.first_name, self.middle_name, self.last_name]
        return ' '.join(n for n in names if n)

    @property
    def age(self):
        from datetime import date
        today = date.today()
        return today.year - self.date_of_birth.year - (
            (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
        )

    @property
    def primary_parent(self):
        """Get the primary parent/guardian."""
        sp = self.student_parents.filter(is_primary=True).select_related("parent").first()
        if sp:
            return sp.parent

        sp_any = self.student_parents.select_related("parent").first()
        return sp_any.parent if sp_any else None



    def recompute_outstanding_balance(self):
        total = self.invoices.filter(
            status__in=[
                InvoiceStatus.OVERDUE,
                InvoiceStatus.PARTIALLY_PAID
            ],
            is_active=True
        ).aggregate(
            total=Sum('balance')
        )['total'] or Decimal('0.00')

        self.outstanding_balance = total + student.balance_bf_original
        self.save(update_fields=['outstanding_balance'])


    def save(self, *args, **kwargs):
        """Override save to auto-generate admission_number if not provided."""
        # Auto-generate admission_number if not set
        if not self.admission_number:
            from .services import StudentService
            self.admission_number = StudentService.generate_admission_number()
        super().save(*args, **kwargs)

class StudentParent(models.Model):
    """
    Through model for Student-Parent relationship.
    Allows specifying relationship type and primary contact.
    """
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='student_parents')
    parent = models.ForeignKey(Parent, on_delete=models.CASCADE, related_name='parent_students')
    relationship = models.CharField(max_length=20, choices=Parent.RELATIONSHIP_CHOICES)
    is_primary = models.BooleanField(default=False)  # Primary contact for this student
    is_emergency_contact = models.BooleanField(default=False)
    can_pickup = models.BooleanField(default=True)  # Authorized to pick up student
    receives_notifications = models.BooleanField(default=True)

    class Meta:
        db_table = 'student_parents'
        unique_together = ['student', 'parent']

    def __str__(self):
        return f"{self.parent.full_name} → {self.student.full_name} ({self.relationship})"


class StudentDocument(BaseModel):
    """
    Documents uploaded for a student (birth cert, transfer letter, etc.)
    """
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='documents')
    
    DOCUMENT_TYPES = [
        ('birth_certificate', 'Birth Certificate'),
        ('transfer_letter', 'Transfer Letter'),
        ('report_card', 'Previous Report Card'),
        ('medical_report', 'Medical Report'),
        ('passport_photo', 'Passport Photo'),
        ('immunization', 'Immunization Record'),
        ('other', 'Other'),
    ]
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPES)
    title = models.CharField(max_length=100)
    file = models.FileField(upload_to='student_documents/')
    description = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        db_table = 'student_documents'

    def __str__(self):
        return f"{self.student.admission_number} - {self.title}"


class DisciplineRecord(BaseModel):
    """
    Track student discipline and behavior (per SRS FR-SM-005).
    """
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='discipline_records')
    
    INCIDENT_TYPES = [
        ('minor', 'Minor Infraction'),
        ('major', 'Major Infraction'),
        ('positive', 'Positive Behavior'),
        ('warning', 'Warning'),
        ('suspension', 'Suspension'),
    ]
    incident_type = models.CharField(max_length=20, choices=INCIDENT_TYPES)
    incident_date = models.DateField()
    description = models.TextField()
    action_taken = models.TextField(blank=True)
    reported_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='reported_incidents'
    )
    parent_notified = models.BooleanField(default=False)
    parent_notified_date = models.DateField(null=True, blank=True)
    follow_up_required = models.BooleanField(default=False)
    follow_up_notes = models.TextField(blank=True)

    class Meta:
        db_table = 'discipline_records'
        ordering = ['-incident_date']

    def __str__(self):
        return f"{self.student.admission_number} - {self.incident_type} - {self.incident_date}"


class MedicalRecord(BaseModel):
    """
    Student medical records (per SRS FR-SM-006).
    """
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='medical_records')
    record_date = models.DateField()
    
    RECORD_TYPES = [
        ('checkup', 'Health Checkup'),
        ('illness', 'Illness'),
        ('injury', 'Injury'),
        ('vaccination', 'Vaccination'),
        ('allergy', 'Allergy'),
        ('other', 'Other'),
    ]
    record_type = models.CharField(max_length=20, choices=RECORD_TYPES)
    description = models.TextField()
    treatment = models.TextField(blank=True)
    prescribed_medication = models.TextField(blank=True)
    doctor_name = models.CharField(max_length=100, blank=True)
    hospital_clinic = models.CharField(max_length=100, blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        db_table = 'medical_records'
        ordering = ['-record_date']

    def __str__(self):
        return f"{self.student.admission_number} - {self.record_type} - {self.record_date}"