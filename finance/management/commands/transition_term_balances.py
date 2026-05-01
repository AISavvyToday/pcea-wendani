"""
Management command to manually transition frozen balance fields between terms.

This is a backup command in case the automatic signal-based transition
needs to be re-run or if you need to specify custom from/to terms.

Usage:
    python manage.py transition_term_balances
    python manage.py transition_term_balances --dry-run
    python manage.py transition_term_balances --from-term 5 --to-term 6
"""
from uuid import UUID

from django.core.management.base import BaseCommand
from django.db.models import Q

from academics.models import Term
from academics.services.term_state import activate_term_for_org
from core.models import Organization


class Command(BaseCommand):
    help = 'Transition frozen balance fields from previous term to current term'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without making changes',
        )
        parser.add_argument(
            '--from-term',
            type=str,
            help='ID of the previous term (auto-detected if not specified)',
        )
        parser.add_argument(
            '--to-term',
            type=str,
            help='ID of the current term (auto-detected if not specified)',
        )
        parser.add_argument(
            '--organization',
            type=str,
            help='Organization id, code, or name to use when auto-detecting terms',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        from_term_id = options.get('from_term')
        to_term_id = options.get('to_term')
        organization_lookup = (options.get('organization') or '').strip()
        organization = None

        if organization_lookup:
            organization = Organization.objects.filter(
                Q(code__iexact=organization_lookup)
                | Q(name__iexact=organization_lookup)
            ).first()
            if not organization:
                try:
                    organization_id = UUID(organization_lookup)
                except ValueError:
                    organization_id = None
                if organization_id:
                    organization = Organization.objects.filter(pk=organization_id).first()
            if not organization:
                self.stdout.write(self.style.ERROR(
                    f'Organization "{organization_lookup}" not found'
                ))
                return
        
        self.stdout.write('=' * 80)
        self.stdout.write('TERM BALANCE TRANSITION')
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        self.stdout.write('=' * 80)
        self.stdout.write('')
        
        # Determine the current term
        if to_term_id:
            try:
                current_term = Term.objects.get(pk=to_term_id)
            except Term.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Term with ID {to_term_id} not found'))
                return
        else:
            current_terms = Term.objects.filter(is_current=True)
            if organization:
                current_terms = current_terms.filter(organization=organization)
            current_term = current_terms.order_by('-start_date').first()
            if not current_term:
                self.stdout.write(self.style.ERROR('No current term found. Please specify --to-term'))
                return

        if organization and current_term.organization_id != organization.id:
            self.stdout.write(self.style.ERROR(
                f'To term "{current_term}" does not belong to {organization.name}'
            ))
            return
        
        self.stdout.write(f'Current term: {current_term}')
        
        # Determine the previous term
        if from_term_id:
            try:
                previous_term = Term.objects.get(pk=from_term_id)
            except Term.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Term with ID {from_term_id} not found'))
                return
            if current_term.organization_id != previous_term.organization_id:
                self.stdout.write(self.style.ERROR(
                    'From term and to term belong to different organizations'
                ))
                return
        else:
            # Auto-detect previous term
            previous_terms = Term.objects.filter(
                academic_year=current_term.academic_year,
                start_date__lt=current_term.start_date
            )
            if current_term.organization_id:
                previous_terms = previous_terms.filter(organization=current_term.organization)
            else:
                previous_terms = previous_terms.filter(organization__isnull=True)
            previous_term = previous_terms.order_by('-start_date').first()
            
            if not previous_term:
                previous_terms = Term.objects.filter(
                    start_date__lt=current_term.start_date
                ).exclude(pk=current_term.pk)
                if current_term.organization_id:
                    previous_terms = previous_terms.filter(organization=current_term.organization)
                else:
                    previous_terms = previous_terms.filter(organization__isnull=True)
                previous_term = previous_terms.order_by('-start_date').first()
            
            if not previous_term:
                self.stdout.write(self.style.ERROR(
                    'No previous term found. This appears to be the first term.'
                ))
                return
        
        self.stdout.write(f'Previous term: {previous_term}')
        self.stdout.write('')
        
        # Run the transition
        self.stdout.write('Running transition...')
        self.stdout.write('')
        
        stats = activate_term_for_org(
            organization=current_term.organization,
            term=current_term,
            previous_term=previous_term,
            transition=True,
            dry_run=dry_run,
            notes='Manual transition_term_balances command',
        )
        
        # Display results
        self.stdout.write('')
        self.stdout.write('=' * 80)
        self.stdout.write('SUMMARY')
        self.stdout.write('=' * 80)
        self.stdout.write(f'Total students processed: {stats.get("total_students", 0)}')
        self.stdout.write(f'With outstanding balance (balance_bf_original set): {stats.get("with_outstanding", 0)}')
        self.stdout.write(f'With overpayment (prepayment_original set): {stats.get("with_overpayment", 0)}')
        self.stdout.write(f'Fully paid (both reset to 0): {stats.get("fully_paid", 0)}')
        self.stdout.write(f'No previous invoice (used credit_balance): {stats.get("no_invoice", 0)}')
        self.stdout.write(f'Records {"would be " if dry_run else ""}updated: {stats.get("updated", 0)}')
        self.stdout.write(f'Errors: {stats.get("errors", 0)}')
        if stats.get('transition_already_logged'):
            self.stdout.write(self.style.WARNING('Transition already logged; balances were not re-run.'))
        
        if dry_run:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'DRY RUN - No changes were made. Run without --dry-run to apply changes.'
            ))
        else:
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS(
                f'Successfully transitioned frozen balances for {stats["updated"]} students.'
            ))

