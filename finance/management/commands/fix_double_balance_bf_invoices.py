"""
Fix invoices where total_amount incorrectly includes balance_bf (double application).

Correct design:
- total_amount = term fees only (subtotal - discount), EXCLUDING balance_bf
- balance_bf is a separate header field, added in balance formula: balance = total_amount + balance_bf - prepayment - amount_paid

Bug: When total_amount = term_fees + balance_bf, balance_bf is counted twice.

Fix: Set total_amount = term_fees only (recalculate from items excluding balance_bf/prepayment).
"""
from decimal import Decimal, ROUND_HALF_UP

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum, Q

from core.models import Organization
from finance.models import Invoice, InvoiceItem


class Command(BaseCommand):
    help = (
        "Fix invoices where total_amount incorrectly includes balance_bf. "
        "Recalculates total_amount from term-fee items only (excludes balance_bf/prepayment items)."
    )

    DEFAULT_ORGANISATION = "PCEA Wendani Academy"

    def add_arguments(self, parser):
        parser.add_argument(
            "--organisation",
            type=str,
            default=self.DEFAULT_ORGANISATION,
            help=f"Organisation to fix. Default: {self.DEFAULT_ORGANISATION!r}",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=True,
            help="Only report what would be fixed (default: True)",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually apply fixes (overrides --dry-run)",
        )

    def handle(self, *args, **options):
        org_name = (options.get("organisation") or self.DEFAULT_ORGANISATION).strip()
        dry_run = not options.get("apply", False)

        org = (
            Organization.objects.filter(name__iexact=org_name).first()
            or Organization.objects.filter(code__iexact=org_name).first()
        )
        if not org:
            self.stderr.write(
                self.style.ERROR(f"Organisation {org_name!r} not found.")
            )
            return

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN - No changes will be applied.")
            )
            self.stdout.write("Run with --apply to fix invoices.")
        else:
            self.stdout.write(
                self.style.WARNING("APPLY MODE - Changes will be saved.")
            )

        self.stdout.write("")
        self.stdout.write("Scanning for invoices with double balance_bf ...")

        invoices = (
            Invoice.objects.filter(is_active=True, balance_bf__gt=0)
            .exclude(status="cancelled")
            .filter(Q(organization=org) | Q(student__organization=org))
            .select_related("student", "term")
        )

        fixed = []
        for inv in invoices:
            # Correct billed = sum of term-fee items only (exclude balance_bf, prepayment)
            term_items = inv.items.filter(is_active=True).exclude(
                category__in=["balance_bf", "prepayment"]
            )
            agg = term_items.aggregate(
                total=Sum("amount"), discount=Sum("discount_applied")
            )
            correct_total = (agg["total"] or Decimal("0")) - (
                agg["discount"] or Decimal("0")
            )
            correct_total = correct_total.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            actual_total = (inv.total_amount or Decimal("0")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            balance_bf = inv.balance_bf or Decimal("0")

            # Detect double: actual_total ≈ correct_total + balance_bf
            if balance_bf > 0 and abs(actual_total - (correct_total + balance_bf)) < Decimal("0.01"):
                fixed.append({
                    "invoice": inv,
                    "old_total": actual_total,
                    "new_total": correct_total,
                    "balance_bf": balance_bf,
                })

        self.stdout.write("")
        self.stdout.write(f"Found {len(fixed)} invoice(s) with double balance_bf.")
        self.stdout.write("")

        for item in fixed:
            inv = item["invoice"]
            self.stdout.write(
                f"  {inv.invoice_number} ({inv.student.admission_number} {inv.student.full_name}):"
            )
            self.stdout.write(
                f"    total_amount: {item['old_total']} → {item['new_total']} "
                f"(balance_bf={item['balance_bf']} was double-counted)"
            )

            if not dry_run:
                with transaction.atomic():
                    inv.subtotal = (
                        inv.items.filter(is_active=True)
                        .exclude(category__in=["balance_bf", "prepayment"])
                        .aggregate(t=Sum("amount"))["t"]
                        or Decimal("0")
                    )
                    inv.discount_amount = (
                        inv.items.filter(is_active=True)
                        .exclude(category__in=["balance_bf", "prepayment"])
                        .aggregate(t=Sum("discount_applied"))["t"]
                        or Decimal("0")
                    )
                    inv.total_amount = inv.subtotal - inv.discount_amount
                    inv.save(update_fields=["subtotal", "discount_amount", "total_amount"])
                    self.stdout.write(
                        self.style.SUCCESS(f"    ✓ Fixed {inv.invoice_number}")
                    )

        self.stdout.write("")
        if dry_run and fixed:
            self.stdout.write(
                "To apply fixes, run: python manage.py fix_double_balance_bf_invoices --apply"
            )
        self.stdout.write("Done.")
