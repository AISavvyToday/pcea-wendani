# payroll/models.py
"""
Payroll management models for staff salary, deductions, allowances, and payslips.
"""

from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator
from core.models import BaseModel
from academics.models import Staff


class SalaryStructure(BaseModel):
    """Salary structure/grade definition."""
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='salary_structures',
        null=True,
        blank=True,
        help_text="Organization this salary structure belongs to"
    )
    
    name = models.CharField(max_length=100, help_text="Grade name, e.g., 'T-Scale 1', 'Administrative Grade 1'")
    code = models.CharField(max_length=20, unique=True, help_text="Unique code for this grade")
    basic_salary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Basic monthly salary"
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'salary_structures'
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} - KSH {self.basic_salary:,.2f}"


class Allowance(BaseModel):
    """Allowance types (housing, transport, medical, etc.)."""
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='allowances',
        null=True,
        blank=True,
        help_text="Organization this allowance belongs to"
    )
    
    ALLOWANCE_TYPES = [
        ('housing', 'Housing Allowance'),
        ('transport', 'Transport Allowance'),
        ('medical', 'Medical Allowance'),
        ('lunch', 'Lunch Allowance'),
        ('overtime', 'Overtime'),
        ('bonus', 'Bonus'),
        ('other', 'Other'),
    ]
    
    name = models.CharField(max_length=100)
    allowance_type = models.CharField(max_length=20, choices=ALLOWANCE_TYPES)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Fixed amount (0 if percentage-based)"
    )
    is_percentage = models.BooleanField(
        default=False,
        help_text="If True, amount is percentage of basic salary"
    )
    percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Percentage of basic salary (if is_percentage=True)"
    )
    is_taxable = models.BooleanField(default=True, help_text="Whether allowance is subject to tax")
    description = models.TextField(blank=True)
    
    class Meta:
        db_table = 'allowances'
        ordering = ['name']
    
    def __str__(self):
        if self.is_percentage:
            return f"{self.name} - {self.percentage}%"
        return f"{self.name} - KSH {self.amount:,.2f}"


class Deduction(BaseModel):
    """Deduction types (NHIF, NSSF, PAYE, loans, etc.)."""
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='deductions',
        null=True,
        blank=True,
        help_text="Organization this deduction belongs to"
    )
    
    DEDUCTION_TYPES = [
        ('nhif', 'NHIF'),
        ('nssf', 'NSSF'),
        ('paye', 'PAYE'),
        ('loan', 'Loan'),
        ('advance', 'Salary Advance'),
        ('other', 'Other'),
    ]
    
    name = models.CharField(max_length=100)
    deduction_type = models.CharField(max_length=20, choices=DEDUCTION_TYPES)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Fixed amount (0 if percentage-based or calculated)"
    )
    is_percentage = models.BooleanField(
        default=False,
        help_text="If True, amount is percentage of gross salary"
    )
    percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Percentage of gross salary (if is_percentage=True)"
    )
    is_calculated = models.BooleanField(
        default=False,
        help_text="If True, deduction is calculated based on brackets (e.g., NHIF, PAYE)"
    )
    description = models.TextField(blank=True)
    
    class Meta:
        db_table = 'deductions'
        ordering = ['name']
    
    def __str__(self):
        if self.is_calculated:
            return f"{self.name} (Calculated)"
        elif self.is_percentage:
            return f"{self.name} - {self.percentage}%"
        return f"{self.name} - KSH {self.amount:,.2f}"


class StaffSalary(BaseModel):
    """Links staff to salary structure with allowances and deductions."""
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='staff_salaries',
        null=True,
        blank=True,
        help_text="Organization this staff salary belongs to"
    )
    
    staff = models.OneToOneField(
        Staff,
        on_delete=models.CASCADE,
        related_name='salary',
        help_text="Staff member"
    )
    salary_structure = models.ForeignKey(
        SalaryStructure,
        on_delete=models.PROTECT,
        related_name='staff_salaries',
        help_text="Salary structure/grade"
    )
    allowances = models.ManyToManyField(Allowance, blank=True, related_name='staff_salaries')
    deductions = models.ManyToManyField(Deduction, blank=True, related_name='staff_salaries')
    effective_date = models.DateField(help_text="Date when this salary becomes effective")
    end_date = models.DateField(null=True, blank=True, help_text="Date when this salary ends (if applicable)")
    notes = models.TextField(blank=True)
    
    class Meta:
        db_table = 'staff_salaries'
        ordering = ['-effective_date']
    
    def __str__(self):
        return f"{self.staff.user.full_name} - {self.salary_structure.name}"


class PayrollPeriod(BaseModel):
    """Monthly payroll periods."""
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='payroll_periods',
        null=True,
        blank=True,
        help_text="Organization this payroll period belongs to"
    )
    
    period_month = models.PositiveIntegerField(help_text="Month (1-12)")
    period_year = models.PositiveIntegerField(help_text="Year (e.g., 2025)")
    start_date = models.DateField()
    end_date = models.DateField()
    is_closed = models.BooleanField(default=False, help_text="Whether payroll is finalized")
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='closed_payrolls'
    )
    
    class Meta:
        db_table = 'payroll_periods'
        unique_together = ['organization', 'period_month', 'period_year']
        ordering = ['-period_year', '-period_month']
    
    def __str__(self):
        from calendar import month_name
        return f"{month_name[self.period_month]} {self.period_year}"


class PayrollEntry(BaseModel):
    """Individual payroll entry for each staff member per period."""
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='payroll_entries',
        null=True,
        blank=True,
        help_text="Organization this payroll entry belongs to"
    )
    
    payroll_period = models.ForeignKey(
        PayrollPeriod,
        on_delete=models.CASCADE,
        related_name='entries',
        help_text="Payroll period"
    )
    staff = models.ForeignKey(
        Staff,
        on_delete=models.PROTECT,
        related_name='payroll_entries',
        help_text="Staff member"
    )
    staff_salary = models.ForeignKey(
        StaffSalary,
        on_delete=models.PROTECT,
        related_name='payroll_entries',
        help_text="Staff salary configuration"
    )
    
    # Calculated amounts
    basic_salary = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_allowances = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    gross_salary = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_deductions = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    net_salary = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Breakdown
    nhif = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    nssf_employee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    nssf_employer = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    paye = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    other_deductions = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    notes = models.TextField(blank=True)
    
    class Meta:
        db_table = 'payroll_entries'
        unique_together = ['payroll_period', 'staff']
        ordering = ['staff__staff_number']
    
    def __str__(self):
        return f"{self.staff.user.full_name} - {self.payroll_period}"


class PayrollAllowance(BaseModel):
    """Allowances applied to a payroll entry."""
    payroll_entry = models.ForeignKey(
        PayrollEntry,
        on_delete=models.CASCADE,
        related_name='allowance_items',
        help_text="Payroll entry"
    )
    allowance = models.ForeignKey(
        Allowance,
        on_delete=models.PROTECT,
        related_name='payroll_allowances',
        help_text="Allowance type"
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Calculated allowance amount for this period"
    )
    
    class Meta:
        db_table = 'payroll_allowances'
        unique_together = ['payroll_entry', 'allowance']
    
    def __str__(self):
        return f"{self.allowance.name} - KSH {self.amount:,.2f}"


class PayrollDeduction(BaseModel):
    """Deductions applied to a payroll entry."""
    payroll_entry = models.ForeignKey(
        PayrollEntry,
        on_delete=models.CASCADE,
        related_name='deduction_items',
        help_text="Payroll entry"
    )
    deduction = models.ForeignKey(
        Deduction,
        on_delete=models.PROTECT,
        related_name='payroll_deductions',
        help_text="Deduction type"
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Calculated deduction amount for this period"
    )
    
    class Meta:
        db_table = 'payroll_deductions'
        unique_together = ['payroll_entry', 'deduction']
    
    def __str__(self):
        return f"{self.deduction.name} - KSH {self.amount:,.2f}"


class Payslip(BaseModel):
    """Generated payslip records."""
    # Multi-tenancy: Organization
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.PROTECT,
        related_name='payslips',
        null=True,
        blank=True,
        help_text="Organization this payslip belongs to"
    )
    
    payroll_entry = models.OneToOneField(
        PayrollEntry,
        on_delete=models.CASCADE,
        related_name='payslip',
        help_text="Payroll entry"
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    generated_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='generated_payslips'
    )
    pdf_file = models.FileField(upload_to='payslips/', null=True, blank=True)
    is_downloaded = models.BooleanField(default=False)
    downloaded_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'payslips'
        ordering = ['-generated_at']
    
    def __str__(self):
        return f"Payslip - {self.payroll_entry.staff.user.full_name} - {self.payroll_entry.payroll_period}"
