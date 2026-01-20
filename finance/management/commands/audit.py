from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum, Q

from students.models import Student
from finance.models import Invoice


class Command(BaseCommand):
    help = (
        "Audit financial consistency between Student and Invoice records:\n"
        "- student.outstanding_balance vs sum of active invoice balances\n"
        "- student.credit_balance invariants with/without invoices\n"
        "- invoice.balance correctness vs header fields (subtotal, discount, "
        "balance_bf, prepayment, amount_paid)"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=True,
            help="Do NOT change any data (default: True). This command is read-only by design.",
        )

    def handle(self, *args, **options):
        """
        NOTE: This command is intentionally read-only. The --dry-run flag is accepted
        for compatibility with other commands, but no writes are performed.
        """
        dry_run = options["dry_run"]
        if not dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "This audit command is read-only. "
                    "No writes will be performed even with --dry-run=False."
                )
            )

        self.stdout.write("")
        self.stdout.write("=" * 80)
        self.stdout.write("🧮 FINANCIAL AUDIT – STUDENTS & INVOICES")
        self.stdout.write("=" * 80)

        stats = {
            "students_total": 0,
            "students_with_invoices": 0,
            "students_without_invoices": 0,
            "outstanding_mismatches": [],
            "credit_invariant_violations": [],
            "no_invoice_invariant_violations": [],
            "invoice_balance_mismatches": [],
        }

        self._audit_students(stats)
        self._audit_invoices(stats)
        self._print_summary(stats)

    # ------------------------------------------------------------------ #
    # Student-level checks
    # ------------------------------------------------------------------ #

    def _audit_students(self, stats):
        """
        1) If a student has invoices:
           - student.outstanding_balance MUST equal sum(active invoice.balance)
             (over all active, non-cancelled invoices).
           - student.credit_balance > 0 is only allowed when:
               • all active invoices are fully paid (balance <= 0), and
               • credit_balance reflects overpayments (payments allocation handles this).

        2) If a student has NO active invoices:
           - outstanding_balance MUST equal balance_bf_original
           - credit_balance MUST equal prepayment_original
        """
        students = Student.objects.all().prefetch_related("invoices")
        stats["students_total"] = students.count()

        self.stdout.write("")
        self.stdout.write("→ Auditing students ...")

        for student in students:
            invoices_qs = student.invoices.filter(is_active=True).exclude(
                status="cancelled"
            )
            has_invoices = invoices_qs.exists()

            if has_invoices:
                stats["students_with_invoices"] += 1
                self._check_student_with_invoices(student, invoices_qs, stats)
            else:
                stats["students_without_invoices"] += 1
                self._check_student_without_invoices(student, stats)

    def _check_student_with_invoices(self, student, invoices_qs, stats):
        # Sum of active invoice balances
        expected_outstanding = (
            invoices_qs.aggregate(total=Sum("balance"))["total"] or Decimal("0.00")
        )
        actual_outstanding = student.outstanding_balance or Decimal("0.00")

        if expected_outstanding != actual_outstanding:
            stats["outstanding_mismatches"].append(
                {
                    "student_id": student.id,
                    "admission": student.admission_number,
                    "name": student.full_name,
                    "expected_outstanding": expected_outstanding,
                    "actual_outstanding": actual_outstanding,
                }
            )

        # Credit invariant:
        # - If credit_balance > 0, all invoices should be effectively paid
        #   (balance <= 0). Overpayments should have been pushed into credit_balance
        #   via payment allocation logic.
        credit_balance = student.credit_balance or Decimal("0.00")
        if credit_balance > 0:
            unpaid_exists = invoices_qs.filter(balance__gt=0).exists()
            if unpaid_exists:
                stats["credit_invariant_violations"].append(
                    {
                        "student_id": student.id,
                        "admission": student.admission_number,
                        "name": student.full_name,
                        "credit_balance": credit_balance,
                        "has_unpaid_invoices": True,
                    }
                )

    def _check_student_without_invoices(self, student, stats):
        expected_outstanding = student.balance_bf_original or Decimal("0.00")
        expected_credit = student.prepayment_original or Decimal("0.00")

        actual_outstanding = student.outstanding_balance or Decimal("0.00")
        actual_credit = student.credit_balance or Decimal("0.00")

        if (
            expected_outstanding != actual_outstanding
            or expected_credit != actual_credit
        ):
            stats["no_invoice_invariant_violations"].append(
                {
                    "student_id": student.id,
                    "admission": student.admission_number,
                    "name": student.full_name,
                    "expected_outstanding": expected_outstanding,
                    "actual_outstanding": actual_outstanding,
                    "expected_credit": expected_credit,
                    "actual_credit": actual_credit,
                }
            )

    # ------------------------------------------------------------------ #
    # Invoice-level checks
    # ------------------------------------------------------------------ #

    def _audit_invoices(self, stats):
        """
        Verify that invoice.balance is consistent with header fields.

        Based on the system's single-source-of-truth logic:
          - total_amount is already net of discount_amount
          - prepayment is stored as NEGATIVE when there is credit
          - balance should be:

              balance = total_amount + balance_bf + prepayment - amount_paid
        """
        self.stdout.write("")
        self.stdout.write("→ Auditing invoices ...")

        invoices = (
            Invoice.objects.filter(is_active=True)
            .exclude(status="cancelled")
            .select_related("student", "term")
        )

        for inv in invoices:
            expected_balance = (
                (inv.total_amount or Decimal("0.00"))
                + (inv.balance_bf or Decimal("0.00"))
                + (inv.prepayment or Decimal("0.00"))
                - (inv.amount_paid or Decimal("0.00"))
            )

            actual_balance = inv.balance or Decimal("0.00")

            if expected_balance != actual_balance:
                stats["invoice_balance_mismatches"].append(
                    {
                        "invoice_id": inv.id,
                        "invoice_number": inv.invoice_number,
                        "student_admission": getattr(inv.student, "admission_number", ""),
                        "student_name": getattr(inv.student, "full_name", ""),
                        "expected_balance": expected_balance,
                        "actual_balance": actual_balance,
                        "subtotal": inv.subtotal,
                        "discount_amount": inv.discount_amount,
                        "total_amount": inv.total_amount,
                        "balance_bf": inv.balance_bf,
                        "prepayment": inv.prepayment,
                        "amount_paid": inv.amount_paid,
                    }
                )

    # ------------------------------------------------------------------ #
    # Reporting
    # ------------------------------------------------------------------ #

    def _print_summary(self, stats):
        self.stdout.write("")
        self.stdout.write("=" * 80)
        self.stdout.write("📊 AUDIT SUMMARY")
        self.stdout.write("=" * 80)

        self.stdout.write(
            f"Total students: {stats['students_total']} "
            f"(with invoices: {stats['students_with_invoices']}, "
            f"without invoices: {stats['students_without_invoices']})"
        )

        self.stdout.write("")
        self.stdout.write(
            f"Student outstanding_balance mismatches: "
            f"{len(stats['outstanding_mismatches'])}"
        )
        for m in stats["outstanding_mismatches"][:10]:
            self.stdout.write(
                f"  - {m['admission']} {m['name']}: "
                f"expected {m['expected_outstanding']}, "
                f"actual {m['actual_outstanding']}"
            )

        self.stdout.write("")
        self.stdout.write(
            f"Student credit_balance invariants (with invoices) violated: "
            f"{len(stats['credit_invariant_violations'])}"
        )
        for m in stats["credit_invariant_violations"][:10]:
            self.stdout.write(
                f"  - {m['admission']} {m['name']}: "
                f"credit_balance={m['credit_balance']} with unpaid invoices"
            )

        self.stdout.write("")
        self.stdout.write(
            f"Students without invoices but mismatched frozen fields: "
            f"{len(stats['no_invoice_invariant_violations'])}"
        )
        for m in stats["no_invoice_invariant_violations"][:10]:
            self.stdout.write(
                f"  - {m['admission']} {m['name']}: "
                f"outstanding (exp {m['expected_outstanding']}, "
                f"act {m['actual_outstanding']}), "
                f"credit (exp {m['expected_credit']}, "
                f"act {m['actual_credit']})"
            )

        self.stdout.write("")
        self.stdout.write(
            f"Invoice balance mismatches: "
            f"{len(stats['invoice_balance_mismatches'])}"
        )
        for m in stats["invoice_balance_mismatches"][:10]:
            self.stdout.write(
                f"  - {m['invoice_number']} "
                f"({m['student_admission']} {m['student_name']}): "
                f"expected {m['expected_balance']}, "
                f"actual {m['actual_balance']}"
            )

        self.stdout.write("")
        self.stdout.write("✅ Audit completed (no data was modified).")


