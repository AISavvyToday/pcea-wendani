# File: payments/services/invoice.py
# ============================================================
# RATIONALE: Invoice & allocation logic
# - Allocate any completed Payment across a student's invoices (oldest first)
# - Allocate within an invoice by fee category priority (invoice items)
# - Recalculate invoice.amount_paid/balance/status from PaymentAllocation
# - Leaves any remainder as unapplied credit (student account +ve)
#   (credit is implicit: payment.amount - sum(payment.allocations))
# ============================================================

import logging
from decimal import Decimal
from datetime import date as date_cls

from django.db import transaction as db_transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce

from core.models import InvoiceStatus, PaymentStatus
from finance.models import Invoice, InvoiceItem
from payments.models import Payment, PaymentAllocation
from students.models import Student

logger = logging.getLogger(__name__)


class InvoiceService:
    """Service for managing invoice updates from payments (oldest-invoice-first)."""

    PRIORITY_ORDER = [
        "tuition",  # 1
        "meals",  # 2 (Lunch)
        "examination",  # 3 (Exam Fee)
        "activity",  # 4
        "transport",  # 5

    ]

    @staticmethod
    def _priority_key(category: str) -> int:
        try:
            return InvoiceService.PRIORITY_ORDER.index(category)
        except ValueError:
            return 999

    @staticmethod
    def _sum_allocations_for_invoice(invoice: Invoice) -> Decimal:
        total = (
            PaymentAllocation.objects.filter(
                is_active=True,
                invoice_item__invoice=invoice,
                payment__is_active=True,
                payment__status=PaymentStatus.COMPLETED,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0")
        )
        return total

    @staticmethod
    def _recalculate_invoice_fields(invoice: Invoice) -> Invoice:
        """
        Recalculate invoice.amount_paid, invoice.balance, invoice.status from allocations.
        IMPORTANT: This preserves balance_bf payments that were added to amount_paid.
        balance_bf is frozen at invoice creation and should never be modified.
        """
        # Get allocations to invoice items only
        allocations_to_items = InvoiceService._sum_allocations_for_invoice(invoice)
        
        # Preserve balance_bf payments from existing amount_paid
        # If invoice has balance_bf and current amount_paid > allocations_to_items,
        # the difference represents balance_bf payments (preserved from previous calculations)
        balance_bf_paid = Decimal('0.00')
        if invoice.balance_bf > 0 and invoice.amount_paid > allocations_to_items:
            balance_bf_paid = invoice.amount_paid - allocations_to_items
            # Can't exceed original balance_bf
            balance_bf_paid = min(balance_bf_paid, invoice.balance_bf)
        
        # amount_paid = allocations to items + balance_bf payments
        invoice.amount_paid = allocations_to_items + balance_bf_paid
        
        # prepayment is stored as negative (credit), so adding it reduces balance
        invoice.balance = invoice.total_amount + invoice.balance_bf + invoice.prepayment - invoice.amount_paid

        today = date_cls.today()

        # Update invoice status based on balance and payment
        if invoice.balance <= 0:
            invoice.status = InvoiceStatus.PAID
        elif invoice.amount_paid > 0:
            invoice.status = InvoiceStatus.PARTIALLY_PAID
        elif invoice.due_date and invoice.due_date < today:
            invoice.status = InvoiceStatus.OVERDUE

        # IMPORTANT: update_fields must include balance/amount_paid/status
        invoice.save(update_fields=["amount_paid", "balance", "status", "updated_at"])
        return invoice

    @staticmethod
    def _allocate_amount_to_invoice_items(payment: Payment, invoice: Invoice, amount_to_apply: Decimal) -> Decimal:
        """
        Allocate up to amount_to_apply into this invoice's items (by priority).
        Returns how much was actually allocated.
        """
        if amount_to_apply <= 0:
            return Decimal("0")

        items = list(invoice.items.filter(is_active=True))
        # Sort by priority order, then stable by id
        items.sort(key=lambda it: (InvoiceService._priority_key(it.category), it.id))

        allocated_total = Decimal("0")
        remaining = amount_to_apply

        for item in items:
            if remaining <= 0:
                break

            already_allocated = (
                    PaymentAllocation.objects.filter(
                        is_active=True,
                        invoice_item=item,
                        payment__is_active=True,
                        payment__status=PaymentStatus.COMPLETED,
                    ).aggregate(total=Sum("amount"))["total"]
                    or Decimal("0")
            )

            item_due = (item.net_amount or Decimal("0")) - already_allocated
            if item_due <= 0:
                continue

            allocation_amount = remaining if remaining < item_due else item_due

            PaymentAllocation.objects.create(
                payment=payment,
                invoice_item=item,
                amount=allocation_amount,
            )

            allocated_total += allocation_amount
            remaining -= allocation_amount

        return allocated_total

    @staticmethod
    def get_student_unapplied_credit(student) -> Decimal:
        """
        Student credit (+ve) = completed payments - allocations applied.
        This is persisted implicitly (no extra model).
        """
        total_payments = (
            Payment.objects.filter(student=student, is_active=True, status=PaymentStatus.COMPLETED)
            .aggregate(total=Sum("amount"))["total"]
            or Decimal("0")
        )

        total_allocated = (
            PaymentAllocation.objects.filter(
                is_active=True,
                payment__student=student,
                payment__is_active=True,
                payment__status=PaymentStatus.COMPLETED,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0")
        )

        credit = total_payments - total_allocated
        if credit < 0:
            # Shouldn't happen, but guard
            credit = Decimal("0")
        return credit

    @staticmethod
    def get_student_net_account_balance(student) -> Decimal:
        """
        +ve means student is in credit
        -ve means student owes money

        net_balance = credit - total_outstanding
        """
        total_outstanding = (
            Invoice.objects.filter(student=student, is_active=True)
            .exclude(status=InvoiceStatus.CANCELLED)
            .aggregate(total=Sum("balance"))["total"]
            or Decimal("0")
        )

        credit = InvoiceService.get_student_unapplied_credit(student)
        return credit - total_outstanding

    @staticmethod
    @db_transaction.atomic
    def apply_payment_to_student_arrears(payment: Payment) -> Decimal:
        """
        Core requirement:
        - First clear balance_bf from all invoices (oldest invoice first)
        - Then allocate remaining payment to invoice items by priority
        - If payment exceeds all invoices, remainder becomes unapplied credit

        Returns remaining unapplied credit for THIS payment:
            payment.amount - sum(balance_bf_cleared) - sum(payment.allocations.amount)
        """
        if not payment or not payment.is_active:
            return Decimal("0")

        if payment.status != PaymentStatus.COMPLETED:
            logger.info(f"Payment {payment.payment_reference} not COMPLETED; skipping allocation.")
            return Decimal("0")

        # Idempotency: if already allocated, just recalc affected invoices and return remaining
        existing_allocations = payment.allocations.filter(is_active=True)
        if existing_allocations.exists():
            invoice_ids = (
                existing_allocations.values_list("invoice_item__invoice_id", flat=True).distinct()
            )
            for inv in Invoice.objects.select_for_update().filter(id__in=list(invoice_ids)):
                InvoiceService._recalculate_invoice_fields(inv)

            allocated = existing_allocations.aggregate(total=Sum("amount"))["total"] or Decimal("0")
            return payment.amount - allocated

        student = payment.student
        remaining = payment.amount
        balance_bf_cleared_total = Decimal("0")

        # Oldest first: issue_date ascending.
        # If issue_date can be NULL, Coalesce pushes NULLs to far-future so they come last.
        invoices = (
            Invoice.objects.select_for_update()
            .filter(student=student, is_active=True)
            .exclude(status=InvoiceStatus.CANCELLED)
            .order_by(Coalesce("issue_date", date_cls(9999, 12, 31)).asc(), "created_at")
        )

        # STEP 1: Clear balance_bf from invoices (oldest first)
        # IMPORTANT: balance_bf is a snapshot at invoice creation and should NEVER be modified
        # Instead, we track balance_bf payments by adding them to amount_paid
        for invoice in invoices:
            if remaining <= 0:
                break

            # Get current allocations total (payments to invoice items only)
            allocations_total = InvoiceService._sum_allocations_for_invoice(invoice)
            
            # Calculate how much of balance_bf is still outstanding
            # Invoice balance = total_amount + balance_bf + prepayment - amount_paid
            # Outstanding balance_bf = balance_bf - (amount_paid - allocations_to_items)
            # Since amount_paid currently only includes allocations to items, outstanding_balance_bf = balance_bf
            # But we need to account for any previous balance_bf payments that were added to amount_paid
            # Actually, let's calculate it differently:
            # Current invoice balance = total_amount + balance_bf + prepayment - allocations_total
            # Outstanding balance_bf = min(balance_bf, current_balance - total_amount - prepayment)
            
            if invoice.balance_bf > 0:
                # Calculate current balance without recalculating (to avoid overwriting amount_paid)
                current_balance = invoice.total_amount + invoice.balance_bf + invoice.prepayment - allocations_total
                
                # Outstanding balance_bf is the portion of balance_bf not yet paid
                # It's the difference between current balance and total_amount (after prepayment)
                outstanding_balance_bf = current_balance - invoice.total_amount - invoice.prepayment
                outstanding_balance_bf = max(Decimal('0.00'), outstanding_balance_bf)  # Can't be negative
                outstanding_balance_bf = min(outstanding_balance_bf, invoice.balance_bf)  # Can't exceed original balance_bf
                
                if outstanding_balance_bf > 0:
                    amount_to_clear_bf = min(remaining, outstanding_balance_bf)
                    
                    # Add this payment to amount_paid (balance_bf payments are tracked here)
                    # We'll manually update balance instead of calling _recalculate_invoice_fields
                    # because _recalculate_invoice_fields would overwrite amount_paid with only allocations
                    invoice.amount_paid = allocations_total + amount_to_clear_bf
                    invoice.balance = invoice.total_amount + invoice.balance_bf + invoice.prepayment - invoice.amount_paid
                    
                    # Update status
                    if invoice.balance <= 0:
                        invoice.status = InvoiceStatus.PAID
                    elif invoice.amount_paid > 0:
                        invoice.status = InvoiceStatus.PARTIALLY_PAID
                    
                    invoice.save(update_fields=['amount_paid', 'balance', 'status', 'updated_at'])
                    
                    balance_bf_cleared_total += amount_to_clear_bf
                    remaining -= amount_to_clear_bf

        # STEP 2: Allocate remaining payment to invoice items (by priority)
        for invoice in invoices:
            # Recalculate to get current state
            InvoiceService._recalculate_invoice_fields(invoice)

            # Only pay invoices that actually have outstanding balance
            if invoice.balance <= 0:
                continue

            if remaining <= 0:
                break

            amount_for_this_invoice = remaining if remaining < invoice.balance else invoice.balance

            allocated = InvoiceService._allocate_amount_to_invoice_items(
                payment=payment,
                invoice=invoice,
                amount_to_apply=amount_for_this_invoice,
            )

            # Recalc invoice after allocations
            InvoiceService._recalculate_invoice_fields(invoice)

            remaining -= allocated

        # Remaining is unapplied credit for this payment (if any)
        allocated_total = (
                payment.allocations.filter(is_active=True).aggregate(total=Sum("amount"))["total"]
                or Decimal("0")
        )
        total_applied = balance_bf_cleared_total + allocated_total
        leftover = payment.amount - total_applied

        if leftover > 0:
            # Add leftover to student's credit balance (negative means credit)
            student = payment.student
            # Since positive = debt, negative = credit, we subtract to make it more negative
            student.credit_balance -= leftover  # Subtracting makes it more negative = more credit
            student.save(update_fields=['credit_balance', 'updated_at'])

            note = f" | Unapplied credit: KES {leftover}"
            if note.strip() not in (payment.notes or ""):
                payment.notes = (payment.notes or "") + note
                payment.save(update_fields=["notes", "updated_at"])

        logger.info(
            f"Payment {payment.payment_reference} allocated. Balance_BF cleared={balance_bf_cleared_total}, "
            f"Items allocated={allocated_total}, Unapplied={leftover}"
        )
        return leftover

    @staticmethod
    @db_transaction.atomic
    def apply_credit_to_invoice(student: Student, invoice: Invoice, amount: Decimal):
        """
        Apply student's credit balance to an invoice.
        """
        if amount <= 0 or student.credit_balance >= 0:  # No credit to apply
            return Decimal("0")

        # Determine how much credit we can use (negative credit_balance is the available credit)
        available_credit = -student.credit_balance  # Convert to positive amount
        amount_to_apply = min(amount, available_credit, invoice.balance)

        if amount_to_apply <= 0:
            return Decimal("0")

        # Create a "virtual" payment from credit
        from payments.models import Payment, PaymentAllocation

        # You might want to create a special payment record for credit application
        # Or just adjust balances directly

        # For now, let's just adjust the student's credit balance and invoice
        student.credit_balance += amount_to_apply  # Add makes it less negative
        student.save(update_fields=['credit_balance', 'updated_at'])

        # Add to invoice payment
        invoice.amount_paid += amount_to_apply
        # prepayment is stored as negative (credit), so adding it reduces balance
        invoice.balance = invoice.total_amount + invoice.balance_bf + invoice.prepayment - invoice.amount_paid
        invoice.save(update_fields=['amount_paid', 'balance', 'updated_at'])

        return amount_to_apply