# File: payments/services/invoice.py
# ============================================================
# RATIONALE:
# - Allocate completed Payments across student invoices (oldest first)
# - Allocate strictly to invoice items by category priority
# - Payments NEVER modify balance_bf or prepayment
# - balance_bf is treated as a frozen snapshot (historical arrears)
# - Invoice financials are always derived from allocations
# - Any excess payment becomes unapplied student credit
# ============================================================

import logging
from decimal import Decimal
from datetime import date as date_cls

from django.db import transaction as db_transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.models import InvoiceStatus, PaymentStatus
from finance.models import Invoice, InvoiceItem
from payments.models import Payment, PaymentAllocation
from students.models import Student

logger = logging.getLogger(__name__)


class InvoiceService:
    """Service for managing invoice updates from payments (allocation-only model)."""

    # NOTE: Balance B/F is treated as a synthetic fee category so that
    # payments can clear arrears using the same allocation engine.
    # It is given highest priority so historical debt is paid first.
    PRIORITY_ORDER = [
        "admission",
        "balance_bf",   # synthetic category for Balance B/F invoice item
        "tuition",
        "meals",
        "examination",
        "activity",
        "transport",
    ]

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------

    @staticmethod
    def _priority_key(category: str) -> int:
        try:
            return InvoiceService.PRIORITY_ORDER.index(category)
        except ValueError:
            return 999

    @staticmethod
    def _sum_allocations_for_invoice(invoice: Invoice) -> Decimal:
        return (
            PaymentAllocation.objects.filter(
                is_active=True,
                invoice_item__invoice=invoice,
                payment__is_active=True,
                payment__status=PaymentStatus.COMPLETED,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )

    # ---------------------------------------------------------
    # Invoice recalculation (allocation-only)
    # ---------------------------------------------------------

    @staticmethod
    def _recalculate_invoice_fields(invoice: Invoice) -> Invoice:
        """
        Recalculate invoice strictly from allocations.
        balance_bf and prepayment are NEVER mutated by payments.

        IMPORTANT INVARIANTS:
        - invoice.amount_paid should reflect ONLY the amount applied to this invoice
        - invoice.balance must NEVER go negative
        - any payment amount beyond invoice due belongs in student.credit_balance,
          not as a negative invoice balance
        """
        allocations_total = InvoiceService._sum_allocations_for_invoice(invoice)

        total_due = (
            (invoice.total_amount or Decimal("0.00"))
            + (invoice.balance_bf or Decimal("0.00"))
            - (invoice.prepayment or Decimal("0.00"))
        )
        total_due = max(total_due, Decimal("0.00"))

        invoice.amount_paid = min(allocations_total, total_due)
        invoice.balance = max(total_due - invoice.amount_paid, Decimal("0.00"))

        today = date_cls.today()

        if invoice.balance == 0:
            invoice.status = InvoiceStatus.PAID
        elif invoice.amount_paid > 0:
            invoice.status = InvoiceStatus.PARTIALLY_PAID
        elif invoice.due_date and invoice.due_date < today:
            invoice.status = InvoiceStatus.OVERDUE

        invoice.save(update_fields=["amount_paid", "balance", "status", "updated_at"])
        return invoice

    # ---------------------------------------------------------
    # Allocation logic
    # ---------------------------------------------------------

    @staticmethod
    def _allocate_amount_to_invoice_items(
        payment: Payment,
        invoice: Invoice,
        amount_to_apply: Decimal,
    ) -> Decimal:
        """
        Allocate payment into invoice items by category priority.
        Returns amount actually allocated.
        """
        if amount_to_apply <= 0:
            return Decimal("0.00")

        items = list(invoice.items.filter(is_active=True))
        items.sort(key=lambda it: (InvoiceService._priority_key(it.category), it.id))

        remaining = amount_to_apply
        allocated_total = Decimal("0.00")

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
                or Decimal("0.00")
            )

            item_due = (item.net_amount or Decimal("0.00")) - already_allocated
            if item_due <= 0:
                continue

            applied = min(item_due, remaining)

            PaymentAllocation.objects.create(
                payment=payment,
                invoice_item=item,
                amount=applied,
            )

            allocated_total += applied
            remaining -= applied

        return allocated_total


    @staticmethod
    @db_transaction.atomic
    def allocate_payment_to_single_invoice(
        payment: Payment,
        invoice: Invoice,
        amount_to_apply: Decimal,
    ) -> Decimal:
        """
        Allocate a payment ONLY to the given invoice.

        Used for:
        - Internal "credit consumption" payments created from Student.credit_balance
          during invoice generation.
        - Any future flows that must not spill over to other invoices.

        Returns the amount actually allocated to this invoice.
        """
        if not payment or not payment.is_active:
            return Decimal("0.00")

        if payment.status != PaymentStatus.COMPLETED:
            logger.info(
                f"Payment {payment.payment_reference} not COMPLETED; "
                f"skipping single-invoice allocation."
            )
            return Decimal("0.00")

        if amount_to_apply <= 0:
            return Decimal("0.00")

        # Lock invoice row while allocating to avoid races
        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)

        # Ensure invoice fields are up to date before we start
        InvoiceService._recalculate_invoice_fields(invoice)

        if invoice.balance <= 0:
            return Decimal("0.00")

        amount_for_invoice = min(amount_to_apply, invoice.balance)

        allocated = InvoiceService._allocate_amount_to_invoice_items(
            payment=payment,
            invoice=invoice,
            amount_to_apply=amount_for_invoice,
        )

        InvoiceService._recalculate_invoice_fields(invoice)
        return allocated

    @staticmethod
    @db_transaction.atomic
    def soft_delete_invoice(invoice: Invoice, deleted_by=None):
        if not invoice or not invoice.is_active:
            return
        if invoice.amount_paid > 0:
            raise ValueError("Cannot soft-delete invoice with payments. Reverse/delete payments first.")

        invoice.is_active = False
        invoice.deleted_at = timezone.now()
        invoice.deleted_by = deleted_by
        invoice.save(update_fields=["is_active", "deleted_at", "deleted_by", "updated_at"])
        invoice.student.recompute_outstanding_balance()

    @staticmethod
    @db_transaction.atomic
    def delete_payment(payment: Payment, deleted_by=None):
        """
        Soft-delete a payment and its allocations and restore all derived state.
        
        Handles two cases:
        1. Payments allocated to invoices - reverse allocations
        2. Payments applied directly to outstanding_balance (no invoices) - 
           parse notes and reverse those changes
        """
        import re
        
        if not payment:
            return

        student = payment.student
        payment_notes = payment.notes or ""

        # 1. Capture allocations BEFORE deletion
        if not payment.is_active:
            return

        allocations = list(payment.allocations.filter(is_active=True))

        invoice_ids = list(
            {a.invoice_item.invoice_id for a in allocations}
        )

        allocated_total = sum(a.amount for a in allocations)

        # 2. Soft-delete allocations
        for alloc in allocations:
            alloc.is_active = False
            alloc.save(update_fields=["is_active", "updated_at"])

        # 3. Soft-delete payment
        payment.is_active = False
        payment.deleted_at = timezone.now()
        payment.deleted_by = deleted_by
        payment.is_reconciled = False
        payment.reconciled_at = None
        payment.reconciled_by = None
        payment.save(update_fields=[
            "is_active",
            "deleted_at",
            "deleted_by",
            "is_reconciled",
            "reconciled_at",
            "reconciled_by",
            "updated_at",
        ])

        # 4. Check if this was a no-invoice payment (applied directly to outstanding_balance)
        no_invoice_marker = "Applied to outstanding balance (no invoices)"
        
        if no_invoice_marker in payment_notes and allocated_total == 0:
            # This payment was applied directly to student balances (no invoices)
            # Parse the notes to extract amounts
            outstanding_reduced = Decimal("0.00")
            credit_added = Decimal("0.00")
            
            # Parse: "reduced outstanding balance by {amount}"
            outstanding_match = re.search(
                r"reduced outstanding balance by ([\d.]+)", 
                payment_notes
            )
            if outstanding_match:
                try:
                    outstanding_reduced = Decimal(outstanding_match.group(1))
                except:
                    outstanding_reduced = Decimal("0.00")
            
            # Parse: "added to credit balance: {amount}"
            credit_match = re.search(
                r"added to credit balance: ([\d.]+)", 
                payment_notes
            )
            if credit_match:
                try:
                    credit_added = Decimal(credit_match.group(1))
                except:
                    credit_added = Decimal("0.00")
            
            # Reverse the changes
            if outstanding_reduced > 0:
                student.outstanding_balance = (
                    student.outstanding_balance or Decimal("0.00")
                ) + outstanding_reduced
            
            if credit_added > 0:
                student.credit_balance = (
                    student.credit_balance or Decimal("0.00")
                ) - credit_added
                # Ensure credit balance doesn't go negative
                student.credit_balance = max(student.credit_balance, Decimal("0.00"))
            
            student.save(update_fields=[
                "outstanding_balance", "credit_balance", "updated_at"
            ])
            
            logger.info(
                f"Payment {payment.payment_reference} deleted (no-invoice payment). "
                f"Outstanding restored=+{outstanding_reduced}, Credit adjusted=-{credit_added}"
            )
        else:
            # Standard case: payment was allocated to invoices
            # 4. CORRECTLY restore student balances
            # Payment creation ADDED unapplied credit; deletion must SUBTRACT it
            unapplied_credit = max(
                Decimal("0.00"),
                payment.amount - allocated_total
            )

            # FIX: Use correct logic for credit balance
            # During payment creation: credit_balance += unapplied_credit
            # During payment deletion: credit_balance -= unapplied_credit
            if unapplied_credit > 0:
                student.credit_balance = (
                    student.credit_balance or Decimal("0.00")
                ) - unapplied_credit
                # Ensure credit balance doesn't go negative
                student.credit_balance = max(student.credit_balance, Decimal("0.00"))
            
            # 5. Recalculate affected invoices
            for invoice in Invoice.objects.select_for_update().filter(
                id__in=invoice_ids
            ):
                InvoiceService._recalculate_invoice_fields(invoice)
            
            # 6. Recompute student's overall balances
            student.save(update_fields=["credit_balance", "updated_at"])
            student.recompute_outstanding_balance()

            logger.info(
                f"Payment {payment.payment_reference} deleted. "
                f"Allocated={allocated_total}, Credit adjusted=-{unapplied_credit}"
            )

    @staticmethod
    @db_transaction.atomic
    def restore_payment(payment: Payment):
        """Restore a soft-deleted payment and allocations, then recalculate balances."""
        if not payment or payment.is_active:
            return

        payment.is_active = True
        payment.deleted_at = None
        payment.deleted_by = None
        payment.save(update_fields=["is_active", "deleted_at", "deleted_by", "updated_at"])

        payment.allocations.filter(is_active=False).update(is_active=True, updated_at=timezone.now())

        invoice_ids = list(payment.allocations.filter(is_active=True).values_list("invoice_item__invoice_id", flat=True).distinct())
        for invoice in Invoice.objects.select_for_update().filter(id__in=invoice_ids):
            InvoiceService._recalculate_invoice_fields(invoice)

        payment.student.recompute_outstanding_balance()

    @staticmethod
    @db_transaction.atomic
    def purge_payment(payment: Payment):
        """Permanently delete a soft-deleted payment."""
        if not payment:
            return
        if payment.is_active:
            raise ValueError("Payment must be in trash before permanent purge.")
        PaymentAllocation.objects.filter(payment=payment).delete()
        Payment.objects.filter(pk=payment.pk).delete()


    # @staticmethod
    # @db_transaction.atomic
    # def delete_payment(payment: Payment):
    #     """
    #     Hard-delete a payment and its allocations and restore all derived state.
    #     """

    #     if not payment:
    #         return

    #     student = payment.student

    #     # 1. Capture allocations BEFORE deletion
    #     allocations = list(payment.allocations.all())

    #     invoice_ids = list(
    #         {a.invoice_item.invoice_id for a in allocations}
    #     )

    #     allocated_total = sum(a.amount for a in allocations)

    #     # 2. Delete allocations
    #     for alloc in allocations:
    #         alloc.delete()

    #     # 3. Delete payment
    #     Payment.objects.filter(pk=payment.pk).delete()

    #     # 4. Restore student credit balance
    #     # Payment creation subtracted this remainder; deletion must add it back
    #     unapplied_credit = max(
    #         Decimal("0.00"),
    #         payment.amount - allocated_total
    #     )

    #     if unapplied_credit > 0:
    #         student.credit_balance += unapplied_credit
    #         student.save(update_fields=["credit_balance", "updated_at"])

    #     # 5. Recalculate affected invoices
    #     for invoice in Invoice.objects.select_for_update().filter(
    #         id__in=invoice_ids
    #     ):
    #         InvoiceService._recalculate_invoice_fields(invoice)

    #     logger.info(
    #         f"Payment {payment.payment_reference} deleted. "
    #         f"Allocated={allocated_total}, Credit restored={unapplied_credit}"
    #     )


    # ---------------------------------------------------------
    # Credit helpers
    # ---------------------------------------------------------

    @staticmethod
    def get_student_unapplied_credit(student: Student) -> Decimal:
        total_payments = (
            Payment.objects.filter(
                student=student,
                is_active=True,
                status=PaymentStatus.COMPLETED,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )

        total_allocated = (
            PaymentAllocation.objects.filter(
                is_active=True,
                payment__student=student,
                payment__is_active=True,
                payment__status=PaymentStatus.COMPLETED,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )

        return max(Decimal("0.00"), total_payments - total_allocated)

    @staticmethod
    def get_student_net_account_balance(student: Student) -> Decimal:
        total_outstanding = (
            Invoice.objects.filter(student=student, is_active=True)
            .exclude(status=InvoiceStatus.CANCELLED)
            .aggregate(total=Sum("balance"))["total"]
            or Decimal("0.00")
        )

        credit = InvoiceService.get_student_unapplied_credit(student)
        return credit - total_outstanding

    # ---------------------------------------------------------
    # Core payment application
    # ---------------------------------------------------------

    @staticmethod
    @db_transaction.atomic
    def apply_payment_to_student_arrears(payment: Payment) -> Decimal:
        """
        Allocate a completed payment:
        - Oldest invoice first
        - Invoice items only (by priority)
        - balance_bf is NEVER modified
        - Remainder becomes student credit
        """
        if not payment or not payment.is_active:
            return Decimal("0.00")

        if payment.status != PaymentStatus.COMPLETED:
            logger.info(
                f"Payment {payment.payment_reference} not COMPLETED; skipping allocation."
            )
            return Decimal("0.00")

        # -----------------------------------------------------
        # Idempotency
        # -----------------------------------------------------
        existing_allocations = payment.allocations.filter(is_active=True)
        if existing_allocations.exists():
            invoice_ids = (
                existing_allocations.values_list(
                    "invoice_item__invoice_id", flat=True
                ).distinct()
            )

            for inv in Invoice.objects.select_for_update().filter(
                id__in=list(invoice_ids)
            ):
                InvoiceService._recalculate_invoice_fields(inv)

            allocated = (
                existing_allocations.aggregate(total=Sum("amount"))["total"]
                or Decimal("0.00")
            )
            return payment.amount - allocated

        remaining = payment.amount
        student = payment.student

        # SAFETY CHECK: Do not allocate payments to invoices for transferred/graduated students
        # Their invoices should be inactive, and payments should go directly to outstanding_balance
        if student.status in ['transferred', 'graduated']:
            logger.error(
                f"CRITICAL: Payment {payment.payment_reference} for {student.status} student "
                f"{student.admission_number} attempted to allocate to invoices. "
                f"This should not happen - student invoices should be inactive. "
                f"Payment will be applied directly to outstanding_balance instead."
            )
            # Return full amount as unapplied - the payment service will handle it
            return payment.amount

        invoices = (
            Invoice.objects.select_for_update()
            .filter(student=student, is_active=True)
            .exclude(status=InvoiceStatus.CANCELLED)
            .order_by(
                Coalesce("issue_date", date_cls(9999, 12, 31)).asc(),
                "created_at",
            )
        )

        # CRITICAL: Loop through ALL invoices until ALL are fully paid or payment is exhausted
        # This ensures invoices are fully cleared before any payment goes to credit_balance
        max_iterations = 10  # Safety limit to prevent infinite loops
        iteration = 0
        
        while remaining > 0 and iteration < max_iterations:
            iteration += 1
            allocated_this_iteration = Decimal('0.00')
            
            for invoice in invoices:
                if remaining <= 0:
                    break
                
                InvoiceService._recalculate_invoice_fields(invoice)
                
                if invoice.balance <= 0:
                    continue
                
                # Allocate to clear this invoice
                amount_for_invoice = min(remaining, invoice.balance)
                
                allocated = InvoiceService._allocate_amount_to_invoice_items(
                    payment=payment,
                    invoice=invoice,
                    amount_to_apply=amount_for_invoice,
                )
                
                InvoiceService._recalculate_invoice_fields(invoice)
                remaining -= allocated
                allocated_this_iteration += allocated
            
            # If no allocation happened this iteration, break to avoid infinite loop
            if allocated_this_iteration == 0:
                break
        
        # Final check: ensure ALL invoices are fully paid
        all_invoices_fully_paid = True
        for invoice in invoices:
            InvoiceService._recalculate_invoice_fields(invoice)
            if invoice.balance > 0:
                all_invoices_fully_paid = False
                if remaining > 0:
                    logger.error(
                        f"FINANCIAL INTEGRITY VIOLATION: Payment {payment.payment_reference} "
                        f"has remaining {remaining} but invoice {invoice.invoice_number} "
                        f"still has balance {invoice.balance}. Attempting to allocate remaining amount."
                    )
                    # Try one more time to allocate remaining
                    force_allocated = InvoiceService._allocate_amount_to_invoice_items(
                        payment=payment,
                        invoice=invoice,
                        amount_to_apply=min(remaining, invoice.balance),
                    )
                    InvoiceService._recalculate_invoice_fields(invoice)
                    remaining -= force_allocated
                    if force_allocated > 0:
                        logger.info(
                            f"Force-allocated {force_allocated} from remaining to invoice {invoice.invoice_number}"
                        )
                    # Re-check if invoice is now fully paid
                    InvoiceService._recalculate_invoice_fields(invoice)
                    if invoice.balance > 0:
                        all_invoices_fully_paid = False

        # Only add to credit_balance if ALL invoices are fully paid (balance === 0) AND outstanding_balance === 0
        if remaining > 0:
            # Double-check: ensure ALL invoices are fully paid
            all_paid = True
            for inv in invoices:
                InvoiceService._recalculate_invoice_fields(inv)
                if inv.balance > 0:
                    all_paid = False
                    logger.error(
                        f"CRITICAL: Cannot add to credit_balance - invoice {inv.invoice_number} "
                        f"still has balance {inv.balance}"
                    )
                    break
            
            if all_paid:
                # CRITICAL: Also verify outstanding_balance is 0 before adding to credit
                # Recompute outstanding_balance to ensure it's accurate
                student.recompute_outstanding_balance()
                
                # Double-check: outstanding_balance MUST be 0 before adding to credit
                if student.outstanding_balance > 0:
                    logger.error(
                        f"CRITICAL FINANCIAL INTEGRITY VIOLATION: Payment {payment.payment_reference} "
                        f"attempted to add {remaining} to credit_balance but student.outstanding_balance "
                        f"is {student.outstanding_balance}. Credit balance NOT increased."
                    )
                    # Don't add to credit - outstanding_balance must be 0 first
                    return payment.amount - remaining
                
                # All checks passed: invoice.balance == 0 AND outstanding_balance == 0
                student.credit_balance = (student.credit_balance or Decimal("0.00")) + remaining
                student.save(update_fields=["credit_balance", "updated_at"])

                total_allocated = payment.amount - remaining
                
                # Create a clear note explaining why funds went to credit balance
                if total_allocated == Decimal("0.00"):
                    # FULL payment went to credit - invoices exist but nothing was allocatable
                    note = f" | ⚠️ Unapplied credit: KES {remaining} (no allocatable invoice items - invoices may be fully paid or items inactive)"
                else:
                    # Partial overpayment - normal case (all invoices fully paid)
                    note = f" | Unapplied credit: KES {remaining} (all invoices fully paid, outstanding balance cleared)"
                
                if note.strip() not in (payment.notes or ""):
                    payment.notes = (payment.notes or "") + note
                    payment.save(update_fields=["notes", "updated_at"])

                logger.info(
                    f"Payment {payment.payment_reference} allocated. "
                    f"Unapplied credit={remaining} (all invoices fully paid, outstanding balance cleared)"
                )
            else:
                logger.error(
                    f"FINANCIAL INTEGRITY VIOLATION: Payment {payment.payment_reference} "
                    f"has {remaining} remaining but invoices are not fully paid. "
                    f"Credit balance NOT increased."
                )

        # -----------------------------------------------------
        # SAFETY CHECK: Warn if payment went fully to credit but
        # student has INACTIVE invoices that might need payment
        # -----------------------------------------------------
        total_allocated = payment.amount - remaining
        if total_allocated == Decimal("0.00") and remaining > 0:
            # Check for inactive invoices with positive balances
            inactive_invoices = (
                Invoice.objects.filter(
                    student=student,
                    is_active=False,  # Soft-deleted invoices
                )
                .exclude(status=InvoiceStatus.CANCELLED)
            )
            if inactive_invoices.exists():
                inactive_count = inactive_invoices.count()
                logger.error(
                    f"ALLOCATION WARNING: Payment {payment.payment_reference} for "
                    f"{student.admission_number} allocated NOTHING to invoices! "
                    f"Full amount ({payment.amount}) went to credit_balance. "
                    f"Student has {inactive_count} INACTIVE invoice(s) that may need "
                    f"to be restored. Check if invoices were accidentally soft-deleted."
                )

        return remaining
