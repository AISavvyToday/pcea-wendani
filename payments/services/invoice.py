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

from core.models import InvoiceStatus, PaymentStatus
from finance.models import Invoice, InvoiceItem
from payments.models import Payment, PaymentAllocation
from students.models import Student

logger = logging.getLogger(__name__)


class InvoiceService:
    """Service for managing invoice updates from payments (allocation-only model)."""

    PRIORITY_ORDER = [
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
        """
        allocations_total = InvoiceService._sum_allocations_for_invoice(invoice)

        invoice.amount_paid = allocations_total
        invoice.balance = (
            invoice.total_amount
            + invoice.balance_bf
            + invoice.prepayment
            - invoice.amount_paid
        )

        today = date_cls.today()

        if invoice.balance <= 0:
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

        invoices = (
            Invoice.objects.select_for_update()
            .filter(student=student, is_active=True)
            .exclude(status=InvoiceStatus.CANCELLED)
            .order_by(
                Coalesce("issue_date", date_cls(9999, 12, 31)).asc(),
                "created_at",
            )
        )

        for invoice in invoices:
            if remaining <= 0:
                break

            InvoiceService._recalculate_invoice_fields(invoice)

            if invoice.balance <= 0:
                continue

            amount_for_invoice = min(remaining, invoice.balance)

            allocated = InvoiceService._allocate_amount_to_invoice_items(
                payment=payment,
                invoice=invoice,
                amount_to_apply=amount_for_invoice,
            )

            InvoiceService._recalculate_invoice_fields(invoice)
            remaining -= allocated

        # -----------------------------------------------------
        # Remaining → student credit
        # -----------------------------------------------------
        if remaining > 0:
            student.credit_balance -= remaining
            student.save(update_fields=["credit_balance", "updated_at"])

            note = f" | Unapplied credit: KES {remaining}"
            if note.strip() not in (payment.notes or ""):
                payment.notes = (payment.notes or "") + note
                payment.save(update_fields=["notes", "updated_at"])

            logger.info(
                f"Payment {payment.payment_reference} allocated. "
                f"Unapplied credit={remaining}"
            )

        return remaining
