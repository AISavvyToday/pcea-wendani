# File: payments/services/resolution.py
# ============================================================
# RATIONALE: Handle resolution of bill numbers to students/invoices
# - Resolves admission numbers to Student records
# - Extracts admission numbers from Co-op narration fields
# - Finds active invoices for students
# ============================================================

import re
import logging
from typing import Optional, Tuple
from django.db.models import Q

from students.models import Student
from finance.models import Invoice
from payments.exceptions import StudentNotFoundError, BillNotFoundError

logger = logging.getLogger(__name__)


class ResolutionService:
    """Service for resolving bill numbers to students and invoices."""
    
    # Pattern for PCEA Wendani admission numbers: PWA followed by digits
    # e.g., PWA2254, PWA1001, etc.
    ADMISSION_PATTERN = re.compile(r'(PWA\d+|\d{4})', re.IGNORECASE)  # Add \d{4} for 4-digit numbers

    @staticmethod
    def resolve_bill_number(bill_number: str) -> Tuple[Student, Optional[Invoice]]:
        """
        Resolve a bill number to a student and optionally an invoice.

        The bill number can be:
        1. Student admission number (e.g., "2284" or "PWA2284")
        2. Invoice number (e.g., INV-2025-00001)
        """
        if not bill_number:
            raise BillNotFoundError("Bill number is required")

        bill_number = bill_number.strip().upper()
        logger.info(f"Resolving bill number: {bill_number}")

        # Clean the bill number - remove PWA prefix if present
        clean_bill_number = bill_number
        if clean_bill_number.startswith('PWA'):
            clean_bill_number = clean_bill_number[3:]

        # Try to find by admission number (with PWA prefix)
        student = Student.objects.filter(
            admission_number__iexact=f"PWA{clean_bill_number}",
            is_active=True
        ).first()

        if not student:
            # Try exact match without PWA
            student = Student.objects.filter(
                admission_number__iexact=clean_bill_number,
                is_active=True
            ).first()

        if not student:
            # Try by numeric suffix
            student = Student.objects.filter(
                admission_number__endswith=clean_bill_number,
                is_active=True
            ).first()

        if student:
            logger.info(f"Found student by admission number: {student.admission_number}")
            # Get the most recent unpaid/partially paid invoice
            invoice = ResolutionService.get_active_invoice(student)
            return student, invoice

        # Try to find by invoice number (original logic)
        invoice = Invoice.objects.filter(
            invoice_number__iexact=bill_number,
            is_active=True
        ).select_related('student').first()

        if invoice:
            logger.info(f"Found invoice: {invoice.invoice_number} for student: {invoice.student.admission_number}")
            return invoice.student, invoice

        # If bill number looks like an admission number pattern, give specific error
        if re.match(r'^\d+$', clean_bill_number) and len(clean_bill_number) >= 3:
            raise StudentNotFoundError(f"Student with admission number {clean_bill_number} not found")

        raise BillNotFoundError(f"Bill number {bill_number} not found")
    
    @staticmethod
    def get_active_invoice(student: Student) -> Optional[Invoice]:
        """
        Get the most recent active (unpaid/partially paid) invoice for a student.
        
        Priority:
        1. Current term invoice with balance > 0
        2. Any invoice with balance > 0 (oldest first to clear arrears)
        """
        from academics.models import Term
        from core.models import InvoiceStatus
        
        # Try to get current term
        current_term = Term.objects.filter(is_current=True).first()
        
        if current_term:
            # First try current term invoice
            current_invoice = Invoice.objects.filter(
                student=student,
                term=current_term,
                is_active=True,
                balance__gt=0
            ).first()
            
            if current_invoice:
                return current_invoice
        
        # Fall back to any invoice with balance (oldest first)
        return Invoice.objects.filter(
            student=student,
            is_active=True,
            balance__gt=0
        ).exclude(
            status=InvoiceStatus.CANCELLED
        ).order_by('issue_date').first()

    @staticmethod
    def extract_admission_from_narration(narration_fields: dict) -> Optional[str]:
        """
        Extract admission number from Co-op Bank narration fields.

        Priority:
        1. Check Narration field for pattern #...~ (text between # and ~)
        2. Fallback to regex pattern matching across all narration fields

        Parents typically include the admission number in the payment narration.
        """
        narration = str(narration_fields.get('Narration', '')).strip()
        
        # Primary: Check Narration field for #...~ pattern
        if narration:
            # Pattern: # followed by text until ~
            hash_tilde_pattern = re.compile(r'#([^~]+)~')
            match = hash_tilde_pattern.search(narration)
            
            if match:
                extracted = match.group(1).strip()
                if extracted:
                    # Remove PWA prefix if present (for consistency with existing logic)
                    admission_number = extracted.upper()
                    if admission_number.startswith('PWA'):
                        admission_number = admission_number[3:]
                    logger.info(f"Extracted admission number from #...~ pattern in Narration: {admission_number}")
                    return admission_number
        
        # Fallback: Use existing regex pattern matching across all narration fields
        search_text = ' '.join([
            narration,
            str(narration_fields.get('CustMemoLine1', '')),
            str(narration_fields.get('CustMemoLine2', '')),
            str(narration_fields.get('CustMemoLine3', '')),
        ])

        logger.debug(f"Searching for admission number in: {search_text[:200]}")

        # Search for admission number pattern
        match = ResolutionService.ADMISSION_PATTERN.search(search_text)

        if match:
            admission_number = match.group(1).upper()
            # Extract just the numeric part if it has PWA prefix
            if admission_number.upper().startswith('PWA'):
                admission_number = admission_number[3:]  # Remove 'PWA' prefix
            logger.info(f"Extracted admission number from regex pattern: {admission_number}")
            return admission_number

        logger.warning(f"No admission number found in narration: {search_text[:100]}")
        return None

    @staticmethod
    def get_student_by_admission(admission_number: str) -> Optional[Student]:
        """Get student by admission number - handles both "PWA2284" and "2284" formats."""
        admission_number = admission_number.strip().upper()

        # If it starts with PWA, remove it for matching
        if admission_number.startswith('PWA'):
            admission_number = admission_number[3:]

        # First try exact match with PWA prefix
        student = Student.objects.filter(
            admission_number__iexact=f"PWA{admission_number}",
            is_active=True
        ).first()

        if student:
            return student

        # Try without PWA prefix (some entries might not have it)
        student = Student.objects.filter(
            admission_number__iexact=admission_number,
            is_active=True
        ).first()

        if student:
            return student

        # Try by numeric part only
        student = Student.objects.filter(
            admission_number__endswith=admission_number,
            is_active=True
        ).first()

        return student
    
    @staticmethod
    def calculate_outstanding_amount(student: Student) -> Tuple[float, str]:
        """
        Calculate total outstanding amount for a student.
        
        Returns:
            Tuple of (total_balance, description)
        """
        from django.db.models import Sum
        from core.models import InvoiceStatus
        
        # Sum all unpaid invoice balances
        result = Invoice.objects.filter(
            student=student,
            is_active=True,
            balance__gt=0
        ).exclude(
            status=InvoiceStatus.CANCELLED
        ).aggregate(
            total=Sum('balance')
        )
        
        total_balance = result['total'] or 0
        
        # Get count of unpaid invoices
        unpaid_count = Invoice.objects.filter(
            student=student,
            is_active=True,
            balance__gt=0
        ).exclude(
            status=InvoiceStatus.CANCELLED
        ).count()
        
        if unpaid_count == 0:
            description = "No outstanding balance"
        elif unpaid_count == 1:
            description = "Current term fees"
        else:
            description = f"Outstanding fees ({unpaid_count} invoices)"
        
        return float(total_balance), description

    @staticmethod
    def extract_phone_from_narration(narration_fields: dict) -> Optional[str]:
        """
        Extracts a phone number from various narration fields.
        Looks for common Kenyan mobile number patterns.
        """
        full_narration = " ".join(narration_fields.values()).upper()

        # Regex for common Kenyan mobile numbers (07..., +2547..., 2547...)
        # This pattern is quite broad and might need refinement based on actual data
        phone_pattern = re.compile(r'(?:(?:\+254|254|0)?(7\d{8}))')

        match = phone_pattern.search(full_narration)
        if match:
            # Return the 10-digit number starting with 7
            return f"254{match.group(1)}"
        return None