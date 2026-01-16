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

from payments.services.payment import logger
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
        """
        Generate invoice for a student for a term.

        Financial rules enforced:
        - Opening balance comes ONLY from student.balance_bf_original
        - Opening credit comes ONLY from student.prepayment_original
        - Live credit_balance may further reduce exposure ONCE
        - Frozen fields are NEVER modified here
        """

        # --------------------------------------------------
        # Prevent duplicate invoice
        # --------------------------------------------------
        existing = Invoice.objects.filter(
            student=student,
            term=term,
            is_active=True
        ).exclude(status='cancelled').first()

        if existing:
            return existing, False

        # --------------------------------------------------
        # Resolve fee structure
        # --------------------------------------------------
        grade_level = getattr(student, 'grade_level', None)
        if not grade_level and getattr(student, 'current_class', None):
            grade_level = student.current_class.grade_level

        fee_structures = FeeStructure.objects.filter(
            academic_year=term.academic_year,
            term=term.term,
            is_active=True
        )

        fee_structure = None
        for fs in fee_structures:
            if not fs.grade_levels or grade_level in fs.grade_levels:
                fee_structure = fs
                break

        if not fee_structure:
            raise ValueError(
                f"No fee structure for {student.admission_number} (Grade: {grade_level})"
            )

        # --------------------------------------------------
        # Create invoice shell
        # --------------------------------------------------
        invoice = Invoice.objects.create(
            student=student,
            term=term,
            fee_structure=fee_structure,
            issue_date=timezone.now().date(),
            due_date=(
                term.start_date + timedelta(days=30)
                if term.start_date
                else timezone.now().date() + timedelta(days=30)
            ),
            generated_by=generated_by,
            status='overdue'
        )

        # --------------------------------------------------
        # Add fee items
        # --------------------------------------------------
        subtotal = Decimal('0.00')
        fee_items = FeeItem.objects.filter(
            fee_structure=fee_structure,
            is_active=True
        )

        for item in fee_items:
            item_amount = Decimal('0.00')
            description = item.description

            if item.category == 'transport':
                if student.uses_school_transport and student.transport_route:
                    from transport.models import TransportFee
                    try:
                        tf = TransportFee.objects.get(
                            route=student.transport_route,
                            academic_year=term.academic_year,
                            term=term.term,
                            is_active=True
                        )
                        item_amount = tf.amount
                        description = f"Transport ({student.transport_route.name})"
                    except TransportFee.DoesNotExist:
                        logger.warning(
                            f"No transport fee for {student.transport_route}"
                        )
            else:
                item_amount = item.amount

            discount_amount = Decimal('0.00')
            student_discounts = StudentDiscount.objects.filter(
                student=student,
                is_active=True,
                is_approved=True,
                discount__academic_year=term.academic_year
            ).filter(
                Q(start_date__lte=timezone.now().date()) | Q(start_date__isnull=True),
                Q(end_date__gte=timezone.now().date()) | Q(end_date__isnull=True),
            )

            for sd in student_discounts:
                discount = sd.discount
                if not discount.applicable_categories or item.category in discount.applicable_categories:
                    if discount.discount_type == 'percentage':
                        discount_amount += item_amount * (discount.value / 100)
                    else:
                        discount_amount += discount.value

            net_amount = item_amount - discount_amount

            InvoiceItem.objects.create(
                invoice=invoice,
                fee_item=item,
                category=item.category,
                description=description,
                amount=item_amount,
                discount_applied=discount_amount,
                net_amount=net_amount
            )

            subtotal += item_amount

        # --------------------------------------------------
        # Finalize totals
        # --------------------------------------------------
        invoice.subtotal = subtotal
        invoice.discount_amount = (
            invoice.items.aggregate(total=Sum('discount_applied'))['total']
            or Decimal('0.00')
        )
        invoice.total_amount = invoice.subtotal - invoice.discount_amount

        # --------------------------------------------------
        # CORE FIX: Apply frozen opening balances
        # --------------------------------------------------
        opening_balance = student.balance_bf_original or Decimal('0.00')
        opening_prepayment = student.prepayment_original or Decimal('0.00')

        invoice.balance_bf = opening_balance
        invoice.prepayment = -opening_prepayment if opening_prepayment > 0 else Decimal('0.00')
        invoice.balance_bf_original = opening_balance

        # --------------------------------------------------
        # Consume live credit_balance once
        # --------------------------------------------------
        available_credit = student.credit_balance or Decimal('0.00')

        exposure = opening_balance + invoice.total_amount - opening_prepayment
        credit_to_apply = min(available_credit, exposure)

        if credit_to_apply > 0:
            invoice.prepayment -= credit_to_apply
            student.credit_balance = available_credit - credit_to_apply

        # --------------------------------------------------
        # Persist
        # --------------------------------------------------
        invoice.save()
        student.save(update_fields=['credit_balance', 'updated_at'])

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
        from datetime import date as date_cls
        from django.db.models import Q

        from core.models import InvoiceStatus
        invoices = Invoice.objects.filter(
            student=student, is_active=True
        ).exclude(status=InvoiceStatus.CANCELLED)

        if term:
            invoices = invoices.filter(term=term)

        # Get payments - if term is specified, only get payments allocated to invoices in that term
        if term:
            # Get payments that have allocations to invoice items in invoices for this term
            from payments.models import PaymentAllocation
            payment_ids = PaymentAllocation.objects.filter(
                is_active=True,
                invoice_item__invoice__in=invoices,
                payment__is_active=True,
                payment__status='completed'
            ).values_list('payment_id', flat=True).distinct()
            
            payments = Payment.objects.filter(
                id__in=payment_ids,
                student=student,
                is_active=True,
                status='completed'
            )
        else:
            payments = Payment.objects.filter(
                student=student, is_active=True, status='completed'
            )

        total_invoiced = invoices.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        
        # Calculate total paid - use invoice.amount_paid which includes both item allocations and balance_bf payments
        # This is more accurate than just summing allocations
        total_paid = invoices.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
        
        # Calculate total balance_bf and prepayment from invoices
        total_balance_bf = invoices.aggregate(total=Sum('balance_bf'))['total'] or Decimal('0.00')
        total_prepayment = invoices.aggregate(total=Sum('prepayment'))['total'] or Decimal('0.00')

        # Build transaction list
        transactions = []
        # Start running balance with total balance_bf (if any invoices have it)
        # We'll show balance_bf as a separate transaction entry for the first invoice that has it
        running_balance = Decimal('0.00')
        balance_bf_shown = False

        all_items = []
        for inv in invoices:
            # Handle None issue_date - use created_at as fallback
            inv_date = inv.issue_date or (inv.created_at.date() if hasattr(inv.created_at, 'date') else inv.created_at)
            all_items.append({
                'date': inv_date,
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

        # Sort by date, handling None dates by putting them at the end
        all_items.sort(key=lambda x: x['date'] if x['date'] is not None else date_cls(9999, 12, 31))

        for item in all_items:
            if item['type'] == 'invoice':
                inv = item['obj']
                inv_date = inv.issue_date or (inv.created_at.date() if hasattr(inv.created_at, 'date') else inv.created_at)
                
                # Show balance_bf first if it exists and hasn't been shown yet
                if inv.balance_bf and inv.balance_bf > 0 and not balance_bf_shown:
                    running_balance += inv.balance_bf
                    balance_bf_shown = True
                    transactions.append({
                        'date': inv_date,
                        'description': f"Balance B/F (Invoice {inv.invoice_number})",
                        'reference': inv.invoice_number,
                        'debit': inv.balance_bf,
                        'credit': None,
                        'running_balance': running_balance
                    })
                
                # Add invoice total amount
                running_balance += inv.total_amount
                transactions.append({
                    'date': inv_date,
                    'description': f"Invoice {inv.invoice_number}",
                    'reference': inv.invoice_number,
                    'debit': inv.total_amount,
                    'credit': None,
                    'running_balance': running_balance
                })
                
                # If invoice has prepayment, show it as a credit entry (reduces balance)
                if inv.prepayment and inv.prepayment != 0:
                    # Prepayment is stored as negative, so adding it reduces balance
                    running_balance -= abs(inv.prepayment)
                    transactions.append({
                        'date': inv_date,
                        'description': f"Prepayment Applied (Invoice {inv.invoice_number})",
                        'reference': inv.invoice_number,
                        'debit': None,
                        'credit': abs(inv.prepayment),
                        'running_balance': running_balance
                    })
            else:
                pmt = item['obj']
                running_balance -= pmt.amount
                pmt_date = pmt.payment_date.date() if hasattr(pmt.payment_date, 'date') else pmt.payment_date
                transactions.append({
                    'date': pmt_date,
                    'description': f"Payment - {pmt.get_payment_source_display()}",
                    'reference': pmt.receipt_number or pmt.payment_reference or '-',
                    'debit': None,
                    'credit': pmt.amount,
                    'running_balance': running_balance
                })

        # Calculate balance due: (total_invoiced + balance_bf + prepayment) - total_paid
        # Prepayment is stored as negative, so adding it reduces the balance
        balance_due = (total_invoiced + total_balance_bf) - total_prepayment - total_paid


        return {
            'total_invoiced': total_invoiced,
            'total_paid': total_paid,
            'balance_bf': total_balance_bf,
            'prepayment': total_prepayment,
            'balance': balance_due,
            'transactions': transactions,
            'invoices': invoices,
            'payments': payments
        }
        
    @staticmethod
    @transaction.atomic
    def delete_invoice(invoice):
        """
        Safely delete an invoice.

        Rules:
        - Block deletion if amount_paid > 0
        - Delete all invoice items (cascade deletes allocations)
        - Restore student.credit_balance if invoice consumed credit
        """

        if invoice.amount_paid > 0:
            raise ValueError(
                f"Cannot delete invoice {invoice.invoice_number}: it has payments applied."
            )

        student = invoice.student

        # Calculate credit used during invoice generation
        credit_used = 0
        if invoice.prepayment < 0:
            credit_used = abs(invoice.prepayment)  # convert to positive
            student.credit_balance += credit_used
            student.save(update_fields=['credit_balance', 'updated_at'])

        # Delete invoice (items and allocations cascade automatically)
        invoice.delete()

        return credit_used




class FinanceReportService:
    """Service for financial reports."""

    @staticmethod
    def get_dashboard_stats(term=None):
        """Get finance dashboard statistics for active students only."""

        # Filter to active students only
        invoices = Invoice.objects.filter(
            is_active=True,
            student__status='active'
        ).exclude(status='cancelled')
        
        # Filter payments to active students only
        payments = Payment.objects.filter(
            is_active=True,
            status='completed',
            student__status='active'
        )

        # If term is provided, filter to that term (typically current term)
        if term:
            invoices = invoices.filter(term=term)

        total_invoiced = invoices.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        
        # Use invoice.amount_paid to get accurate total collected
        # This includes both item allocations AND balance_bf payments
        # This ensures all payments are captured, including those that go to balance_bf
        total_collected = invoices.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
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
        """
        grade_level = student.grade_level

        fee_structure = FeeStructure.objects.filter(
            academic_year=term.academic_year,
            term=term,
            is_active=True
        ).filter(
            grade_levels__contains=[grade_level]
        ).first()

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


def transition_frozen_balances(previous_term, new_term, dry_run=False):
    """
    Calculate and update frozen balances for all active students
    based on their previous term invoice outcomes.
    
    When a new term starts, this recalculates balance_bf_original and
    prepayment_original for all active students based on their previous term
    invoice outcomes.
    
    Args:
        previous_term: The Term object for the previous term
        new_term: The Term object for the new current term
        dry_run: If True, don't save changes, just log what would happen
        
    Returns:
        dict: Statistics about the transition
    """
    stats = {
        'total_students': 0,
        'with_outstanding': 0,
        'with_overpayment': 0,
        'fully_paid': 0,
        'no_invoice': 0,
        'updated': 0,
        'errors': 0,
    }
    
    logger.info(f"Starting term transition from {previous_term} to {new_term}")
    if dry_run:
        logger.info("DRY RUN MODE - No changes will be saved")
    
    active_students = Student.objects.filter(status='active')
    stats['total_students'] = active_students.count()
    
    for student in active_students:
        try:
            # Get previous term's invoice (if any)
            prev_invoice = Invoice.objects.filter(
                student=student,
                term=previous_term,
                is_active=True
            ).first()
            
            old_balance_bf = student.balance_bf_original
            old_prepayment = student.prepayment_original
            old_credit = student.credit_balance
            
            if prev_invoice:
                # Use invoice balance as new term-start position
                if prev_invoice.balance > 0:
                    # Student owes money
                    student.balance_bf_original = prev_invoice.balance
                    student.prepayment_original = Decimal('0.00')
                    student.credit_balance = prev_invoice.balance
                    stats['with_outstanding'] += 1
                elif prev_invoice.balance < 0:
                    # Student overpaid
                    student.balance_bf_original = Decimal('0.00')
                    student.prepayment_original = abs(prev_invoice.balance)
                    student.credit_balance = prev_invoice.balance
                    stats['with_overpayment'] += 1
                else:
                    # Fully paid
                    student.balance_bf_original = Decimal('0.00')
                    student.prepayment_original = Decimal('0.00')
                    student.credit_balance = Decimal('0.00')
                    stats['fully_paid'] += 1
            else:
                # No invoice - use existing credit_balance (may have been set manually or from import)
                stats['no_invoice'] += 1
                if student.credit_balance > 0:
                    student.balance_bf_original = student.credit_balance
                    student.prepayment_original = Decimal('0.00')
                elif student.credit_balance < 0:
                    student.balance_bf_original = Decimal('0.00')
                    student.prepayment_original = abs(student.credit_balance)
                else:
                    # Zero balance - reset frozen fields too
                    student.balance_bf_original = Decimal('0.00')
                    student.prepayment_original = Decimal('0.00')
            
            # Check if values changed
            changed = (
                old_balance_bf != student.balance_bf_original or
                old_prepayment != student.prepayment_original or
                old_credit != student.credit_balance
            )
            
            if changed:
                logger.debug(
                    f"{student.admission_number}: "
                    f"balance_bf_original: {old_balance_bf} -> {student.balance_bf_original}, "
                    f"prepayment_original: {old_prepayment} -> {student.prepayment_original}, "
                    f"credit_balance: {old_credit} -> {student.credit_balance}"
                )
                
                if not dry_run:
                    student.save(update_fields=[
                        'balance_bf_original', 'prepayment_original', 'credit_balance'
                    ])
                stats['updated'] += 1
                
        except Exception as e:
            logger.error(f"Error processing student {student.admission_number}: {e}")
            stats['errors'] += 1
    
    logger.info(
        f"Term transition complete: "
        f"{stats['total_students']} students processed, "
        f"{stats['updated']} updated, "
        f"{stats['with_outstanding']} with outstanding balance, "
        f"{stats['with_overpayment']} with overpayment, "
        f"{stats['fully_paid']} fully paid, "
        f"{stats['no_invoice']} without previous invoice, "
        f"{stats['errors']} errors"
    )
    
    return stats

