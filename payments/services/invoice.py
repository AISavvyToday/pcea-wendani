# payments/services/invoice.py
from decimal import Decimal
import logging

from django.db import transaction
from django.db.models import Sum

from core.models import InvoiceStatus, PaymentStatus
from finance.models import Invoice
from payments.models import Payment, PaymentAllocation

logger = logging.getLogger(__name__)


class InvoiceService:
    """
    Payment allocation service.
    Payments NEVER touch balance_bf or prepayment.
    """

    PRIORITY_ORDER = ["tuition", "meals", "examination", "activity", "transport"]

    @staticmethod
    def _priority_key(category):
        try:
            return InvoiceService.PRIORITY_ORDER.index(category)
        except ValueError:
            return 999

    @staticmethod
    def _sum_allocations(invoice):
        return (
            PaymentAllocation.objects.filter(
                is_active=True,
                invoice_item__invoice=invoice,
                payment__status=PaymentStatus.COMPLETED,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )

    @staticmethod
    def _recalculate_invoice_from_allocations(invoice):
        """
        amount_paid = sum(payment allocations)
        balance/status handled by Invoice.save()
        """
        invoice.amount_paid = InvoiceService._sum_allocations(invoice)
        invoice.save(update_fields=["amount_paid", "updated_at"])
        return invoice

    @staticmethod
    @transaction.atomic
    def apply_payment(payment: Payment):
        if payment.status != PaymentStatus.COMPLETED or not payment.is_active:
            return Decimal("0.00")

        # Idempotency
        if payment.allocations.filter(is_active=True).exists():
            invoices = (
                Invoice.objects.filter(
                    items__allocations__payment=payment
                ).distinct()
            )
            for inv in invoices:
                InvoiceService._recalculate_invoice_from_allocations(inv)

            allocated = payment.allocations.aggregate(
                total=Sum("amount")
            )["total"] or Decimal("0.00")

            return payment.amount - allocated

        remaining = payment.amount

        invoices = (
            Invoice.objects.select_for_update()
            .filter(student=payment.student, is_active=True)
            .exclude(status=InvoiceStatus.CANCELLED)
            .order_by("issue_date", "created_at")
        )

        for invoice in invoices:
            if remaining <= 0:
                break

            InvoiceService._recalculate_invoice_from_allocations(invoice)

            if invoice.balance <= 0:
                continue

            items = list(invoice.items.filter(is_active=True))
            items.sort(key=lambda i: (InvoiceService._priority_key(i.category), i.id))

            for item in items:
                if remaining <= 0:
                    break

                already = (
                    PaymentAllocation.objects.filter(
                        is_active=True,
                        invoice_item=item,
                        payment__status=PaymentStatus.COMPLETED,
                    ).aggregate(total=Sum("amount"))["total"]
                    or Decimal("0.00")
                )

                due = item.net_amount - already
                if due <= 0:
                    continue

                applied = min(due, remaining)

                PaymentAllocation.objects.create(
                    payment=payment,
                    invoice_item=item,
                    amount=applied,
                )

                remaining -= applied

            InvoiceService._recalculate_invoice_from_allocations(invoice)

        # Remaining becomes credit
        if remaining > 0:
            student = payment.student
            student.credit_balance -= remaining
            student.save(update_fields=["credit_balance", "updated_at"])

        return remaining
