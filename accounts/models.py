# accounts/models.py

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from core.models import BaseModel, UserRole

from datetime import timedelta

class UserManager(BaseUserManager):
    """Custom user manager."""
    
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', UserRole.SUPER_ADMIN)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom User model for PWASMS.
    - Uses email as username
    - Supports role-based access control
    - Links to Staff, Parent, or Student profile
    """
    id = models.UUIDField(primary_key=True, default=__import__('uuid').uuid4, editable=False)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    
    # Profile info
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    profile_photo = models.ImageField(upload_to='profile_photos/', blank=True, null=True)
    
    # Role-based access
    role = models.CharField(max_length=20, choices=UserRole.choices, default=UserRole.PARENT)
    
    # Status flags
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)  # Can access admin site
    is_verified = models.BooleanField(default=False)  # Email/phone verified
    
    # Security
    failed_login_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    password_changed_at = models.DateTimeField(null=True, blank=True)
    must_change_password = models.BooleanField(default=False)
    
    # Timestamps
    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)
    
    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.email})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def is_locked(self):
        """Check if account is locked due to failed login attempts."""
        if self.locked_until and self.locked_until > timezone.now():
            return True
        return False

    def record_failed_login(self):
        """Record failed login attempt, lock after 5 failures (per SRS NFR-SEC-007)."""
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= 5:
            self.locked_until = timezone.now() + timedelta(minutes=30)
        self.save(update_fields=["failed_login_attempts", "locked_until"])

    def reset_failed_logins(self):
        """Reset failed login counter on successful login."""
        self.failed_login_attempts = 0
        self.locked_until = None
        self.save(update_fields=['failed_login_attempts', 'locked_until'])

    def get_short_name(self):
        """Return first name."""
        return self.first_name

    def get_full_name(self):
        """Return full name."""
        return f"{self.first_name} {self.last_name}".strip()


class AuditLog(models.Model):
    """
    Audit trail for all significant actions (per SRS NFR-SEC-004).
    Tracks who did what, when, and from where.
    """
    id = models.UUIDField(primary_key=True, default=__import__('uuid').uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='audit_logs')
    action = models.CharField(max_length=100)  # e.g., 'student.create', 'payment.process'
    model_name = models.CharField(max_length=50, blank=True)
    object_id = models.CharField(max_length=50, blank=True)
    changes = models.JSONField(default=dict, blank=True)  # Before/after values
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_logs'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['model_name', 'object_id']),
            models.Index(fields=['action', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.user} - {self.action} - {self.timestamp}"