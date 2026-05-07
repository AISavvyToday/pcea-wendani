from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from academics.models import Term
from academics.services.term_state import backfill_student_term_states, find_organization_for_pcea
from core.models import TermChoices
from students.metrics import get_student_base_queryset, get_student_status_counters


class Command(BaseCommand):
    help = "Repair PCEA Wendani Term 2 student dashboard/list breakdowns."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Persist the repair. Default is dry-run.")

    def handle(self, *args, **options):
        apply = options["apply"]
        organization = find_organization_for_pcea()
        if not organization:
            raise CommandError("PCEA Wendani organization was not found.")

        term = (
            Term.objects.select_related("academic_year")
            .filter(
                organization=organization,
                academic_year__year=2026,
                term=TermChoices.TERM_2,
                is_active=True,
            )
            .first()
        )
        if not term:
            raise CommandError("PCEA Wendani Term 2 2026 was not found.")

        target_start = date(2026, 5, 1)
        target_end = date(2026, 8, 31)
        dry_run = not apply

        self.stdout.write(
            self.style.WARNING("DRY RUN - no data changed.") if dry_run else self.style.SUCCESS("APPLYING repair.")
        )
        self.stdout.write(f"Organization: {organization.name} ({organization.code})")
        self.stdout.write(f"Current Term 2 dates: {term.start_date} to {term.end_date}")
        self.stdout.write(f"Target Term 2 dates: {target_start} to {target_end}")

        base_queryset = get_student_base_queryset(organization=organization)
        before_counts = get_student_status_counters(base_queryset, term=term, organization=organization)
        target_new = base_queryset.filter(
            status__in=("active", "inactive"),
            admission_date__gte=target_start,
            admission_date__lte=target_end,
        ).count()

        self.stdout.write(f"Before counts: {before_counts}")
        self.stdout.write(f"New students using target dates: {target_new}")

        if dry_run:
            self.stdout.write(
                f"Would update Term 2 dates to {target_start} - {target_end} and backfill student term states."
            )
            state_stats = backfill_student_term_states(term, organization=organization, dry_run=True)
            self.stdout.write(f"Student term state dry-run: {state_stats}")
            return

        with transaction.atomic():
            term.start_date = target_start
            term.end_date = target_end
            term.save(update_fields=["start_date", "end_date", "updated_at"])
            state_stats = backfill_student_term_states(term, organization=organization, dry_run=False)

        term.refresh_from_db()
        after_counts = get_student_status_counters(base_queryset, term=term, organization=organization)
        self.stdout.write(f"Student term state repair: {state_stats}")
        self.stdout.write(f"After counts: {after_counts}")
        self.stdout.write(self.style.SUCCESS("Student dashboard/list breakdown repair complete."))
