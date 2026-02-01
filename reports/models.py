# reports/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.contrib.postgres.fields import JSONField  # If using Postgres; otherwise use models.JSONField on Django >=3.1

REPORT_TYPE_CHOICES = [
    ('invoice_summary', 'Invoice Summary'),
    ('collection_analysis', 'Fees Collection Analysis'),
    ('outstanding', 'Outstanding Balances'),
    ('transport', 'Transport Report'),
    ('transferred_students', 'Transferred Students Report'),
    ('admitted_students', 'Admitted Students Report'),
]

try:
    # Django >= 3.1
    JSONFieldImpl = models.JSONField
except AttributeError:
    # older versions with Postgres
    try:
        from django.contrib.postgres.fields import JSONField as JSONFieldImpl
    except Exception:
        JSONFieldImpl = None

class ReportRequest(models.Model):
    """
    Stores parameters for generated reports (helpful for audit/tracking).
    """
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='report_requests',
        null=True,
        blank=True,
        help_text="Organization this report request belongs to"
    )
    
    report_type = models.CharField(max_length=50, choices=REPORT_TYPE_CHOICES)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    academic_year = models.ForeignKey('academics.AcademicYear', on_delete=models.SET_NULL, null=True, blank=True)
    term = models.CharField(max_length=20, null=True, blank=True)
    params = (JSONFieldImpl(blank=True, null=True) if JSONFieldImpl is not None else models.TextField(blank=True, null=True))
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'reports_requests'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_report_type_display()} - {self.academic_year} {self.term} @ {self.created_at:%Y-%m-%d %H:%M}"