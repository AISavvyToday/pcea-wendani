"""
Term transition service for recalculating frozen balance fields.

When a new term starts, this service recalculates balance_bf_original and
prepayment_original for all active students based on their previous term
invoice outcomes.
"""
from decimal import Decimal
import logging

from django.db import transaction

from students.models import Student
from finance.models import Invoice

logger = logging.getLogger(__name__)


def transition_frozen_balances(previous_term, new_term, dry_run=False):
    """
    Calculate and update frozen balances for all active students
    based on their previous term invoice outcomes.
    
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

