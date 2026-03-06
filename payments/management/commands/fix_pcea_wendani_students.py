from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum

from core.models import Organization, PaymentStatus
from students.models import Student
from finance.models import Invoice, InvoiceItem
from payments.models import Payment, PaymentAllocation


class Command(BaseCommand):
    """
    Targeted data-fix command for PCEA Wendani Academy.

    Fixes:
    1. Student organisation linkage:
       - Sets the organization for Aubrey Mwikali Ndolo (adm 3301) where it is missing.
    2. Payment allocation gap for Maya Tamara (adm 2601):
       - Ensures that total payment allocations match payment amounts so that
         no spurious "credit" appears on receipts.

    The command is *safe by default*:
    - Runs in DRY-RUN mode unless --apply is provided.
    - Prints a detailed plan of what it WILL do before making any changes.
    """

    help = "Fix specific student and payment issues for PCEA Wendani Academy (Aubrey 3301, Maya 2601)."

    DEFAULT_ORGANISATION = "PCEA Wendani Academy"

    def add_arguments(self, parser):
        parser.add_argument(
            "--organisation",
            type=str,
            default=Command.DEFAULT_ORGANISATION,
            help=(
                "Organisation name (or code) to run the fixes on. "
                f"Default: {Command.DEFAULT_ORGANISATION!r}"
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=True,
            help=(
                "Dry-run mode (NO changes will be written). "
                "This is the default."
            ),
        )
        parser.add_argument(
            "--apply",
            action="store_false",
            dest="dry_run",
            help="Apply the fixes to the database (turns off dry-run).",
        )

    def handle(self, *args, **options):
        organisation_arg = (options.get("organisation") or self.DEFAULT_ORGANISATION).strip()
        dry_run = options["dry_run"]

        if not organisation_arg:
            raise CommandError(
                "Organisation name/code cannot be empty. "
                f"Default: {self.DEFAULT_ORGANISATION!r}"
            )

        org = (
            Organization.objects.filter(name__iexact=organisation_arg).first()
            or Organization.objects.filter(code__iexact=organisation_arg).first()
        )
        if not org:
            raise CommandError(
                f"Organisation {organisation_arg!r} not found. "
                "Check the name/code or create it in Django admin."
            )

        mode = "DRY-RUN (no changes written)" if dry_run else "APPLY (changes will be written)"
        self.stdout.write("")
        self.stdout.write("=" * 80)
        self.stdout.write("🛠  FIX PCEA WENDANI STUDENT / PAYMENT ISSUES")
        self.stdout.write(f"Organisation: {org.name} ({org.code})")
        self.stdout.write(f"Mode       : {mode}")
        self.stdout.write("=" * 80)
        self.stdout.write("")

        # 1. Fix Aubrey Mwikali Ndolo (adm 3301) organisation linkage
        self._fix_aubrey_organisation(org, dry_run)

        # 2. Fix Maya Tamara (adm 2601) payment allocation gap
        self._fix_maya_payment_allocations(org, dry_run)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Done. Review output above for details."))

    # ------------------------------------------------------------------ #
    # 1) Aubrey Mwikali Ndolo (adm 3301) – missing organisation
    # ------------------------------------------------------------------ #
    def _fix_aubrey_organisation(self, org, dry_run: bool):
        admission = "3301"
        self.stdout.write("")
        self.stdout.write("-" * 80)
        self.stdout.write(f"1) Checking organisation linkage for Aubrey (adm {admission}) ...")

        students_qs = Student.objects.filter(admission_number=admission)

        if not students_qs.exists():
            self.stdout.write(
                self.style.WARNING(
                    f"  • No student found with admission_number={admission!r}. "
                    "Nothing to do."
                )
            )
            return

        for student in students_qs:
            self.stdout.write(
                f"  • Found student: {student.full_name} "
                f"(adm {student.admission_number}, "
                f"org_id={student.organization_id}, status={student.status}, is_active={student.is_active})"
            )

            if student.organization_id == org.id:
                self.stdout.write(
                    self.style.SUCCESS(
                        "    - Student already linked to correct organisation. No change needed."
                    )
                )
                continue

            if student.organization_id is None:
                self.stdout.write(
                    "    - organisation_id is NULL. "
                    f"Will set organisation to {org.name} ({org.id})."
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"    - organisation_id currently points to a different org ({student.organization_id}). "
                        f"Will re-link to {org.name} ({org.id})."
                    )
                )

            if not dry_run:
                student.organization = org
                student.save(update_fields=["organization"])
                self.stdout.write(
                    self.style.SUCCESS(
                        f"    ✓ Updated student {student.admission_number} organisation to {org.code}."
                    )
                )
            else:
                self.stdout.write(
                    self.style.NOTICE(
                        "    (dry-run) Would update organisation field for this student."
                    )
                )

    # ------------------------------------------------------------------ #
    # 2) Maya Tamara (adm 2601) – payment allocation gap / phantom credit
    # ------------------------------------------------------------------ #
    def _fix_maya_payment_allocations(self, org, dry_run: bool):
        admission = "2601"
        self.stdout.write("")
        self.stdout.write("-" * 80)
        self.stdout.write(f"2) Checking payment allocations for Maya (adm {admission}) ...")

        student = (
            Student.objects.filter(organization=org, admission_number=admission)
            .select_related("organization")
            .first()
        )

        if not student:
            self.stdout.write(
                self.style.WARNING(
                    f"  • Student with admission_number={admission!r} not found in organisation {org.name!r}."
                )
            )
            return

        self.stdout.write(
            f"  • Found student: {student.full_name} "
            f"(adm {student.admission_number}, outstanding={student.outstanding_balance}, "
            f"credit={student.credit_balance})"
        )

        current_invoices = Invoice.objects.filter(student=student, is_active=True)
        if not current_invoices.exists():
            self.stdout.write(
                self.style.WARNING(
                    "  • Student has no active invoices. Nothing to do for allocation fix."
                )
            )
            return

        payments = Payment.objects.filter(
            student=student,
            is_active=True,
            status=PaymentStatus.COMPLETED,
        ).order_by("payment_date", "created_at")

        if not payments.exists():
            self.stdout.write(
                self.style.WARNING(
                    "  • Student has no completed payments. Nothing to do."
                )
            )
            return

        self.stdout.write("  • Inspecting payments vs allocations:")
        total_payments = Decimal("0.00")
        total_allocations = Decimal("0.00")
        to_fix = []

        for payment in payments:
            payment_total = payment.amount or Decimal("0.00")
            total_payments += payment_total

            allocations_total = (
                PaymentAllocation.objects.filter(
                    payment=payment,
                    invoice_item__invoice__in=current_invoices,
                    is_active=True,
                ).aggregate(total=Sum("amount"))["total"]
                or Decimal("0.00")
            )
            total_allocations += allocations_total

            diff = (payment_total - allocations_total).quantize(Decimal("0.01"))

            self.stdout.write(
                f"    - Payment {payment.payment_reference}: amount={payment_total}, "
                f"allocated={allocations_total}, diff={diff}"
            )

            if diff > Decimal("0.00"):
                to_fix.append((payment, diff))
            elif diff < Decimal("0.00"):
                # Over-allocation should never happen; flag loudly but do not auto-fix.
                self.stdout.write(
                    self.style.ERROR(
                        f"      ! Over-allocation detected for {payment.payment_reference}: "
                        f"allocations exceed payment by {-diff}. Manual review required."
                    )
                )

        self.stdout.write("")
        self.stdout.write(
            f"  • Totals: payments={total_payments}, allocations={total_allocations}, "
            f"overall_diff={(total_payments - total_allocations).quantize(Decimal('0.01'))}"
        )

        if not to_fix:
            self.stdout.write(
                self.style.SUCCESS(
                    "  • No positive allocation gaps detected for this student. Nothing to fix."
                )
            )
            return

        # Choose a target invoice + item for additional allocations.
        # For simplicity and determinism, use the latest active invoice and its largest item.
        target_invoice = current_invoices.order_by("-issue_date", "-created_at").first()
        if not target_invoice:
            self.stdout.write(
                self.style.ERROR(
                    "  • Could not determine a target invoice for additional allocations."
                )
            )
            return

        target_item = (
            InvoiceItem.objects.filter(invoice=target_invoice)
            .order_by("-amount", "id")
            .first()
        )
        if not target_item:
            self.stdout.write(
                self.style.ERROR(
                    f"  • Invoice {target_invoice.invoice_number} has no items. Cannot create allocations."
                )
            )
            return

        self.stdout.write(
            f"  • Will allocate missing amounts to invoice {target_invoice.invoice_number} "
            f"item '{target_item.description}' (category={target_item.category}, amount={target_item.amount})."
        )

        for payment, gap in to_fix:
            self.stdout.write(
                f"    - Missing allocation for payment {payment.payment_reference}: "
                f"gap={gap} → will create PaymentAllocation to "
                f"{target_invoice.invoice_number} / '{target_item.description}'."
            )

            if not dry_run:
                PaymentAllocation.objects.create(
                    payment=payment,
                    invoice_item=target_item,
                    amount=gap,
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"      ✓ Created allocation of {gap} for payment {payment.payment_reference}."
                    )
                )
            else:
                self.stdout.write(
                    self.style.NOTICE(
                        "      (dry-run) Would create this PaymentAllocation."
                    )
                )

        if not dry_run:
            # Refresh aggregates for logging purposes (student balances are already correct).
            refreshed_allocations = (
                PaymentAllocation.objects.filter(
                    payment__student=student,
                    invoice_item__invoice__in=current_invoices,
                    is_active=True,
                ).aggregate(total=Sum("amount"))["total"]
                or Decimal("0.00")
            )
            refreshed_payments = (
                Payment.objects.filter(
                    student=student,
                    is_active=True,
                    status=PaymentStatus.COMPLETED,
                ).aggregate(total=Sum("amount"))["total"]
                or Decimal("0.00")
            )

            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(
                    "  • After fix: payments={0}, allocations={1}, diff={2}".format(
                        refreshed_payments,
                        refreshed_allocations,
                        (refreshed_payments - refreshed_allocations).quantize(Decimal("0.01")),
                    )
                )
            )

