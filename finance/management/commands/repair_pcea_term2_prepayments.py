from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from academics.models import Term
from core.models import Organization, TermChoices
from finance.models import Invoice, InvoiceItem
from students.models import Student


class Command(BaseCommand):
    help = "Repair PCEA Wendani Term 2 2026 opening prepayments for named students."

    TARGETS = {
        "2631": Decimal("36000.00"),
        "2877": Decimal("31000.00"),
        "2587": Decimal("28900.00"),
        "3148": Decimal("28000.00"),
    }

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
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
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

        with transaction.atomic():
            stats = self._repair(organization=organization, term=term, dry_run=dry_run)
            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            f"{'DRY RUN ' if dry_run else ''}checked={stats['checked']} updated={stats['updated']}"
        ))

    def _repair(self, *, organization, term, dry_run):
        stats = {"checked": 0, "updated": 0}
        for admission_number, target_prepayment in self.TARGETS.items():
            stats["checked"] += 1
            student = Student.objects.select_for_update().filter(
                admission_number=admission_number,
                organization=organization,
            ).first()
            if not student:
                raise CommandError(f"Student not found in {organization.name}: {admission_number}")

            invoice = Invoice.objects.select_for_update().filter(
                student=student,
                term=term,
            ).filter(
                Q(organization=organization) | Q(organization__isnull=True)
            ).exclude(status="cancelled").first()
            if not invoice:
                raise CommandError(f"Invoice not found for {admission_number} in {term}")

            exposure = (invoice.total_amount or Decimal("0.00")) + Decimal("0.00")
            carry_forward_credit = max(Decimal("0.00"), target_prepayment - exposure)

            before = {
                "student_prepayment_original": student.prepayment_original,
                "student_credit_balance": student.credit_balance,
                "student_outstanding_balance": student.outstanding_balance,
                "invoice_balance_bf": invoice.balance_bf,
                "invoice_prepayment": invoice.prepayment,
                "invoice_amount_paid": invoice.amount_paid,
                "invoice_balance": invoice.balance,
            }

            self.stdout.write(
                f"{admission_number} {student.full_name}: "
                f"invoice={invoice.invoice_number} billed={invoice.total_amount} "
                f"target_prepayment={target_prepayment} carry_forward_credit={carry_forward_credit}"
            )
            self.stdout.write(f"  before={before}")

            if not dry_run:
                student.balance_bf_original = Decimal("0.00")
                student.prepayment_original = target_prepayment
                student.credit_balance = carry_forward_credit

                invoice.balance_bf = Decimal("0.00")
                invoice.balance_bf_original = Decimal("0.00")
                invoice.prepayment = target_prepayment

                self._replace_opening_item(
                    invoice=invoice,
                    category="balance_bf",
                    amount=Decimal("0.00"),
                )
                self._replace_opening_item(
                    invoice=invoice,
                    category="prepayment",
                    amount=-target_prepayment,
                )

                invoice.save()
                student.outstanding_balance = Decimal("0.00")
                student.credit_balance = carry_forward_credit
                student.save(update_fields=[
                    "balance_bf_original",
                    "prepayment_original",
                    "outstanding_balance",
                    "credit_balance",
                    "updated_at",
                ])
                stats["updated"] += 1
                invoice.refresh_from_db()
                student.refresh_from_db()

            after = {
                "student_prepayment_original": target_prepayment if dry_run else student.prepayment_original,
                "student_credit_balance": carry_forward_credit if dry_run else student.credit_balance,
                "student_outstanding_balance": Decimal("0.00") if dry_run else student.outstanding_balance,
                "invoice_balance_bf": Decimal("0.00") if dry_run else invoice.balance_bf,
                "invoice_prepayment": target_prepayment if dry_run else invoice.prepayment,
                "invoice_amount_paid": invoice.amount_paid,
                "invoice_balance": Decimal("0.00") if dry_run else invoice.balance,
            }
            self.stdout.write(f"  after={after}")

        return stats

    def _replace_opening_item(self, *, invoice, category, amount):
        items = list(invoice.items.filter(category=category).order_by("created_at", "id"))
        if amount == Decimal("0.00"):
            for item in items:
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
            extra.is_active = False
            extra.save(update_fields=["is_active", "updated_at"])
