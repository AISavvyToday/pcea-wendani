"""
Management command to manually transition frozen balance fields between terms.

This is a backup command in case the automatic signal-based transition
needs to be re-run or if you need to specify custom from/to terms.

Usage:
    python manage.py transition_term_balances
    python manage.py transition_term_balances --dry-run
    python manage.py transition_term_balances --from-term 5 --to-term 6
"""
from django.core.management.base import BaseCommand

from academics.models import Term
from finance.services import transition_frozen_balances


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

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        from_term_id = options.get('from_term')
        to_term_id = options.get('to_term')
        
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
            current_term = Term.objects.filter(is_current=True).first()
            if not current_term:
                self.stdout.write(self.style.ERROR('No current term found. Please specify --to-term'))
                return
        
        self.stdout.write(f'Current term: {current_term}')
        
        # Determine the previous term
        if from_term_id:
            try:
                previous_term = Term.objects.get(pk=from_term_id)
            except Term.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Term with ID {from_term_id} not found'))
                return
        else:
            # Auto-detect previous term
            previous_term = Term.objects.filter(
                academic_year=current_term.academic_year,
                start_date__lt=current_term.start_date
            ).order_by('-start_date').first()
            
            if not previous_term:
                previous_term = Term.objects.filter(
                    start_date__lt=current_term.start_date
                ).exclude(pk=current_term.pk).order_by('-start_date').first()
            
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
        
        stats = transition_frozen_balances(previous_term, current_term, dry_run=dry_run)
        
        # Display results
        self.stdout.write('')
        self.stdout.write('=' * 80)
        self.stdout.write('SUMMARY')
        self.stdout.write('=' * 80)
        self.stdout.write(f'Total students processed: {stats["total_students"]}')
        self.stdout.write(f'With outstanding balance (balance_bf_original set): {stats["with_outstanding"]}')
        self.stdout.write(f'With overpayment (prepayment_original set): {stats["with_overpayment"]}')
        self.stdout.write(f'Fully paid (both reset to 0): {stats["fully_paid"]}')
        self.stdout.write(f'No previous invoice (used credit_balance): {stats["no_invoice"]}')
        self.stdout.write(f'Records {"would be " if dry_run else ""}updated: {stats["updated"]}')
        self.stdout.write(f'Errors: {stats["errors"]}')
        
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

