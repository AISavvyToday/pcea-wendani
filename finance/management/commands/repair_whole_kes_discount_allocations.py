from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import PaymentStatus
from finance.models import Invoice
from finance.views import InvoiceEditView
from payments.models import PaymentAllocation
from payments.services.invoice import InvoiceService


class Command(BaseCommand):
    help = "Round discounted invoice items and payment allocations back to whole KES."

    def add_arguments(self, parser):
        parser.add_argument("--organization-code", default="PCEA_WENDANI")
        parser.add_argument("--year", type=int, default=2026)
        parser.add_argument("--term", default="term_2")
        parser.add_argument("--invoice-number")
        parser.add_argument("--payment-reference")
        parser.add_argument("--apply", action="store_true", help="Persist the repair. Default is dry-run.")

    def handle(self, *args, **options):
        apply = options["apply"]
        qs = Invoice.objects.filter(
            organization__code=options["organization_code"],
            term__academic_year__year=options["year"],
            term__term=options["term"],
            is_active=True,
        ).select_related("student", "term", "organization")

        if options.get("invoice_number"):
            qs = qs.filter(invoice_number=options["invoice_number"])

        if options.get("payment_reference"):
            invoice_ids = PaymentAllocation.objects.filter(
                payment__payment_reference=options["payment_reference"],
                is_active=True,
            ).values_list("invoice_item__invoice_id", flat=True).distinct()
            qs = qs.filter(id__in=list(invoice_ids))

        invoices = list(qs.order_by("invoice_number"))
        if not invoices:
            raise CommandError("No matching invoices found.")

        self.stdout.write(self.style.WARNING("DRY RUN - no data changed.") if not apply else self.style.SUCCESS("APPLYING repair."))

        changed_invoices = 0
        changed_allocations = 0
        for invoice in invoices:
            item_cents = self._count_item_cents(invoice)
            allocation_cents = self._count_allocation_cents(invoice)
            if not item_cents and not allocation_cents:
                continue

            self.stdout.write(
                f"{invoice.invoice_number} {invoice.student.admission_number} "
                f"{invoice.student.full_name}: discount={invoice.discount_amount}, "
                f"item_cents={item_cents}, allocation_cents={allocation_cents}"
            )

            if apply:
                repaired_allocations = self._repair_invoice(invoice)
                changed_allocations += repaired_allocations

            changed_invoices += 1

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. invoices_reviewed={len(invoices)}, invoices_needing_repair={changed_invoices}, "
                f"allocations_rebuilt={changed_allocations}"
            )
        )

    def _has_cents(self, amount):
        amount = amount or Decimal("0.00")
        return amount != amount.quantize(Decimal("1"))

    def _count_item_cents(self, invoice):
        count = 0
        for item in invoice.items.filter(is_active=True):
            if self._has_cents(item.discount_applied) or self._has_cents(item.net_amount):
                count += 1
        return count

    def _count_allocation_cents(self, invoice):
        return sum(
            1
            for allocation in PaymentAllocation.objects.filter(
                is_active=True,
                invoice_item__invoice=invoice,
                payment__is_active=True,
                payment__status=PaymentStatus.COMPLETED,
            ).only("amount")
            if self._has_cents(allocation.amount)
        )

    def _repair_invoice(self, invoice):
        with transaction.atomic():
            locked_invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
            allocations = list(
                PaymentAllocation.objects.select_for_update().filter(
                    is_active=True,
                    invoice_item__invoice=locked_invoice,
                    payment__is_active=True,
                    payment__status=PaymentStatus.COMPLETED,
                ).select_related("payment", "invoice_item")
            )
            payment_totals = defaultdict(lambda: Decimal("0.00"))
            payments = {}
            for allocation in allocations:
                payment_totals[allocation.payment_id] += allocation.amount or Decimal("0.00")
                payments[allocation.payment_id] = allocation.payment

            InvoiceEditView().recalculate_invoice_totals(
                locked_invoice,
                discount_amount=locked_invoice.discount_amount or Decimal("0.00"),
            )
            locked_invoice.save()

            rebuilt = 0
            if allocations:
                PaymentAllocation.objects.filter(id__in=[allocation.id for allocation in allocations]).update(
                    is_active=False,
                    updated_at=timezone.now(),
                )
                for payment_id, amount in sorted(
                    payment_totals.items(),
                    key=lambda pair: (payments[pair[0]].payment_date, payments[pair[0]].id),
                ):
                    rebuilt_amount = InvoiceService._allocate_amount_to_invoice_items(
                        payment=payments[payment_id],
                        invoice=locked_invoice,
                        amount_to_apply=amount,
                    )
                    if rebuilt_amount != amount:
                        raise CommandError(
                            f"Could not rebuild allocations for {locked_invoice.invoice_number}: "
                            f"expected {amount}, rebuilt {rebuilt_amount}"
                        )
                rebuilt = len(allocations)

            InvoiceService._recalculate_invoice_fields(locked_invoice)
            return rebuilt
