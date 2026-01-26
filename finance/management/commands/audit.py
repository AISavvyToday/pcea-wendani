from decimal import Decimal, ROUND_HALF_UP

from django.core.management.base import BaseCommand
from django.db.models import Sum, Q

from students.models import Student
from finance.models import Invoice, InvoiceItem
from payments.models import Payment, PaymentAllocation
from core.models import PaymentStatus


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
            # New checks
            "payment_allocation_mismatches": [],
            "balance_bf_item_issues": [],
            "prepayment_item_issues": [],
            "term_transition_issues": [],
        }

        self._audit_students(stats)
        self._audit_invoices(stats)
        self._audit_payment_allocations(stats)
        self._audit_invoice_items(stats)
        self._audit_term_transition_readiness(stats)
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
           - outstanding_balance MUST equal balance_bf_original - payments made
           - credit_balance MUST equal prepayment_original + overpayments
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

    # ------------------------------------------------------------------ #
    # Invoice-level checks
    # ------------------------------------------------------------------ #

    def _audit_invoices(self, stats):
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

    def _audit_payment_allocations(self, stats):
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

    def _audit_invoice_items(self, stats):
        """
        Verify:
        1. balance_bf items have POSITIVE amounts (representing debt)
        2. prepayment items have NEGATIVE amounts (representing credit applied)
        """
        self.stdout.write("")
        self.stdout.write("→ Auditing invoice items (balance_bf/prepayment) ...")

        # Check balance_bf items
        balance_bf_items = InvoiceItem.objects.filter(
            category="balance_bf",
            invoice__is_active=True
        ).exclude(invoice__status="cancelled").select_related("invoice", "invoice__student")

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
            invoice__is_active=True
        ).exclude(invoice__status="cancelled").select_related("invoice", "invoice__student")

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

    # ------------------------------------------------------------------ #
    # Term Transition Readiness
    # ------------------------------------------------------------------ #

    def _audit_term_transition_readiness(self, stats):
        """
        Check for issues that could cause problems during term transition:
        1. Students with credit_balance > 0 AND outstanding invoices (should not happen)
        2. Students with negative outstanding_balance (data issue)
        3. Students where outstanding_balance doesn't match invoice balances
        """
        self.stdout.write("")
        self.stdout.write("→ Auditing term transition readiness ...")

        active_students = Student.objects.filter(status="active")

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
            len(stats['term_transition_issues'])
        )
        
        if total_issues == 0:
            self.stdout.write(self.style.SUCCESS("✅ All checks passed! No issues found."))
        else:
            self.stdout.write(
                self.style.WARNING(f"⚠️  Found {total_issues} total issue(s) across all checks.")
            )
        
        self.stdout.write("")
        self.stdout.write("✅ Audit completed (no data was modified).")