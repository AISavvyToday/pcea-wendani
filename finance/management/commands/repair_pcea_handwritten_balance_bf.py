import re
from decimal import Decimal, ROUND_HALF_UP

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q, Sum

from academics.models import Term
from core.models import InvoiceStatus, Organization, TermChoices
from finance.models import Invoice, InvoiceItem
from students.models import Student


class Command(BaseCommand):
    help = "Repair PCEA Wendani handwritten Balance B/F cases from the May 2026 review."

    OPENING_CATEGORIES = ("balance_bf", "prepayment")

    TARGETS = [
        {"admission": "2810", "expected_name": "Kyle Yator Bundotich", "kind": "balance_bf"},
        {"admission": "3138", "expected_name": "Wanyua Kiboe", "kind": "balance_bf"},
        {"admission": "2434", "expected_name": "Trevor Gones Atai", "kind": "balance_bf"},
        {"admission": "2314", "expected_name": "Hype Wambui", "kind": "balance_bf"},
        {"admission": "2340", "expected_name": "Prudence Wanjiku", "kind": "balance_bf"},
        {"admission": "2421", "expected_name": "Islemah Muthoni", "kind": "balance_bf"},
        {"admission": "2582", "expected_name": "Lila Kllinmu", "kind": "balance_bf"},
        {"admission": "3189", "expected_name": "Inana Wambui", "kind": "balance_bf"},
        {"admission": "3190", "expected_name": "Elyana Njeri", "kind": "balance_bf"},
        {"admission": "2338", "expected_name": "Bilquees Kamami", "kind": "balance_bf"},
        {"admission": "2657", "expected_name": "Caleb Kamau", "kind": "balance_bf"},
        {"admission": "2739", "expected_name": "Edna Zgyde", "kind": "balance_bf"},
        {"admission": "3262", "expected_name": "Myllan Xela Nyambura", "kind": "prepayment"},
        {"admission": "3023", "expected_name": "Emmanuel Githa", "kind": "balance_bf"},
        {"admission": "2317", "expected_name": "Doris Makena", "kind": "balance_bf"},
        {"admission": "3030", "expected_name": "Gael Byce", "kind": "balance_bf"},
        {"admission": "2542", "expected_name": "Jabez Ndeiya", "kind": "balance_bf"},
        {"admission": "3272", "expected_name": "Declan Baraka", "kind": "balance_bf"},
        {"admission": "2848", "expected_name": "Meyer Njoki", "kind": "balance_bf"},
        {"admission": "2295", "expected_name": "Abigael Karubo", "kind": "balance_bf"},
        {"admission": "3078", "expected_name": "Elyana Klayui Klambuyu", "kind": "balance_bf"},
        {"admission": "2466", "expected_name": "Esther Katheren", "kind": "balance_bf"},
        {"admission": "2298", "expected_name": "Annamarie", "kind": "balance_bf"},
        {"admission": "3033", "expected_name": "Abigael Muthoni", "kind": "balance_bf"},
        {"admission": "3026", "expected_name": "Nycy Wambui", "kind": "balance_bf"},
        {"admission": "3203", "expected_name": "Shanice Njeri", "kind": "balance_bf"},
        {"admission": "2962", "expected_name": "Micole Mumo", "kind": "balance_bf"},
        {"admission": "2721", "expected_name": "Micole Kembo", "kind": "balance_bf"},
        {"admission": "2591", "expected_name": "Kai Nganga", "kind": "balance_bf"},
        {"admission": "2502", "expected_name": "Iman", "kind": "balance_bf"},
        {"admission": "2944", "expected_name": "Princess Aria", "kind": "balance_bf"},
        {"admission": "2935", "expected_name": "Precious Esther", "kind": "balance_bf"},
    ]

    TERM_MAP = {
        "1": TermChoices.TERM_1,
        "term_1": TermChoices.TERM_1,
        "2": TermChoices.TERM_2,
        "term_2": TermChoices.TERM_2,
        "3": TermChoices.TERM_3,
        "term_3": TermChoices.TERM_3,
    }

    def add_arguments(self, parser):
        parser.add_argument("--organization-code", default="PCEA_WENDANI")
        parser.add_argument("--year", type=int, default=2026)
        parser.add_argument("--term", default="2")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument(
            "--admissions",
            default="",
            help="Optional comma-separated admission numbers to repair instead of the full handwritten list.",
        )

    def handle(self, *args, **options):
        dry_run = not options["apply"]
        organization = Organization.objects.filter(code__iexact=options["organization_code"]).first()
        if not organization:
            raise CommandError(f"Organization not found: {options['organization_code']}")

        term_value = self.TERM_MAP.get(str(options["term"]).lower())
        if not term_value:
            raise CommandError(f"Unsupported term value: {options['term']}")

        term = Term.objects.filter(
            organization=organization,
            academic_year__year=options["year"],
            term=term_value,
            is_active=True,
        ).select_related("academic_year").first()
        if not term:
            raise CommandError(f"Term not found: {options['year']} {term_value} for {organization.name}")

        targets = self._selected_targets(options["admissions"])
        mode = "DRY RUN" if dry_run else "APPLY"
        self.stdout.write(f"{mode}: {len(targets)} handwritten B/F targets for {organization.name}, {term}")

        with transaction.atomic():
            stats = self._repair(organization=organization, term=term, targets=targets, dry_run=dry_run)
            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(
            self.style.SUCCESS(
                f"{mode} checked={stats['checked']} updated={stats['updated']} "
                f"blocked={stats['blocked']} double_count_candidates={stats['double_count_candidates']}"
            )
        )
        if stats["blocked"]:
            self.stdout.write(
                self.style.WARNING(
                    f"{stats['blocked']} row(s) need admission/name review before APPLY."
                )
            )
            if not dry_run:
                raise CommandError("Blocked rows were found; apply was rolled back.")
        if dry_run:
            self.stdout.write("No DB changes were saved. Re-run with --apply after reviewing every match.")

    def _selected_targets(self, admissions):
        if not admissions.strip():
            return list(self.TARGETS)

        wanted = {value.strip() for value in admissions.split(",") if value.strip()}
        known = {target["admission"] for target in self.TARGETS}
        unknown = sorted(wanted - known)
        if unknown:
            raise CommandError(f"Admission(s) not in handwritten target list: {', '.join(unknown)}")

        return [target for target in self.TARGETS if target["admission"] in wanted]

    def _repair(self, *, organization, term, targets, dry_run):
        stats = {"checked": 0, "updated": 0, "blocked": 0, "double_count_candidates": 0}

        for target in targets:
            stats["checked"] += 1
            admission_number = target["admission"]
            kind = target["kind"]

            student = Student.objects.select_for_update().filter(
                admission_number=admission_number,
                organization=organization,
            ).first()
            if not student:
                stats["blocked"] += 1
                self._write_blocked(
                    admission_number=admission_number,
                    expected_name=target["expected_name"],
                    reason="student admission number not found",
                    organization=organization,
                )
                continue

            if not self._name_matches(student.full_name, target["expected_name"]):
                stats["blocked"] += 1
                self._write_blocked(
                    admission_number=admission_number,
                    expected_name=target["expected_name"],
                    reason=f"name mismatch: DB has '{student.full_name}'",
                    organization=organization,
                )
                continue

            try:
                invoice = self._get_invoice(student=student, term=term, organization=organization)
            except CommandError as exc:
                stats["blocked"] += 1
                self._write_blocked(
                    admission_number=admission_number,
                    expected_name=target["expected_name"],
                    reason=str(exc),
                    organization=organization,
                )
                continue
            term_totals = self._term_item_totals(invoice)
            correct_total = term_totals["total"]
            current_total = self._money(invoice.total_amount)
            balance_bf = self._money(invoice.balance_bf)
            prepayment = self._money(invoice.prepayment)
            amount_paid = self._money(invoice.amount_paid)
            expected_balance = max(
                correct_total + balance_bf - prepayment - amount_paid,
                Decimal("0.00"),
            )

            if balance_bf > 0 and abs(current_total - (correct_total + balance_bf)) <= Decimal("0.01"):
                stats["double_count_candidates"] += 1

            if kind == "prepayment" and prepayment <= 0:
                stats["blocked"] += 1
                self._write_blocked(
                    admission_number=admission_number,
                    expected_name=target["expected_name"],
                    reason=(
                        f"marked as prepayment in the handwritten list, but invoice "
                        f"{invoice.invoice_number} has prepayment={prepayment}"
                    ),
                    organization=organization,
                )
                continue

            projected_credit = self._project_credit(student=student, invoice=invoice, correct_total=correct_total)
            projected_outstanding = self._project_student_outstanding(
                student=student,
                invoice=invoice,
                invoice_balance=expected_balance,
            )

            before = {
                "student_name": student.full_name,
                "expected_name_from_note": target["expected_name"],
                "kind": kind,
                "student_balance_bf_original": self._money(student.balance_bf_original),
                "student_prepayment_original": self._money(student.prepayment_original),
                "student_outstanding_balance": self._money(student.outstanding_balance),
                "student_credit_balance": self._money(student.credit_balance),
                "invoice": invoice.invoice_number,
                "invoice_subtotal": self._money(invoice.subtotal),
                "invoice_discount_amount": self._money(invoice.discount_amount),
                "invoice_total_amount": current_total,
                "invoice_balance_bf": balance_bf,
                "invoice_prepayment": prepayment,
                "invoice_amount_paid": amount_paid,
                "invoice_balance": self._money(invoice.balance),
                "term_item_total_excluding_opening": correct_total,
            }

            after = {
                "student_balance_bf_original": balance_bf,
                "student_prepayment_original": prepayment if kind == "prepayment" else self._money(student.prepayment_original),
                "student_outstanding_balance": projected_outstanding,
                "student_credit_balance": projected_credit if kind == "prepayment" else self._money(student.credit_balance),
                "invoice_subtotal": term_totals["subtotal"],
                "invoice_discount_amount": term_totals["discount"],
                "invoice_total_amount": correct_total,
                "invoice_balance_bf": balance_bf,
                "invoice_prepayment": prepayment,
                "invoice_amount_paid": amount_paid,
                "invoice_balance": expected_balance,
            }

            self.stdout.write(
                f"{admission_number} {student.full_name} | note='{target['expected_name']}' "
                f"| invoice={invoice.invoice_number} | kind={kind}"
            )
            self.stdout.write(f"  before={before}")
            self.stdout.write(f"  after={after}")

            if dry_run:
                continue

            self._replace_opening_item(invoice=invoice, category="balance_bf", amount=balance_bf)
            self._replace_opening_item(invoice=invoice, category="prepayment", amount=-prepayment)

            invoice.subtotal = term_totals["subtotal"]
            invoice.discount_amount = term_totals["discount"]
            invoice.total_amount = correct_total
            invoice.balance_bf_original = balance_bf
            invoice.save()

            student.balance_bf_original = balance_bf
            if kind == "prepayment":
                student.prepayment_original = prepayment
                student.credit_balance = projected_credit
            student.save(update_fields=[
                "balance_bf_original",
                "prepayment_original",
                "outstanding_balance",
                "credit_balance",
                "updated_at",
            ])
            stats["updated"] += 1

        return stats

    def _write_blocked(self, *, admission_number, expected_name, reason, organization):
        self.stdout.write(
            self.style.WARNING(
                f"BLOCKED {admission_number} | note='{expected_name}' | reason={reason}"
            )
        )
        suggestions = self._student_suggestions(expected_name=expected_name, organization=organization)
        if suggestions:
            self.stdout.write("  possible DB matches:")
            for student in suggestions:
                self.stdout.write(f"    {student.admission_number} {student.full_name}")
        else:
            self.stdout.write("  possible DB matches: none")

    def _get_invoice(self, *, student, term, organization):
        invoices = list(
            Invoice.objects.select_for_update()
            .filter(student=student, term=term, is_active=True)
            .filter(Q(organization=organization) | Q(organization__isnull=True))
            .exclude(status=InvoiceStatus.CANCELLED)
            .order_by("issue_date", "created_at", "invoice_number")
        )
        if len(invoices) != 1:
            raise CommandError(
                f"Expected exactly one active invoice for {student.admission_number} "
                f"{student.full_name} in {term}; found {len(invoices)}."
            )
        return invoices[0]

    def _term_item_totals(self, invoice):
        items = invoice.items.filter(is_active=True).exclude(category__in=self.OPENING_CATEGORIES)
        count = items.count()
        if count == 0:
            raise CommandError(f"Invoice {invoice.invoice_number} has no active term-fee items.")

        totals = items.aggregate(
            subtotal=Sum("amount"),
            discount=Sum("discount_applied"),
        )
        subtotal = self._money(totals["subtotal"])
        discount = self._money(totals["discount"])
        total = self._money(subtotal - discount)
        return {"count": count, "subtotal": subtotal, "discount": discount, "total": total}

    def _project_student_outstanding(self, *, student, invoice, invoice_balance):
        other_balance = sum(
            max(self._money(other.balance), Decimal("0.00"))
            for other in student.invoices.filter(is_active=True)
            .exclude(status=InvoiceStatus.CANCELLED)
            .exclude(pk=invoice.pk)
            .only("balance")
        )
        return self._money(other_balance + invoice_balance)

    def _project_credit(self, *, student, invoice, correct_total):
        due_before_payment = max(
            correct_total
            + self._money(invoice.balance_bf)
            - self._money(invoice.prepayment),
            Decimal("0.00"),
        )
        excess_payment = max(self._money(invoice.amount_paid) - due_before_payment, Decimal("0.00"))
        prepayment_credit = max(
            self._money(invoice.prepayment) - (correct_total + self._money(invoice.balance_bf)),
            Decimal("0.00"),
        )
        return self._money(max(self._money(student.credit_balance), excess_payment, prepayment_credit))

    def _replace_opening_item(self, *, invoice, category, amount):
        items = list(invoice.items.filter(category=category).order_by("created_at", "id"))
        amount = self._money(amount)

        if amount == Decimal("0.00"):
            for item in items:
                if item.is_active:
                    item.is_active = False
                    item.save(update_fields=["is_active", "updated_at"])
            return

        item = items[0] if items else InvoiceItem(invoice=invoice, fee_item=None, category=category)
        item.description = (
            "Prepayment / Credit from previous term"
            if category == "prepayment"
            else "Balance B/F from previous term"
        )
        item.amount = amount
        item.discount_applied = Decimal("0.00")
        item.is_active = True
        item.save()

        for extra in items[1:]:
            if extra.is_active:
                extra.is_active = False
                extra.save(update_fields=["is_active", "updated_at"])

    def _money(self, value):
        return (value or Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _name_matches(self, db_name, expected_name):
        expected_tokens = self._name_tokens(expected_name)
        db_tokens = self._name_tokens(db_name)
        if not expected_tokens or not db_tokens:
            return False

        for expected in expected_tokens:
            for actual in db_tokens:
                if expected == actual:
                    return True
                if len(expected) >= 5 and len(actual) >= 5 and self._edit_distance(expected, actual) <= 2:
                    return True
        return False

    def _student_suggestions(self, *, expected_name, organization):
        expected_tokens = self._name_tokens(expected_name)
        if not expected_tokens:
            return []

        scored = []
        qs = Student.objects.filter(organization=organization).only(
            "admission_number", "first_name", "middle_name", "last_name"
        )
        for student in qs:
            db_tokens = self._name_tokens(student.full_name)
            score = 0
            for expected in expected_tokens:
                for actual in db_tokens:
                    if expected == actual:
                        score += 3
                    elif len(expected) >= 5 and len(actual) >= 5 and self._edit_distance(expected, actual) <= 2:
                        score += 2
            if score:
                scored.append((score, student.admission_number or "", student))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [student for _, _, student in scored[:5]]

    def _name_tokens(self, value):
        return [
            token
            for token in re.sub(r"[^a-z0-9 ]+", " ", (value or "").lower()).split()
            if len(token) >= 4
        ]

    def _edit_distance(self, left, right):
        if abs(len(left) - len(right)) > 2:
            return 3
        previous = list(range(len(right) + 1))
        for i, left_char in enumerate(left, start=1):
            current = [i]
            for j, right_char in enumerate(right, start=1):
                current.append(
                    min(
                        current[-1] + 1,
                        previous[j] + 1,
                        previous[j - 1] + (left_char != right_char),
                    )
                )
            previous = current
        return previous[-1]
