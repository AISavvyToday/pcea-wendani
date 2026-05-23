from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from academics.services.term_state import backfill_student_term_states, get_current_term_for_org
from core.models import Organization
from students.metrics import apply_student_filters, get_student_base_queryset
from students.models import StudentTermState


class Command(BaseCommand):
    help = "Backfill transferred student term states for the active PCEA Wendani term."

    WATCH_ADMISSIONS = ("2885", "2830", "3153", "2895")

    def add_arguments(self, parser):
        parser.add_argument("--organization-code", default="PCEA_WENDANI")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        organization = Organization.objects.filter(code__iexact=options["organization_code"]).first()
        if not organization:
            raise CommandError(f"Organization not found: {options['organization_code']}")

        term = get_current_term_for_org(organization)
        if not term:
            raise CommandError(f"No active term found for {organization.name}")

        dry_run = options["dry_run"]
        with transaction.atomic():
            stats = backfill_student_term_states(term, organization=organization, dry_run=dry_run)
            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            f"{'DRY RUN ' if dry_run else ''}{term}: {stats}"
        ))

        table_qs = apply_student_filters(
            get_student_base_queryset(organization=organization, include_inactive_terminal=True),
            status="transferred",
            term=term,
            organization=organization,
        )
        self.stdout.write(f"Transferred students visible in table rule: {table_qs.count()}")

        for admission_number in self.WATCH_ADMISSIONS:
            student = table_qs.filter(admission_number=admission_number).first()
            state = StudentTermState.objects.filter(
                student__admission_number=admission_number,
                term=term,
            ).filter(
                Q(organization=organization) | Q(organization__isnull=True)
            ).first()
            if student:
                self.stdout.write(self.style.SUCCESS(
                    f"  visible: {admission_number} {student.full_name}"
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f"  missing: {admission_number}; state={state.status if state else 'none'} "
                    f"active={state.is_active if state else 'n/a'}"
                ))
