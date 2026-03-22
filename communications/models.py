# communications/models.py
"""
Communications module models for announcements, SMS, and email notifications.
"""

from django.db import models
from django.utils import timezone
from core.models import BaseModel
from accounts.models import User


class Announcement(BaseModel):
    """
    School announcements that can be sent via SMS and/or email.
    """
    TARGET_AUDIENCE_CHOICES = [
        ('all', 'All Users'),
        ('parents', 'Parents Only'),
        ('teachers', 'Teachers Only'),
        ('students', 'Students Only'),
        ('staff', 'Staff Only'),
    ]
    
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='announcements',
        null=True,
        blank=True,
        help_text="Organization this announcement belongs to"
    )
    
    title = models.CharField(max_length=200)
    message = models.TextField()
    target_audience = models.CharField(
        max_length=20,
        choices=TARGET_AUDIENCE_CHOICES,
        default='all'
    )
    
    # Send options
    send_sms = models.BooleanField(default=False, help_text="Send via SMS")
    send_email = models.BooleanField(default=False, help_text="Send via Email")
    
    # Status
    sent_at = models.DateTimeField(null=True, blank=True, help_text="When announcement was sent")
    is_sent = models.BooleanField(default=False)
    
    # Metadata
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='announcements_created'
    )
    
    # Statistics
    sms_count = models.IntegerField(default=0, help_text="Number of SMS sent")
    email_count = models.IntegerField(default=0, help_text="Number of emails sent")
    
    class Meta:
        db_table = 'announcements'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} - {self.get_target_audience_display()}"


class SMSNotification(BaseModel):
    """
    Individual SMS notification record.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]
    
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='sms_notifications',
        null=True,
        blank=True,
        help_text="Organization this SMS notification belongs to"
    )
    
    recipient_phone = models.CharField(max_length=15, help_text="Phone number in format 254XXXXXXXXX")
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Tracking
    sent_at = models.DateTimeField(null=True, blank=True)
    message_id = models.CharField(max_length=100, blank=True, help_text="Central SMS service message identifier")
    error_message = models.TextField(blank=True, help_text="Error message if sending failed")
    
    # Purpose/Context
    purpose = models.CharField(
        max_length=100,
        blank=True,
        help_text="Purpose of SMS (e.g., 'fee_reminder', 'announcement', 'attendance_alert')"
    )
    
    # Optional link to related objects
    related_student = models.ForeignKey(
        'students.Student',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sms_notifications'
    )
    related_announcement = models.ForeignKey(
        Announcement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sms_notifications'
    )
    
    # User who triggered (if applicable)
    triggered_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sms_triggered'
    )
    
    class Meta:
        db_table = 'sms_notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['recipient_phone', 'created_at']),
        ]
    
    def __str__(self):
        return f"SMS to {self.recipient_phone} - {self.status}"


class EmailNotification(BaseModel):
    """
    Individual email notification record.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]
    
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='email_notifications',
        null=True,
        blank=True,
        help_text="Organization this email notification belongs to"
    )
    
    recipient_email = models.EmailField()
    subject = models.CharField(max_length=200)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Tracking
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, help_text="Error message if sending failed")
    
    # Purpose/Context
    purpose = models.CharField(
        max_length=100,
        blank=True,
        help_text="Purpose of email (e.g., 'fee_reminder', 'announcement')"
    )
    
    # Optional link to related objects
    related_student = models.ForeignKey(
        'students.Student',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='email_notifications'
    )
    related_announcement = models.ForeignKey(
        Announcement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='email_notifications'
    )
    
    # User who triggered (if applicable)
    triggered_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='emails_triggered'
    )
    
    class Meta:
        db_table = 'email_notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['recipient_email', 'created_at']),
        ]
    
    def __str__(self):
        return f"Email to {self.recipient_email} - {self.status}"


class NotificationTemplate(BaseModel):
    """
    Reusable templates for SMS and email notifications.
    """
    TEMPLATE_TYPE_CHOICES = [
        ('sms', 'SMS Template'),
        ('email', 'Email Template'),
    ]
    
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='notification_templates',
        null=True,
        blank=True,
        help_text="Organization this template belongs to"
    )
    
    name = models.CharField(max_length=100, help_text="Template name (e.g., 'Fee Reminder', 'Attendance Alert')")
    template_type = models.CharField(max_length=20, choices=TEMPLATE_TYPE_CHOICES)
    
    # For SMS: just message text
    # For Email: subject and message
    subject = models.CharField(max_length=200, blank=True, help_text="Email subject (for email templates)")
    template_text = models.TextField(help_text="Template text with variables like {{student_name}}, {{amount}}, etc.")
    
    # Variables documentation
    variables = models.JSONField(
        default=list,
        blank=True,
        help_text="List of available variables (e.g., ['student_name', 'amount', 'due_date'])"
    )
    
    description = models.TextField(blank=True, help_text="Description of when to use this template")
    
    class Meta:
        db_table = 'notification_templates'
        ordering = ['name']
        unique_together = ['organization', 'name', 'template_type']
    
    def __str__(self):
        return f"{self.name} ({self.get_template_type_display()})"
