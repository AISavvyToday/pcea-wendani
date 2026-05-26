from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from academics.models import Term
from core.models import InvoiceStatus, Organization, PaymentStatus, TermChoices
from finance.models import Invoice, InvoiceItem
from payments.models import PaymentAllocation
from payments.services.invoice import InvoiceService


class Command(BaseCommand):
    help = (
        "Move post-rollover allocations from the previous-term invoice into the "
        "current term Balance B/F item, then deactivate the previous invoice."
    )

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
        parser.add_argument("--previous-term", default="")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument(
            "--admissions",
            default="",
            help="Optional comma-separated admission numbers to repair.",
        )

    def handle(self, *args, **options):
        dry_run = not options["apply"]
        organization = Organization.objects.filter(
            code__iexact=options["organization_code"]
        ).first()
        if not organization:
            raise CommandError(f"Organization not found: {options['organization_code']}")

        term_value = self.TERM_MAP.get(str(options["term"]).lower())
        if not term_value:
            raise CommandError(f"Unsupported term: {options['term']}")

        current_term = Term.objects.filter(
            organization=organization,
            academic_year__year=options["year"],
            term=term_value,
        ).first()
        if not current_term:
            raise CommandError(
                f"Current term not found: {organization.code} {options['year']} {term_value}"
            )

        previous_term = self._resolve_previous_term(
            organization=organization,
            current_term=current_term,
            requested=options["previous_term"],
        )
        if not previous_term:
            raise CommandError("Previous term not found")

        admissions = [
            value.strip()
            for value in options["admissions"].split(",")
            if value.strip()
        ]

        self.stdout.write(
            f"{'APPLY' if options['apply'] else 'DRY RUN'} carried-forward B/F allocation repair"
        )
        self.stdout.write(f"Organization: {organization.name} ({organization.code})")
        self.stdout.write(f"Previous term: {previous_term}")
        self.stdout.write(f"Current term: {current_term}")

        if dry_run:
            stats = self._run(
                organization=organization,
                previous_term=previous_term,
                current_term=current_term,
                admissions=admissions,
                dry_run=True,
            )
        else:
            with transaction.atomic():
                stats = self._run(
                    organization=organization,
                    previous_term=previous_term,
                    current_term=current_term,
                    admissions=admissions,
                    dry_run=False,
                )

        self.stdout.write(
            "SUMMARY "
            f"checked={stats['checked']} repaired={stats['repaired']} "
            f"allocations_moved={stats['allocations_moved']} "
            f"amount_moved={stats['amount_moved']} "
            f"previous_invoices_deactivated={stats['previous_invoices_deactivated']} "
            f"blocked={stats['blocked']} skipped={stats['skipped']}"
        )

        if dry_run:
            self.stdout.write("No DB changes were saved. Re-run with --apply after review.")
        elif stats["blocked"]:
            raise CommandError("Some rows were blocked during apply; transaction was rolled back.")

    def _resolve_previous_term(self, *, organization, current_term, requested):
        requested = (requested or "").strip()
        if requested:
            term_value = self.TERM_MAP.get(requested.lower())
            queryset = Term.objects.filter(organization=organization)
            if term_value:
                return queryset.filter(
                    academic_year=current_term.academic_year,
                    term=term_value,
                ).first()
            return queryset.filter(pk=requested).first()

        return (
            Term.objects.filter(
                organization=organization,
                is_active=True,
                start_date__lt=current_term.start_date,
            )
            .exclude(pk=current_term.pk)
            .order_by("-start_date", "-end_date", "-academic_year__year")
            .first()
        )

    def _target_invoices(self, *, organization, current_term, admissions):
        invoices = (
            Invoice.objects.select_related("student", "term", "term__academic_year")
            .filter(
                student__organization=organization,
                term=current_term,
                is_active=True,
                balance_bf__gt=0,
            )
            .exclude(status=InvoiceStatus.CANCELLED)
            .order_by("student__admission_number")
        )
        if admissions:
            invoices = invoices.filter(student__admission_number__in=admissions)
        return invoices

    def _run(self, *, organization, previous_term, current_term, admissions, dry_run):
        stats = {
            "checked": 0,
            "repaired": 0,
            "allocations_moved": 0,
            "amount_moved": Decimal("0.00"),
            "previous_invoices_deactivated": 0,
            "blocked": 0,
            "skipped": 0,
        }

        for current_invoice in self._target_invoices(
            organization=organization,
            current_term=current_term,
            admissions=admissions,
        ):
            stats["checked"] += 1
            student = current_invoice.student
            previous_invoice_qs = (
                Invoice.objects.filter(
                    student=student,
                    term=previous_term,
                    is_active=True,
                )
                .exclude(status=InvoiceStatus.CANCELLED)
                .order_by("issue_date", "created_at")
            )
            if not dry_run:
                previous_invoice_qs = previous_invoice_qs.select_for_update()
            previous_invoices = list(previous_invoice_qs)

            if not previous_invoices:
                stats["skipped"] += 1
                continue

            bf_item = current_invoice.items.filter(
                is_active=True,
                category="balance_bf",
            ).first()

            current_bf_allocated = Decimal("0.00")
            if bf_item:
                current_bf_allocated = (
                    PaymentAllocation.objects.filter(
                        is_active=True,
                        invoice_item=bf_item,
                        payment__is_active=True,
                        payment__status=PaymentStatus.COMPLETED,
                    ).aggregate(total=Sum("amount"))["total"]
                    or Decimal("0.00")
                )

            bf_due = max(
                Decimal("0.00"),
                (current_invoice.balance_bf or Decimal("0.00")) - current_bf_allocated,
            )

            move_candidate_qs = (
                PaymentAllocation.objects.select_related("payment", "invoice_item", "invoice_item__invoice")
                .filter(
                    is_active=True,
                    invoice_item__invoice__in=previous_invoices,
                    payment__is_active=True,
                    payment__status=PaymentStatus.COMPLETED,
                    payment__payment_date__date__gte=current_term.start_date,
                )
                .order_by("payment__payment_date", "created_at")
            )
            if not dry_run:
                move_candidate_qs = move_candidate_qs.select_for_update()
            move_candidates = list(move_candidate_qs)
            movable_total = sum((a.amount for a in move_candidates), Decimal("0.00"))

            if bf_due > 0 and movable_total < bf_due:
                stats["blocked"] += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"BLOCKED {student.admission_number} {student.full_name}: "
                        f"current_bf_due={bf_due} movable_old_allocations={movable_total}"
                    )
                )
                continue

            moved_amount = Decimal("0.00")
            moved_rows = 0
            if bf_due > 0:
                if not bf_item and not dry_run:
                    bf_item = InvoiceItem.objects.create(
                        invoice=current_invoice,
                        fee_item=None,
                        category="balance_bf",
                        description="Balance B/F from previous term",
                        amount=current_invoice.balance_bf,
                        discount_applied=Decimal("0.00"),
                        net_amount=current_invoice.balance_bf,
                    )

                remaining_to_move = bf_due
                for allocation in move_candidates:
                    if remaining_to_move <= 0:
                        break
                    move_amount = min(allocation.amount, remaining_to_move)
                    if not dry_run:
                        if move_amount == allocation.amount:
                            allocation.invoice_item = bf_item
                            allocation.save(update_fields=["invoice_item", "updated_at"])
                        else:
                            allocation.amount -= move_amount
                            allocation.save(update_fields=["amount", "updated_at"])
                            PaymentAllocation.objects.create(
                                payment=allocation.payment,
                                invoice_item=bf_item,
                                amount=move_amount,
                            )

                    moved_amount += move_amount
                    moved_rows += 1
                    remaining_to_move -= move_amount

            if not dry_run:
                for previous_invoice in previous_invoices:
                    InvoiceService._recalculate_invoice_fields(previous_invoice)
                    previous_invoice.is_active = False
                    previous_invoice.save(update_fields=["is_active", "updated_at"])

                if moved_amount > 0:
                    InvoiceService._recalculate_invoice_fields(current_invoice)
                student.recompute_outstanding_balance()

            previous_balance = sum(
                (invoice.balance or Decimal("0.00")) for invoice in previous_invoices
            )
            self.stdout.write(
                f"{'WOULD REPAIR' if dry_run else 'REPAIRED'} "
                f"{student.admission_number} {student.full_name} | "
                f"current={current_invoice.invoice_number} bf_due={bf_due} "
                f"moved={moved_amount} previous_active={len(previous_invoices)} "
                f"previous_balance={previous_balance}"
            )

            stats["repaired"] += 1
            stats["allocations_moved"] += moved_rows
            stats["amount_moved"] += moved_amount
            stats["previous_invoices_deactivated"] += len(previous_invoices)

        return stats
