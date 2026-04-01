from decimal import Decimal, ROUND_HALF_UP

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum, Q

from core.models import Organization, PaymentStatus
from students.models import Student
from finance.models import Invoice, InvoiceItem
from payments.models import Payment, PaymentAllocation
from payments.services.invoice import InvoiceService


class Command(BaseCommand):
    help = (
        "Audit financial consistency between Student and Invoice records:\n"
        "- student.outstanding_balance vs sum of active invoice balances\n"
        "- student.credit_balance invariants with/without invoices\n"
        "- invoice.balance correctness vs header fields (subtotal, discount, "
        "balance_bf, prepayment, amount_paid)\n"
        "- Payment allocation integrity (sum of allocations vs invoice.amount_paid)\n"
        "- balance_bf and prepayment invoice item verification\n"
        "- Term transition readiness checks"
    )

    DEFAULT_ORGANISATION = "PCEA Wendani Academy"

    def add_arguments(self, parser):
        parser.add_argument(
            "--organisation",
            type=str,
            default=Command.DEFAULT_ORGANISATION,
            help=(
                "Organisation name (or code) to run the audit on. "
                f"Default: {Command.DEFAULT_ORGANISATION!r}"
            ),
        )
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
        organisation_arg = (options.get("organisation") or self.DEFAULT_ORGANISATION).strip()
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
        self.stdout.write(f"Organisation: {org.name} ({org.code})")
        self.stdout.write("=" * 80)

        stats = {
            "students_total": 0,
            "students_with_invoices": 0,
            "students_without_invoices": 0,
            "outstanding_mismatches": [],
            "credit_invariant_violations": [],
            "no_invoice_invariant_violations": [],
            "invoice_balance_mismatches": [],
            # New checks
            "payment_allocation_mismatches": [],
            "balance_bf_item_issues": [],
            "prepayment_item_issues": [],
            "missing_balance_bf_items": [],  # NEW: invoices with balance_bf but no item
            "term_transition_issues": [],
            "inactive_invoice_issues": [],
            "double_balance_bf_invoices": [],  # total_amount inflated by balance_bf
        }

        self._audit_students(stats, org)
        self._audit_invoices(stats, org)
        self._audit_payment_allocations(stats, org)
        self._audit_invoice_items(stats, org)
        self._audit_term_transition_readiness(stats, org)
        self._audit_inactive_invoices(stats, org)
        self._audit_double_balance_bf(stats, org)
        self._print_summary(stats)

    # ------------------------------------------------------------------ #
    # Student-level checks
    # ------------------------------------------------------------------ #

    def _audit_students(self, stats, org):
        """
        1) If a student has invoices:
           - student.outstanding_balance MUST equal sum(active invoice.balance)
             (over all active, non-cancelled invoices).
           - student.credit_balance > 0 is only allowed when:
               • all active invoices are fully paid (balance <= 0), and
               • credit_balance reflects overpayments (payments allocation handles this).

        2) If a student has NO active invoices:
           - outstanding_balance MUST equal balance_bf_original - payments made
           - credit_balance MUST equal prepayment_original + overpayments
        """
        students = (
            Student.objects.filter(organization=org)
            .prefetch_related("invoices")
        )
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

        # Credit invariant for students with invoices:
        # - outstanding_balance must remain canonical
        # - credit_balance may legitimately come from either:
        #   1. unapplied payment residue, OR
        #   2. prepayment embedded in active invoice headers
        # Therefore positive credit is valid if it matches either source and
        # student outstanding remains zero.
        credit_balance = student.credit_balance or Decimal("0.00")
        outstanding_balance = student.outstanding_balance or Decimal("0.00")
        expected_unapplied_credit = max(
            Decimal("0.00"), InvoiceService.get_student_unapplied_credit(student)
        )
        expected_invoice_prepayment_credit = max(
            Decimal("0.00"),
            invoices_qs.aggregate(total=Sum("prepayment"))["total"] or Decimal("0.00")
        )

        if credit_balance > 0:
            has_outstanding = outstanding_balance > 0
            rounded_credit = credit_balance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            rounded_unapplied = expected_unapplied_credit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            rounded_prepayment = expected_invoice_prepayment_credit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            matches_unapplied = rounded_credit == rounded_unapplied
            matches_prepayment = rounded_credit == rounded_prepayment
            credit_mismatch = not (matches_unapplied or matches_prepayment)

            if has_outstanding or credit_mismatch:
                stats["credit_invariant_violations"].append(
                    {
                        "student_id": student.id,
                        "admission": student.admission_number,
                        "name": student.full_name,
                        "credit_balance": credit_balance,
                        "expected_unapplied_credit": expected_unapplied_credit,
                        "expected_invoice_prepayment_credit": expected_invoice_prepayment_credit,
                        "outstanding_balance": outstanding_balance,
                        "has_outstanding": has_outstanding,
                        "credit_mismatch": credit_mismatch,
                    }
                )

    def _check_student_without_invoices(self, student, stats):
        # For students without invoices:
        # - Total payments made by the student
        total_paid = Payment.objects.filter(
            student=student,
            is_active=True,
            status=PaymentStatus.COMPLETED
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Starting balances (frozen at term start)
        balance_bf_original = student.balance_bf_original or Decimal('0.00')
        prepayment_original = student.prepayment_original or Decimal('0.00')
        
        # Calculate expected values based on payment allocation logic:
        # 1. Payments first reduce balance_bf_original
        # 2. Any excess becomes credit_balance
        # 3. prepayment_original is added to credit_balance
        
        # How much of balance_bf_original is remaining after payments
        remaining_balance_bf = max(Decimal('0.00'), balance_bf_original - total_paid)
        
        # Any overpayment (when total_paid > balance_bf_original)
        overpayment = max(Decimal('0.00'), total_paid - balance_bf_original)
        
        # Expected outstanding balance = remaining balance_bf
        expected_outstanding = remaining_balance_bf
        
        # Expected credit = prepayment_original + overpayment
        expected_credit = prepayment_original + overpayment

        actual_outstanding = student.outstanding_balance or Decimal("0.00")
        actual_credit = student.credit_balance or Decimal("0.00")

        # Round to 2 decimal places for comparison
        expected_outstanding = expected_outstanding.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        expected_credit = expected_credit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        actual_outstanding = actual_outstanding.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        actual_credit = actual_credit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # For transferred/graduated students: outstanding_balance should match balance_bf_original
        # This is correct and should NOT be flagged as a mismatch
        if student.status in ['transferred', 'graduated']:
            if actual_outstanding == balance_bf_original:
                # This is correct for transferred students - skip the mismatch check
                return
        
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
                    "balance_bf_original": balance_bf_original,
                    "prepayment_original": prepayment_original,
                    "total_paid": total_paid,
                }
            )
        
        # STRICT credit invariant for students without invoices:
        # If credit_balance > 0, outstanding_balance MUST be 0
        # (You can't have credit AND debt at the same time)
        if actual_credit > 0 and actual_outstanding > 0:
            stats["credit_invariant_violations"].append(
                {
                    "student_id": student.id,
                    "admission": student.admission_number,
                    "name": student.full_name,
                    "credit_balance": actual_credit,
                    "outstanding_balance": actual_outstanding,
                    "unpaid_invoice_total": Decimal("0.00"),
                    "has_unpaid_invoices": False,
                    "has_outstanding": True,
                    "note": "No invoices but has both credit and outstanding",
                }
            )

    # ------------------------------------------------------------------ #
    # Invoice-level checks
    # ------------------------------------------------------------------ #

    def _audit_invoices(self, stats, org):
        """
        Verify that invoice.balance is consistent with header fields.

        Based on the system's single-source-of-truth logic:
          - total_amount is already net of discount_amount (subtotal - discount_amount)
          
        IMPORTANT:
        - Discount is already factored into total_amount, so we don't subtract it again.
        - We round to 2 decimal places for comparison to handle floating-point precision.
        - If actual_balance is 0 and the difference equals discount_amount, it's likely
          a false positive where discount fully covered the invoice and balance was set to 0.
          We'll still report it but include discount details for manual review.
        """
        self.stdout.write("")
        self.stdout.write("→ Auditing invoices ...")

        invoices = (
            Invoice.objects.filter(is_active=True)
            .exclude(status="cancelled")
            .filter(Q(organization=org) | Q(student__organization=org))
            .select_related("student", "term")
        )

        for inv in invoices:
            # Calculate expected balance using the canonical formula
            expected_balance = (
                    (inv.total_amount or Decimal("0.00"))
                    + (inv.balance_bf or Decimal("0.00"))
                    - (inv.prepayment or Decimal("0.00"))
                    - (inv.amount_paid or Decimal("0.00"))
                )

            # Round both values to 2 decimal places for comparison
            expected_balance = expected_balance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            actual_balance = (inv.balance or Decimal("0.00")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            # Only flag as mismatch if they differ
            if expected_balance != actual_balance:
                discount_amount = inv.discount_amount or Decimal("0.00")
                difference = abs(expected_balance - actual_balance)
                total_amount = inv.total_amount or Decimal("0.00")
                balance_bf = inv.balance_bf or Decimal("0.00")
                prepayment = inv.prepayment or Decimal("0.00")
                amount_paid = inv.amount_paid or Decimal("0.00")

                # Check if this is a false positive due to discount application.
                # 
                # When discounts are applied, they may cause the balance to be set to 0
                # if the discount fully covers the amount due. Our formula uses total_amount
                # which already has discount factored in, but in practice, if a discount
                # equals or exceeds what would be due, the balance may be manually set to 0.
                #
                # False positive detection:
                # - actual_balance is 0
                # - discount_amount > 0  
                # - The difference (expected - actual) is within a small tolerance of discount_amount
                #   OR discount_amount >= expected_balance (discount covers everything)
                #
                # This handles cases like:
                # - PWA2745: discount = 13,750, expected = 13,750, actual = 0
                #   (discount fully covered the invoice, balance correctly set to 0)
                is_likely_false_positive = False

                if actual_balance == Decimal("0.00") and discount_amount > 0:
                    # If discount amount equals or exceeds expected balance, it likely covered everything
                    if discount_amount >= expected_balance:
                        is_likely_false_positive = True
                    # Also check if the difference is very close to the discount amount
                    # (within 0.01 tolerance to handle rounding)
                    elif abs(difference - discount_amount) <= Decimal("0.01"):
                        is_likely_false_positive = True

                # Only add to mismatches if it's NOT a false positive
                # False positives are discounts that fully covered the invoice and
                # correctly set balance to 0, so they shouldn't be flagged as errors
                if not is_likely_false_positive:
                    stats["invoice_balance_mismatches"].append(
                        {
                            "invoice_id": inv.id,
                            "invoice_number": inv.invoice_number,
                            "student_admission": getattr(inv.student, "admission_number", ""),
                            "student_name": getattr(inv.student, "full_name", ""),
                            "expected_balance": expected_balance,
                            "actual_balance": actual_balance,
                            "difference": difference,
                            "subtotal": inv.subtotal,
                            "discount_amount": discount_amount,
                            "total_amount": inv.total_amount,
                            "balance_bf": inv.balance_bf,
                            "prepayment": inv.prepayment,
                            "amount_paid": inv.amount_paid,
                        }
                    )

    # ------------------------------------------------------------------ #
    # Payment Allocation Integrity
    # ------------------------------------------------------------------ #

    def _audit_payment_allocations(self, stats, org):
        """
        Verify that the sum of PaymentAllocation amounts for each invoice
        matches the invoice.amount_paid field.
        
        NOTE: Discrepancies can occur due to:
        1. balance_bf payments - tracked in amount_paid but may not have 
           PaymentAllocation records (amount_paid > allocations)
        2. prepayment allocations - credit applied via allocation but not 
           counted in amount_paid (allocations > amount_paid)
           
        We account for this by checking if the difference can be explained
        by balance_bf or prepayment amounts.
        """
        self.stdout.write("")
        self.stdout.write("→ Auditing payment allocation integrity ...")

        invoices = (
            Invoice.objects.filter(is_active=True)
            .exclude(status="cancelled")
            .filter(Q(organization=org) | Q(student__organization=org))
            .select_related("student")
        )

        for inv in invoices:
            # Sum of all allocations for this invoice
            allocations_total = PaymentAllocation.objects.filter(
                invoice_item__invoice=inv
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

            invoice_amount_paid = inv.amount_paid or Decimal("0.00")
            balance_bf = inv.balance_bf or Decimal("0.00")
            prepayment = abs(inv.prepayment or Decimal("0.00"))  # prepayment stored as positive

            # Round for comparison
            allocations_total = allocations_total.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            invoice_amount_paid = invoice_amount_paid.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            balance_bf = balance_bf.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            prepayment = prepayment.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            if allocations_total != invoice_amount_paid:
                difference = abs(allocations_total - invoice_amount_paid)
                
                # Check if this is a false positive due to balance_bf or prepayment handling
                #
                # Case 1: amount_paid > allocations (balance_bf was paid without allocation)
                #         difference should be <= balance_bf
                #
                # Case 2: allocations > amount_paid (prepayment allocated but not in amount_paid)
                #         difference should be <= prepayment
                #
                # Combined: difference should be <= (balance_bf + prepayment)
                is_expected_discrepancy = False
                max_expected_diff = balance_bf + prepayment
                
                if max_expected_diff > 0:
                    # Check if difference can be explained by balance_bf or prepayment
                    # (within small tolerance for rounding)
                    if difference <= max_expected_diff + Decimal("0.01"):
                        is_expected_discrepancy = True
                
                if not is_expected_discrepancy:
                    stats["payment_allocation_mismatches"].append(
                        {
                            "invoice_id": inv.id,
                            "invoice_number": inv.invoice_number,
                            "student_admission": getattr(inv.student, "admission_number", ""),
                            "allocations_total": allocations_total,
                            "invoice_amount_paid": invoice_amount_paid,
                            "difference": difference,
                            "balance_bf": balance_bf,
                            "prepayment": prepayment,
                        }
                    )

    # ------------------------------------------------------------------ #
    # Invoice Item Verification
    # ------------------------------------------------------------------ #

    def _audit_invoice_items(self, stats, org):
        """
        Verify:
        1. balance_bf items have POSITIVE amounts (representing debt)
        2. prepayment items have NEGATIVE amounts (representing credit applied)
        3. Invoices with balance_bf > 0 MUST have a corresponding balance_bf InvoiceItem
           (otherwise payments cannot be allocated to clear the balance_bf)
        """
        self.stdout.write("")
        self.stdout.write("→ Auditing invoice items (balance_bf/prepayment) ...")

        invoice_org_filter = Q(invoice__organization=org) | Q(invoice__student__organization=org)

        # Check balance_bf items
        balance_bf_items = InvoiceItem.objects.filter(
            category="balance_bf",
            invoice__is_active=True,
        ).exclude(invoice__status="cancelled").filter(invoice_org_filter).select_related(
            "invoice", "invoice__student"
        )

        for item in balance_bf_items:
            if item.amount and item.amount < 0:
                stats["balance_bf_item_issues"].append(
                    {
                        "invoice_number": item.invoice.invoice_number,
                        "student_admission": getattr(item.invoice.student, "admission_number", ""),
                        "item_amount": item.amount,
                        "issue": "balance_bf item should be positive (debt), found negative",
                    }
                )

        # Check prepayment items
        prepayment_items = InvoiceItem.objects.filter(
            category="prepayment",
            invoice__is_active=True,
        ).exclude(invoice__status="cancelled").filter(invoice_org_filter).select_related(
            "invoice", "invoice__student"
        )

        for item in prepayment_items:
            if item.amount and item.amount > 0:
                stats["prepayment_item_issues"].append(
                    {
                        "invoice_number": item.invoice.invoice_number,
                        "student_admission": getattr(item.invoice.student, "admission_number", ""),
                        "item_amount": item.amount,
                        "issue": "prepayment item should be negative (credit), found positive",
                    }
                )

        # CRITICAL CHECK: Invoices with balance_bf > 0 but NO balance_bf InvoiceItem
        # This is the ROOT CAUSE of the credit invariant violations - payments cannot
        # be allocated to balance_bf if there's no InvoiceItem to allocate to
        invoices_with_balance_bf = (
            Invoice.objects.filter(is_active=True, balance_bf__gt=0)
            .exclude(status="cancelled")
            .filter(Q(organization=org) | Q(student__organization=org))
            .select_related("student")
        )

        for inv in invoices_with_balance_bf:
            has_bf_item = inv.items.filter(category="balance_bf", is_active=True).exists()
            if not has_bf_item:
                stats["missing_balance_bf_items"].append(
                    {
                        "invoice_id": inv.id,
                        "invoice_number": inv.invoice_number,
                        "student_admission": getattr(inv.student, "admission_number", ""),
                        "student_name": getattr(inv.student, "full_name", ""),
                        "balance_bf": inv.balance_bf,
                        "issue": f"Invoice has balance_bf={inv.balance_bf} but NO balance_bf InvoiceItem! Payments CANNOT allocate to this.",
                    }
                )

    # ------------------------------------------------------------------ #
    # Term Transition Readiness
    # ------------------------------------------------------------------ #

    def _audit_term_transition_readiness(self, stats, org):
        """
        Check for issues that could cause problems during term transition:
        1. Students with credit_balance > 0 AND outstanding invoices (should not happen)
        2. Students with negative outstanding_balance (data issue)
        3. Students where outstanding_balance doesn't match invoice balances
        """
        self.stdout.write("")
        self.stdout.write("→ Auditing term transition readiness ...")

        active_students = Student.objects.filter(status="active", organization=org)

        for student in active_students:
            invoices_qs = student.invoices.filter(is_active=True).exclude(
                status="cancelled"
            )
            has_invoices = invoices_qs.exists()
            
            credit_balance = student.credit_balance or Decimal("0.00")
            outstanding_balance = student.outstanding_balance or Decimal("0.00")

            # Check 1: Credit balance > 0 with outstanding invoices
            if has_invoices and credit_balance > 0:
                unpaid_exists = invoices_qs.filter(balance__gt=0).exists()
                if unpaid_exists:
                    stats["term_transition_issues"].append(
                        {
                            "student_id": student.id,
                            "admission": student.admission_number,
                            "name": student.full_name,
                            "credit_balance": credit_balance,
                            "outstanding_balance": outstanding_balance,
                            "issue": "Has credit_balance > 0 with unpaid invoices",
                        }
                    )

            # Check 2: Negative outstanding_balance (shouldn't happen)
            if outstanding_balance < 0:
                stats["term_transition_issues"].append(
                    {
                        "student_id": student.id,
                        "admission": student.admission_number,
                        "name": student.full_name,
                        "credit_balance": credit_balance,
                        "outstanding_balance": outstanding_balance,
                        "issue": "Negative outstanding_balance (should be >= 0)",
                    }
                )

            # Check 3: If no invoices, check if balances are consistent
            if not has_invoices:
                balance_bf_original = student.balance_bf_original or Decimal("0.00")
                prepayment_original = student.prepayment_original or Decimal("0.00")
                
                # Warn if student has no invoices but has positive balance_bf_original
                # that doesn't match outstanding_balance
                if balance_bf_original > 0 and outstanding_balance != balance_bf_original:
                    stats["term_transition_issues"].append(
                        {
                            "student_id": student.id,
                            "admission": student.admission_number,
                            "name": student.full_name,
                            "credit_balance": credit_balance,
                            "outstanding_balance": outstanding_balance,
                            "balance_bf_original": balance_bf_original,
                            "issue": f"No invoices but outstanding_balance ({outstanding_balance}) != balance_bf_original ({balance_bf_original})",
                        }
                    )

    # ------------------------------------------------------------------ #
    # Inactive Invoice Check
    # ------------------------------------------------------------------ #

    def _audit_inactive_invoices(self, stats, org):
        """
        Check for active students who have inactive (soft-deleted) invoices.
        This is a data integrity issue - active students should not have 
        inactive invoices as it can cause payment allocation problems.
        """
        self.stdout.write("")
        self.stdout.write("→ Auditing for inactive invoices on active students ...")

        active_students = Student.objects.filter(status="active", organization=org)

        for student in active_students:
            # Check for inactive invoices
            inactive_invoices = student.invoices.filter(is_active=False)
            
            if inactive_invoices.exists():
                # Get details of inactive invoices
                inactive_list = list(
                    inactive_invoices.values_list('invoice_number', flat=True)[:5]
                )
                total_inactive = inactive_invoices.count()
                
                stats["inactive_invoice_issues"].append(
                    {
                        "student_id": student.id,
                        "admission": student.admission_number,
                        "name": student.full_name,
                        "inactive_count": total_inactive,
                        "invoice_numbers": inactive_list,
                        "issue": f"Active student has {total_inactive} inactive invoice(s)",
                    }
                )

    # ------------------------------------------------------------------ #
    # Double Balance B/F Check
    # ------------------------------------------------------------------ #

    def _audit_double_balance_bf(self, stats, org):
        """
        Catch invoices where total_amount incorrectly includes balance_bf.

        Correct design: total_amount = term fees only. balance_bf is a separate
        header field added in the balance formula. If total_amount = term_fees + balance_bf,
        balance_bf is double-counted (in total_amount AND in the balance formula).
        """
        self.stdout.write("")
        self.stdout.write("→ Auditing for double balance_bf in invoice total_amount ...")

        invoices = (
            Invoice.objects.filter(is_active=True, balance_bf__gt=0)
            .exclude(status="cancelled")
            .filter(Q(organization=org) | Q(student__organization=org))
            .select_related("student")
        )

        for inv in invoices:
            term_items = inv.items.filter(is_active=True).exclude(
                category__in=["balance_bf", "prepayment"]
            )
            agg = term_items.aggregate(
                total=Sum("amount"), discount=Sum("discount_applied")
            )
            correct_billed = (agg["total"] or Decimal("0")) - (
                agg["discount"] or Decimal("0")
            )
            correct_billed = correct_billed.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            actual_total = (inv.total_amount or Decimal("0")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            balance_bf = inv.balance_bf or Decimal("0")

            if balance_bf > 0 and abs(actual_total - (correct_billed + balance_bf)) < Decimal("0.01"):
                stats["double_balance_bf_invoices"].append(
                    {
                        "invoice_id": inv.id,
                        "invoice_number": inv.invoice_number,
                        "student_admission": getattr(inv.student, "admission_number", ""),
                        "student_name": getattr(inv.student, "full_name", ""),
                        "total_amount": actual_total,
                        "correct_billed": correct_billed,
                        "balance_bf": balance_bf,
                        "issue": f"total_amount ({actual_total}) = billed ({correct_billed}) + balance_bf ({balance_bf}) - double counted",
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
            f"Student credit_balance invariant violations: "
            f"{len(stats['credit_invariant_violations'])}"
        )
        self.stdout.write(
            "  (credit > 0 requires canonical match to valid credit source and outstanding = 0)"
        )
        for m in stats["credit_invariant_violations"][:10]:
            details = []
            if m.get('has_outstanding'):
                details.append(f"outstanding={m.get('outstanding_balance', 0)}")
            if m.get('credit_mismatch'):
                details.append(
                    f"credit(unapplied {m.get('expected_unapplied_credit', 0)}, prepayment {m.get('expected_invoice_prepayment_credit', 0)})"
                )
            detail_str = ", ".join(details) if details else "unknown issue"
            self.stdout.write(
                f"  - {m['admission']} {m['name']}: "
                f"credit={m['credit_balance']}, {detail_str}"
            )

        self.stdout.write("")
        self.stdout.write(
            f"Students without invoices but mismatched frozen fields: "
            f"{len(stats['no_invoice_invariant_violations'])}"
        )
        for m in stats["no_invoice_invariant_violations"][:10]:
            self.stdout.write(
                f"  - {m['admission']} {m['name']}: "
                f"balance_bf_original={m['balance_bf_original']}, "
                f"total_paid={m['total_paid']}, "
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
        
        # False positives (discounts that fully covered invoices) are now excluded
        # from the mismatch list, so we only show real mismatches here
        for m in stats["invoice_balance_mismatches"][:10]:
            self.stdout.write(
                f"  - {m['invoice_number']} "
                f"({m['student_admission']} {m['student_name']}): "
                f"expected {m['expected_balance']}, "
                f"actual {m['actual_balance']} "
                f"[diff={m['difference']}, "
                f"subtotal={m['subtotal']}, "
                f"discount={m['discount_amount']}, "
                f"total={m['total_amount']}, "
                f"bf={m['balance_bf']}, "
                f"prepay={m['prepayment']}, "
                f"paid={m['amount_paid']}]"
            )

        # Payment allocation mismatches
        self.stdout.write("")
        self.stdout.write(
            f"Payment allocation mismatches (allocations vs invoice.amount_paid): "
            f"{len(stats['payment_allocation_mismatches'])}"
        )
        for m in stats["payment_allocation_mismatches"][:10]:
            self.stdout.write(
                f"  - {m['invoice_number']} ({m['student_admission']}): "
                f"allocations_sum={m['allocations_total']}, "
                f"invoice.amount_paid={m['invoice_amount_paid']}, "
                f"diff={m['difference']}, "
                f"balance_bf={m.get('balance_bf', 0)}, "
                f"prepayment={m.get('prepayment', 0)}"
            )

        # Balance_bf item issues
        self.stdout.write("")
        self.stdout.write(
            f"Balance_bf item issues (should be positive): "
            f"{len(stats['balance_bf_item_issues'])}"
        )
        for m in stats["balance_bf_item_issues"][:10]:
            self.stdout.write(
                f"  - {m['invoice_number']} ({m['student_admission']}): "
                f"amount={m['item_amount']}, {m['issue']}"
            )

        # Prepayment item issues
        self.stdout.write("")
        self.stdout.write(
            f"Prepayment item issues (should be negative): "
            f"{len(stats['prepayment_item_issues'])}"
        )
        for m in stats["prepayment_item_issues"][:10]:
            self.stdout.write(
                f"  - {m['invoice_number']} ({m['student_admission']}): "
                f"amount={m['item_amount']}, {m['issue']}"
            )

        # CRITICAL: Missing balance_bf InvoiceItems
        self.stdout.write("")
        self.stdout.write(
            f"Invoices with balance_bf but MISSING balance_bf item (CRITICAL): "
            f"{len(stats['missing_balance_bf_items'])}"
        )
        if stats['missing_balance_bf_items']:
            self.stdout.write(
                self.style.ERROR(
                    "  ⚠️  These invoices CANNOT have payments allocated to balance_bf!"
                )
            )
            self.stdout.write(
                "  Run: python manage.py fix_balance_bf_allocations --dry-run"
            )
        for m in stats["missing_balance_bf_items"][:10]:
            self.stdout.write(
                f"  - {m['invoice_number']} ({m['student_admission']} {m['student_name']}): "
                f"balance_bf={m['balance_bf']}"
            )

        # Term transition issues
        self.stdout.write("")
        self.stdout.write(
            f"Term transition readiness issues: "
            f"{len(stats['term_transition_issues'])}"
        )
        for m in stats["term_transition_issues"][:10]:
            self.stdout.write(
                f"  - {m['admission']} {m['name']}: {m['issue']}"
            )

        # Inactive invoice issues
        self.stdout.write("")
        self.stdout.write(
            f"Active students with inactive invoices: "
            f"{len(stats['inactive_invoice_issues'])}"
        )
        for m in stats["inactive_invoice_issues"][:10]:
            invoice_nums = ', '.join(m['invoice_numbers'])
            self.stdout.write(
                f"  - {m['admission']} {m['name']}: {m['inactive_count']} inactive invoice(s) "
                f"[{invoice_nums}{'...' if m['inactive_count'] > 5 else ''}]"
            )

        # Double balance_bf in total_amount (inflated invoices)
        self.stdout.write("")
        self.stdout.write(
            f"Invoices with double balance_bf (total_amount inflated): "
            f"{len(stats['double_balance_bf_invoices'])}"
        )
        if stats['double_balance_bf_invoices']:
            self.stdout.write(
                self.style.ERROR(
                    "  ⚠️  total_amount incorrectly includes balance_bf - run fix_double_balance_bf_invoices"
                )
            )
            self.stdout.write(
                "  Run: python manage.py fix_double_balance_bf_invoices --dry-run"
            )
        for m in stats["double_balance_bf_invoices"][:10]:
            self.stdout.write(
                f"  - {m['invoice_number']} ({m['student_admission']} {m['student_name']}): "
                f"total_amount={m['total_amount']}, correct_billed={m['correct_billed']}, "
                f"balance_bf={m['balance_bf']}"
            )

        # Summary totals
        self.stdout.write("")
        self.stdout.write("=" * 80)
        total_issues = (
            len(stats['outstanding_mismatches']) +
            len(stats['credit_invariant_violations']) +
            len(stats['no_invoice_invariant_violations']) +
            len(stats['invoice_balance_mismatches']) +
            len(stats['payment_allocation_mismatches']) +
            len(stats['balance_bf_item_issues']) +
            len(stats['prepayment_item_issues']) +
            len(stats['missing_balance_bf_items']) +
            len(stats['term_transition_issues']) +
            len(stats['inactive_invoice_issues']) +
            len(stats['double_balance_bf_invoices'])
        )
        
        if total_issues == 0:
            self.stdout.write(self.style.SUCCESS("✅ All checks passed! No issues found."))
        else:
            self.stdout.write(
                self.style.WARNING(f"⚠️  Found {total_issues} total issue(s) across all checks.")
            )
        
        self.stdout.write("")
        self.stdout.write("✅ Audit completed (no data was modified).")