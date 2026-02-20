"""
Investigate students 2637 and 2632 for double balance_bf application.

Dumps invoice details to diagnose: total_amount inflated by balance_bf
(when total_amount = term_fees + balance_bf instead of term_fees only).
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum

from students.models import Student
from finance.models import Invoice, InvoiceItem


class Command(BaseCommand):
    help = "Investigate students PWA2637 and PWA2632 for double balance_bf in invoice total"

    def handle(self, *args, **options):
        admissions = ["PWA2637", "PWA2632", "2637", "2632"]

        for adm in admissions:
            student = Student.objects.filter(
                admission_number__icontains=adm
            ).select_related("organization").first()
            if not student:
                continue

            self.stdout.write("")
            self.stdout.write("=" * 80)
            self.stdout.write(f"STUDENT: {student.full_name} (Adm: {student.admission_number})")
            self.stdout.write("=" * 80)
            self.stdout.write(
                f"  balance_bf_original: {student.balance_bf_original or 0}"
            )
            self.stdout.write(
                f"  prepayment_original: {student.prepayment_original or 0}"
            )
            self.stdout.write(
                f"  outstanding_balance: {student.outstanding_balance or 0}"
            )
            self.stdout.write(
                f"  credit_balance: {student.credit_balance or 0}"
            )

            invoices = Invoice.objects.filter(
                student=student, is_active=True
            ).exclude(status="cancelled").select_related("term").order_by("term__academic_year__year", "term__term")

            for inv in invoices:
                self.stdout.write("")
                self.stdout.write(f"  --- Invoice {inv.invoice_number} ({inv.term}) ---")
                self.stdout.write(
                    f"    subtotal: {inv.subtotal}, discount: {inv.discount_amount}, "
                    f"total_amount: {inv.total_amount}"
                )
                self.stdout.write(
                    f"    balance_bf (header): {inv.balance_bf}, prepayment: {inv.prepayment}"
                )
                self.stdout.write(
                    f"    amount_paid: {inv.amount_paid}, balance: {inv.balance}"
                )

                # Sum items by category
                term_items = inv.items.filter(is_active=True).exclude(
                    category__in=["balance_bf", "prepayment"]
                )
                bf_items = inv.items.filter(
                    is_active=True, category="balance_bf"
                )
                prepay_items = inv.items.filter(
                    is_active=True, category="prepayment"
                )

                term_sum = term_items.aggregate(
                    total=Sum("amount"), discount=Sum("discount_applied")
                )
                term_total = (term_sum["total"] or Decimal("0")) - (
                    term_sum["discount"] or Decimal("0")
                )
                bf_sum = bf_items.aggregate(total=Sum("amount"))["total"] or Decimal("0")
                prepay_sum = prepay_items.aggregate(total=Sum("amount"))["total"] or Decimal("0")

                self.stdout.write("")
                self.stdout.write("    Item breakdown:")
                self.stdout.write(
                    f"      Term-fee items sum (excl bf/prepay): {term_total}"
                )
                self.stdout.write(f"      Balance B/F items sum: {bf_sum}")
                self.stdout.write(f"      Prepayment items sum: {prepay_sum}")

                # Check for double counting
                expected_billed = term_total
                actual_total = inv.total_amount or Decimal("0")
                balance_bf = inv.balance_bf or Decimal("0")

                if balance_bf > 0 and abs(actual_total - (expected_billed + balance_bf)) < Decimal("0.01"):
                    self.stdout.write(
                        self.style.ERROR(
                            f"    ⚠️  DOUBLE BALANCE_BF: total_amount ({actual_total}) = "
                            f"term_fees ({expected_billed}) + balance_bf ({balance_bf})"
                        )
                    )
                elif abs(actual_total - expected_billed) > Decimal("0.01"):
                    self.stdout.write(
                        self.style.WARNING(
                            f"    ⚠️  total_amount ({actual_total}) != term_fees ({expected_billed})"
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"    ✓ total_amount correctly = term_fees only"
                        )
                    )

                # List all items
                self.stdout.write("")
                self.stdout.write("    All items:")
                for it in inv.items.filter(is_active=True).order_by("category"):
                    self.stdout.write(
                        f"      - {it.category}: {it.description} | "
                        f"amount={it.amount}, discount={it.discount_applied}, "
                        f"net={it.net_amount}"
                    )

        self.stdout.write("")
        self.stdout.write("=" * 80)
        self.stdout.write("Investigation complete.")
