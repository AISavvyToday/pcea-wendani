# finance/services/term_transition.py
from decimal import Decimal
import logging

from django.db import transaction

from students.models import Student
from finance.models import Invoice
from core.models import InvoiceStatus

logger = logging.getLogger(__name__)


@transaction.atomic
def transition_frozen_balances(previous_term, new_term, dry_run=False):
    """
    Freeze opening balances for a new term based on the previous term's
    final invoice balance.

    MUST be run ONCE per term rollover, before new invoices are generated.
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

    logger.info(
        f"Starting term transition: {previous_term} → {new_term} "
        f"{'(DRY RUN)' if dry_run else ''}"
    )

    students = Student.objects.filter(is_active=True, status='active')
    stats['total_students'] = students.count()

    for student in students:
        try:
            prev_invoice = Invoice.objects.filter(
                student=student,
                term=previous_term,
                is_active=True
            ).exclude(
                status=InvoiceStatus.CANCELLED
            ).order_by('-created_at').first()

            old_balance_bf = student.balance_bf_original or Decimal('0.00')
            old_prepayment = student.prepayment_original or Decimal('0.00')
            old_credit = student.credit_balance or Decimal('0.00')

            # ===============================
            # CASE 1: Previous term invoice exists
            # ===============================
            if prev_invoice:
                final_balance = prev_invoice.balance or Decimal('0.00')

                if final_balance > 0:
                    # Student owes money
                    student.balance_bf_original = final_balance
                    student.prepayment_original = Decimal('0.00')
                    student.credit_balance = Decimal('0.00')
                    stats['with_outstanding'] += 1

                elif final_balance < 0:
                    # Student overpaid
                    credit = abs(final_balance)
                    student.balance_bf_original = Decimal('0.00')
                    student.prepayment_original = credit
                    student.credit_balance = credit
                    stats['with_overpayment'] += 1

                else:
                    # Fully settled
                    student.balance_bf_original = Decimal('0.00')
                    student.prepayment_original = Decimal('0.00')
                    student.credit_balance = Decimal('0.00')
                    stats['fully_paid'] += 1

                # Deactivate ALL previous-term invoices
                if not dry_run:
                    Invoice.objects.filter(
                        student=student,
                        term=previous_term,
                        is_active=True
                    ).update(is_active=False)

            # ===============================
            # CASE 2: No invoice in previous term
            # ===============================
            else:
                stats['no_invoice'] += 1

                if old_credit > 0:
                    student.balance_bf_original = Decimal('0.00')
                    student.prepayment_original = old_credit
                    student.credit_balance = old_credit
                elif old_credit < 0:
                    # Treat negative credit as debt
                    student.balance_bf_original = abs(old_credit)
                    student.prepayment_original = Decimal('0.00')
                    student.credit_balance = Decimal('0.00')

                else:
                    student.balance_bf_original = Decimal('0.00')
                    student.prepayment_original = Decimal('0.00')
                    student.credit_balance = Decimal('0.00')

            changed = (
                old_balance_bf != student.balance_bf_original or
                old_prepayment != student.prepayment_original or
                old_credit != student.credit_balance
            )

            if changed:
                logger.debug(
                    f"{student.admission_number} | "
                    f"BF: {old_balance_bf} → {student.balance_bf_original}, "
                    f"PREPAY: {old_prepayment} → {student.prepayment_original}, "
                    f"CREDIT: {old_credit} → {student.credit_balance}"
                )

                if not dry_run:
                    student.save(update_fields=[
                        'balance_bf_original',
                        'prepayment_original',
                        'credit_balance',
                        'updated_at',
                    ])

                stats['updated'] += 1

        except Exception:
            logger.exception(
                f"Term transition failed for {student.admission_number}"
            )
            stats['errors'] += 1

    logger.info(
        "Term transition completed | "
        f"Processed: {stats['total_students']} | "
        f"Updated: {stats['updated']} | "
        f"Owing: {stats['with_outstanding']} | "
        f"Overpaid: {stats['with_overpayment']} | "
        f"Settled: {stats['fully_paid']} | "
        f"No invoice: {stats['no_invoice']} | "
        f"Errors: {stats['errors']}"
    )

    return stats
