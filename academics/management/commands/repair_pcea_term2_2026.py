"""Repair PCEA Wendani Term 2 2026 term state and related term data."""

from django.core.management.base import BaseCommand, CommandError

from academics.services.term_state import (
    activate_term_for_org,
    backfill_student_term_states,
    copy_missing_transport_fees,
    ensure_pcea_wendani_term2_2026,
    find_organization_for_pcea,
    get_previous_term,
    hydrate_invoice_transport_metadata,
    recalculate_term_invoices,
)


class Command(BaseCommand):
    help = "Activate and repair PCEA Wendani Term 2 2026 after a verified DB backup."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show planned changes without writing data.",
        )
        parser.add_argument(
            "--skip-transition",
            action="store_true",
            help="Activate/backfill term data without carrying balances forward.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        organization = find_organization_for_pcea()
        if not organization:
            raise CommandError("PCEA Wendani organization was not found.")

        academic_year, term2 = ensure_pcea_wendani_term2_2026(
            organization,
            dry_run=dry_run,
        )
        previous_term = get_previous_term(term2)

        self.stdout.write(f"Organization: {organization.name} ({organization.code})")
        self.stdout.write(f"Academic year: {academic_year.year}")
        self.stdout.write(f"Term 2: {term2.start_date} to {term2.end_date}")
        self.stdout.write(f"Previous term: {previous_term or 'None'}")

        transition_stats = activate_term_for_org(
            organization=organization,
            term=term2,
            previous_term=previous_term,
            transition=not options["skip_transition"],
            dry_run=dry_run,
            notes="repair_pcea_term2_2026 command",
        )
        state_stats = backfill_student_term_states(
            term2,
            organization=organization,
            dry_run=dry_run,
        )
        fee_stats = (
            copy_missing_transport_fees(previous_term, term2, dry_run=dry_run)
            if previous_term
            else {"source": 0, "created": 0, "skipped": 0}
        )
        metadata_stats = hydrate_invoice_transport_metadata(
            term2,
            organization=organization,
            dry_run=dry_run,
        )
        invoice_stats = recalculate_term_invoices(
            term2,
            organization=organization,
            dry_run=dry_run,
        )

        self.stdout.write("")
        self.stdout.write(self.style.WARNING("DRY RUN - no data changed.") if dry_run else self.style.SUCCESS("Repair complete."))
        self.stdout.write(f"Activation/transition: {transition_stats}")
        self.stdout.write(f"Student term states: {state_stats}")
        self.stdout.write(f"Transport fees copied: {fee_stats}")
        self.stdout.write(f"Transport invoice metadata: {metadata_stats}")
        self.stdout.write(f"Invoice recalculation: {invoice_stats}")
