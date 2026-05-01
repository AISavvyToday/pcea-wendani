# academics/models.py
from decimal import Decimal

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from core.models import BaseModel, GradeLevel, TermChoices, AttendanceStatus, StreamChoices
from accounts.models import User


class AcademicYear(BaseModel):
    """
    Academic year configuration.
    e.g., 2024, 2025
    """
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='academic_years',
        null=True,
        blank=True,
        help_text="Organization this academic year belongs to"
    )
    
    year = models.PositiveIntegerField()  # e.g., 2025
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        db_table = 'academic_years'
        ordering = ['-year']
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'year'],
                name='unique_academic_year_per_organization',
            ),
        ]

    def __str__(self):
        return str(self.year)

    def save(self, *args, **kwargs):
        # Ensure only one current year per organization scope.
        if self.is_current:
            queryset = AcademicYear.objects.filter(is_current=True)
            if self.organization_id is None:
                queryset = queryset.filter(organization__isnull=True)
            else:
                queryset = queryset.filter(organization_id=self.organization_id)
            if self.pk:
                queryset = queryset.exclude(pk=self.pk)
            queryset.update(is_current=False)
        super().save(*args, **kwargs)


class Term(BaseModel):
    """
    Academic term within a year.
    Kenya has 3 terms per year.
    """
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='terms',
        null=True,
        blank=True,
        help_text="Organization this term belongs to"
    )
    
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, related_name='terms')
    term = models.CharField(max_length=10, choices=TermChoices.choices)
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)

    # Fee deadlines
    fee_deadline = models.DateField(null=True, blank=True)
    late_fee_start_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'terms'
        ordering = ['academic_year', 'term']
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'academic_year', 'term'],
                name='unique_term_per_organization_year',
            ),
        ]

    def __str__(self):
        return f"{self.academic_year.year} - {self.get_term_display()}"

    def save(self, *args, **kwargs):
        if self.is_current:
            queryset = Term.objects.filter(is_current=True)
            if self.organization_id is None:
                queryset = queryset.filter(organization__isnull=True)
            else:
                queryset = queryset.filter(organization_id=self.organization_id)
            if self.pk:
                queryset = queryset.exclude(pk=self.pk)
            queryset.update(is_current=False)
        super().save(*args, **kwargs)


class TermTransitionLog(BaseModel):
    """Idempotency record for carrying balances from one term into another."""

    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='term_transition_logs',
        null=True,
        blank=True,
    )
    previous_term = models.ForeignKey(
        Term,
        on_delete=models.PROTECT,
        related_name='outgoing_transition_logs',
    )
    new_term = models.ForeignKey(
        Term,
        on_delete=models.PROTECT,
        related_name='incoming_transition_logs',
    )
    executed_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='term_transitions_executed',
    )
    dry_run = models.BooleanField(default=False)
    stats = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'term_transition_logs'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'previous_term', 'new_term'],
                condition=models.Q(dry_run=False),
                name='unique_executed_term_transition_per_org',
            ),
        ]

    def __str__(self):
        return f"{self.previous_term} -> {self.new_term}"


class Department(BaseModel):
    """
    Academic departments (for staff organization).
    e.g., Languages, Sciences, Humanities
    """
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='departments',
        null=True,
        blank=True,
        help_text="Organization this department belongs to"
    )
    
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True)
    head = models.ForeignKey(
        'Staff', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='headed_departments'
    )
    description = models.TextField(blank=True)

    class Meta:
        db_table = 'departments'
        ordering = ['name']

    def __str__(self):
        return self.name


class Staff(BaseModel):
    """
    Staff members (teachers, admin, support staff).
    """
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='staff',
        null=True,
        blank=True,
        help_text="Organization this staff member belongs to"
    )
    
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='staff_profile'
    )

    # Employment info
    staff_number = models.CharField(max_length=20, unique=True)  # e.g., PWA-T-001

    STAFF_TYPES = [
        ('teaching', 'Teaching Staff'),
        ('admin', 'Administrative Staff'),
        ('support', 'Support Staff'),
    ]
    staff_type = models.CharField(max_length=20, choices=STAFF_TYPES)

    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='staff_members'
    )

    # Personal info
    id_number = models.CharField(max_length=20, unique=True)
    tsc_number = models.CharField(max_length=20, blank=True)  # Teachers Service Commission
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, choices=[('M', 'Male'), ('F', 'Female')], blank=True)

    # Contact
    phone_number = models.CharField(max_length=15)
    address = models.TextField(blank=True)

    # Employment details
    date_joined = models.DateField()
    employment_type = models.CharField(
        max_length=20,
        choices=[('permanent', 'Permanent'), ('contract', 'Contract'), ('parttime', 'Part-time')],
        default='permanent'
    )

    # Qualifications
    qualifications = models.TextField(blank=True)
    specialization = models.CharField(max_length=100, blank=True)

    # Status
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('on_leave', 'On Leave'),
        ('suspended', 'Suspended'),
        ('terminated', 'Terminated'),
        ('retired', 'Retired'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')

    class Meta:
        db_table = 'staff'
        verbose_name_plural = 'Staff'
        ordering = ['staff_number']

    def __str__(self):
        return f"{self.staff_number} - {self.user.full_name}"


class Class(BaseModel):
    """
    Class/Grade definition.
    e.g., Grade 1A, Grade 1B, Grade 7 Blue
    """
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='classes',
        null=True,
        blank=True,
        help_text="Organization this class belongs to"
    )
    
    name = models.CharField(max_length=50)  # e.g., "Grade 1A", "Grade 7 Blue"
    grade_level = models.CharField(max_length=20, choices=GradeLevel.choices)
    stream = models.CharField(max_length=10, choices=StreamChoices.choices, default=StreamChoices.EAST)

    # Class teacher
    class_teacher = models.ForeignKey(
        Staff, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='classes_taught'
    )

    # Room
    room = models.CharField(max_length=20, blank=True)

    # Academic year (classes are recreated each year)
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.CASCADE, related_name='classes'
    )

    class Meta:
        db_table = 'classes'
        verbose_name_plural = 'Classes'
        unique_together = ['name', 'academic_year']
        ordering = ['grade_level', 'stream']

    def __str__(self):
        year_str = str(self.academic_year.year)
        if self.name and year_str in self.name:
            return self.name
        return f"{self.name} {year_str}".strip()

    @property
    def student_count(self):
        return self.students.filter(status='active').count()


class Subject(BaseModel):
    """
    Subject catalog.
    Aligned with CBC curriculum.
    """
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='subjects',
        null=True,
        blank=True,
        help_text="Organization this subject belongs to"
    )
    
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=10, unique=True)

    # Which grade levels this subject applies to
    grade_levels = models.JSONField(default=list)  # e.g., ['grade_1', 'grade_2', 'grade_3']

    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='subjects'
    )

    # Subject type
    SUBJECT_TYPES = [
        ('core', 'Core Subject'),
        ('elective', 'Elective'),
        ('activity', 'Co-curricular Activity'),
    ]
    subject_type = models.CharField(max_length=20, choices=SUBJECT_TYPES, default='core')

    description = models.TextField(blank=True)

    # Grading
    max_marks = models.PositiveIntegerField(default=100)
    pass_marks = models.PositiveIntegerField(default=40)

    class Meta:
        db_table = 'subjects'
        ordering = ['name']

    def __str__(self):
        return f"{self.code} - {self.name}"


class ClassSubject(BaseModel):
    """
    Links subjects to classes with assigned teachers.
    """
    class_obj = models.ForeignKey(Class, on_delete=models.CASCADE, related_name='class_subjects')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='class_subjects')
    teacher = models.ForeignKey(
        Staff, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='subject_assignments'
    )
    periods_per_week = models.PositiveIntegerField(default=5)

    class Meta:
        db_table = 'class_subjects'
        unique_together = ['class_obj', 'subject']

    def __str__(self):
        return f"{self.class_obj.name} - {self.subject.name}"


class Exam(BaseModel):
    """
    Examination definition.
    """
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='exams',
        null=True,
        blank=True,
        help_text="Organization this exam belongs to"
    )
    
    name = models.CharField(max_length=100)  # e.g., "Mid-Term Exam", "End of Term Exam"
    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name='exams')

    EXAM_TYPES = [
        ('cat', 'Continuous Assessment Test'),
        ('midterm', 'Mid-Term Exam'),
        ('endterm', 'End of Term Exam'),
        ('mock', 'Mock Exam'),
        ('assignment', 'Assignment'),
    ]
    exam_type = models.CharField(max_length=20, choices=EXAM_TYPES)

    start_date = models.DateField()
    end_date = models.DateField()

    # Weighting for final grade calculation
    weight_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=100,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )

    # Applicable classes
    classes = models.ManyToManyField(Class, related_name='exams')

    is_published = models.BooleanField(default=False)  # Results visible to parents

    class Meta:
        db_table = 'exams'
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.name} - {self.term}"


class Grade(BaseModel):
    """
    Student grades/marks for exams.
    """
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='grades',
        null=True,
        blank=True,
        help_text="Organization this grade belongs to"
    )
    
    student = models.ForeignKey(
        'students.Student', on_delete=models.CASCADE, related_name='grades'
    )
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='grades')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='grades')

    marks = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0)]
    )

    # Calculated grade
    grade_letter = models.CharField(max_length=2, blank=True)  # A, B+, B, etc.
    points = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)

    # Teacher remarks
    remarks = models.TextField(blank=True)

    # Entry tracking
    entered_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='grades_entered'
    )
    entered_at = models.DateTimeField(auto_now_add=True)
    modified_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='grades_modified'
    )

    class Meta:
        db_table = 'grades'
        unique_together = ['student', 'exam', 'subject']
        indexes = [
            models.Index(fields=['student', 'exam']),
            models.Index(fields=['exam', 'subject']),
        ]

    def __str__(self):
        return f"{self.student.admission_number} - {self.subject.code} - {self.marks}"

    def save(self, *args, **kwargs):
        # Auto-calculate grade letter based on marks
        self.grade_letter = self.calculate_grade_letter()
        self.points = self.calculate_points()
        super().save(*args, **kwargs)

    def calculate_grade_letter(self):
        """CBC grading system."""
        if self.marks >= 80:
            return 'EE'  # Exceeding Expectations
        elif self.marks >= 65:
            return 'ME'  # Meeting Expectations
        elif self.marks >= 50:
            return 'AE'  # Approaching Expectations
        elif self.marks >= 40:
            return 'BE'  # Below Expectations
        else:
            return 'BE'

    def calculate_points(self):
        """Points for ranking."""
        if self.marks >= 80:
            return 4
        elif self.marks >= 65:
            return 3
        elif self.marks >= 50:
            return 2
        elif self.marks >= 40:
            return 1
        return 0


class Attendance(BaseModel):
    """
    Daily student attendance tracking.
    """
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='attendance_records',
        null=True,
        blank=True,
        help_text="Organization this attendance record belongs to"
    )
    
    student = models.ForeignKey(
        'students.Student', on_delete=models.CASCADE, related_name='attendance_records'
    )
    date = models.DateField()
    class_obj = models.ForeignKey(Class, on_delete=models.CASCADE, related_name='attendance_records')

    status = models.CharField(max_length=10, choices=AttendanceStatus.choices)

    # Time tracking (for late arrivals)
    arrival_time = models.TimeField(null=True, blank=True)
    departure_time = models.TimeField(null=True, blank=True)

    remarks = models.TextField(blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        db_table = 'attendance'
        unique_together = ['student', 'date']
        indexes = [
            models.Index(fields=['date', 'class_obj']),
            models.Index(fields=['student', 'date']),
        ]

    def __str__(self):
        return f"{self.student.admission_number} - {self.date} - {self.status}"


class Timetable(BaseModel):
    """
    Class timetable entries.
    """
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='timetable_entries',
        null=True,
        blank=True,
        help_text="Organization this timetable entry belongs to"
    )
    
    class_obj = models.ForeignKey(Class, on_delete=models.CASCADE, related_name='timetable_entries')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='timetable_entries')
    teacher = models.ForeignKey(Staff, on_delete=models.SET_NULL, null=True, related_name='timetable_entries')

    DAY_CHOICES = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
    ]
    day_of_week = models.PositiveSmallIntegerField(choices=DAY_CHOICES)

    start_time = models.TimeField()
    end_time = models.TimeField()

    room = models.CharField(max_length=20, blank=True)

    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name='timetable_entries')

    class Meta:
        db_table = 'timetables'
        ordering = ['day_of_week', 'start_time']
        indexes = [
            models.Index(fields=['class_obj', 'day_of_week']),
            models.Index(fields=['teacher', 'day_of_week']),
        ]

    def __str__(self):
        return f"{self.class_obj.name} - {self.get_day_of_week_display()} - {self.subject.name}"


# ============== REPORT CARDS ==============

class ReportCard(BaseModel):
    """
    Student report card for a term.
    """
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='report_cards',
        null=True,
        blank=True,
        help_text="Organization this report card belongs to"
    )
    
    student = models.ForeignKey(
        'students.Student', on_delete=models.CASCADE, related_name='report_cards'
    )
    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name='report_cards')
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, related_name='report_cards')
    class_obj = models.ForeignKey(Class, on_delete=models.SET_NULL, null=True, related_name='report_cards')
    
    # Overall performance
    overall_grade = models.CharField(max_length=10, blank=True, help_text="Overall grade (e.g., A, B+, B)")
    position = models.PositiveIntegerField(null=True, blank=True, help_text="Class position")
    total_marks = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))
    average_marks = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    # Comments
    teacher_comments = models.TextField(blank=True)
    principal_comments = models.TextField(blank=True)
    
    # Status
    is_published = models.BooleanField(default=False, help_text="Published report cards are visible to parents")
    published_at = models.DateTimeField(null=True, blank=True)
    
    # Generated by
    generated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='report_cards_generated')
    
    class Meta:
        db_table = 'report_cards'
        unique_together = ['student', 'term']
        ordering = ['-academic_year__year', '-term', 'student__last_name']
    
    def __str__(self):
        return f"{self.student.admission_number} - {self.term} - {self.overall_grade}"


class ReportCardItem(BaseModel):
    """
    Individual subject entry on a report card.
    """
    report_card = models.ForeignKey(ReportCard, on_delete=models.CASCADE, related_name='items')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='report_card_items')
    
    marks = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    grade = models.CharField(max_length=10, blank=True, help_text="Grade letter (e.g., A, B+, B)")
    remarks = models.TextField(blank=True)
    
    class Meta:
        db_table = 'report_card_items'
        unique_together = ['report_card', 'subject']
        ordering = ['subject__name']
    
    def __str__(self):
        return f"{self.report_card.student.admission_number} - {self.subject.name} - {self.marks}"


# ============== LEAVE MANAGEMENT ==============

class LeaveApplication(BaseModel):
    """
    Staff leave application.
    """
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='leave_applications',
        null=True,
        blank=True,
        help_text="Organization this leave application belongs to"
    )
    
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name='leave_applications')
    
    LEAVE_TYPES = [
        ('annual', 'Annual Leave'),
        ('sick', 'Sick Leave'),
        ('casual', 'Casual Leave'),
        ('maternity', 'Maternity Leave'),
        ('paternity', 'Paternity Leave'),
        ('compassionate', 'Compassionate Leave'),
        ('study', 'Study Leave'),
        ('other', 'Other'),
    ]
    leave_type = models.CharField(max_length=20, choices=LEAVE_TYPES)
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Approval
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='leave_applications_approved'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    
    class Meta:
        db_table = 'leave_applications'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.staff.staff_number} - {self.get_leave_type_display()} - {self.status}"
