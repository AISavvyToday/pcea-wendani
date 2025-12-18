# finance/services.py
"""
Finance module services for invoice generation, payment processing, and reporting.
"""

from decimal import Decimal
from typing import List, Optional

from django.db import transaction
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta, date

from .models import (
    FeeStructure, FeeItem, Invoice, InvoiceItem,
     StudentDiscount
)

from payments.models import Payment, PaymentAllocation, BankTransaction
from students.models import Student
from academics.models import Term


class InvoiceService:
    """Service for invoice operations."""

    @staticmethod
    @transaction.atomic
    def generate_invoice(student, term, generated_by=None):
        """Generate invoice for a student for a term."""

        # Check if invoice already exists
        existing = Invoice.objects.filter(
            student=student,
            term=term
        ).exclude(status='cancelled').first()

        if existing:
            return existing, False

        # Find applicable fee structure
        grade_level = student.grade_level if hasattr(student, 'grade_level') else None
        if not grade_level and hasattr(student, 'current_class'):
            grade_level = student.current_class.grade_level if student.current_class else None

        fee_structure = FeeStructure.objects.filter(
            academic_year=term.academic_year,
            term=term.term,  # Note: term.term is the string (term_1, term_2, term_3)
            is_active=True
        ).filter(
            Q(grade_levels__contains=[grade_level]) | Q(grade_levels=[])
        ).first()

        if not fee_structure:
            raise ValueError(f"No fee structure found for student {student.admission_number} (Grade: {grade_level})")

        # Create invoice
        invoice = Invoice.objects.create(
            student=student,
            term=term,
            fee_structure=fee_structure,  # Make sure Invoice model has this field
            issue_date=timezone.now().date(),
            due_date=term.start_date + timedelta(days=30) if term.start_date else timezone.now().date() + timedelta(
                days=30),
            generated_by=generated_by,
            status='draft'
        )

        # Add fee items
        subtotal = Decimal('0.00')
        fee_items = FeeItem.objects.filter(fee_structure=fee_structure, is_active=True)

        for item in fee_items:
            # Calculate discount for this item
            discount_amount = Decimal('0.00')

            # Get applicable student discounts
            student_discounts = StudentDiscount.objects.filter(
                student=student,
                is_active=True,
                is_approved=True,
                discount__academic_year=term.academic_year
            ).filter(
                Q(start_date__lte=timezone.now().date()) | Q(start_date__isnull=True)
            ).filter(
                Q(end_date__gte=timezone.now().date()) | Q(end_date__isnull=True)
            )

            for sd in student_discounts:
                discount = sd.discount
                if not discount.applicable_categories or item.category in discount.applicable_categories:
                    if discount.discount_type == 'percentage':
                        discount_amount += item.amount * (discount.value / 100)
                    else:
                        discount_amount += discount.value

            net_amount = item.amount - discount_amount

            InvoiceItem.objects.create(
                invoice=invoice,
                fee_item=item,
                category=item.category,
                description=item.description,
                amount=item.amount,
                discount_applied=discount_amount,
                net_amount=net_amount
            )
            subtotal += item.amount

        # Update invoice totals
        invoice.subtotal = subtotal

        # Calculate total discount (sum of all item discounts)
        total_discount = invoice.items.aggregate(total=Sum('discount_applied'))['total'] or Decimal('0.00')
        invoice.discount_amount = total_discount
        invoice.total_amount = invoice.subtotal - invoice.discount_amount
        invoice.save()

        return invoice, True

    @staticmethod
    @transaction.atomic
    def bulk_generate_invoices(term, grade_levels=None, generated_by=None):
        """Generate invoices for multiple students."""

        students = Student.objects.filter(is_active=True, status='active')

        if grade_levels:
            students = students.filter(current_class__grade_level__in=grade_levels)

        created_count = 0
        error_details = []

        for student in students:
            try:
                _, created = InvoiceService.generate_invoice(
                    student=student,
                    term=term,
                    generated_by=generated_by
                )
                if created:
                    created_count += 1
            except Exception as e:
                error_msg = f"{student.admission_number} ({student.full_name}): {str(e)}"
                error_details.append(error_msg)
                logger.error(f"Failed to generate invoice for {student.admission_number}: {str(e)}", exc_info=True)

        return created_count, error_details

    @staticmethod
    def get_student_statement(student, term=None):
        """Get student financial statement."""

        invoices = Invoice.objects.filter(
            student=student, is_active=True
        ).exclude(status='cancelled')

        payments = Payment.objects.filter(
            student=student, is_active=True, status='completed'
        )

        if term:
            invoices = invoices.filter(term=term)

        total_invoiced = invoices.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        total_paid = payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        # Build transaction list
        transactions = []
        running_balance = Decimal('0.00')

        all_items = []
        for inv in invoices:
            all_items.append({
                'date': inv.issue_date,
                'type': 'invoice',
                'obj': inv
            })
        for pmt in payments:
            pmt_date = pmt.payment_date.date() if hasattr(pmt.payment_date, 'date') else pmt.payment_date
            all_items.append({
                'date': pmt_date,
                'type': 'payment',
                'obj': pmt
            })

        all_items.sort(key=lambda x: x['date'])

        for item in all_items:
            if item['type'] == 'invoice':
                inv = item['obj']
                running_balance += inv.total_amount
                transactions.append({
                    'date': inv.issue_date,
                    'description': f"Invoice {inv.invoice_number}",
                    'reference': inv.invoice_number,
                    'debit': inv.total_amount,
                    'credit': None,
                    'running_balance': running_balance
                })
            else:
                pmt = item['obj']
                running_balance -= pmt.amount
                transactions.append({
                    'date': pmt.payment_date,
                    'description': f"Payment - {pmt.get_payment_method_display()}",
                    'reference': pmt.receipt_number or pmt.transaction_reference or '-',
                    'debit': None,
                    'credit': pmt.amount,
                    'running_balance': running_balance
                })

        return {
            'total_invoiced': total_invoiced,
            'total_paid': total_paid,
            'balance': total_invoiced - total_paid,
            'transactions': transactions,
            'invoices': invoices,
            'payments': payments
        }




class FinanceReportService:
    """Service for financial reports."""

    @staticmethod
    def get_dashboard_stats(term=None):
        """Get finance dashboard statistics."""

        invoices = Invoice.objects.filter(is_active=True).exclude(status='cancelled')
        payments = Payment.objects.filter(is_active=True, status='completed')

        if term:
            invoices = invoices.filter(term=term)

        total_invoiced = invoices.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        total_collected = payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        total_outstanding = invoices.aggregate(total=Sum('balance'))['total'] or Decimal('0.00')

        collection_rate = (total_collected / total_invoiced * 100) if total_invoiced > 0 else 0

        recent_payments = payments.select_related('student').order_by('-payment_date')[:10]
        pending_transactions = BankTransaction.objects.filter(processing_status='pending').order_by(
            '-callback_received_at')[:5]

        return {
            'total_invoiced': total_invoiced,
            'total_collected': total_collected,
            'total_outstanding': total_outstanding,
            'collection_rate': collection_rate,
            'recent_payments': recent_payments,
            'pending_transactions': pending_transactions
        }

    @staticmethod
    def get_outstanding_report(term=None, grade_level=None):
        """Get outstanding fees report."""

        invoices = Invoice.objects.filter(
            is_active=True, balance__gt=0
        ).exclude(status='cancelled').select_related('student', 'student__current_class')

        if term:
            invoices = invoices.filter(term=term)
        if grade_level:
            invoices = invoices.filter(student__current_class__grade_level=grade_level)

        student_balances = {}
        for inv in invoices:
            sid = inv.student.pk
            if sid not in student_balances:
                student_balances[sid] = {
                    'student': inv.student,
                    'total_invoiced': Decimal('0.00'),
                    'total_paid': Decimal('0.00'),
                    'balance': Decimal('0.00')
                }
            student_balances[sid]['total_invoiced'] += inv.total_amount
            student_balances[sid]['total_paid'] += inv.amount_paid
            student_balances[sid]['balance'] += inv.balance

        outstanding_list = sorted(student_balances.values(), key=lambda x: x['balance'], reverse=True)
        total_outstanding = sum(s['balance'] for s in outstanding_list)
        students_with_balance = len(outstanding_list)
        average_balance = total_outstanding / students_with_balance if students_with_balance > 0 else 0

        return {
            'outstanding_list': outstanding_list,
            'total_outstanding': total_outstanding,
            'students_with_balance': students_with_balance,
            'average_balance': average_balance
        }

    @staticmethod
    def get_collections_summary(start_date=None, end_date=None, term=None):
        """Get collections summary report."""

        payments = Payment.objects.filter(is_active=True, status='completed')

        if start_date:
            payments = payments.filter(payment_date__date__gte=start_date)
        if end_date:
            payments = payments.filter(payment_date__date__lte=end_date)

        total_collected = payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        transaction_count = payments.count()

        by_method = payments.values('payment_method').annotate(
            count=Count('id'), total=Sum('amount')
        ).order_by('-total')

        method_display = {
            'mpesa': 'M-PESA',
            'bank': 'Bank Transfer',
            'bank_transfer': 'Bank Transfer',
            'cash': 'Cash',
            'cheque': 'Cheque',
            'other': 'Other'
        }

        by_method_list = []
        for m in by_method:
            by_method_list.append({
                'method': method_display.get(m['payment_method'], m['payment_method']),
                'count': m['count'],
                'total': m['total'] or 0,
                'percentage': (m['total'] / total_collected * 100) if total_collected > 0 else 0
            })

        daily = payments.extra(
            select={'date': 'DATE(payment_date)'}
        ).values('date').annotate(
            count=Count('id'), total=Sum('amount')
        ).order_by('-date')[:30]

        mpesa_total = payments.filter(payment_method='mpesa').aggregate(total=Sum('amount'))['total'] or 0
        bank_total = payments.filter(
            Q(payment_method='bank') | Q(payment_method='bank_transfer')
        ).aggregate(total=Sum('amount'))['total'] or 0

        return {
            'total_collected': total_collected,
            'transaction_count': transaction_count,
            'by_method': by_method_list,

            'daily': list(daily),
            'mpesa_total': mpesa_total,
            'bank_total': bank_total
        }


class FeeStructureService:
    """Service for managing fee structures."""

    @staticmethod
    def get_fee_structure_for_student(student: Student, term: Term) -> Optional[FeeStructure]:
        """
        Get the applicable fee structure for a student in a given term.

        Matches based on:
        - Academic year
        - Term
        - Grade level
        - Boarding status
        """
        grade_level = student.grade_level
        is_boarding = getattr(student, 'is_boarding', False)

        fee_structure = FeeStructure.objects.filter(
            academic_year=term.academic_year,
            term=term,
            is_boarding=is_boarding,
            is_active=True
        ).filter(
            grade_levels__contains=[grade_level]
        ).first()

        # Fallback: try without boarding filter
        if not fee_structure:
            fee_structure = FeeStructure.objects.filter(
                academic_year=term.academic_year,
                term=term,
                is_active=True
            ).filter(
                grade_levels__contains=[grade_level]
            ).first()

        return fee_structure

    @staticmethod
    def calculate_total_fees(fee_structure: FeeStructure, include_optional: bool = False) -> Decimal:
        """Calculate total fees for a fee structure."""
        items = fee_structure.items.filter(is_active=True)
        if not include_optional:
            items = items.filter(is_optional=False)
        return items.aggregate(total=Sum('amount'))['total'] or Decimal('0')
class DiscountService:
    """Service for managing discounts."""

    @staticmethod
    def get_applicable_discounts(student: Student, term: Term) -> List[StudentDiscount]:
        """Get all applicable discounts for a student in a term."""
        today = date.today()

        return StudentDiscount.objects.filter(
            student=student,
            is_active=True,
            is_approved=True,
            start_date__lte=today
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=today)
        ).filter(
            Q(discount__academic_year__isnull=True) | Q(discount__academic_year=term.academic_year)
        ).select_related('discount')

    @staticmethod
    def calculate_discount_amount(
            student_discount: StudentDiscount,
            fee_items: List[FeeItem]
    ) -> Decimal:
        """Calculate discount amount for given fee items."""
        discount = student_discount.discount
        value = student_discount.custom_value or discount.value

        # Filter items by applicable categories
        applicable_items = fee_items
        if discount.applicable_categories:
            applicable_items = [
                item for item in fee_items
                if item.category in discount.applicable_categories
            ]

        total_applicable = sum(item.amount for item in applicable_items)

        if discount.discount_type == 'percentage':
            return total_applicable * (value / 100)
        else:
            return min(value, total_applicable)


